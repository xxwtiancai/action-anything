"""Action executors, including a zero-dependency dry-run implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from .actions import Action, ActionKind


class Executor(Protocol):
    """Execute one normalized action."""

    is_dry_run: bool

    def execute(self, action: Action) -> Mapping[str, Any]:
        """Execute an action and return JSON-compatible output."""


class DryRunExecutor:
    """Validate an action flow without touching a real browser or desktop."""

    is_dry_run = True

    def execute(self, action: Action) -> Mapping[str, Any]:
        return {
            "message": f"would execute {action.kind.value}",
            "params": dict(action.params),
        }


class PlaywrightExecutor:
    """Optional Playwright-backed browser executor.

    Install it with ``pip install 'actionanything[browser]'`` and then run
    ``playwright install chromium``.
    """

    is_dry_run = False

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def start(self) -> "PlaywrightExecutor":
        if self._page is not None:
            return self
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is optional; install actionanything[browser] first"
            ) from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        return self

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None

    def __enter__(self) -> "PlaywrightExecutor":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def execute(self, action: Action) -> Mapping[str, Any]:
        page = self.start()._page
        params = action.params

        if action.kind is ActionKind.NAVIGATE:
            response = page.goto(str(params["url"]))
            return {
                "url": page.url,
                "status": response.status if response is not None else None,
            }
        if action.kind is ActionKind.CLICK:
            page.locator(str(params["selector"])).click()
            return {"url": page.url}
        if action.kind is ActionKind.TYPE:
            selector = str(params.get("selector") or params["target"])
            page.locator(selector).fill(str(params.get("text", "")))
            return {"selector": selector, "characters": len(str(params.get("text", "")))}
        if action.kind is ActionKind.SCROLL:
            delta_x = int(params.get("delta_x", 0))
            delta_y = int(params.get("delta_y", 500))
            page.mouse.wheel(delta_x, delta_y)
            return {"delta_x": delta_x, "delta_y": delta_y}
        if action.kind is ActionKind.WAIT:
            milliseconds = int(params.get("milliseconds", 500))
            page.wait_for_timeout(milliseconds)
            return {"milliseconds": milliseconds}
        if action.kind is ActionKind.SCREENSHOT:
            path = Path(str(params.get("path", "actionanything-screenshot.png")))
            page.screenshot(path=str(path), full_page=bool(params.get("full_page", False)))
            return {"path": str(path)}
        raise ValueError(f"unsupported action kind: {action.kind.value}")

