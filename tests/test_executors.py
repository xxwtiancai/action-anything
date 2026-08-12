import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from actionanything import Action, ActionKind
from actionanything.executors import ExecutorSafetyError, PlaywrightExecutor


class FakeLocator:
    def __init__(self, events, selector, page):
        self.events = events
        self.selector = selector
        self.page = page

    def click(self, *, button):
        self.events.append(("locator.click", self.selector, button))
        if self.page.url_after_click is not None:
            self.page.url = self.page.url_after_click

    def fill(self, text):
        self.events.append(("locator.fill", self.selector, text))


class FakeMouse:
    def __init__(self, events):
        self.events = events

    def click(self, x, y, *, button):
        self.events.append(("mouse.click", x, y, button))

    def move(self, x, y):
        self.events.append(("mouse.move", x, y))

    def wheel(self, x, y):
        self.events.append(("mouse.wheel", x, y))


class FakeKeyboard:
    def __init__(self, events):
        self.events = events

    def insert_text(self, text):
        self.events.append(("keyboard.insert_text", text))

    def press(self, key):
        self.events.append(("keyboard.press", key))


class FakePage:
    def __init__(self, url="https://example.com/start"):
        self.url = url
        self.events = []
        self.url_after_click = None
        self.url_after_goto = None
        self.url_after_screenshot = None
        self.mouse = FakeMouse(self.events)
        self.keyboard = FakeKeyboard(self.events)

    def locator(self, selector):
        return FakeLocator(self.events, selector, self)

    def goto(self, url):
        self.url = self.url_after_goto or url
        self.events.append(("goto", url))
        return None

    def wait_for_timeout(self, milliseconds):
        self.events.append(("wait", milliseconds))

    def screenshot(self, *, path, full_page):
        self.events.append(("screenshot", path, full_page))
        Path(path).write_bytes(b"fake png")
        if self.url_after_screenshot is not None:
            self.url = self.url_after_screenshot


class FakeRequest:
    def __init__(self, url):
        self.url = url


class FakeRoute:
    def __init__(self, url):
        self.request = FakeRequest(url)
        self.events = []

    def abort(self, reason):
        self.events.append(("abort", reason))

    def continue_(self):
        self.events.append(("continue",))


class FakePopup:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeWebSocket:
    def __init__(self):
        self.closed_with = None

    def close(self, *, code, reason):
        self.closed_with = (code, reason)


