from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from homework_assistant import cli, collector, local, storage
from homework_assistant.config import Config, Source, clean_url, load
from homework_assistant.browsers import Tab


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.source = Source("physics", "smartphysics", "https://physics.example.edu/", ("physics.example.edu",))
        self.config = Config(self.root, "Asia/Shanghai", "arc", 10, "DUEDATES.md", ("materials",), (self.source,))

    def page(self, n="1", date="2026-10-14T01:00:00Z", text="Homework due tomorrow"):
        return {"url": f"https://physics.example.edu/Course?enrollmentID={n}", "title": "Physics",
                "fetched_at": date, "text": text, "scope": "all DOM rows", "itemCount": 2}


class ConfigTests(Workspace):
    def test_presets_have_no_personal_courses_and_do_not_assert_no_work(self):
        cli.init(self.root, "zju", "firefox")
        config = load(self.root)
        self.assertEqual(config.browser, "firefox")
        bb = next(s for s in config.sources if s.adapter == "blackboard")
        self.assertFalse(bb.enabled)
        self.assertEqual(bb.courses, ())
        physics = next(s for s in config.sources if s.adapter == "smartphysics")
        self.assertNotIn("enrollmentID", physics.home)
        with self.assertRaises(ValueError):
            cli.init(self.root, "zju", "arc")

    def test_host_boundaries_and_private_parameters(self):
        self.assertFalse(self.source.allows("https://physics.example.edu.evil.test/"))
        self.assertFalse(self.source.allows("https://user:pass@physics.example.edu/"))
        self.assertFalse(self.source.allows("https://physics.example.edu:8443/"))
        self.assertEqual(clean_url("https://physics.example.edu/?course=1&UserPass=SECRET#x"), "https://physics.example.edu/?course=1")

    def test_custom_domains_and_sources_are_configured(self):
        cli.init(self.root, "generic", "chromium")
        file = self.root / "homework.toml"
        text = file.read_text().replace("courses.example.edu", "lms.example.org").replace("enabled = false", "enabled = true")
        file.write_text(text)
        config = load(self.root)
        source = config.sources[0]
        self.assertTrue(source.allows("https://lms.example.org/assignments"))
        self.assertEqual(source.options["selector"], ".assignment-row")
        job = collector.job_script(source, "fixture", ["https://lms.example.org/assignments?token=SECRET"])
        self.assertNotIn("SECRET", job)
        self.assertIn("lms.example.org", job)
        self.assertNotIn("learn.intl.zju.edu.cn", job)

    def test_invalid_paths_domains_timezone_and_cdp_are_rejected(self):
        cli.init(self.root, "generic", "chromium")
        file = self.root / "homework.toml"
        original = file.read_text()
        variants = [original.replace('output = "DUEDATES.md"', 'output = "../outside.md"'),
                    original.replace('timezone = "Asia/Shanghai"', 'timezone = "Made/Up"'),
                    original.replace('domains = ["courses.example.edu"]', 'domains = ["evil,other"]'),
                    original.replace('timeout = 180', 'timeout = 0'),
                    original.replace('timeout = 180', 'timeout = 180\ncdp_endpoint = "http://remote.example:9222"'),
                    original.replace('domains = ["courses.example.edu"]', 'domains = ["courses.example.edu"]\nassignment_domains = ["*.courses.example.edu"]')]
        for text in variants:
            with self.subTest(text=text):
                file.write_text(text)
                with self.assertRaises(ValueError):
                    load(self.root)


