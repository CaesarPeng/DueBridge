from __future__ import annotations

import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from homework_assistant import cli, evidence, jobs, service, storage
from homework_assistant.config import load


class AgentInterfaces(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        cli.init(self.root, "generic", "chromium")
        path = self.root / "homework.toml"
        path.write_text(path.read_text().replace("enabled = false", "enabled = true"))
        self.config = load(self.root)
        self.source = self.config.sources[0]
        self.text = "Original context\n" + "x" * 100 + "\nHomework due Friday\nLate policy: 50% credit"
        self.save(self.text)

    def save(self, text):
        storage.save(self.config, self.source, {"pages": [{"url": self.source.home, "title": "List",
                     "fetched_at": "2026-10-14T01:00:00Z", "text": text, "scope": "Fixture rows", "itemCount": 1}]})

    def test_evidence_pages_revision_and_no_private_paths(self):
        match = evidence.search(self.config, "Friday")["items"][0]
        self.assertTrue(match["snippet_only"])
        record = evidence.list_evidence(self.config)["items"][0]
        offset, chunks = 0, []
        while True:
            page = evidence.read_evidence(self.config, record["id"], offset, 30, record["revision"])
            self.assertTrue(page["untrusted_content"])
            chunks.append(page["text"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual("".join(chunks), self.text)
        self.save("New context")
        with self.assertRaisesRegex(ValueError, "已更新"):
            evidence.read_evidence(self.config, record["id"], expected_revision=record["revision"])
        with self.assertRaises(ValueError):
            evidence.read_evidence(self.config, ".homework/sessions/cookies")
        with self.assertRaises(ValueError):
            evidence.safe_cache(self.config, ".homework/../homework.toml")
        service.prepare_state(self.config)
        (self.config.state / "text/link.md").symlink_to(self.root / "homework.toml")
        with self.assertRaises(ValueError):
            evidence.safe_cache(self.config, ".homework/text/link.md")

    def test_scan_all_includes_reading_without_deadline_and_detects_changes(self):
        folder = self.root / "materials"
        folder.mkdir(exist_ok=True)
        original = folder / "lecture.txt"
        original.write_text("Lecture material: energy conservation")
        service.scan_materials(self.config)
        self.assertEqual(evidence.list_evidence(self.config, kind="local")["total"], 0)
        service.scan_materials(self.config, include_all=True)
        record = evidence.list_evidence(self.config, kind="local")["items"][0]
        self.assertFalse(record["has_deadline_cue"])
        self.assertFalse(record["original_changed"])
        original.write_text("Updated lecture: momentum")
        self.assertTrue(evidence.read_evidence(self.config, record["id"])["original_changed"])

    def test_scan_all_rejects_alias_directory_into_private_session_cache(self):
        service.prepare_state(self.config)
        (self.config.state / "private.txt").write_text("Session secret must never be indexed")
        (self.root / "alias").symlink_to(self.config.state, target_is_directory=True)
        result = service.scan_materials(replace(self.config, local_paths=("alias",)), True)
        self.assertEqual(result["indexed"], 0)
        self.assertTrue(result["failures"])

    def test_failures_do_not_advance_capture_and_mutations_are_serialized(self):
        before = evidence.overview(self.config)["sources"][0]["fetched_at"]
        storage.health(self.config, self.source.id, "error", "Login expired")
        overview = evidence.overview(self.config)["sources"][0]
        self.assertEqual(overview["fetched_at"], before)
        self.assertTrue(overview["needs_refresh"])
        with service.mutation_lock(self.config):
            with self.assertRaisesRegex(RuntimeError, "正在写入"):
                service.scan_materials(self.config, True)

    def test_local_custom_reader_changes_invalidate_old_evidence(self):
        folder = self.root / "adapters"
        folder.mkdir()
        reader = folder / "niche.js"
        reader.write_text("customReader={parse(){}};")
        path = self.root / "homework.toml"
        text = path.read_text().replace('adapter = "generic"', 'adapter = "custom"\nreader = "adapters/niche.js"')
        text += '\nsite_field = "niche-custom-option"\n'
        path.write_text(text)
        config = load(self.root)
        self.assertEqual(config.sources[0].options["site_field"], "niche-custom-option")
        storage.save(config, config.sources[0], {"pages": [{"url": self.source.home, "title": "Niche",
                    "fetched_at": "2026-10-14T01:00:00Z", "text": "Custom raw text", "scope": "Rows"}]})
        self.assertEqual(evidence.list_evidence(config)["total"], 1)
        reader.write_text("customReader={parse(){/* new logic */}};")
        self.assertEqual(evidence.list_evidence(load(self.root))["total"], 0)
        reader.unlink()
        reader.symlink_to(self.root / "homework.toml")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            load(self.root)

    def test_background_scan_runs_real_worker_and_reports_result(self):
        folder = self.root / "materials"
        folder.mkdir(exist_ok=True)
        (folder / "notes.txt").write_text("Reading without a due date")
        job = jobs.start(self.config, "scan", include_all=True)
        self.addCleanup(jobs._children[job["id"]].wait, 5)
        deadline = time.monotonic() + 15
        while job["status"] not in jobs.TERMINAL and time.monotonic() < deadline:
            time.sleep(.05)
            job = jobs.get(self.config, job["id"])
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["result"]["indexed"], 1)
        self.assertNotIn("parameters", job)
        self.assertTrue((self.root / "DUEDATES.md").is_file())
        self.assertTrue(any(e["phase"] == "scanning" for e in job["events"]))
        with self.assertRaises(ValueError):
            jobs.get(self.config, "../../secrets")

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for protocol tests")
    def test_real_stdio_tools_resources_prompt_and_opt_in_collection(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        launcher = Path(__file__).resolve().parents[1] / "duebridge"

        async def exercise():
            args = [str(launcher), "--project", str(self.root), "mcp", "serve"]
            async with Client(StdioServerParameters(command=sys.executable, args=args)) as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("read_evidence", names)
                self.assertNotIn("start_refresh", names)
                result = await client.call_tool("list_evidence", {})
                self.assertFalse(result.is_error, result)
                content = json.loads(result.content[0].text)
                self.assertEqual(content["total"], 1)
                record = content["items"][0]
                read = await client.call_tool("read_evidence", {"evidence_id": record["id"]})
                self.assertEqual(json.loads(read.content[0].text)["text"], self.text)
                bad = await client.call_tool("read_evidence", {"evidence_id": "../homework.toml"})
                self.assertTrue(bad.is_error)
                resources = await client.list_resources()
                self.assertIn("duebridge://guide", {str(r.uri) for r in resources.resources})
                overview = await client.read_resource("duebridge://overview")
                self.assertEqual(json.loads(overview.contents[0].text)["timezone"], "Asia/Shanghai")
                prompt = await client.get_prompt("analyze_materials", {"question": "What should I read?"})
                self.assertIn("What should I read?", prompt.messages[0].content.text)
            async with Client(StdioServerParameters(command=sys.executable, args=args + ["--allow-refresh"])) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertTrue({"start_refresh", "start_scan", "start_inspection"} <= names)
                started = await client.call_tool("start_scan", {})
                job = json.loads(started.content[0].text)
                for _ in range(200):
                    checked = await client.call_tool("get_job", {"job_id": job["id"]})
                    job = json.loads(checked.content[0].text)
                    if job["status"] in jobs.TERMINAL:
                        break
                    await asyncio.sleep(.05)
                self.assertEqual(job["status"], "completed", job)
                self.assertEqual(job["result"]["mode"], "all_documents")
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