class FakeContext:
    def __init__(self):
        self.options = None
        self.default_timeout = None
        self.navigation_timeout = None
        self.routes = []
        self.web_socket_routes = []
        self.handlers = {}
        self.page = FakePage("about:blank")
        self.closed = False

    def set_default_timeout(self, milliseconds):
        self.default_timeout = milliseconds

    def set_default_navigation_timeout(self, milliseconds):
        self.navigation_timeout = milliseconds

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def route_web_socket(self, pattern, handler):
        self.web_socket_routes.append((pattern, handler))

    def new_page(self):
        return self.page

    def on(self, event, handler):
        self.handlers[event] = handler

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.closed = False

    def new_context(self, **options):
        self.context.options = options
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_options = None

    def launch(self, **options):
        self.launch_options = options
        return self.browser


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakePlaywrightStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class PlaywrightExecutorTests(unittest.TestCase):
    def _executor(self, page, artifact_dir=None):
        executor = PlaywrightExecutor(
            allowed_domains=["example.com"],
            artifact_dir=artifact_dir or "actionanything-artifacts-test",
        )
        executor._page = page
        return executor

    def test_selector_and_coordinate_click_use_correct_path(self) -> None:
        page = FakePage()
        executor = self._executor(page)

        executor.execute(Action(ActionKind.CLICK, {"selector": "#submit", "button": "right"}))
        executor.execute(Action(ActionKind.CLICK, {"x": 10, "y": 20}))

        self.assertIn(("locator.click", "#submit", "right"), page.events)
        self.assertIn(("mouse.click", 10, 20, "left"), page.events)

    def test_selector_and_focused_type_use_correct_path(self) -> None:
        page = FakePage()
        executor = self._executor(page)

        selector_result = executor.execute(
            Action(ActionKind.TYPE, {"selector": "#name", "text": "Ada", "press_enter": True})
        )
        focused_result = executor.execute(Action(ActionKind.TYPE, {"text": "Grace"}))

        self.assertIn(("locator.fill", "#name", "Ada"), page.events)
        self.assertIn(("keyboard.press", "Enter"), page.events)
        self.assertIn(("keyboard.insert_text", "Grace"), page.events)
        self.assertEqual(selector_result["target"], "selector")
        self.assertEqual(focused_result["target"], "focused_input")

    def test_scroll_moves_pointer_when_provider_supplies_coordinates(self) -> None:
        page = FakePage()
        executor = self._executor(page)
        executor.execute(
            Action(ActionKind.SCROLL, {"x": 10, "y": 20, "delta_x": 0, "delta_y": 500})
        )
        self.assertIn(("mouse.move", 10, 20), page.events)
        self.assertIn(("mouse.wheel", 0, 500), page.events)

    def test_navigation_and_current_page_are_allowlist_checked(self) -> None:
        page = FakePage()
        executor = self._executor(page)
        with self.assertRaises(ExecutorSafetyError):
            executor.execute(Action(ActionKind.NAVIGATE, {"url": "https://evil.test"}))

        page.url = "https://evil.test/redirect"
        with self.assertRaises(ExecutorSafetyError):
            executor.execute(Action(ActionKind.CLICK, {"selector": "#safe"}))

    def test_request_routing_rejects_non_http_and_off_domain_urls(self) -> None:
        executor = self._executor(FakePage())

        allowed = FakeRoute("https://cdn.example.com/app.js")
        executor._route_request(allowed)
        self.assertEqual(allowed.events, [("continue",)])

        for url in (
            "file:///etc/passwd",
            "data:text/plain,not-a-page",
            "blob:https://example.com/id",
            "mailto:owner@example.com",
            "https://evil.test/script.js",
            "http://127.0.0.1/admin",
            "https://faß.de/",
        ):
            with self.subTest(url=url):
                route = FakeRoute(url)
                executor._route_request(route)
                self.assertEqual(route.events, [("abort", "blockedbyclient")])

    def test_executor_requires_ascii_punycode_domain_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "ASCII hostnames"):
            PlaywrightExecutor(allowed_domains=["faß.de"])

        executor = PlaywrightExecutor(allowed_domains=["xn--fa-hia.de"])
        allowed = FakeRoute("https://xn--fa-hia.de/")
        executor._route_request(allowed)
        self.assertEqual(allowed.events, [("continue",)])
        self.assertFalse(executor._url_is_allowed("https://faß.de/"))
        collision_executor = PlaywrightExecutor(allowed_domains=["fass.de"])
        self.assertFalse(collision_executor._url_is_allowed("https://faß.de/"))
        executor._page = FakePage("https://faß.de/")
        with self.assertRaises(ExecutorSafetyError):
            executor._assert_page_url_allowed()

    def test_start_blocks_workers_downloads_and_popups(self) -> None:
        context = FakeContext()
        browser = FakeBrowser(context)
        chromium = FakeChromium(browser)
        playwright = FakePlaywright(chromium)
        package = ModuleType("playwright")
        sync_api = ModuleType("playwright.sync_api")
        sync_api.sync_playwright = lambda: FakePlaywrightStarter(playwright)
        package.sync_api = sync_api
        executor = PlaywrightExecutor(
            False,
            allowed_domains=["example.com"],
            timeout_milliseconds=1_234,
        )

        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": sync_api},
        ):
            executor.start()

        self.assertEqual(context.options, {"accept_downloads": False, "service_workers": "block"})
        self.assertEqual(context.default_timeout, 1_234)
        self.assertEqual(context.navigation_timeout, 1_234)
        self.assertEqual(context.routes[0][0], "**/*")
        self.assertEqual(context.web_socket_routes[0][0], "**/*")
        self.assertIn("page", context.handlers)
        self.assertFalse(chromium.launch_options["headless"])
        self.assertEqual(chromium.launch_options["env"], {})

        popup = FakePopup()
        context.handlers["page"](popup)
        self.assertTrue(popup.closed)
        web_socket = FakeWebSocket()
        context.web_socket_routes[0][1](web_socket)
        self.assertEqual(web_socket.closed_with[0], 1008)
        executor.close()
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)

    def test_post_action_url_containment_rejects_redirects_and_blank_pages(self) -> None:
        page = FakePage()
        page.url_after_goto = "file:///etc/passwd"
        executor = self._executor(page)
        with self.assertRaises(ExecutorSafetyError):
            executor.execute(Action(ActionKind.NAVIGATE, {"url": "https://example.com/"}))

        page = FakePage()
        page.url_after_click = "about:blank"
        executor = self._executor(page)
        with self.assertRaises(ExecutorSafetyError):
            executor.execute(Action(ActionKind.CLICK, {"selector": "#redirect"}))

        with tempfile.TemporaryDirectory() as directory:
            page = FakePage()
            page.url_after_screenshot = "https://evil.test/"
            executor = self._executor(page, Path(directory) / "artifacts")
            with self.assertRaises(ExecutorSafetyError):
                executor.execute(Action(ActionKind.SCREENSHOT, {"path": "step.png"}))
            self.assertFalse((Path(directory) / "artifacts" / "step.png").exists())

    def test_only_navigation_may_begin_from_initial_blank_page(self) -> None:
        page = FakePage("about:blank")
        executor = self._executor(page)
        with self.assertRaises(ExecutorSafetyError):
            executor.execute(Action(ActionKind.SCREENSHOT, {"path": "blank.png"}))

        result = executor.execute(Action(ActionKind.NAVIGATE, {"url": "https://example.com/"}))
        self.assertEqual(result["url"], "https://example.com/")

    def test_screenshot_is_confined_to_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory) / "artifacts"
            page = FakePage()
            executor = self._executor(page, artifact_dir)
            result = executor.execute(
                Action(ActionKind.SCREENSHOT, {"path": "steps/one.png", "full_page": True})
            )
            self.assertEqual(result["path"], "steps/one.png")
            written_path = artifact_dir.resolve() / result["path"]
            self.assertTrue(written_path.is_relative_to(artifact_dir.resolve()))
            self.assertIn(("screenshot", str(written_path), True), page.events)
            self.assertEqual(written_path.read_bytes(), b"fake png")
            self.assertEqual(written_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(artifact_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual((artifact_dir / "steps").stat().st_mode & 0o777, 0o700)

    def test_screenshot_paths_are_fresh_and_cannot_overwrite_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory) / "artifacts"
            executor = self._executor(FakePage(), artifact_dir)

            first = executor._screenshot_path(None)
            second = executor._screenshot_path(None)
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_relative_to(artifact_dir.resolve()))
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)

            with self.assertRaisesRegex(ExecutorSafetyError, "already exists"):
                executor._screenshot_path(first.relative_to(artifact_dir.resolve()).as_posix())

    def test_executor_defends_against_escaping_screenshot_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executor = self._executor(FakePage(), Path(directory) / "artifacts")
            with self.assertRaisesRegex(ExecutorSafetyError, "escaped artifact directory"):
                executor._screenshot_path("../outside.png")

    def test_executor_requires_allowlist(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires at least one allowed domain"):
            PlaywrightExecutor()


if __name__ == "__main__":
    unittest.main()
