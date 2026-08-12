import unittest

from actionanything import ActionKind
from actionanything.adapters import AdapterError, OpenAIComputerUseAdapter


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


if __name__ == "__main__":
    unittest.main()
