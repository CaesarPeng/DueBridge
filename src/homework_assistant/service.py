"""Shared operations for CLI and MCP. No terminal output or model calls."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
import time
from typing import Callable

from . import browsers, collector, local, storage
from .config import Config, ENGINES, load

Progress = Callable[[dict], None]


def select_sources(config: Config, source_id: str | None):
    if source_id is not None:
        source = next((s for s in config.sources if s.id == source_id), None)
        if source is None:
            raise ValueError(f"没有名为 {source_id} 的来源")
        if not source.enabled:
            raise ValueError(f"{source_id} 已禁用；请在配置中启用")
        return [source]
    return [s for s in config.sources if s.enabled]


def validate_refresh(config: Config, source_id: str | None, engine: str | None, timeout: int | None):
    sources = select_sources(config, source_id)
    if not sources:
        raise ValueError("没有启用的来源；请编辑 homework.toml")
    if engine is not None and engine not in ENGINES:
        raise ValueError("未知浏览器")
    seconds = config.timeout if timeout is None else timeout
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError("timeout 必须是 1–3600 秒的整数")
    return sources, seconds


def prepare_state(config: Config) -> None:
    for path in (config.state, config.state / "sources", config.state / "text", config.state / "jobs", config.state / "inspections"):
        if path.is_symlink():
            raise ValueError("私有缓存目录不能是符号链接")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.resolve().is_relative_to(config.root.resolve()):
            raise ValueError("私有缓存必须位于当前项目内")


@contextmanager
def mutation_lock(config: Config):
    """OS lock automatically releases when a CLI/MCP worker exits."""
    prepare_state(config)
    path = config.state / "mutation.lock"
    if path.is_symlink():
        raise ValueError("缓存锁不能是符号链接")
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            import fcntl
        except ImportError:
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("该项目已有采集或扫描正在写入，请稍后重试") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("该项目已有采集或扫描正在写入，请稍后重试") from None
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def refresh(config: Config, source_id: str | None = None, engine: str | None = None,
            timeout: int | None = None, progress: Progress | None = None) -> dict:
    sources, seconds = validate_refresh(config, source_id, engine, timeout)
    report = progress or (lambda event: None)
    browser = None
    results = []
    with mutation_lock(config):
        try:
            for source in sources:
                report({"source": source.id, "phase": "starting", "message": "准备读取来源"})
                try:
                    if source.adapter == "blackboard" and not source.courses:
                        raise ValueError(f"{source.id}：请配置 courses 的名称和课程 id")
                    if browser is None:
                        browser = browsers.create(replace(config, sources=tuple(sources)), engine)
                    old = storage.read_json(config.state / "sources" / f"{source.id}.json", {})
                    pages = old.get("pages", []) if old.get("identity") == source.identity() else []
                    result = collector.capture(browser, source, seconds, pages, progress=report)
                    data = storage.save(config, source, result)
                    warnings = data.get("warnings", [])
                    results.append({"source": source.id, "status": "partial" if warnings else "ok",
                                    "saved": True, "fetched_at": data["fetched_at"], "warnings": warnings})
                    report({"source": source.id, "phase": "saved", "message": "已采集并保存"})
                except (RuntimeError, ValueError, OSError) as error:
                    storage.health(config, source.id, "error", str(error))
                    results.append({"source": source.id, "status": "error", "saved": False, "message": str(error)})
                    report({"source": source.id, "phase": "error", "message": str(error)})
                storage.render(config)
        finally:
            if browser:
                browser.close()
    failed = any(r["status"] == "error" for r in results)
    partial = failed or any(r["status"] == "partial" for r in results)
    return {"status": "partial" if partial else "ok", "exit_code": 2 if failed else 0,
            "output": config.output, "sources": results, "finished_at": storage.stamp(config)}


def scan_materials(config: Config, include_all: bool = False, progress: Progress | None = None) -> dict:
    report = progress or (lambda event: None)
    with mutation_lock(config):
        report({"phase": "scanning", "message": "正在读取配置目录中的本地资料"})
        data = local.scan(config, include_all=include_all)
        storage.render(config)
    return {"status": "partial" if data["failures"] else "ok", "exit_code": 2 if data["failures"] else 0,
            "scanned": data["scanned"], "indexed": len(data["entries"]), "mode": data["mode"],
            "failures": data["failures"], "output": config.output, "finished_at": data["fetched_at"]}


def inspect_source(config: Config, source_id: str, engine: str | None = None,
                   timeout: int | None = None, progress: Progress | None = None) -> dict:
    sources, seconds = validate_refresh(config, source_id, engine, timeout)
    source = sources[0]
    report = progress or (lambda event: None)
    with mutation_lock(config):
        browser = browsers.create(replace(config, sources=(source,)), engine)
        try:
            deadline = time.monotonic() + seconds
            opened = False
            while time.monotonic() < deadline:
                tabs = [t for t in browser.tabs() if source.allows(t.url, assignment=True)]
                if tabs:
                    break
                if not opened:
                    browser.open(source.home)
                    opened = True
                    report({"source": source_id, "phase": "waiting_for_user", "message": "请在浏览器中登录并打开需要适配的课程列表"})
                browser.pause(1)
            else:
                raise RuntimeError("等待可读取的课程页面超时；没有保存结构快照")
            pages = []
            # Inspection never runs user adapters: broken adapters can still be diagnosed.
            parser = "const SOURCE_CONFIG=" + json.dumps(source.job_config()) + ";let customReader=null;" + (collector.ASSETS / "sites.js").read_text()
            code = "(()=>{" + parser + """
const doc=document;
let selectorCount=null,selectorError=null;
if(SOURCE_CONFIG.options?.selector){try{selectorCount=doc.querySelectorAll(SOURCE_CONFIG.options.selector).length;}catch{selectorError='选择器无效';}}
return JSON.stringify({url:cleanURL(location.href),title:doc.title,html:sanitizeHTML(doc,location.href),
fetched_at:new Date().toISOString(),scope:'当前已加载 DOM 的结构快照；保留隐藏元素；不代表完整作业采集',
diagnostics:{selector_count:selectorCount,selector_error:selectorError,links:doc.querySelectorAll('a[href]').length,
omitted_iframes:doc.querySelectorAll('iframe').length,password_field_present:!!doc.querySelector('input[type=password]')}});
})()"""
            for tab in tabs[:10]:
                report({"source": source_id, "phase": "inspecting", "message": "读取已加载页面的结构"})
                page = json.loads(browser.execute(tab, code))
                if not source.allows(page["url"], assignment=True):
                    raise ValueError("结构快照超出配置来源")
                pages.append(page)
            data = {"source": source_id, "domains": list(source.domains), "pages": pages,
                    "fetched_at": storage.stamp(config), "tab_limit_reached": len(tabs) > 10}
            storage.write_json(config.state / "inspections" / f"{source_id}.json", data)
            return {"status": "partial" if len(tabs) > 10 else "ok", "exit_code": 0, "source": source_id,
                    "saved_snapshots": len(pages), "finished_at": data["fetched_at"],
                    "next_step": "list_evidence kind=snapshot；分页读取结构后编辑本地 adapters/ 下的适配器。"}
        finally:
            browser.close()
