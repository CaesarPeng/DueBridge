from __future__ import annotations

import json
from pathlib import Path
import secrets
import time
from typing import Callable
from urllib.parse import urlsplit

from .browsers import Browser
from .config import Source, clean_url

ASSETS = Path(__file__).parent / "assets"


def parser_script(source: Source) -> str:
    return ("const SOURCE_CONFIG=" + json.dumps(source.job_config()) + ";"
            + "let customReader=null;" + source.reader_code + "\n"
            + (ASSETS / "sites.js").read_text(encoding="utf-8"))


def job_script(source: Source, key: str, seeds: list[str]) -> str:
    config = source.job_config()
    config["seeds"] = [clean_url(u) for u in seeds if source.allows(u, assignment=True)]
    parser = "let customReader=null;" + source.reader_code + "\n" + (ASSETS / "sites.js").read_text(encoding="utf-8")
    collector = (ASSETS / "collector.js").read_text(encoding="utf-8")
    return ("(()=>{const SOURCE_CONFIG=" + json.dumps(config) + ";" + parser + "\n" + collector
            + "\nconst key=" + json.dumps(key) + ";window[key]={phase:'running'};"
            + "collectSource(SOURCE_CONFIG).then(result=>window[key]={phase:'done',result})"
            + ".catch(()=>window[key]={phase:'done',result:{waiting:true,message:'页面结构变化或尚未进入作业列表'}});"
            + "return 'started';})()")


def capture(browser: Browser, source: Source, timeout: int, old_pages: list[dict] | None = None,
            progress: Callable[[dict], None] | None = None) -> dict:
    def report(phase, message):
        if progress:
            progress({"source": source.id, "phase": phase, "message": message})
    if source.adapter == "blackboard" and not source.courses:
        raise ValueError(f"{source.id}：请在 homework.toml 中配置 courses，课程 id 来自课程页面 URL 的 course_id")
    if source.adapter == "generic" and not source.options.get("selector"):
        raise ValueError(f"{source.id}：请配置 options.selector")
    deadline = time.monotonic() + timeout
    key = "__homeworkRead_" + secrets.token_hex(12)
    jobs, focused = {}, set()
    opened, last_message = False, ""
    try:
        while time.monotonic() < deadline:
            tabs = [t for t in browser.tabs() if source.allows(t.url)]
            eligible = [t for t in tabs if source.allows(t.url, assignment=True)]
            if not eligible and not opened:
                if not tabs:
                    browser.open(source.home)
                    report("waiting_for_user", "已打开入口；请在浏览器中登录并进入课程作业列表")
                else:
                    browser.focus(tabs[0])
                    report("waiting_for_user", "请从入口进入实际作业列表")
                opened = True
            groups = {}
            for tab in eligible:
                groups.setdefault(urlsplit(tab.url).netloc, []).append(tab)
            # Every origin must finish; never report only one origin as full coverage.
            completed = []
            for origin, group in groups.items():
                tab = next((t for t in group if "/assessments" in t.url or "/Course?" in t.url), group[0])
                signature = (tab.id, clean_url(tab.url))
                active = jobs.get(origin)
                if not active or active["signature"] != signature:
                    if tab.id not in focused:
                        browser.focus(tab)
                        focused.add(tab.id)
                    seeds = [t.url for t in group] + [p["url"] for p in old_pages or [] if source.allows(p["url"])]
                    browser.execute(tab, job_script(source, key, seeds))
                    report("collecting", "正在读取课程列表")
                    jobs[origin] = {"signature": signature, "tab": tab}
                    continue
                value = json.loads(browser.execute(tab, "JSON.stringify(window[" + json.dumps(key) + "]||null)") or "null")
                if value is None:
                    jobs.pop(origin, None)
                elif value.get("phase") == "done":
                    result = value["result"]
                    if result.get("waiting"):
                        message = result.get("message", "请先登录课程页面")
                        if message != last_message:
                            report("waiting_for_user", message + "；本次运行会继续等待")
                            last_message = message
                        jobs.pop(origin, None)
                    else:
                        completed.append({**result, "_origin": origin})
            if completed and len(completed) == len(groups):
                if source.adapter == "blackboard":
                    return completed[0]
                return {"pages": [p for r in completed for p in r.get("pages", [])],
                        "warnings": [m for r in completed for m in r.get("warnings", [])],
                        "diagnostics": {"origins": [{"origin": r["_origin"], **r.get("diagnostics", {})} for r in completed]}}
            browser.pause(min(1, max(0, deadline - time.monotonic())))
        raise RuntimeError(f"{source.id} 等待登录或完整作业列表超时；旧资料保留")
    finally:
        for active in jobs.values():
            try:
                browser.execute(active["tab"], "delete window[" + json.dumps(key) + "];'done'")
            except Exception:
                pass
