import unittest

from actionanything import Action, ActionKind, RiskLevel
from actionanything.actions import ActionValidationError


class ActionTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        action = Action(
            ActionKind.CLICK,
            {"selector": "#submit"},
            RiskLevel.REVERSIBLE,
            id="action-1",
            metadata={"source": "test"},
        )

        self.assertEqual(Action.from_dict(action.to_dict()), action)

    def test_missing_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "requires 'kind'"):
            Action.from_dict({"params": {}})

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "unsupported action kind"):
            Action.from_dict({"kind": "launch_missile"})

    def test_click_requires_exactly_one_target(self) -> None:
        invalid_params = (
            {},
            {"x": 10},
            {"selector": "#submit", "x": 10, "y": 20},
        )
        for params in invalid_params:
            with self.subTest(params=params):
                with self.assertRaises(ActionValidationError):
                    Action(ActionKind.CLICK, params)

        selector = Action(ActionKind.CLICK, {"selector": "#submit"})
        coordinates = Action(ActionKind.CLICK, {"x": 10, "y": 20, "button": "right"})
        self.assertEqual(selector.params["selector"], "#submit")
        self.assertEqual(coordinates.params["button"], "right")

    def test_navigation_only_accepts_safe_http_urls(self) -> None:
        for url in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://user:password@example.com",
            "https://example.com/a path",
            "https://[::1",
            "not-a-url",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ActionValidationError):
                    Action(ActionKind.NAVIGATE, {"url": url})

    def test_unknown_action_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "does not support"):
            Action(ActionKind.CLICK, {"selector": "#submit", "force": True})

    def test_type_and_bounded_values_are_validated(self) -> None:
        with self.assertRaises(ActionValidationError):
            Action(ActionKind.TYPE, {"selector": "#x"})
        with self.assertRaises(ActionValidationError):
            Action(ActionKind.TYPE, {"text": 1})
        with self.assertRaises(ActionValidationError):
            Action(ActionKind.WAIT, {"milliseconds": 60_001})
        with self.assertRaises(ActionValidationError):
            Action(ActionKind.SCROLL, {"delta_y": 0})
        with self.assertRaises(ActionValidationError):
            Action(ActionKind.SCROLL, {"delta_y": True})

    def test_screenshot_path_is_constrained(self) -> None:
        for path in ("../secret.png", "/tmp/secret.png", "image.jpg", "a\\b.png"):
            with self.subTest(path=path):
                with self.assertRaises(ActionValidationError):
                    Action(ActionKind.SCREENSHOT, {"path": path})

        action = Action(ActionKind.SCREENSHOT, {"path": "evidence/step-1.png"})
        self.assertEqual(action.params["path"], "evidence/step-1.png")

    def test_risk_can_be_elevated_but_not_lowered(self) -> None:
        click = Action(ActionKind.CLICK, {"selector": "#submit"})
        self.assertIs(click.risk, RiskLevel.REVERSIBLE)

        model_payload = {
            "kind": "type",
            "params": {"selector": "#email", "text": "hello"},
            "risk": 0,
        }
        self.assertIs(Action.from_dict(model_payload).risk, RiskLevel.REVERSIBLE)
        elevated = Action(ActionKind.CLICK, {"selector": "#submit"}, RiskLevel.CRITICAL)
        self.assertIs(elevated.risk, RiskLevel.CRITICAL)

    def test_params_and_metadata_are_deeply_immutable(self) -> None:
        params = {"selector": "#submit"}
        metadata = {"nested": {"origin": "provider"}}
        action = Action(ActionKind.CLICK, params, metadata=metadata)
        params["selector"] = "#other"
        metadata["nested"]["origin"] = "tampered"

        self.assertEqual(action.params["selector"], "#submit")
        self.assertEqual(action.metadata["nested"]["origin"], "provider")
        with self.assertRaises(TypeError):
            action.params["selector"] = "#other"  # type: ignore[index]
        with self.assertRaises(TypeError):
            action.metadata["nested"]["origin"] = "tampered"  # type: ignore[index]

    def test_payload_fields_are_strict(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "unsupported field"):
            Action.from_dict(
                {"kind": "click", "params": {"selector": "#x"}, "extra": True}
            )


if __name__ == "__main__":
    unittest.main()
