import unittest
import traceback
from collections.abc import Mapping

from actionanything import Action, ActionKind, ActionResult, ResultStatus, RiskLevel
from actionanything.actions import (
    ActionValidationError,
    MAX_METADATA_NESTING,
    MAX_RESULT_OUTPUT_NESTING,
)


class DivergentText(str):
    def __str__(self) -> str:
        return "https://example.com/"


class OversizedText(str):
    def __len__(self) -> int:
        return 0


class UnderstatedInteger(int):
    def __int__(self) -> int:
        return 0


class DivergentFloat(float):
    def __float__(self) -> float:
        return float("nan")


class MaskedNanFloat(float):
    def __float__(self) -> float:
        return 1.0


class DistinctAlias(str):
    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other


class ReprBomb(str):
    def __repr__(self) -> str:
        return "untrusted-repr-diagnostic-" + ("x" * 4_096)


class IntegerReprBomb(int):
    def __repr__(self) -> str:
        return "untrusted-repr-diagnostic-" + ("x" * 4_096)


class DivergentDict(dict):
    def items(self):
        return (("selector", "#replaced"),)


class DivergentList(list):
    def __iter__(self):
        return iter(("replaced",))


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
        with self.assertRaisesRegex(ActionValidationError, "unsupported parameters"):
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

    def test_schema_normalizes_scalar_subclasses_to_builtin_values(self) -> None:
        action = Action(
            ActionKind.TYPE,
            {"text": DivergentText("safe"), "selector": DivergentText("#safe")},
            id=DivergentText("action-1"),
            metadata={DivergentText("source"): DivergentText("provider")},
        )
        result = ActionResult(
            DivergentText("action-1"),
            ResultStatus.DRY_RUN,
            output={"message": DivergentText("safe")},
            error=DivergentText(""),
            audit_error=DivergentText("audit"),
        )

        self.assertIs(type(action.id), str)
        self.assertIs(type(action.params["text"]), str)
        self.assertEqual(action.params["text"], "safe")
        self.assertIs(type(action.params["selector"]), str)
        self.assertEqual(action.params["selector"], "#safe")
        self.assertEqual(action.metadata, {"source": "provider"})
        self.assertIs(type(action.metadata["source"]), str)
        self.assertIs(type(result.action_id), str)
        self.assertIs(type(result.output["message"]), str)
        self.assertIs(type(result.error), str)
        self.assertIs(type(result.audit_error), str)
        self.assertTrue(all(type(value) is str for value in action.to_dict()["params"].values()))

    def test_schema_uses_base_scalar_values_for_validation_and_storage(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "at most"):
            Action(ActionKind.CLICK, {"selector": OversizedText("x" * 4_097)})
        with self.assertRaisesRegex(ActionValidationError, "between"):
            Action(ActionKind.WAIT, {"milliseconds": UnderstatedInteger(60_001)})
        with self.assertRaisesRegex(ActionValidationError, "finite"):
            Action(ActionKind.CLICK, {"x": MaskedNanFloat(float("nan")), "y": 0})

        action = Action(
            ActionKind.WAIT,
            {"milliseconds": UnderstatedInteger(1)},
            metadata={"count": UnderstatedInteger(4), "ratio": DivergentFloat(1.0)},
        )
        self.assertIs(type(action.params["milliseconds"]), int)
        self.assertEqual(action.params["milliseconds"], 1)
        self.assertIs(type(action.metadata["count"]), int)
        self.assertEqual(action.metadata["count"], 4)
        self.assertIs(type(action.metadata["ratio"]), float)
        self.assertEqual(action.metadata["ratio"], 1.0)

    def test_schema_rejects_mapping_key_aliases_after_normalization(self) -> None:
        first = DistinctAlias("source")
        second = DistinctAlias("source")
        with self.assertRaisesRegex(ActionValidationError, "unique strings"):
            Action(
                ActionKind.CLICK,
                {"selector": "#safe"},
                metadata={first: "one", second: "two"},
            )

    def test_schema_uses_base_container_operations_before_freezing(self) -> None:
        action = Action(
            ActionKind.CLICK,
            DivergentDict({"selector": "#safe"}),
            metadata={"items": DivergentList(["original"])},
        )
        result = ActionResult(
            "result-1",
            ResultStatus.DRY_RUN,
            output=DivergentDict({"message": "original"}),
        )

        self.assertEqual(action.params, {"selector": "#safe"})
        self.assertEqual(action.metadata["items"], ("original",))
        self.assertEqual(result.output, {"message": "original"})

    def test_metadata_rejects_cycles_and_preserves_shared_children(self) -> None:
        direct_cycle: dict[str, object] = {}
        direct_cycle["self"] = direct_cycle
        indirect_cycle: dict[str, object] = {}
        child_list: list[object] = [indirect_cycle]
        indirect_cycle["children"] = child_list

        for build in (
            lambda: Action(
                ActionKind.WAIT,
                {"milliseconds": 1},
                metadata=direct_cycle,
            ),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "metadata": indirect_cycle,
                }
            ),
        ):
            with self.subTest(build=build):
                with self.assertRaisesRegex(
                    ActionValidationError, "circular references"
                ):
                    build()

        shared = {"source": "provider"}
        action = Action(
            ActionKind.WAIT,
            {"milliseconds": 1},
            metadata={"first": shared, "second": shared},
        )
        self.assertEqual(action.metadata["first"], {"source": "provider"})
        self.assertEqual(action.metadata["second"], {"source": "provider"})

    def test_metadata_has_a_stable_container_nesting_limit(self) -> None:
        accepted: object = "leaf"
        for _ in range(MAX_METADATA_NESTING):
            accepted = {"child": accepted}
        for build in (
            lambda: Action(
                ActionKind.WAIT, {"milliseconds": 1}, metadata=accepted
            ),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "metadata": accepted,
                }
            ),
        ):
            with self.subTest(build=build):
                build()

        rejected: object = "leaf"
        for _ in range(MAX_METADATA_NESTING + 1):
            rejected = {"child": rejected}
        for build in (
            lambda: Action(
                ActionKind.WAIT, {"milliseconds": 1}, metadata=rejected
            ),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "metadata": rejected,
                }
            ),
        ):
            with self.subTest(build=build):
                with self.assertRaisesRegex(ActionValidationError, "must not exceed"):
                    build()

    def test_result_output_has_a_stable_container_nesting_limit(self) -> None:
        accepted: object = "leaf"
        for _ in range(MAX_RESULT_OUTPUT_NESTING):
            accepted = {"child": accepted}
        result = ActionResult("result-1", ResultStatus.DRY_RUN, output=accepted)
        cursor: object = result.output
        for _ in range(MAX_RESULT_OUTPUT_NESTING):
            self.assertIsInstance(cursor, Mapping)
            cursor = cursor["child"]  # type: ignore[index]
        self.assertEqual(cursor, "leaf")

        # The root mapping counts too: 1 mapping plus 63 alternating
        # list/tuple containers remains within the same path-nesting cap.
        mixed: object = "leaf"
        for index in range(MAX_RESULT_OUTPUT_NESTING - 1):
            mixed = [mixed] if index % 2 else (mixed,)
        mixed_result = ActionResult(
            "result-1", ResultStatus.DRY_RUN, output={"child": mixed}
        )
        mixed_cursor: object = mixed_result.output["child"]
        for _ in range(MAX_RESULT_OUTPUT_NESTING - 1):
            # Mutable JSON lists are deliberately frozen to tuples.
            self.assertIsInstance(mixed_cursor, tuple)
            mixed_cursor = mixed_cursor[0]  # type: ignore[index]
        self.assertEqual(mixed_cursor, "leaf")

        # The bound is per path rather than a total container-count quota.
        wide_result = ActionResult(
            "result-1",
            ResultStatus.DRY_RUN,
            output={str(index): {} for index in range(MAX_RESULT_OUTPUT_NESTING + 1)},
        )
        self.assertEqual(len(wide_result.output), MAX_RESULT_OUTPUT_NESTING + 1)

        rejected: object = "leaf"
        for _ in range(MAX_RESULT_OUTPUT_NESTING + 1):
            rejected = {"child": rejected}
        with self.assertRaisesRegex(ActionValidationError, "must not exceed"):
            ActionResult("result-1", ResultStatus.DRY_RUN, output=rejected)

    def test_result_output_rejects_cycles_and_preserves_shared_children(self) -> None:
        direct_cycle: dict[str, object] = {}
        direct_cycle["self"] = direct_cycle
        indirect_cycle: dict[str, object] = {}
        children: list[object] = []
        children.append((indirect_cycle,))
        indirect_cycle["children"] = children

        for output in (direct_cycle, indirect_cycle):
            with self.subTest(output=output):
                with self.assertRaisesRegex(
                    ActionValidationError, "circular references"
                ):
                    ActionResult("result-1", ResultStatus.DRY_RUN, output=output)

        shared = {"source": "executor"}
        result = ActionResult(
            "result-1",
            ResultStatus.DRY_RUN,
            output={"first": shared, "second": shared},
        )
        self.assertEqual(result.output["first"], {"source": "executor"})
        self.assertEqual(result.output["second"], {"source": "executor"})

    def test_schema_errors_do_not_reflect_untrusted_values_or_nested_keys(self) -> None:
        sentinel = "untrusted-schema-diagnostic-" + ("x" * 4_096)
        invalid_inputs = (
            lambda: Action.from_dict(
                {"kind": "click", "params": {"selector": "#x"}, sentinel: True}
            ),
            lambda: Action(ActionKind.CLICK, {"selector": "#x", sentinel: True}),
            lambda: Action.from_dict({"kind": sentinel, "params": {}}),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "risk": sentinel,
                }
            ),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "risk": 10**2_000,
                }
            ),
            lambda: Action(
                ActionKind.CLICK,
                {"selector": "#x"},
                metadata={sentinel: object()},
            ),
            lambda: ActionResult("result-1", sentinel),
            lambda: ActionResult(
                "result-1", ResultStatus.DRY_RUN, output={sentinel: object()}
            ),
            lambda: Action(ReprBomb("unsupported-kind"), {}),
            lambda: Action(
                ActionKind.WAIT,
                {"milliseconds": 1},
                risk=IntegerReprBomb(99),
            ),
        )

        for build in invalid_inputs:
            with self.subTest(build=build):
                with self.assertRaises((ActionValidationError, ValueError)) as context:
                    build()
                message = str(context.exception)
                self.assertNotIn(sentinel, message)
                self.assertNotIn("untrusted-repr-diagnostic-", message)
                self.assertLessEqual(len(message), 128)

    def test_schema_preserves_root_mapping_contracts_and_safe_url_error_chains(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "action metadata must be a mapping"):
            Action(ActionKind.WAIT, {"milliseconds": 1}, metadata=["not-a-mapping"])
        with self.assertRaisesRegex(TypeError, "result output must be a mapping"):
            ActionResult("result-1", ResultStatus.DRY_RUN, output=["not-a-mapping"])

        sentinel = "untrusted-port-diagnostic-" + ("x" * 4_096)
        with self.assertRaises(ActionValidationError) as context:
            Action(ActionKind.NAVIGATE, {"url": f"https://example.com:{sentinel}/"})
        rendered = "".join(traceback.format_exception(context.exception))
        self.assertNotIn(sentinel, rendered)

    def test_payload_fields_are_strict(self) -> None:
        with self.assertRaisesRegex(ActionValidationError, "unsupported field"):
            Action.from_dict(
                {"kind": "click", "params": {"selector": "#x"}, "extra": True}
            )

    def test_untrusted_input_is_not_reflected_in_validation_errors(self) -> None:
        sentinel = "untrusted-action-diagnostic-" + ("x" * 4_096)
        invalid_inputs = (
            lambda: Action.from_dict(
                {"kind": "click", "params": {"selector": "#x"}, sentinel: True}
            ),
            lambda: Action(ActionKind.CLICK, {"selector": "#x", sentinel: True}),
            lambda: Action.from_dict({"kind": sentinel, "params": {}}),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "risk": sentinel,
                }
            ),
            lambda: Action.from_dict(
                {
                    "kind": "wait",
                    "params": {"milliseconds": 1},
                    "risk": 10**2_000,
                }
            ),
            lambda: ActionResult("result-1", sentinel),
        )

        for build in invalid_inputs:
            with self.subTest(build=build):
                with self.assertRaises((ActionValidationError, ValueError)) as context:
                    build()
                message = str(context.exception)
                self.assertNotIn(sentinel, message)
                self.assertLessEqual(len(message), 128)

    def test_nested_untrusted_keys_are_not_reflected_in_validation_errors(self) -> None:
        sentinel = "nested-diagnostic-" + ("x" * 4_096)
        invalid_inputs = (
            lambda: Action(
                ActionKind.WAIT,
                {"milliseconds": 1},
                metadata={sentinel: float("nan")},
            ),
            lambda: ActionResult(
                "result-1",
                "dry_run",
                output={sentinel: float("nan")},
            ),
        )

        for build in invalid_inputs:
            with self.subTest(build=build):
                with self.assertRaises((ActionValidationError, ValueError)) as context:
                    build()
                message = str(context.exception)
                self.assertNotIn(sentinel, message)
                self.assertLessEqual(len(message), 128)


if __name__ == "__main__":
    unittest.main()