class StorageTests(Workspace):
    def test_page_merge_preserves_other_courses_and_newest_capture(self):
        storage.save(self.config, self.source, {"pages": [self.page(), self.page("2", text="Other course")]})
        storage.save(self.config, self.source, {"pages": [self.page(date="2026-10-13T01:00:00Z", text="OLDER")], "warnings": ["partial list"]})
        data = storage.read_json(self.config.state / "sources/physics.json")
        self.assertEqual(len(data["pages"]), 2)
        self.assertNotIn("OLDER", json.dumps(data))
        self.assertEqual(storage.read_json(self.config.state / "health.json")["physics"]["status"], "partial")

    def test_failure_keeps_source_timestamp_and_marks_attempt(self):
        storage.save(self.config, self.source, {"pages": [self.page()]})
        original = (self.config.state / "sources/physics.json").read_bytes()
        storage.health(self.config, "physics", "error", "Login expired")
        self.assertEqual((self.config.state / "sources/physics.json").read_bytes(), original)
        output = storage.render(self.config).read_text()
        self.assertIn("2026-10-14T09:00:00+08:00", output)
        self.assertIn("Login expired", output)
        self.assertIn("Homework due tomorrow", output)

    def test_invalid_or_foreign_capture_does_not_overwrite_cache(self):
        storage.save(self.config, self.source, {"pages": [self.page()]})
        original = (self.config.state / "sources/physics.json").read_bytes()
        for bad in ({**self.page(), "url": "https://evil.example/"}, {**self.page(), "fetched_at": "yesterday"}):
            with self.assertRaises(ValueError):
                storage.save(self.config, self.source, {"pages": [bad]})
            self.assertEqual((self.config.state / "sources/physics.json").read_bytes(), original)

    def test_new_school_does_not_inherit_old_school_cache(self):
        storage.save(self.config, self.source, {"pages": [self.page()]})
        other = replace(self.source, domains=("other.example.edu",), home="https://other.example.edu/")
        config = replace(self.config, sources=(other,))
        self.assertIn("未采集当前配置", storage.render(config).read_text())
        self.assertNotIn("Homework due tomorrow", storage.render(config).read_text())

    def test_blackboard_partial_merge_keeps_original_course_timestamp(self):
        source = Source("bb", "blackboard", "https://lms.example.edu/", ("lms.example.edu",), courses=({"id": "_1_1", "name": "A"}, {"id": "_2_1", "name": "B"}))
        first = {"api": {"fetched_at": "2026-10-13T01:00:00Z", "courses": [{"id": "_1_1", "name": "A", "columns": [{"due": None}], "fetched_at": "2026-10-13T01:00:00Z"}]}}
        storage.save(self.config, source, first)
        second = {"api": {"fetched_at": "2026-10-14T01:00:00Z", "courses": [{"id": "_2_1", "name": "B", "columns": [], "fetched_at": "2026-10-14T01:00:00Z"}]}, "warnings": ["A failed"]}
        data = storage.save(self.config, source, second)
        old = next(c for c in data["courses"] if c["id"] == "_1_1")
        self.assertTrue(old["stale"])
        self.assertEqual(old["fetched_at"], "2026-10-13T01:00:00Z")


class LocalTests(Workspace):
    def test_scan_retains_full_context_and_avoids_private_and_external_files(self):
        materials = self.root / "materials"
        materials.mkdir()
        (materials / "syllabus.txt").write_text("Important context\nHomework due tomorrow\nLate policy: 50% credit\n")
        (materials / "no-work.txt").write_text("Due to an emergency\nWalk due east")
        (materials / ".homework").mkdir()
        (materials / ".homework/private.txt").write_text("Never read this deadline")
        (materials / "outside.txt").symlink_to(Path(__file__))
        result = local.scan(self.config)
        self.assertEqual(len(result["entries"]), 1)
        full = (self.root / result["entries"][0]["text"]).read_text()
        self.assertIn("Important context", full)
        self.assertIn("Late policy", full)
        self.assertTrue(any("符号链接" in f["reason"] for f in result["failures"]))
        nested = replace(self.config, output="reports/deadlines.md")
        self.assertIn("../.homework/text/", storage.render(nested).read_text())

    def test_pdf_and_docx_text_extraction(self):
        materials = self.root / "materials"
        materials.mkdir()
        with ZipFile(materials / "notes.docx", "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Homework deadline Friday</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn("deadline Friday", local.extract(materials / "notes.docx"))
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 100 Td (Homework due Friday) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(materials / "syllabus.pdf")
        self.assertIn("due Friday", local.extract(materials / "syllabus.pdf"))
        self.assertEqual(len(local.scan(self.config)["entries"]), 2)


class CaptureTests(Workspace):
    def test_waits_for_every_origin_and_cleans_transient_jobs(self):
        source = replace(self.source, domains=("physics.example.edu", "other.example.edu"))
        tabs = [Tab("one", source.home), Tab("two", "https://other.example.edu/")]
        page = self.page()
        other = {**page, "url": "https://other.example.edu/Course?enrollmentID=2"}
        calls = []
        class FakeBrowser:
            name = "fake"
            def tabs(self): return tabs
            def focus(self, tab): pass
            def execute(self, tab, code):
                calls.append(code)
                if code.startswith("JSON.stringify"):
                    return json.dumps({"phase": "done", "result": {"pages": [page if tab.id == "one" else other], "warnings": []}})
                return "started"
            def pause(self, seconds): pass
        result = collector.capture(FakeBrowser(), source, 10)
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(sum(c.startswith("delete window") for c in calls), 2)

    def test_sync_records_failure_without_overwriting_old_source(self):
        cli.init(self.root, "zju", "arc")
        config = load(self.root)
        source = next(s for s in config.sources if s.id == "smartphysics")
        page = {**self.page(), "url": "https://smart.physics.illinois.edu/Course?enrollmentID=1"}
        storage.save(config, source, {"pages": [page]})
        original = (config.state / "sources/smartphysics.json").read_bytes()
        with patch("homework_assistant.cli.browsers.create", side_effect=RuntimeError("permission denied")):
            self.assertEqual(cli.sync(config, source.id, None, None), 2)
        self.assertEqual((config.state / "sources/smartphysics.json").read_bytes(), original)
        self.assertIn("permission denied", (self.root / config.output).read_text())


if __name__ == "__main__":
    unittest.main()
