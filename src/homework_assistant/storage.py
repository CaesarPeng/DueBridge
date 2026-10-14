from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from .config import Config, Source, clean_url


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_text(path: Path, text: str, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, data) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", private=True)


def stamp(config: Config) -> str:
    return datetime.now(ZoneInfo(config.timezone)).isoformat()


def timestamp(value) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("抓取时间必须含时区")
        return parsed.timestamp()
    except (TypeError, AttributeError, ValueError):
        raise ValueError("返回资料包含无效抓取时间") from None


def save(config: Config, source: Source, result: dict) -> dict:
    path = config.state / "sources" / f"{source.id}.json"
    old = read_json(path, {})
    if old.get("identity") != source.identity():
        old = {}
    warnings = list(result.get("warnings", []))
    if source.adapter == "blackboard":
        api = result.get("api", {})
        courses = api.get("courses", [])
        if not courses:
            raise ValueError("没有新的 Blackboard 课程数据；旧资料保留")
        timestamp(api.get("fetched_at"))
        allowed = {c["id"] for c in source.courses}
        if any(c.get("id") not in allowed for c in courses):
            raise ValueError("返回的 Blackboard 课程不在配置中")
        courses = [{k: c[k] for k in ("id", "name", "columns", "fetched_at") if k in c} for c in courses]
        ids = {c["id"] for c in courses}
        courses += [{**c, "stale": True} for c in old.get("courses", []) if c["id"] not in ids and c["id"] in allowed]
        data = {"courses": courses, "fetched_at": api["fetched_at"], "errors": api.get("errors", [])}
    else:
        if not result.get("pages"):
            raise ValueError("没有新课程文本；旧资料保留")
        pages = {clean_url(p["url"]): p for p in old.get("pages", []) if source.allows(p["url"], assignment=True)}
        for raw in result["pages"]:
            if not source.allows(raw["url"], assignment=True):
                raise ValueError("返回页面来源超出配置域名；旧资料保留")
            timestamp(raw.get("fetched_at"))
            page = {k: raw[k] for k in ("title", "text", "fetched_at", "scope", "itemCount", "empty") if k in raw}
            page["url"] = clean_url(raw["url"])
            previous = pages.get(page["url"])
            if previous is None or timestamp(page["fetched_at"]) >= timestamp(previous["fetched_at"]):
                pages[page["url"]] = page
        data = {"pages": list(pages.values()), "fetched_at": max((p["fetched_at"] for p in pages.values()), key=timestamp)}
    data.update({"identity": source.identity(), "warnings": warnings, "home": source.home})
    write_json(path, data)
    health(config, source.id, "partial" if warnings else "ok", "；".join(warnings) or "已保存课程列表原文")
    return data


def health(config: Config, id: str, status: str, message: str) -> None:
    path = config.state / "health.json"
    data = read_json(path, {})
    data[id] = {"attempted_at": stamp(config), "status": status, "message": message}
    write_json(path, data)


def cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def local_time(value: str, config: Config) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(config.timezone)).isoformat()
    except (ValueError, AttributeError):
        return value


def render(config: Config) -> Path:
    attempts = read_json(config.state / "health.json", {})
    out = ["# 作业来源原始资料", "", f"汇总生成时间：{stamp(config)}（{config.timezone}）。", "",
           "这里只保存原文和平台字段。截止日期、时区、是否提交、去重、旧学期及规则冲突需要结合完整来源判断。",
           "未采集不代表没有作业，部分列表不代表全部作业，过期不代表未完成。日期冲突请同时保留来源，并按较早时间安排。", "",
           "## 来源覆盖", "", "| 来源 | 抓取时间（配置时区） | 范围 / 最近尝试 |", "| --- | --- | --- |"]
    bodies = []
    for source in config.sources:
        data = read_json(config.state / "sources" / f"{source.id}.json", {})
        if not source.enabled:
            out.append(f"| {cell(source.id)} | — | 配置禁用；没有进行采集 |")
            continue
        if data and data.get("identity") != source.identity():
            out.append(f"| {cell(source.id)} | 未采集当前配置 | 域名或适配器已变化，旧缓存仍保留 |")
            continue
        attempt = attempts.get(source.id, {})
        count = f"{len(data.get('courses', []))} 门配置课程的原始作业列" if source.adapter == "blackboard" else f"{len(data.get('pages', []))} 页；每页时间及范围见下文"
        out.append(f"| {cell(source.id)} | {cell(local_time(data['fetched_at'], config) if data else '未采集')} | {cell(count if data else source.home)}；{cell(attempt.get('status', '未尝试'))} {cell(attempt.get('message', ''))} |")
        bodies.extend(["", f"## {source.id}", "", f"[平台入口]({source.home})", ""])
        for course in data.get("courses", []):
            from urllib.parse import urlsplit
            origin = urlsplit(source.home)
            url = f"{origin.scheme}://{origin.netloc}/webapps/blackboard/execute/modulepage/view?course_id={course['id']}"
            bodies.extend([f"### {course['name']}", "", f"[课程原站]({url})", "",
                           f"读取时间：{local_time(course.get('fetched_at', data['fetched_at']), config)}；旧缓存：{course.get('stale', False)}。", "",
                           "```json", json.dumps(course["columns"], ensure_ascii=False, indent=2).replace("```", "``\u200b`"), "```", ""])
        for page in data.get("pages", []):
            bodies.extend([f"### {page.get('title') or source.id}", "", f"来源：[{page['url']}]({page['url']})", "",
                           f"读取时间：{local_time(page['fetched_at'], config)}（原始时间：{page['fetched_at']}）",
                           f"范围：{page.get('scope', '原始页面')}；记录数：{page.get('itemCount', '未提供')}。", "",
                           "```text", page["text"].replace("```", "``\u200b`"), "```", ""])
        if data.get("warnings"):
            bodies.extend(["读取限制：" + "；".join(data["warnings"]), ""])
    out.extend(bodies)
    local = read_json(config.state / "local.json", {})
    out.extend(["", "## 本地全文索引", "", f"已读取 {local.get('scanned', 0)} 份文件；保留 {len(local.get('entries', []))} 份含截止日期关键词的全文。未做 OCR。", ""])
    from urllib.parse import quote
    for entry in local.get("entries", []):
        link = os.path.relpath(config.root / entry["text"], (config.root / config.output).parent)
        out.append(f"- [{entry['path']}]({quote(link, safe='/')})：{entry['sample']}")
    if local.get("failures"):
        out.extend(["", "读取失败：", "", "```json", json.dumps(local["failures"], ensure_ascii=False, indent=2), "```"])
    output = config.root / config.output
    write_text(output, "\n".join(out) + "\n")
    return output
