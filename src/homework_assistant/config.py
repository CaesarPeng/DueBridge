from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENGINES = ("arc", "chromium", "chrome", "edge", "firefox", "webkit", "cdp")
ADAPTERS = ("blackboard", "webassign", "smartphysics", "zjuilearn", "prairielearn", "generic", "custom")
PRIVATE = frozenset("userpass password passwd auth authorization access_token id_token refresh_token token session sessionid sid code state ticket csrf csrf_token signature".split())


def host_matches(host: str, pattern: str) -> bool:
    host, pattern = host.lower(), pattern.lower()
    return host.endswith(pattern[1:]) if pattern.startswith("*.") else host == pattern


def clean_url(raw: str) -> str:
    u = urlsplit(raw)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError("课程来源必须是没有用户名、密码或非标准端口的 HTTPS URL")
    query = urlencode([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in PRIVATE])
    return urlunsplit((u.scheme, u.netloc, u.path, query, ""))


@dataclass(frozen=True)
class Source:
    id: str
    adapter: str
    home: str
    domains: tuple[str, ...]
    assignment_domains: tuple[str, ...] = ()
    courses: tuple[dict, ...] = ()
    enabled: bool = True
    options: dict = field(default_factory=dict)
    reader_code: str = ""

    def allows(self, url: str, *, assignment: bool = False) -> bool:
        try:
            clean_url(url)
            patterns = self.assignment_domains if assignment and self.assignment_domains else self.domains
            return any(host_matches(urlsplit(url).hostname or "", p) for p in patterns)
        except (TypeError, ValueError):
            return False

    def job_config(self) -> dict:
        return {"platform": self.adapter, "home": self.home, "domains": self.domains,
                "assignment_domains": self.assignment_domains or self.domains,
                "courses": self.courses, "options": self.options}

    def identity(self) -> dict:
        result = {"adapter": self.adapter, "domains": list(self.domains)}
        if self.adapter in {"generic", "custom"}:
            result["options"] = self.options
        if self.adapter == "custom":
            result["reader_revision"] = hashlib.sha256(self.reader_code.encode()).hexdigest()
        return result


@dataclass(frozen=True)
class Config:
    root: Path
    timezone: str
    browser: str
    timeout: int
    output: str
    local_paths: tuple[str, ...]
    sources: tuple[Source, ...]
    cdp_endpoint: str = "http://127.0.0.1:9222"
    state_directory: str = ".homework"

    @property
    def state(self) -> Path:
        return self.root / self.state_directory


def config_path(root: Path) -> Path:
    """Keep course paths relative to the workspace even with a nested config."""
    primary = root / "homework.toml"
    nested = root / "tools" / "duebridge" / "homework.toml"
    return nested if not primary.exists() and nested.is_file() else primary


def relative_path(value, name: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"{name} 必须是项目内的相对路径")
    if any(p in {".homework", ".venv", ".git"} for p in Path(value).parts):
        raise ValueError(f"{name} 不能指向会话、依赖或版本控制目录")
    return value


def domains(values, name: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} 必须是非空域名列表")
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{name} 包含无效域名")
        value = value.lower()
        host = value.removeprefix("*.")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
            raise ValueError(f"{name} 包含无效域名：{value}")
        result.append(value)
    return tuple(result)


