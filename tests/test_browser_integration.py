"""Run the actual browser backend and page collector against intercepted fixtures."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

from homework_assistant import collector
from homework_assistant.config import Config, Source
from homework_assistant.browsers.playwright import PlaywrightBrowser

ENGINES = tuple(x for x in os.environ.get("HOMEWORK_TEST_ENGINES", "").split(",") if x)


@unittest.skipUnless(ENGINES, "Set HOMEWORK_TEST_ENGINES=chromium,firefox,webkit to run browser fixtures")
class BrowserIntegrationTests(unittest.TestCase):
    def run_fixture(self, engine, source, route_handler, initial):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(Path(folder), "Asia/Shanghai", engine, 5, "DUEDATES.md", ("materials",), (source,))
            browser = PlaywrightBrowser(config, engine, headless=True)
            try:
                browser.context.route("https://**/*", route_handler)
                browser.open(initial)
                result = collector.capture(browser, source, 5)
                return result
            finally:
                browser.close()

    def test_hidden_physics_rows_with_custom_school_domain(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("physics", "smartphysics", "https://physics.example.edu/", ("physics.example.edu",))
                def handle(route):
                    html = '<title>Courses</title><a href="/Course?enrollmentID=1">Physics</a>' if route.request.url.endswith("/") else '<title>Physics</title><div><h2 class="UnitTitle">Unit 3</h2><div style="display:none"><div class="unit-assignment">HW3 Due tomorrow</div><div class="unit-assignment">Checkpoint Due Friday</div></div></div>'
                    route.fulfill(content_type="text/html", body=html)
                result = self.run_fixture(engine, source, handle, "https://physics.example.edu/Course?enrollmentID=1")
                self.assertEqual(result["pages"][0]["itemCount"], 2)
                self.assertIn("Due tomorrow", result["pages"][0]["text"])

    def test_blackboard_pagination_raw_fields_and_missing_course(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("school", "blackboard", "https://lms.example.edu/", ("lms.example.edu",), courses=({"id": "_1_1", "name": "A"}, {"id": "_2_1", "name": "B"}))
                def handle(route):
                    url = route.request.url
                    if "_2_1" in url:
                        route.fulfill(status=403, content_type="application/json", body="{}")
                    elif "/gradebook/columns" in url:
                        second = "offset" in url
                        data = {"results": [{"id": "2" if second else "1", "name": "HW raw", "grading": {"due": None if second else "2026-10-16T15:59:00Z"}, "score": 99}]}
                        if not second:
                            data["paging"] = {"nextPage": "/learn/api/public/v2/courses/_1_1/gradebook/columns?offset=1"}
                        route.fulfill(content_type="application/json", body=json.dumps(data))
                    else:
                        route.fulfill(content_type="text/html", body="<title>Course</title><h1>Course</h1>")
                result = self.run_fixture(engine, source, handle, source.home)
                columns = result["api"]["courses"][0]["columns"]
                self.assertEqual(len(columns), 2)
                self.assertIsNone(columns[1]["due"])
                self.assertNotIn("score", columns[0])
                self.assertTrue(result["warnings"])

    def test_zjui_tooltip_and_no_answer_instance_navigation(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("learn", "zjuilearn", "https://learn.example.edu/", ("learn.example.edu",))
                requests = []
                def handle(route):
                    requests.append(route.request.url)
                    html = '<title>Courses</title><a href="/pl/course_instance/1/">Course</a>' if "/assessments" not in route.request.url else '<title>Assessments</title><table><tr><td>HW1</td><td>100%</td><td>Friday</td></tr></table><button data-content="&lt;p&gt;2026-10-22 20:00:00+08&lt;/p&gt;">i</button><a href="/pl/assessment_instance/42">Answer</a>'
                    route.fulfill(content_type="text/html", body=html)
                result = self.run_fixture(engine, source, handle, source.home)
                self.assertIn("2026-10-22 20:00:00+08", result["pages"][0]["text"])
                self.assertFalse(any("assessment_instance" in u for u in requests))

    def test_generic_custom_selector_and_safe_list_links(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("generic", "generic", "https://courses.example.edu/assignments", ("courses.example.edu",), options={"selector": ".hw", "list_links": "a.list", "list_url_pattern": "^https://courses\\.example\\.edu/"})
                requests = []
                def handle(route):
                    requests.append(route.request.url)
                    text = "Next list deadline Friday" if route.request.url.endswith("/archive") else "Current homework due tomorrow"
                    html = f'<title>List</title><div style="display:none" class="hw">{text}<input type="password" value="DO_NOT_EXPORT"></div><a class="list" href="/archive">Archive</a><a class="list" href="/exam/42">Exam</a><a class="list" href="/submit/42">Submit</a><a class="list" href="https://outside.example/archive">External</a>'
                    route.fulfill(content_type="text/html", body=html)
                result = self.run_fixture(engine, source, handle, source.home)
                self.assertEqual(len(result["pages"]), 2)
                self.assertNotIn("DO_NOT_EXPORT", json.dumps(result))
                self.assertFalse(any("/exam/" in u or "/submit/" in u or "outside.example" in u for u in requests))

    def test_webassign_deep_page_lists_and_token_removal(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("math", "webassign", "https://portal.example.edu/", ("portal.example.edu", "assign.example.edu"), ("assign.example.edu",))
                requests = []
                def handle(route):
                    requests.append(route.request.url)
                    if "action=question" in route.request.url:
                        html = "<title>Question</title><p>Question content</p>"
                    elif "assignments/list" in route.request.url:
                        html = "<title>Past Assignments</title><h1>Past Assignments</h1><p>Old list Due Friday</p>"
                    else:
                        html = '<title>My Assignments</title><h1>My Assignments</h1><p>Name Due</p><p>Homework Due tomorrow</p><a href="/v4cgi/student.pl?action=assignments/list&amp;UserPass=SECRET">My Assignments</a><a href="/v4cgi/student.pl?action=assignment/submit">Submit</a>'
                    route.fulfill(content_type="text/html", body=html)
                result = self.run_fixture(engine, source, handle, "https://assign.example.edu/v4cgi/student.pl?action=question&course=1&UserPass=SECRET")
                self.assertEqual(len(result["pages"]), 2)
                self.assertNotIn("SECRET", json.dumps(result))
                self.assertFalse(any("assignment/submit" in u for u in requests))

    def test_dynamic_webassign_fallback_marks_limited_coverage(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("math", "webassign", "https://assign.example.edu/", ("assign.example.edu",))
                def handle(route):
                    html = '<title>My Assignments</title><h1>My Assignments</h1><p>Name Due</p><p>HW Due tomorrow</p>' if route.request.is_navigation_request() else '<title>App</title><div>Loading application</div>'
                    route.fulfill(content_type="text/html", body=html)
                result = self.run_fixture(engine, source, handle, "https://assign.example.edu/v4cgi/student.pl?action=home/index")
                self.assertEqual(len(result["pages"]), 1)
                self.assertIn("动态作业列表", result["pages"][0]["scope"])
                self.assertTrue(result["warnings"])

    def test_explicit_generic_empty_marker_is_saved_as_evidence(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("generic", "generic", "https://courses.example.edu/assignments", ("courses.example.edu",), options={"selector": ".hw", "empty_selector": ".empty"})
                def handle(route):
                    route.fulfill(content_type="text/html", body='<title>List</title><div class="empty">No assignments</div>')
                result = self.run_fixture(engine, source, handle, source.home)
                self.assertEqual(result["pages"][0]["itemCount"], 0)
                self.assertTrue(result["pages"][0]["empty"])

    def test_login_page_exports_no_password_or_source_capture(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                source = Source("generic", "generic", "https://courses.example.edu/login", ("courses.example.edu",), options={"selector": ".hw"})
                with tempfile.TemporaryDirectory() as folder:
                    config = Config(Path(folder), "Asia/Shanghai", engine, 1, "DUEDATES.md", (), (source,))
                    browser = PlaywrightBrowser(config, engine, headless=True)
                    try:
                        browser.context.route("https://**/*", lambda route: route.fulfill(content_type="text/html", body='<title>Login</title><input type="password" value="PRIVATE_PASSWORD"><button>Sign in</button>'))
                        browser.open(source.home)
                        with self.assertRaisesRegex(RuntimeError, "超时"):
                            collector.capture(browser, source, 1)
                        self.assertFalse((config.state / "sources/generic.json").exists())
                    finally:
                        browser.close()

    @unittest.skipUnless("chromium" in ENGINES, "CDP fixture needs the Chromium test engine")
    def test_cdp_collects_and_disconnects_without_closing_external_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            # Launch in another process through Playwright so its platform-specific
            # browser arguments are preserved on Linux as well as macOS. The CDP
            # client below still attaches to an independently owned browser.
            worker = """
