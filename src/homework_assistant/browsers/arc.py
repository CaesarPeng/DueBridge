from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from ..config import Config, clean_url
from . import Tab

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class ArcBrowser:
    name = "arc"

    def __init__(self, config: Config):
        if sys.platform != "darwin" or not Path("/Applications/Arc.app").is_dir():
            raise RuntimeError("Arc 接入需要 macOS 和 /Applications/Arc.app；其他系统可选 chromium/firefox/webkit")
        self.sources = tuple(s for s in config.sources if s.enabled)
        self.domains = ",".join(sorted({d for s in self.sources for d in s.domains}))

    def _call(self, action: str, *args) -> str:
        try:
            result = subprocess.run(["osascript", str(ASSETS / "arc.applescript"), action, self.domains, *map(str, args)],
                                    capture_output=True, text=True, timeout=35)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Arc 响应超时；请恢复窗口后重试") from None
        if result.returncode:
            error = result.stderr.lower()
            if "-1743" in error or "not authorized" in error or "not permitted" in error:
                raise RuntimeError("请在系统设置 → 隐私与安全性 → 自动化，允许运行 CLI 的终端控制 Arc")
            if "javascript" in error or "apple events" in error:
                raise RuntimeError("请在 Arc 的 View → Developer 中手动开启 Allow JavaScript from Apple Events")
            raise RuntimeError("Arc 页面读取失败；请检查登录、窗口和权限")
        return result.stdout.strip()

    def tabs(self) -> list[Tab]:
        return [Tab(str(t), u, str(w)) for w, t, u in json.loads(self._call("list") or "[]")
                if any(s.allows(u) for s in self.sources)]

    def open(self, url: str) -> None:
        if not any(s.allows(url) for s in self.sources):
            raise ValueError("页面不在配置域名中")
        self._call("open", clean_url(url))

    def focus(self, tab: Tab) -> None:
        self._call("focus", tab.window, tab.id)

    def execute(self, tab: Tab, javascript: str) -> str:
        with tempfile.TemporaryDirectory(prefix="homework-arc-") as folder:
            script = Path(folder) / "read.js"
            script.write_text(javascript, encoding="utf-8")
            script.chmod(0o600)
            raw = self._call("execute", tab.window, tab.id, script)
        try:
            value = json.loads(raw)
        except ValueError:
            return raw
        return value if isinstance(value, str) else raw

    def pause(self, seconds: float) -> None:
        time.sleep(seconds)

    def close(self) -> None:
        pass  # The user's browser stays open.