def load(root: Path) -> Config:
    root = root.expanduser().resolve()
    path = config_path(root)
    if not path.is_file():
        raise ValueError("找不到 homework.toml；先运行 homework init --preset zju，或 homework init")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"homework.toml 格式错误：{error}") from None
    browser = data.get("browser", {})
    if not isinstance(browser, dict) or not isinstance(data.get("local", {}), dict):
        raise ValueError("browser 和 local 必须是 TOML 配置表")
    engine = browser.get("engine", "arc")
    if engine not in ENGINES:
        raise ValueError("未知浏览器；可用：" + ", ".join(ENGINES))
    timeout = browser.get("timeout", 180)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("browser.timeout 必须是 1–3600 秒的整数")
    endpoint = browser.get("cdp_endpoint", "http://127.0.0.1:9222")
    if not isinstance(endpoint, str):
        raise ValueError("browser.cdp_endpoint 必须是字符串")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "ws"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
        raise ValueError("CDP 仅允许本机 http/ws 地址")
    timezone = data.get("timezone", "Asia/Shanghai")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("未知 timezone；请填写 IANA 时区，例如 Asia/Shanghai") from None
    output = relative_path(data.get("output", "DUEDATES.md"), "output")
    if output == "homework.toml" or Path(output).suffix.lower() != ".md":
        raise ValueError("output 必须是 Markdown 文件，且不能覆盖配置")
    local = data.get("local", {}).get("paths", ["materials"])
    if not isinstance(local, list):
        raise ValueError("local.paths 必须是相对路径列表")
    local = tuple(relative_path(x, "local.paths") for x in local)
    sources, ids = [], set()
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("sources 必须使用 [[sources]] 配置列表")
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("sources 必须使用 [[sources]] 配置列表")
        id = raw.get("id", "")
        if not isinstance(id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", id) or id in ids:
            raise ValueError("每个 source.id 必须是唯一的字母开头的小写名称")
        ids.add(id)
        adapter = raw.get("adapter", "generic")
        if adapter not in ADAPTERS:
            raise ValueError(f"{id} 的 adapter 未知；可用：{', '.join(ADAPTERS)}")
        home = raw.get("home", "")
        if not isinstance(home, str):
            raise ValueError(f"{id}.home 必须是 HTTPS URL 字符串")
        clean = clean_url(home)
        if any(k.lower() in PRIVATE for k, _ in parse_qsl(urlsplit(home).query)):
            raise ValueError(f"{id}.home 不能包含登录凭据参数")
        allowed = domains(raw.get("domains", []), f"{id}.domains")
        assignment = domains(raw["assignment_domains"], f"{id}.assignment_domains") if "assignment_domains" in raw else ()
        for pattern in assignment:
            host = pattern.removeprefix("*.")
            if not any((p.startswith("*.") and (pattern == p or host_matches(host, p))) if pattern.startswith("*.") else host_matches(host, p) for p in allowed):
                raise ValueError(f"{id}.assignment_domains 必须包含在 domains 中")
        courses = raw.get("courses", [])
        if not isinstance(courses, list) or any(not isinstance(c, dict) or not isinstance(c.get("name"), str) or not re.fullmatch(r"_[0-9]+_[0-9]+", str(c.get("id", ""))) for c in courses):
            raise ValueError(f"{id}.courses 必须包含 name 和 Blackboard 课程 id（如 _1234_1）")
        enabled = raw.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(f"{id}.enabled 必须是 true 或 false")
        options = raw.get("options", {})
        if not isinstance(options, dict) or any(not isinstance(v, str) for v in options.values()):
            raise ValueError(f"{id}.options 必须是字符串配置表")
        allowed_options = {"selector", "empty_selector", "list_links", "list_url_pattern", "max_pages"}
        if adapter != "custom" and set(options) - allowed_options:
            raise ValueError(f"{id}.options 包含未知字段")
        if "max_pages" in options and (not options["max_pages"].isdigit() or not 1 <= int(options["max_pages"]) <= 100):
            raise ValueError(f"{id}.options.max_pages 必须是字符串形式的 1–100")
        code = ""
        if adapter == "custom":
            relative = relative_path(raw.get("reader", ""), f"{id}.reader")
            reader = root / relative
            if not relative.startswith("adapters/") or reader.suffix != ".js":
                raise ValueError(f"{id}.reader 必须位于项目 adapters/ 下，且为 .js")
            if not reader.resolve().is_relative_to(root / "adapters") or reader.is_symlink():
                raise ValueError("自定义适配器不能通过符号链接加载")
            if enabled:
                if not reader.is_file() or reader.stat().st_size > 200_000:
                    raise ValueError(f"{id}.reader 不存在或超过 200 KB")
                code = reader.read_text(encoding="utf-8")
        source = Source(id, adapter, clean, allowed, assignment, tuple(courses), enabled, options, code)
        if not source.allows(clean):
            raise ValueError(f"{id}.home 不在配置的域名范围内")
        sources.append(source)
    state_directory = str(path.parent.relative_to(root) / ".homework")
    return Config(root, timezone, engine, timeout, output, local, tuple(sources), endpoint, state_directory)
