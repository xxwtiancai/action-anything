import unittest

from actionanything import (
    ActionKind,
    ActionRuntime,
    DryRunExecutor,
    ResultStatus,
)
from actionanything.adapters import (
    AdapterError,
    AnthropicComputerUseAdapter,
    OpenAIComputerUseAdapter,
)


_DEFAULT_PENDING_SAFETY_CHECKS = object()


class OpenAIComputerUseAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OpenAIComputerUseAdapter()

    def test_adapts_documented_singular_computer_call(self) -> None:
        actions = self.adapter.adapt(
            {
                "type": "computer_call",
                "id": "cu_002",
                "call_id": "call_002",
                "status": "completed",
                "pending_safety_checks": [],
                "action": {"type": "click", "button": "left", "x": 405, "y": 157},
            }
        )

        self.assertEqual([action.kind for action in actions], [ActionKind.CLICK])
        self.assertEqual(actions[0].params, {"x": 405, "y": 157, "button": "left"})
        self.assertEqual(actions[0].metadata["provider"], "openai")
        self.assertEqual(actions[0].metadata["provider_item_id"], "cu_002")
        self.assertEqual(actions[0].metadata["provider_call_id"], "call_002")
        self.assertEqual(actions[0].metadata["provider_action_type"], "click")
        self.assertNotIn("text", actions[0].metadata)

    def test_adapts_each_supported_singular_action(self) -> None:
        cases = (
            (
                {"type": "type", "text": "penguin"},
                ActionKind.TYPE,
                {"text": "penguin"},
            ),
            (
                {
                    "type": "scroll",
                    "x": 405,
                    "y": 157,
                    "scroll_x": 0,
                    "scroll_y": 640,
                },
                ActionKind.SCROLL,
                {"delta_x": 0, "delta_y": 640, "x": 405, "y": 157},
            ),
            ({"type": "wait"}, ActionKind.WAIT, {"milliseconds": 2_000}),
            ({"type": "screenshot"}, ActionKind.SCREENSHOT, {}),
        )

        for raw_action, kind, params in cases:
            with self.subTest(raw_action=raw_action):
                actions = self.adapter.adapt(self._computer_call(raw_action))
                self.assertEqual([action.kind for action in actions], [kind])
                self.assertEqual(actions[0].params, params)

    def test_rejects_wrong_or_incomplete_provider_shape(self) -> None:
        for item in (
            {},
            self._computer_call({"type": "wait"}, id=""),
            self._computer_call({"type": "wait"}, call_id=""),
            self._computer_call({"type": "wait"}, status="in_progress"),
            self._computer_call({"type": "wait"}, status=None),
            self._computer_call({"type": "wait"}, pending_safety_checks=None),
            {**self._computer_call({"type": "wait"}), "action": None},
            {
                **self._computer_call({"type": "wait"}),
                "actions": [{"type": "wait"}],
            },
        ):
            with self.subTest(item=item):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(item)

    def test_rejects_unsupported_or_malformed_provider_action(self) -> None:
        for action in (
            {"type": "drag", "path": []},
            {"type": "click", "x": 10, "y": 20},
            {"type": "type", "text": "hello", "keys": ["SHIFT"]},
            {"type": "scroll", "x": 10, "y": 20, "scroll_x": 0},
        ):
            with self.subTest(action=action):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(self._computer_call(action))

    def test_rejects_pending_safety_checks_without_exposing_their_payload(self) -> None:
        with self.assertRaises(AdapterError) as raised:
            self.adapter.adapt(
                self._computer_call(
                    {"type": "screenshot"},
                    pending_safety_checks=[
                        {
                            "id": "cu_sc_001",
                            "code": "malicious_instructions",
                            "message": "Sensitive page text must never be copied into errors.",
                        }
                    ],
                )
            )

        self.assertNotIn("Sensitive page text", str(raised.exception))
        self.assertIn("pending safety checks", str(raised.exception))

    def test_rejection_messages_do_not_echo_untrusted_action_fields(self) -> None:
        with self.assertRaises(AdapterError) as unsupported:
            self.adapter.adapt(
                self._computer_call({"type": "secret-action-token-123"})
            )
        self.assertNotIn("secret-action-token-123", str(unsupported.exception))

        with self.assertRaises(AdapterError) as unknown_field:
            self.adapter.adapt(
                self._computer_call(
                    {
                        "type": "wait",
                        "sensitive-untrusted-field-456": "do not echo me",
                    }
                )
            )
        self.assertNotIn("sensitive-untrusted-field-456", str(unknown_field.exception))

        with self.assertRaises(AdapterError) as invalid_parameter:
            self.adapter.adapt(
                self._computer_call(
                    {
                        "type": "click",
                        "button": "left",
                        "x": 1,
                        "y": "sensitive-invalid-coordinate-789",
                    }
                )
            )
        self.assertNotIn("sensitive-invalid-coordinate-789", str(invalid_parameter.exception))

    def test_capabilities_are_explicit(self) -> None:
        self.assertTrue(self.adapter.capabilities.coordinate_click)
        self.assertTrue(self.adapter.capabilities.focused_type)
        self.assertIn(ActionKind.CLICK, self.adapter.capabilities.action_kinds)

    @staticmethod
    def _computer_call(
        action: object,
        *,
        id: object = "cu_001",
        call_id: object = "call_001",
        status: object = "completed",
        pending_safety_checks: object = _DEFAULT_PENDING_SAFETY_CHECKS,
    ) -> dict[str, object]:
        return {
            "type": "computer_call",
            "id": id,
            "call_id": call_id,
            "status": status,
            "pending_safety_checks": (
                []
                if pending_safety_checks is _DEFAULT_PENDING_SAFETY_CHECKS
                else pending_safety_checks
            ),
            "action": action,
        }


class AnthropicComputerUseAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AnthropicComputerUseAdapter(
            tool_version="computer_20250124",
            display_width_px=1_024,
            display_height_px=768,
        )

    def test_adapts_each_supported_direct_action(self) -> None:
        cases = (
            (
                {"action": "left_click", "coordinate": [405, 157]},
                ActionKind.CLICK,
                {"x": 405, "y": 157, "button": "left"},
            ),
            (
                {"action": "right_click", "coordinate": [0, 0]},
                ActionKind.CLICK,
                {"x": 0, "y": 0, "button": "right"},
            ),
            (
                {"action": "middle_click", "coordinate": [1_023, 767]},
                ActionKind.CLICK,
                {"x": 1_023, "y": 767, "button": "middle"},
            ),
            (
                {"action": "type", "text": "penguin"},
                ActionKind.TYPE,
                {"text": "penguin"},
            ),
            (
                {"action": "wait", "duration": 1.5},
                ActionKind.WAIT,
                {"milliseconds": 1_500},
            ),
            ({"action": "screenshot"}, ActionKind.SCREENSHOT, {}),
        )

        for version in ("computer_20250124", "computer_20251124"):
            adapter = AnthropicComputerUseAdapter(
                tool_version=version,
                display_width_px=1_024,
                display_height_px=768,
            )
            for input_payload, kind, params in cases:
                with self.subTest(version=version, input_payload=input_payload):
                    action = adapter.adapt(self._tool_use(input_payload))[0]
                    self.assertIs(action.kind, kind)
                    self.assertEqual(action.params, params)
                    self.assertEqual(action.metadata["provider"], "anthropic")
                    self.assertEqual(action.metadata["provider_item_id"], "toolu_001")
                    self.assertEqual(action.metadata["provider_tool_name"], "computer")
                    self.assertEqual(
                        action.metadata["provider_tool_version"], version
                    )
                    self.assertEqual(
                        action.metadata["provider_action_type"], input_payload["action"]
                    )

    def test_adapts_explicit_direct_caller(self) -> None:
        item = self._tool_use({"action": "screenshot"}, caller={"type": "direct"})
        self.assertIs(self.adapter.adapt(item)[0].kind, ActionKind.SCREENSHOT)

    def test_accepts_legacy_direct_caller_shapes(self) -> None:
        for item in (
            self._tool_use({"action": "screenshot"}, include_caller=False),
            self._tool_use({"action": "screenshot"}, caller=None),
        ):
            with self.subTest(item=item):
                self.assertIs(
                    self.adapter.adapt(item)[0].kind,
                    ActionKind.SCREENSHOT,
                )

    def test_newer_version_still_rejects_zoom(self) -> None:
        adapter = AnthropicComputerUseAdapter(
            tool_version="computer_20251124",
            display_width_px=1_024,
            display_height_px=768,
        )
        with self.assertRaises(AdapterError):
            adapter.adapt(self._tool_use({"action": "zoom", "region": [0, 0, 2, 2]}))

    def test_constructor_rejects_untrusted_or_unsupported_configuration(self) -> None:
        invalid = (
            {"tool_version": "computer_latest"},
            {"display_width_px": True},
            {"display_width_px": 0},
            {"display_height_px": -1},
            {"display_height_px": 100_001},
            {"tool_version": []},
        )
        defaults = {
            "tool_version": "computer_20250124",
            "display_width_px": 1_024,
            "display_height_px": 768,
        }
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    AnthropicComputerUseAdapter(**{**defaults, **changes})

    def test_rejects_incomplete_or_non_direct_tool_use_shapes(self) -> None:
        cases = (
            {},
            self._tool_use({"action": "screenshot"}, id=""),
            {**self._tool_use({"action": "screenshot"}), "name": "other"},
            {**self._tool_use({"action": "screenshot"}), "type": "text"},
            {**self._tool_use({"action": "screenshot"}), "input": None},
            {**self._tool_use({"action": "screenshot"}), "extra": "value"},
            self._tool_use({"action": "screenshot"}, caller={"type": "indirect"}),
            self._tool_use(
                {"action": "screenshot"},
                caller={
                    "type": "code_execution_20250825",
                    "tool_id": "srvtoolu_001",
                },
            ),
            self._tool_use(
                {"action": "screenshot"},
                caller={"type": "direct", "tool_id": "srvtoolu_001"},
            ),
        )
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(item)

    def test_rejects_invalid_coordinate_parameters(self) -> None:
        for input_payload in (
            {"action": "left_click"},
            {"action": "left_click", "coordinate": [1]},
            {"action": "left_click", "coordinate": (1, 2)},
            {"action": "left_click", "coordinate": [True, 2]},
            {"action": "left_click", "coordinate": [1.0, 2]},
            {"action": "left_click", "coordinate": [-1, 2]},
            {"action": "left_click", "coordinate": [1_024, 2]},
            {"action": "left_click", "coordinate": [2, 768]},
        ):
            with self.subTest(input_payload=input_payload):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(self._tool_use(input_payload))

    def test_rejects_invalid_wait_and_type_parameters(self) -> None:
        for input_payload in (
            {"action": "wait"},
            {"action": "wait", "duration": True},
            {"action": "wait", "duration": float("nan")},
            {"action": "wait", "duration": 60.001},
            {"action": "wait", "duration": 0.0001},
            {"action": "type"},
            {"action": "type", "text": None},
            {"action": "type", "text": "x" * 50_001},
        ):
            with self.subTest(input_payload=input_payload):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(self._tool_use(input_payload))

    def test_rejects_unknown_fields_and_unsupported_actions(self) -> None:
        for input_payload in (
            {"action": "left_click", "coordinate": [1, 2], "key": "SHIFT"},
            {"action": "type", "text": "hello", "key": "SHIFT"},
            {
                "action": "scroll",
                "coordinate": [1, 2],
                "scroll_direction": "down",
                "scroll_amount": 1,
            },
            {"action": "screenshot", "path": "secret.png"},
            {"action": "key", "text": "ctrl+s"},
            {"action": "mouse_move", "coordinate": [1, 2]},
            {"action": "left_click_drag", "coordinate": [1, 2]},
            {"action": "double_click", "coordinate": [1, 2]},
            {"action": "triple_click", "coordinate": [1, 2]},
            {"action": "left_mouse_down"},
            {"action": "left_mouse_up"},
            {"action": "hold_key", "text": "SHIFT", "duration": 1},
            {"action": "cursor_position"},
            {"action": "zoom", "region": [0, 0, 2, 2]},
        ):
            with self.subTest(input_payload=input_payload):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(self._tool_use(input_payload))

    def test_rejects_scroll_without_interpreting_provider_units(self) -> None:
        for direction in ("down", [], {}):
            with self.subTest(direction=direction):
                with self.assertRaises(AdapterError):
                    self.adapter.adapt(
                        self._tool_use(
                            {
                                "action": "scroll",
                                "coordinate": [1, 2],
                                "scroll_direction": direction,
                                "scroll_amount": 1,
                            }
                        )
                    )

    def test_rejection_messages_do_not_echo_untrusted_provider_data(self) -> None:
        secret = "untrusted-secret-token-987"
        cases = (
            self._tool_use({"action": secret}),
            self._tool_use(
                {"action": "screenshot", "untrusted-field-token-456": secret}
            ),
            self._tool_use({"action": "type", "text": secret, "key": "SHIFT"}),
            self._tool_use(
                {"action": "left_click", "coordinate": [secret, 2]}
            ),
        )
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(AdapterError) as raised:
                    self.adapter.adapt(item)
                self.assertNotIn(secret, str(raised.exception))

    def test_metadata_never_contains_raw_input(self) -> None:
        secret = "do-not-record-provider-text"
        action = self.adapter.adapt(self._tool_use({"action": "type", "text": secret}))[0]
        self.assertEqual(
            set(action.metadata),
            {
                "provider",
                "provider_item_id",
                "provider_tool_name",
                "provider_tool_version",
                "provider_action_type",
            },
        )
        self.assertNotIn(secret, str(dict(action.metadata)))
        self.assertNotIn("input", action.metadata)

    def test_adapted_click_and_type_remain_subject_to_confirmation(self) -> None:
        runtime = ActionRuntime(DryRunExecutor())
        for input_payload in (
            {"action": "left_click", "coordinate": [1, 2]},
            {"action": "type", "text": "approved by a human first"},
        ):
            with self.subTest(input_payload=input_payload):
                action = self.adapter.adapt(self._tool_use(input_payload))[0]
                self.assertIs(
                    runtime.execute(action).status,
                    ResultStatus.CANCELLED,
                )

    def test_capabilities_are_explicit(self) -> None:
        self.assertTrue(self.adapter.capabilities.coordinate_click)
        self.assertTrue(self.adapter.capabilities.focused_type)
        self.assertEqual(
            self.adapter.capabilities.action_kinds,
            frozenset(
                {
                    ActionKind.CLICK,
                    ActionKind.TYPE,
                    ActionKind.WAIT,
                    ActionKind.SCREENSHOT,
                }
            ),
        )

    @staticmethod
    def _tool_use(
        input_payload: object,
        *,
        id: object = "toolu_001",
        caller: object = _DEFAULT_PENDING_SAFETY_CHECKS,
        include_caller: bool = True,
    ) -> dict[str, object]:
        item: dict[str, object] = {
            "type": "tool_use",
            "id": id,
            "name": "computer",
            "input": input_payload,
        }
        if include_caller:
            item["caller"] = (
                {"type": "direct"}
                if caller is _DEFAULT_PENDING_SAFETY_CHECKS
                else caller
            )
        return item


if __name__ == "__main__":
    unittest.main()
