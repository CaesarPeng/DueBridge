from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import Config


@dataclass(frozen=True)
class Tab:
    id: str
    url: str
    window: str = ""


class Browser(Protocol):
    name: str

    def tabs(self) -> list[Tab]: ...
    def open(self, url: str) -> None: ...
    def focus(self, tab: Tab) -> None: ...
    def execute(self, tab: Tab, javascript: str) -> str: ...
    def pause(self, seconds: float) -> None: ...
    def close(self) -> None: ...


def create(config: Config, override: str | None = None) -> Browser:
    engine = override or config.browser
    if engine == "arc":
        from .arc import ArcBrowser
        return ArcBrowser(config)
    from .playwright import PlaywrightBrowser
    return PlaywrightBrowser(config, engine)
