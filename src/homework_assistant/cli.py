from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from . import __version__
from . import browsers, collector, evidence, jobs, local, service, storage
from .config import Config, ENGINES, load

ASSETS = Path(__file__).parent / "assets"


def init(root: Path, preset: str, engine: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "homework.toml"
    if path.exists():
        raise ValueError("homework.toml 已存在；保留现有配置，请直接编辑")
    text = (ASSETS / f"{preset}.toml").read_text(encoding="utf-8")
    if engine:
        text = text.replace('engine = "arc"', f'engine = "{engine}"').replace('engine = "chromium"', f'engine = "{engine}"')
    elif sys.platform != "darwin":
        text = text.replace('engine = "arc"', 'engine = "chromium"')
    storage.write_text(path, text)
    (root / "materials").mkdir(exist_ok=True)
    ignore = root / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    patterns = [".homework/", "homework.toml", "DUEDATES.md", "materials/", ".venv/", ".env", ".env.*", "storage-state*.json", "cookies*.json", "credentials*.json", "*.har"]
    missing = [p for p in patterns if p not in existing.splitlines()]
    if missing:
        storage.write_text(ignore, existing.rstrip() + "\n" + "\n".join(missing) + "\n")
    print(f"已创建：{path}\n请核对启用的平台、课程和浏览器；把本地课程资料放入 materials/。")


def selected(config: Config, id: str | None):
    return service.select_sources(config, id)


def print_progress(event: dict, *, json_mode: bool = False) -> None:
    message = (event.get("source", "") + "：" + event["message"]).lstrip("：")
    print(message, file=sys.stderr if json_mode or event.get("phase") == "error" else sys.stdout, flush=True)


def sync(config: Config, source_id: str | None, engine: str | None, timeout: int | None) -> int:
    result = service.refresh(config, source_id, engine, timeout, print_progress)
    print(f'已保存：{config.root / config.output}')
    return result["exit_code"]


def doctor(root: Path) -> None:
    print(f"DueBridge {__version__}；Python {sys.version.split()[0]}")
    print("Arc：" + ("已安装" if Path("/Applications/Arc.app").is_dir() and sys.platform == "darwin" else "不可用（需要 macOS + Arc）"))
    print("Playwright：" + ("已安装" if importlib.util.find_spec("playwright") else "未安装；Arc 和本地扫描不需要"))
    if (root / "homework.toml").exists():
        config = load(root)
        print(f"配置有效；浏览器 {config.browser}；时区 {config.timezone}")
        for s in config.sources:
            detail = "启用" if s.enabled else "禁用（不等于没有作业）"
            if s.enabled and s.adapter == "blackboard" and not s.courses:
                detail += "；需要填写 courses"
            if s.enabled and s.adapter == "generic" and not s.options.get("selector"):
                detail += "；需要填写 options.selector"
            print(f"  {s.id} ({s.adapter})：{detail}")
    else:
        print("未初始化；运行 homework init --preset zju 或 homework init")
    print("Arc 首次使用：允许当前终端控制 Arc，并手动开启 View → Developer → Allow JavaScript from Apple Events。")
    print("其他内核使用项目专属登录目录；CDP 为显式本机会话连接。doctor 不改变浏览器权限。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="可配置的本地作业资料助手：采集原文，保存来源与覆盖范围")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="配置和输出所在的项目目录")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="生成通用或 ZJU 平台配置，不覆盖已有文件")
    initialize.add_argument("--preset", choices=("generic", "zju"), default="generic")
    initialize.add_argument("--browser", choices=ENGINES)
    commands.add_parser("doctor", help="检查安装及配置，不改变安全设置")
    install = commands.add_parser("browser-install", help="安装可选的 Playwright 浏览器内核")
    install.add_argument("engine", choices=("chromium", "firefox", "webkit"))
    update = commands.add_parser("sync", aliases=["capture", "refresh"], help="采集网页来源并生成 Markdown")
    update.add_argument("--source", help="仅采集一个配置来源")
    update.add_argument("--browser", choices=ENGINES)
    update.add_argument("--timeout", type=int)
    update.add_argument("--json", action="store_true")
    update.add_argument("--background", action="store_true", help="启动后台任务，随后用 job 查询")
    login = commands.add_parser("login", help="打开课程入口，完成正常网页登录")
    login.add_argument("source")
    login.add_argument("--browser", choices=ENGINES)
    scan = commands.add_parser("scan", help="扫描配置路径中的本地课程文件")
    scan.add_argument("--all", action="store_true", help="保留全部支持的资料，不限截止关键词")
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--background", action="store_true")
    overview = commands.add_parser("overview", help="结构化检查来源覆盖、缓存年龄及失败")
    overview.add_argument("--max-age-hours", type=float, default=24)
    listing = commands.add_parser("evidence", help="列出证据编号与来源；默认不含结构诊断快照")
    listing.add_argument("--source")
    listing.add_argument("--kind", choices=evidence.KINDS, default="all")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    search = commands.add_parser("search", help="按原文关键词搜索已保存资料")
    search.add_argument("query")
    search.add_argument("--source")
    search.add_argument("--kind", choices=evidence.KINDS, default="all")
    search.add_argument("--limit", type=int, default=20)
    read = commands.add_parser("read", help="按证据编号分页读取完整资料")
    read.add_argument("evidence_id")
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--max-chars", type=int, default=16000)
    read.add_argument("--revision")
    job = commands.add_parser("job", help="查询后台任务及登录/保存状态")
    job.add_argument("job_id")
    inspect_site = commands.add_parser("inspect", help="保存清理过的 DOM 结构快照，供 Agent 开发小众网站适配器")
    inspect_site.add_argument("source")
    inspect_site.add_argument("--browser", choices=ENGINES)
    inspect_site.add_argument("--timeout", type=int)
    inspect_site.add_argument("--background", action="store_true")
    inspect_site.add_argument("--json", action="store_true")
    adapter = commands.add_parser("adapter-check", help="离线检查本地 HTML 样例的适配器输出，不访问真实站点")
    adapter.add_argument("source")
    adapter.add_argument("--html", type=Path, required=True)
    adapter.add_argument("--url", required=True)
    adapter.add_argument("--engine", choices=("chromium", "firefox", "webkit"), default="chromium")
    mcp = commands.add_parser("mcp", help="可选的 MCP 标准化适配层")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_commands.add_parser("serve", help="通过本地 stdio 提供 MCP，默认仅读取缓存")
    serve.add_argument("--allow-refresh", action="store_true", help="允许启动浏览器采集、本地扫描和结构检查任务")
    mcp_config = mcp_commands.add_parser("config", help="生成通用 MCP 客户端配置，不更改客户端设置")
    mcp_config.add_argument("--allow-refresh", action="store_true")
    commands.add_parser("status", help="列出独立抓取时间和最近错误")
    show = commands.add_parser("show", help="查看现有 Markdown 或原始 JSON")
    show.add_argument("--json", action="store_true", help="输出原始资料、健康状态和本地索引")
    args = parser.parse_args(argv)
    root = args.project.expanduser().resolve()
    try:
        if args.command == "init":
            init(root, args.preset, args.browser)
            return 0
        if args.command == "doctor":
            doctor(root)
            return 0
        if args.command == "browser-install":
            if not importlib.util.find_spec("playwright"):
                raise ValueError('请先安装可选依赖：python -m pip install ".[browser]"')
            return subprocess.run([sys.executable, "-m", "playwright", "install", args.engine]).returncode
        config = load(root)
        def output(data):
            print(json.dumps(data, ensure_ascii=False, indent=2))
        if args.command == "mcp":
            if args.mcp_command == "config":
                arguments = ["-m", "homework_assistant", "--project", str(root), "mcp", "serve"]
                if args.allow_refresh:
                    arguments.append("--allow-refresh")
                output({"mcpServers": {"duebridge": {"command": sys.executable, "args": arguments}}})
            else:
                from .mcp_server import serve
                serve(root, args.allow_refresh)
            return 0
        if args.command == "overview":
            output(evidence.overview(config, args.max_age_hours))
            return 0
        if args.command == "evidence":
            output(evidence.list_evidence(config, args.source, args.kind, args.offset, args.limit))
            return 0
        if args.command == "search":
            output(evidence.search(config, args.query, args.source, args.kind, args.limit))
            return 0
        if args.command == "read":
            output(evidence.read_evidence(config, args.evidence_id, args.offset, args.max_chars, args.revision))
            return 0
        if args.command == "job":
            output(jobs.get(config, args.job_id))
            return 0
        if args.command == "adapter-check":
            from .adapters import check_fixture
            output(check_fixture(config, args.source, args.html, args.url, args.engine))
            return 0
        if args.command in {"sync", "capture", "refresh"}:
            if args.background:
                output(jobs.start(config, "refresh", args.source, args.browser, args.timeout))
                return 0
            if args.json:
                result = service.refresh(config, args.source, args.browser, args.timeout,
                                         lambda event: print_progress(event, json_mode=True))
                output(result)
                return result["exit_code"]
            return sync(config, args.source, args.browser, args.timeout)
        if args.command == "scan":
            if args.background:
                output(jobs.start(config, "scan", include_all=args.all))
                return 0
            result = service.scan_materials(config, args.all)
            if args.json:
                output(result)
            else:
                print(f"已保存：{config.root / config.output}；全文 {result['indexed']} 份，读取失败 {len(result['failures'])} 份。")
            return result["exit_code"]
        if args.command == "inspect":
            if args.background:
                output(jobs.start(config, "inspect", args.source, args.browser, args.timeout))
                return 0
            result = service.inspect_source(config, args.source, args.browser, args.timeout,
                                            lambda event: print_progress(event, json_mode=args.json))
            output(result)
            return result["exit_code"]
        if args.command == "login":
            source = selected(config, args.source)[0]
            browser = browsers.create(replace(config, sources=(source,)), args.browser)
            try:
                browser.open(source.home)
                print("请在浏览器中正常登录；不会自动填写或导出密码。", flush=True)
                if browser.name != "arc":
                    input("登录完成后按 Enter 保存项目会话并关闭此窗口：")
            finally:
                browser.close()
            return 0
        health = storage.read_json(config.state / "health.json", {})
        if args.command == "status":
            for source in config.sources:
                data = storage.read_json(config.state / "sources" / f"{source.id}.json", {})
                current = data.get("identity") == source.identity()
                print(source.id, "禁用" if not source.enabled else storage.local_time(data["fetched_at"], config) if current and data else "未采集当前配置", json.dumps(health.get(source.id, {}), ensure_ascii=False))
            return 0
        if args.json:
            data = {"sources": {s.id: storage.read_json(config.state / "sources" / f"{s.id}.json", {}) for s in config.sources},
                    "health": health, "local": storage.read_json(config.state / "local.json", {})}
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            path = root / config.output
            if not path.exists():
                raise ValueError("没有汇总文件；先运行 homework scan 或 homework sync")
            print(path.read_text(encoding="utf-8"), end="")
        return 0
    except KeyboardInterrupt:
        print("已取消；已保存资料和旧抓取时间保留。", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, EOFError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
