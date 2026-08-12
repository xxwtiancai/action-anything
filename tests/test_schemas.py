import json
import unittest

from jsonschema import Draft202012Validator

from actionanything import (
    Action,
    ActionKind,
    RiskLevel,
    action_plan_schema,
    action_schema,
)
from actionanything.schemas import (
    ACTION_PLAN_SCHEMA_ID,
    ACTION_SCHEMA_ID,
    JSON_SCHEMA_DRAFT,
)


class SchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.action_document = action_schema()
        cls.plan_document = action_plan_schema()
        Draft202012Validator.check_schema(cls.action_document)
        Draft202012Validator.check_schema(cls.plan_document)
        cls.action_validator = Draft202012Validator(cls.action_document)
        cls.plan_validator = Draft202012Validator(cls.plan_document)

    def test_documents_are_self_contained_versioned_and_json_serializable(self) -> None:
        self.assertEqual(self.action_document["$schema"], JSON_SCHEMA_DRAFT)
        self.assertEqual(self.plan_document["$schema"], JSON_SCHEMA_DRAFT)
        self.assertEqual(self.action_document["$id"], ACTION_SCHEMA_ID)
        self.assertEqual(self.plan_document["$id"], ACTION_PLAN_SCHEMA_ID)
        json.dumps(self.action_document)
        json.dumps(self.plan_document)

        references: list[str] = []

        def collect_references(value: object) -> None:
            if isinstance(value, dict):
                if "$ref" in value:
                    references.append(value["$ref"])
                for item in value.values():
                    collect_references(item)
            elif isinstance(value, list):
                for item in value:
                    collect_references(item)

        collect_references(self.action_document)
        collect_references(self.plan_document)
        self.assertTrue(references)
        self.assertTrue(all(reference.startswith("#/") for reference in references))

    def test_schema_exports_are_fresh_values(self) -> None:
        exported = action_schema()
        exported["$defs"]["action"]["title"] = "changed by a caller"
        self.assertEqual(
            action_schema()["$defs"]["action"]["title"],
            "ActionAnything Action v1",
        )

    def test_all_canonical_action_kinds_match_action_schema(self) -> None:
        actions = [
            Action(ActionKind.NAVIGATE, {"url": "https://example.com"}),
            Action(ActionKind.CLICK, {"selector": "#submit"}),
            Action(ActionKind.TYPE, {"text": "hello", "press_enter": True}),
            Action(ActionKind.SCROLL, {"delta_x": 0, "delta_y": 200, "x": 3, "y": 4}),
            Action(ActionKind.WAIT, {"milliseconds": 500}),
            Action(ActionKind.SCREENSHOT, {"path": "evidence/step.png", "full_page": True}),
            Action(ActionKind.SCREENSHOT, {"path": "./evidence/step.png"}),
        ]

        for action in actions:
            with self.subTest(kind=action.kind):
                self.action_validator.validate(action.to_dict())

    def test_action_schema_rejects_wrong_shapes_and_unknown_fields(self) -> None:
        invalid_payloads = [
            {
                "kind": "navigate",
                "params": {"url": "data:text/plain,not-a-url"},
            },
            {"kind": "click", "params": {"selector": "#x", "x": 1, "y": 2}},
            {"kind": "type", "params": {"selector": "#x"}},
            {"kind": "scroll", "params": {"delta_y": 0}},
            {"kind": "wait", "params": {"milliseconds": 60_001}},
            {"kind": "screenshot", "params": {"path": "../private.png"}},
            {
                "kind": "wait",
                "params": {"milliseconds": 1, "unexpected": True},
            },
            {
                "kind": "wait",
                "params": {"milliseconds": 1},
                "unexpected": True,
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertFalse(self.action_validator.is_valid(payload))

    def test_schema_allows_declared_low_risk_that_runtime_raises(self) -> None:
        payload = {
            "kind": "click",
            "params": {"selector": "#x"},
            "risk": 0,
        }

        self.action_validator.validate(payload)
        self.assertEqual(Action.from_dict(payload).risk, RiskLevel.REVERSIBLE)

    def test_navigate_schema_matches_protocol_case_and_rejects_newlines(self) -> None:
        self.action_validator.validate(
            {"kind": "navigate", "params": {"url": "HTTPS://example.com"}}
        )
        self.assertFalse(
            self.action_validator.is_valid(
                {"kind": "navigate", "params": {"url": "https://example.com\n"}}
            )
        )

    def test_schema_retains_documented_json_integer_precheck_boundary(self) -> None:
        for payload in (
            {"kind": "wait", "params": {"milliseconds": 1.0}},
            {"kind": "scroll", "params": {"delta_y": 1.0}},
            {"kind": "click", "params": {"selector": "#x"}, "risk": 1.0},
        ):
            with self.subTest(payload=payload):
                self.action_validator.validate(payload)
                with self.assertRaises(ValueError):
                    Action.from_dict(payload)

    def test_screenshot_schema_rejects_a_trailing_newline(self) -> None:
        for path in ("evidence/a.png\n", "../evidence/a.png"):
            with self.subTest(path=path):
                payload = {"kind": "screenshot", "params": {"path": path}}
                self.assertFalse(self.action_validator.is_valid(payload))
                with self.assertRaises(ValueError):
                    Action.from_dict(payload)

    def test_plan_schema_matches_supported_envelopes(self) -> None:
        action = {"kind": "wait", "params": {"milliseconds": 1}}
        self.plan_validator.validate([action])
        self.plan_validator.validate(
            {
                "actions": [action],
                "version": "app-owned",
                "metadata": {"source": "test"},
            }
        )

        invalid_plans = [
            {},
            {"actions": {}},
            {"actions": [{"kind": "click", "params": {}}]},
        ]
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                self.assertFalse(self.plan_validator.is_valid(plan))


if __name__ == "__main__":
    unittest.main()
