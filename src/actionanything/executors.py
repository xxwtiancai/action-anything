"""Action executors, including a zero-dependency dry-run implementation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from .actions import Action, ActionKind
from .policy import host_is_allowed, is_public_http_url, normalize_allowed_domains


class Executor(Protocol):
    """Execute one canonical action."""

    is_dry_run: bool

    def execute(self, action: Action) -> Mapping[str, Any]:
        """Execute an action and return JSON-compatible output."""


class ExecutorSafetyError(RuntimeError):
    """Raised when a real executor refuses an unsafe environment or action."""


class DryRunExecutor:
    """Inspect a validated action flow without touching a browser or desktop."""

    is_dry_run = True

    def execute(self, action: Action) -> Mapping[str, Any]:
        # Do not mirror parameters here. In particular, TYPE parameters can
        # contain credentials and callers should use the Action itself when
        # they intentionally need to inspect a plan.
        return {"message": f"would execute {action.kind.value}"}


class PlaywrightExecutor:
    """Optional, allowlist-contained Playwright browser executor.

    Install with ``pip install 'actionanything[browser]'`` followed by
    ``playwright install chromium``. Real execution requires a non-empty
    hostname allowlist. The browser context blocks requests outside it; this is
    defense in depth, not a replacement for an isolated browser/VM.
    """

    is_dry_run = False

    def __init__(
        self,
        headless: bool = True,
        *,
        allowed_domains: tuple[str, ...] | list[str] | set[str] = (),
        artifact_dir: str | Path = "actionanything-artifacts",
        timeout_milliseconds: int = 30_000,
    ) -> None:
        if timeout_milliseconds <= 0:
            raise ValueError("timeout_milliseconds must be positive")
        self.allowed_domains = normalize_allowed_domains(allowed_domains)
        if not self.allowed_domains:
            raise ValueError(
                "PlaywrightExecutor requires at least one allowed domain for real execution"
            )
        self.headless = headless
        self.timeout_milliseconds = timeout_milliseconds
        self.artifact_dir = Path(artifact_dir).expanduser().resolve()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    def _url_is_allowed(self, url: str) -> bool:
        if not is_public_http_url(url):
            return False
        host = urlparse(url).hostname
        return host is not None and host_is_allowed(host, self.allowed_domains)

    def _route_request(self, route: Any) -> None:
        request = route.request
        url = str(request.url)
        parsed = urlparse(url)
        # The primary page begins at about:blank. Everything it fetches after
        # that must be an explicitly allowed HTTP(S) resource; this blocks
        # file:, data:, blob:, custom protocol, and off-domain requests.
        if parsed.scheme not in {"http", "https"} or not self._url_is_allowed(url):
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _reject_popup(self, popup: Any) -> None:
        # A popup is not an approved execution surface. Closing it prevents
        # click-triggered cross-domain UI interaction even if a browser ignores
        # a blocked subresource request.
        try:
            popup.close()
        except Exception:
            # A popup may already have been closed by the browser. It must not
            # turn a completed primary-page action into an executor crash.
            pass

    @staticmethod
    def _block_web_socket(web_socket: Any) -> None:
        """Keep WebSockets from becoming an un-routed egress path.

        ``route_web_socket`` is installed before the initial page exists, as
        required by Playwright.  A route that does not connect the socket to a
        server is mocked by Playwright; explicitly close it so page code sees a
        deterministic failure rather than an open-but-unforwarded channel.
        """

        try:
            web_socket.close(code=1008, reason="blocked by ActionAnything policy")
        except Exception:
            # The route can already be closed by page teardown. It is still
            # never forwarded to a server because this handler does not call
            # ``connect_to_server``.
            pass

    def _assert_page_url_allowed(self, *, allow_initial_blank: bool = False) -> None:
        if self._page is None:
            return
        url = str(self._page.url)
        if url == "about:blank" and allow_initial_blank:
            return
        if not self._url_is_allowed(url):
            raise ExecutorSafetyError(
                "browser left the configured domain allowlist; further execution stopped"
            )

    def start(self) -> "PlaywrightExecutor":
        if self._page is not None:
            return self
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is optional; install actionanything[browser] first"
            ) from exc

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                # These settings follow the official Computer Use deployment
                # guidance and reduce accidental host-environment exposure.
                env={},
                args=["--disable-extensions", "--disable-file-system"],
            )
            self._context = self._browser.new_context(
                accept_downloads=False,
                service_workers="block",
            )
            self._context.set_default_timeout(self.timeout_milliseconds)
            self._context.set_default_navigation_timeout(self.timeout_milliseconds)
            self._context.route("**/*", self._route_request)
            route_web_socket = getattr(self._context, "route_web_socket", None)
            if route_web_socket is None:
                raise RuntimeError(
                    "Playwright 1.48 or newer is required to contain WebSocket egress"
                )
            route_web_socket("**/*", self._block_web_socket)
            self._page = self._context.new_page()
            # Attach after creating the one approved primary page. New pages
            # created by target=_blank or window.open are popups and are not an
            # approved execution surface.
            self._context.on("page", self._reject_popup)
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        # Always try every cleanup operation; an error while closing the
        # browser should not leak the Playwright driver process.
        errors: list[Exception] = []
        for resource, method in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception as exc:  # Best-effort teardown.
                errors.append(exc)
        self._playwright = self._browser = self._context = self._page = None
        if errors:
            raise RuntimeError("one or more Playwright resources failed to close") from errors[0]

    def __enter__(self) -> "PlaywrightExecutor":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def _screenshot_path(self, requested_path: str | None) -> Path:
        relative = Path(requested_path or f"screenshot-{uuid4().hex}.png")
        candidate = (self.artifact_dir / relative).resolve()
        try:
            candidate.relative_to(self.artifact_dir)
        except ValueError as exc:
            raise ExecutorSafetyError("screenshot path escaped artifact directory") from exc

        # Paths supplied by actions are only relative names. Create each
        # directory with owner-only permissions before letting Playwright
        # write, so nested evidence paths work without widening visibility.
        candidate.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for directory in (self.artifact_dir, candidate.parent):
            try:
                directory.chmod(0o700)
            except OSError:
                pass

        # Reserve a fresh per-action output. This prevents an action from
        # silently overwriting earlier evidence (or targeting an existing
        # symlink) before Playwright receives the path.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(candidate, flags, 0o600)
        except FileExistsError as exc:
            raise ExecutorSafetyError("screenshot path already exists") from exc
        try:
            os.fchmod(descriptor, 0o600)
        except (AttributeError, OSError):
            # Windows and some filesystems do not expose POSIX descriptor
            # permissions; the post-write Path.chmod below remains best effort.
            pass
        finally:
            os.close(descriptor)
        try:
            candidate.chmod(0o600)
        except OSError:
            pass
        return candidate

    def execute(self, action: Action) -> Mapping[str, Any]:
        page = self.start()._page
        # A new context begins at about:blank. It is only an acceptable
        # precondition for a direct, allowlisted navigation; every other
        # action requires a current HTTP(S) page inside the allowlist.
        self._assert_page_url_allowed(
            allow_initial_blank=action.kind is ActionKind.NAVIGATE
        )
        params = action.params

        if action.kind is ActionKind.NAVIGATE:
            url = str(params["url"])
            if not self._url_is_allowed(url):
                raise ExecutorSafetyError("navigation target is outside the domain allowlist")
            response = page.goto(url)
            self._assert_page_url_allowed()
            return {
                "url": page.url,
                "status": response.status if response is not None else None,
            }
        if action.kind is ActionKind.CLICK:
            button = str(params.get("button", "left"))
            if "selector" in params:
                page.locator(str(params["selector"])).click(button=button)
            else:
                page.mouse.click(params["x"], params["y"], button=button)
            self._assert_page_url_allowed()
            return {"url": page.url}
        if action.kind is ActionKind.TYPE:
            text = str(params["text"])
            selector = params.get("selector")
            if selector is not None:
                page.locator(str(selector)).fill(text)
            else:
                page.keyboard.insert_text(text)
            if params.get("press_enter"):
                page.keyboard.press("Enter")
            self._assert_page_url_allowed()
            return {
                "target": "selector" if selector is not None else "focused_input",
                "characters": len(text),
            }
        if action.kind is ActionKind.SCROLL:
            x = params.get("x")
            y = params.get("y")
            if x is not None and y is not None:
                page.mouse.move(x, y)
            delta_x = int(params.get("delta_x", 0))
            delta_y = int(params.get("delta_y", 0))
            page.mouse.wheel(delta_x, delta_y)
            self._assert_page_url_allowed()
            return {"delta_x": delta_x, "delta_y": delta_y}
        if action.kind is ActionKind.WAIT:
            milliseconds = int(params["milliseconds"])
            page.wait_for_timeout(milliseconds)
            self._assert_page_url_allowed()
            return {"milliseconds": milliseconds}
        if action.kind is ActionKind.SCREENSHOT:
            path = self._screenshot_path(params.get("path"))
            try:
                page.screenshot(path=str(path), full_page=bool(params.get("full_page", False)))
                self._assert_page_url_allowed()
            except Exception:
                # The reserved output belongs to this action. Do not leave a
                # partial or out-of-bound screenshot behind on failure.
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            try:
                path.chmod(0o600)
            except OSError:
                pass
            # Traces are often shared for debugging. Keep the host filesystem
            # location private while returning a stable artifact identifier.
            return {"path": path.relative_to(self.artifact_dir).as_posix()}
        raise ValueError(f"unsupported action kind: {action.kind.value}")
