from __future__ import annotations

from ..config import Config, ENGINES, clean_url
from . import Tab


class PlaywrightBrowser:
    """Dedicated profiles by default; explicit local CDP connection as an option."""

    def __init__(self, config: Config, engine: str, *, headless: bool = False):
        if engine not in ENGINES or engine == "arc":
            raise ValueError("未知 Playwright 浏览器")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError('请先安装浏览器支持：python -m pip install ".[browser]"') from None
        self.name = engine
        self.sources = tuple(s for s in config.sources if s.enabled)
        self.runtime = sync_playwright().start()
        self.attached = engine == "cdp"
        self.pages = {}
        try:
            if self.attached:
                self.browser = self.runtime.chromium.connect_over_cdp(config.cdp_endpoint, timeout=15000)
                if not self.browser.contexts:
                    raise RuntimeError("CDP 浏览器没有可用窗口")
                self.context = self.browser.contexts[0]
            else:
                kind = "chromium" if engine in {"chrome", "edge"} else engine
                profile = (config.state / "sessions" / engine).resolve()
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                profile.chmod(0o700)
                options = {"headless": headless, "accept_downloads": False}
                if engine in {"chrome", "edge"}:
                    options["channel"] = "chrome" if engine == "chrome" else "msedge"
                self.context = getattr(self.runtime, kind).launch_persistent_context(str(profile), **options)
        except Exception as error:
            self.runtime.stop()
            if "Could not find profile folder" in str(error):
                raise RuntimeError("Firefox 内核无法打开专用登录目录；请检查系统权限或重新安装内核") from None
            raise RuntimeError(f"{engine} 连接失败；检查安装、浏览器内核或本机 CDP 端口。可运行 homework browser-install {engine if engine in {'chromium','firefox','webkit'} else 'chromium'}") from None

    def tabs(self) -> list[Tab]:
        contexts = self.browser.contexts if self.attached else [self.context]
        result = []
        for context in contexts:
            for page in context.pages:
                if not page.is_closed() and any(s.allows(page.url) for s in self.sources):
                    key = str(id(page))
                    self.pages[key] = page
                    result.append(Tab(key, page.url))
        return result

    def open(self, url: str) -> None:
        if not any(s.allows(url) for s in self.sources):
            raise ValueError("页面不在配置域名中")
        page = self.context.new_page()
        try:
            page.goto(clean_url(url), timeout=30000, wait_until="domcontentloaded")
        except Exception:
            # SSO navigation can outlive the initial navigation timeout.
            if page.is_closed():
                raise RuntimeError("课程窗口已关闭") from None

    def focus(self, tab: Tab) -> None:
        try:
            self.pages[tab.id].bring_to_front()
        except Exception:
            raise RuntimeError("课程标签页已关闭或无法切换") from None

    def execute(self, tab: Tab, javascript: str) -> str:
        page = self.pages[tab.id]
        if not any(s.allows(page.url) for s in self.sources):
            raise RuntimeError("页面已离开配置的课程域名")
        try:
            result = page.evaluate(javascript)
        except Exception:
            raise RuntimeError("页面正在导航或已关闭；请待课程列表加载后重试") from None
        if not isinstance(result, str):
            raise RuntimeError("浏览器没有返回文本结果")
        return result

    def pause(self, seconds: float) -> None:
        # Process protocol events while waiting; time.sleep would stall the sync client.
        for context in (self.browser.contexts if self.attached else [self.context]):
            for page in context.pages:
                if not page.is_closed():
                    page.wait_for_timeout(seconds * 1000)
                    return
        raise RuntimeError("没有可用浏览器窗口")

    def close(self) -> None:
        try:
            if not self.attached:
                self.context.close()
        finally:
            # Disconnect CDP without issuing Browser.close to the user's browser.
            self.runtime.stop()