from playwright.sync_api import sync_playwright
import sys
with sync_playwright() as runtime:
    context = runtime.chromium.launch_persistent_context(
        sys.argv[1], headless=True, accept_downloads=False,
        args=['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + sys.argv[2]])
    sys.stdin.read()
    context.close()
"""
            errors = tempfile.TemporaryFile(mode="w+b")
            process = subprocess.Popen([sys.executable, "-c", worker, folder + "/external", str(port)],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            browser = None
            try:
                endpoint = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with urlopen(endpoint + "/json/version", timeout=0.5) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except OSError:
                        if process.poll() is not None:
                            errors.seek(0)
                            self.fail("CDP test browser exited: " + errors.read().decode(errors="replace")[-2000:])
                        if time.monotonic() >= deadline:
                            self.fail("CDP test browser did not start")
                        time.sleep(0.1)
                source = Source("generic", "generic", "https://courses.example.edu/list", ("courses.example.edu",), options={"selector": ".hw"})
                config = Config(Path(folder), "Asia/Shanghai", "cdp", 5, "DUEDATES.md", (), (source,), endpoint)
                browser = PlaywrightBrowser(config, "cdp")
                browser.context.route("https://**/*", lambda route: route.fulfill(content_type="text/html", body='<title>List</title><div class="hw">Homework due tomorrow</div>'))
                browser.open(source.home)
                result = collector.capture(browser, source, 5)
                self.assertIn("due tomorrow", result["pages"][0]["text"])
                browser.close()
                browser = None
                self.assertIsNone(process.poll())
            finally:
                if browser:
                    browser.close()
                process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
                errors.close()


if __name__ == "__main__":
    unittest.main()
