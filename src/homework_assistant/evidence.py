"""Bounded access to captured evidence. No arbitrary filesystem access."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from .config import Config, clean_url
from . import storage

KINDS = ("all", "web", "blackboard", "local", "snapshot")


def safe_cache(config: Config, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("缓存路径超出当前项目")
    # Internal cache locators are independent of the configuration's location.
    path = config.state / relative[len(".homework/"):] if relative.startswith(".homework/") else config.root / relative
    if not path.resolve().is_relative_to(config.state.resolve()):
        raise ValueError("缓存路径超出当前项目")
    current = path
    while current != config.root:
        if current.is_symlink():
            raise ValueError("缓存不能通过符号链接读取")
        current = current.parent
    return path


def read_cache(config: Config, relative: str, default=None):
    return storage.read_json(safe_cache(config, relative), default)


def age_hours(value) -> float | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return round(max(0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600), 2)
    except (AttributeError, ValueError):
        return None


def overview(config: Config, max_age_hours: float = 24) -> dict:
    if not math.isfinite(max_age_hours) or not 0 <= max_age_hours <= 87600:
        raise ValueError("max_age_hours 必须是 0–87600 小时")
    health = read_cache(config, ".homework/health.json", {})
    sources = []
    for source in config.sources:
        data = read_cache(config, f".homework/sources/{source.id}.json", {})
        current = bool(data) and data.get("identity") == source.identity()
        fetched = data.get("fetched_at") if current else None
        age = age_hours(fetched)
        pages = [{"url": clean_url(p["url"]), "title": p.get("title"), "fetched_at": p.get("fetched_at"),
                  "scope": p.get("scope", "范围未提供"), "item_count": p.get("itemCount"),
                  "age_hours": age_hours(p.get("fetched_at"))} for p in data.get("pages", [])
                 if current and source.allows(p.get("url"), assignment=True)]
        courses = [{"id": c["id"], "name": c.get("name"), "fetched_at": c.get("fetched_at", fetched),
                    "stale": c.get("stale", False), "configured": c["id"] in {x["id"] for x in source.courses}}
                   for c in data.get("courses", []) if current]
        sources.append({"id": source.id, "adapter": source.adapter, "enabled": source.enabled,
                        "home": source.home, "cache_matches_config": current,
                        "status": "disabled" if not source.enabled else "captured" if current else "not_captured",
                        "fetched_at": fetched, "age_hours": age,
                        "needs_refresh": source.enabled and (not current or age is None or age > max_age_hours
                                                              or health.get(source.id, {}).get("status") in {"partial", "error"}),
                        "last_attempt": health.get(source.id), "warnings": data.get("warnings", []) if current else [],
                        "pages": pages, "courses": courses, "diagnostics": data.get("diagnostics", {}) if current else {}})
    local = read_cache(config, ".homework/local.json", {})
    return {"schema_version": 1, "generated_at": storage.stamp(config), "timezone": config.timezone,
            "sources": sources, "local": {"status": "scanned" if local else "not_scanned",
                                           "fetched_at": local.get("fetched_at"), "mode": local.get("mode", "deadline_cues"),
                                           "scanned": local.get("scanned", 0), "indexed": len(local.get("entries", [])),
                                           "failures": local.get("failures", [])},
            "interpretation": "日期字段保留原文；未采集不代表没有资料，部分读取不代表完整覆盖，过期不代表未完成。"}


def record_id(kind: str, source: str, key: str) -> str:
    return "ev_" + hashlib.sha256(json.dumps([kind, source, key]).encode()).hexdigest()[:24]


def _record(kind, source, key, text, **metadata):
    return {"id": record_id(kind, source, key), "kind": kind, "source_id": source,
            "revision": hashlib.sha256(text.encode()).hexdigest(), "total_chars": len(text),
            **metadata, "_text": text}


def records(config: Config):
    for source in config.sources:
        if not source.enabled:
            continue
        data = read_cache(config, f".homework/sources/{source.id}.json", {})
        if data.get("identity") != source.identity():
            continue
        for page in data.get("pages", []):
            if not source.allows(page.get("url"), assignment=True):
                continue
            url = clean_url(page["url"])
            yield _record("web", source.id, url, page.get("text", ""), title=page.get("title", source.id),
                          url=url, fetched_at=page.get("fetched_at"), scope=page.get("scope", "范围未提供"),
                          item_count=page.get("itemCount"), warnings=data.get("warnings", []))
        for course in data.get("courses", []):
            from urllib.parse import urlsplit
            parsed = urlsplit(source.home)
            url = f"{parsed.scheme}://{parsed.netloc}/webapps/blackboard/execute/modulepage/view?course_id={course['id']}"
            text = json.dumps(course["columns"], ensure_ascii=False, indent=2)
            yield _record("blackboard", source.id, course["id"], text, title=course.get("name", course["id"]),
                          url=url, fetched_at=course.get("fetched_at", data.get("fetched_at")),
                          scope="配置课程的原始成绩册列；公告/内容页不在此范围", stale=course.get("stale", False),
                          configured_course=course["id"] in {c["id"] for c in source.courses}, warnings=data.get("warnings", []))
    for source in config.sources:
        if not source.enabled:
            continue
        data = read_cache(config, f".homework/inspections/{source.id}.json", {})
        if data.get("domains") != list(source.domains):
            continue
        for page in data.get("pages", []):
            if source.allows(page.get("url"), assignment=True):
                url = clean_url(page["url"])
                yield _record("snapshot", source.id, url, page["html"], title=page.get("title", source.id),
                              url=url, fetched_at=page.get("fetched_at"), scope=page["scope"],
                              diagnostics=page.get("diagnostics", {}))
    local = read_cache(config, ".homework/local.json", {})
    for entry in local.get("entries", []):
        relative = entry.get("text", "")
        prefix = re.escape(str(config.state.relative_to(config.root)))
        if not re.fullmatch(prefix + r"/text/[0-9a-f]{20}\.md", relative):
            raise ValueError("本地索引指向非全文缓存；拒绝读取")
        path = safe_cache(config, relative)
        if not path.is_file():
            continue
        changed = None
        original = config.root / entry["path"]
        if original.resolve().is_relative_to(config.root.resolve()) and original.is_file() and entry.get("fingerprint"):
            stat = original.stat()
            changed = entry["fingerprint"] != {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        yield _record("local", "local", entry["path"], path.read_text(encoding="utf-8"), title=entry["path"],
                      path=entry["path"], fetched_at=entry.get("fetched_at", local.get("fetched_at")),
                      scope="配置目录内提取的全文；无 OCR", original_changed=changed,
                      has_deadline_cue=entry.get("has_deadline_cue"))


def metadata(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "_text"}


def filtered(config: Config, source_id: str | None, kind: str):
    if kind not in KINDS:
        raise ValueError("未知证据类型")
    if source_id is not None and source_id not in {"local", *(s.id for s in config.sources)}:
        raise ValueError("未知来源")
    return [r for r in records(config) if (source_id is None or r["source_id"] == source_id)
            and ((kind == "all" and r["kind"] != "snapshot") or r["kind"] == kind)]


def list_evidence(config: Config, source_id: str | None = None, kind: str = "all", offset: int = 0, limit: int = 50) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("offset 必须非负，limit 必须是 1–200")
    values = filtered(config, source_id, kind)
    end = min(len(values), offset + limit)
    return {"total": len(values), "items": [metadata(r) for r in values[offset:end]],
            "next_offset": end if end < len(values) else None, "timezone": config.timezone}


def search(config: Config, query: str, source_id: str | None = None, kind: str = "all", limit: int = 20) -> dict:
    if not query.strip() or len(query) > 500 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("query 必须为 1–500 字符，limit 必须是 1–100")
    pattern = re.compile(re.escape(query), re.I)
    hits = []
    for record in filtered(config, source_id, kind):
        text = record["_text"]
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 420)
            hits.append({**metadata(record), "match_offset": match.start(), "snippet_offset": start,
                         "snippet": text[start:end], "snippet_only": True})
    return {"query": query, "search_type": "literal_keyword", "total_matches": len(hits), "items": hits[:limit],
            "truncated": len(hits) > limit, "next_step": "按 id 和 revision 读取完整证据，不能只根据片段推断日期。"}


def read_evidence(config: Config, evidence_id: str, offset: int = 0, max_chars: int = 16000,
                  expected_revision: str | None = None) -> dict:
    if not re.fullmatch(r"ev_[0-9a-f]{24}", evidence_id):
        raise ValueError("无效证据编号；请先 list_evidence 或 search_evidence")
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 50000:
        raise ValueError("offset 必须非负，max_chars 必须是 1–50000")
    record = next((r for r in records(config) if r["id"] == evidence_id), None)
    if record is None:
        raise ValueError("证据不存在于当前配置，请重新列出证据")
    if expected_revision is not None and expected_revision != record["revision"]:
        raise ValueError("证据在搜索后已更新，请重新获取 revision 并从头读取")
    text = record["_text"]
    if offset > len(text):
        raise ValueError("offset 超出全文范围")
    end = min(len(text), offset + max_chars)
    return {**metadata(record), "offset": offset, "text": text[offset:end],
            "next_offset": end if end < len(text) else None, "complete_document": offset == 0 and end == len(text),
            "untrusted_content": True, "timezone": config.timezone}
