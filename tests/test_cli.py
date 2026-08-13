import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from actionanything import (
    Action,
    ActionKind,
    ActionResult,
    Decision,
    DryRunExecutor,
    ResultStatus,
    TraceRecorder,
    action_plan_schema,
    action_schema,
    read_trace,
)
from actionanything.cli import main
from actionanything.policy import PolicyOutcome


class CliTests(unittest.TestCase):
    def _main(self, arguments: list[str]) -> tuple[int, str, str]:
        output = StringIO()
        errors = StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(arguments)
        return code, output.getvalue(), errors.getvalue()

    def test_run_inspect_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            trace = root / "trace.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "actions": [
                            {
                                "kind": "navigate",
                                "params": {"url": "https://example.com"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output, _ = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(trace),
                    "--allowed-domain",
                    "example.com",
                ]
            )
            inspect_code, inspect_output, _ = self._main(["inspect", str(trace)])
            validate_code, validate_output, _ = self._main(["validate", str(plan)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(inspect_code, 0)
            self.assertEqual(validate_code, 0)
            self.assertIn("dry_run", output)
            self.assertIn("navigate", inspect_output)
            self.assertIn('"valid": true', validate_output)

    def test_validate_rejects_plan_before_trace_or_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "invalid.json"
            plan.write_text(
                json.dumps({"actions": [{"kind": "click", "params": {}}]}),
                encoding="utf-8",
            )
            code, _, errors = self._main(["validate", str(plan)])
            self.assertEqual(code, 2)
            self.assertIn("invalid action at index 0", errors)

    def test_schema_command_prints_public_contracts(self) -> None:
        action_code, action_output, action_errors = self._main(["schema", "action"])
        plan_code, plan_output, plan_errors = self._main(["schema", "plan"])

        self.assertEqual(action_code, 0)
        self.assertEqual(plan_code, 0)
        self.assertEqual(action_errors, "")
        self.assertEqual(plan_errors, "")
        self.assertEqual(json.loads(action_output), action_schema())
        self.assertEqual(json.loads(plan_output), action_plan_schema())

    def test_plan_rejects_unsupported_top_level_budget_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "invalid-plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "actions": [{"kind": "wait", "params": {"milliseconds": 1}}],
                        "budget": {"max_actions": 999},
                    }
                ),
                encoding="utf-8",
            )
            code, _, errors = self._main(["validate", str(plan)])

        self.assertEqual(code, 2)
        self.assertIn("action plans must not set budget", errors)

    def test_run_rejects_plan_budget_but_preserves_other_envelope_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_plan = root / "invalid-plan.json"
            compatible_plan = root / "compatible-plan.json"
            compatible_trace = root / "compatible-trace.jsonl"
            invalid_plan.write_text(
                json.dumps(
                    {
                        "actions": [{"kind": "wait", "params": {"milliseconds": 1}}],
                        "budget": {"max_actions": 999},
                    }
                ),
                encoding="utf-8",
            )
            compatible_plan.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "metadata": {"producer": "portable-plan"},
                        "actions": [{"kind": "wait", "params": {"milliseconds": 1}}],
                    }
                ),
                encoding="utf-8",
            )

            invalid_code, _, invalid_errors = self._main(["run", str(invalid_plan)])
            compatible_code, compatible_output, _ = self._main(
                ["run", str(compatible_plan), "--trace", str(compatible_trace)]
            )

        self.assertEqual(invalid_code, 2)
        self.assertIn("action plans must not set budget", invalid_errors)
        self.assertEqual(compatible_code, 0)
        self.assertIn('"status": "dry_run"', compatible_output)

    def test_real_execution_requires_domain_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(
                json.dumps({"actions": [{"kind": "click", "params": {"selector": "#x"}}]}),
                encoding="utf-8",
            )
            code, _, errors = self._main(["run", str(plan), "--execute"])
            self.assertEqual(code, 2)
            self.assertIn("--execute requires at least one --allowed-domain", errors)

    def test_real_execution_rejects_unicode_domain_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(
                json.dumps({"actions": [{"kind": "click", "params": {"selector": "#x"}}]}),
                encoding="utf-8",
            )
            code, _, errors = self._main(
                ["run", str(plan), "--execute", "--allowed-domain", "faß.de"]
            )
            self.assertEqual(code, 2)
            self.assertIn("ASCII hostnames", errors)

    def test_run_enforces_action_and_wait_budgets_before_more_dry_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            action_trace = root / "action-limit.jsonl"
            wait_trace = root / "wait-limit.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "actions": [
                            {"kind": "wait", "params": {"milliseconds": 1}},
                            {"kind": "wait", "params": {"milliseconds": 1}},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            action_code, action_output, _ = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(action_trace),
                    "--max-actions",
                    "1",
                ]
            )
            wait_code, wait_output, _ = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(wait_trace),
                    "--max-total-wait-ms",
                    "1",
                ]
            )

            action_events = list(read_trace(action_trace))
            wait_events = list(read_trace(wait_trace))

        self.assertEqual(action_code, 1)
        self.assertEqual(wait_code, 1)
        self.assertEqual(action_output.count('"status": "dry_run"'), 1)
        self.assertEqual(wait_output.count('"status": "dry_run"'), 1)
        self.assertEqual(action_output.count('"status": "denied"'), 1)
        self.assertEqual(wait_output.count('"status": "denied"'), 1)
        self.assertEqual(
            [event["result"]["status"] for event in action_events],
            ["dry_run", "denied"],
        )
        self.assertEqual(
            [event["result"]["status"] for event in wait_events],
            ["dry_run", "denied"],
        )

    def test_run_rejects_invalid_budget_without_creating_a_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            trace = root / "trace.jsonl"
            plan.write_text(
                json.dumps({"actions": [{"kind": "wait", "params": {"milliseconds": 1}}]}),
                encoding="utf-8",
            )

            code, _, errors = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(trace),
                    "--max-actions",
                    "-1",
                ]
            )
            trace_created = trace.exists()

        self.assertEqual(code, 2)
        self.assertIn("max_actions must be a non-negative integer", errors)
        self.assertFalse(trace_created)

    def test_run_rejects_negative_wait_budget_and_accepts_the_long_flag_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            invalid_trace = root / "invalid-trace.jsonl"
            alias_trace = root / "alias-trace.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "actions": [
                            {"kind": "wait", "params": {"milliseconds": 1}},
                            {"kind": "wait", "params": {"milliseconds": 1}},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            invalid_code, _, invalid_errors = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(invalid_trace),
                    "--max-total-wait-ms",
                    "-1",
                ]
            )
            alias_code, alias_output, _ = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(alias_trace),
                    "--max-total-wait-milliseconds",
                    "1",
                ]
            )
            trace_created = invalid_trace.exists()

        self.assertEqual(invalid_code, 2)
        self.assertIn(
            "max_total_wait_milliseconds must be a non-negative integer",
            invalid_errors,
        )
        self.assertFalse(trace_created)
        self.assertEqual(alias_code, 1)
        self.assertEqual(alias_output.count('"status": "dry_run"'), 1)
        self.assertEqual(alias_output.count('"status": "denied"'), 1)

    def test_replay_rejects_nested_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            recorder = TraceRecorder(trace)
            action = Action(
                ActionKind.TYPE,
                {"selector": "#search", "text": "private input"},
            )
            recorder.record(
                action,
                PolicyOutcome(Decision.ALLOW, "test", "test"),
                # Dry-run-like output deliberately puts sensitive data in a nested map.
                __import__("actionanything").ActionResult(
                    action.id,
                    __import__("actionanything").ResultStatus.DRY_RUN,
                    output={"nested": {"text": "private input"}},
                ),
            )
            code, _, errors = self._main(["replay", str(trace)])
            self.assertEqual(code, 2)
            self.assertIn("contains redacted values", errors)

    def test_replay_rejects_mixed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.CLICK, {"selector": "#x"})
            outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
            from actionanything import ActionResult, ResultStatus

            TraceRecorder(trace, redact=False, trace_id="one").record(
                action, outcome, ActionResult(action.id, ResultStatus.DRY_RUN)
            )
            TraceRecorder(trace, redact=False, trace_id="two").record(
                action, outcome, ActionResult(action.id, ResultStatus.DRY_RUN)
            )
            code, _, errors = self._main(["replay", str(trace)])
            self.assertEqual(code, 2)
            self.assertIn("multiple runs", errors)

    def test_replay_rejects_actions_previously_not_admitted_by_a_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            trace = root / "unsafe-trace.jsonl"
            plan.write_text(
                json.dumps({"actions": [{"kind": "wait", "params": {"milliseconds": 1}}]}),
                encoding="utf-8",
            )
            run_code, _, _ = self._main(
                [
                    "run",
                    str(plan),
                    "--trace",
                    str(trace),
                    "--unsafe-trace",
                    "--max-actions",
                    "0",
                ]
            )
            replay_code, _, errors = self._main(["replay", str(trace)])

        self.assertEqual(run_code, 1)
        self.assertEqual(replay_code, 2)
        self.assertIn("not admitted", errors)

    def test_replay_rejects_any_non_completed_or_non_executable_event_before_runtime(self) -> None:
        cases = (
            (
                PolicyOutcome(Decision.DENY, "blocked", "test"),
                ResultStatus.DENIED,
                "without an executable policy decision",
            ),
            (
                PolicyOutcome(Decision.CONFIRM, "not approved", "test"),
                ResultStatus.CANCELLED,
                "without a completed dry-run result",
            ),
            (
                PolicyOutcome(Decision.ALLOW, "attempted", "test"),
                ResultStatus.ERROR,
                "without a completed dry-run result",
            ),
            (
                PolicyOutcome(Decision.ALLOW, "completed", "test"),
                ResultStatus.SUCCESS,
                "without a completed dry-run result",
            ),
        )
        action = Action(ActionKind.WAIT, {"milliseconds": 1})

        for outcome, status, message in cases:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as directory:
                    trace = Path(directory) / "trace.jsonl"
                    TraceRecorder(trace, redact=False).record(
                        action,
                        outcome,
                        ActionResult(action.id, status),
                    )
                    with patch("actionanything.cli._build_runtime") as build_runtime:
                        code, _, errors = self._main(["replay", str(trace)])

                self.assertEqual(code, 2)
                self.assertIn(message, errors)
                build_runtime.assert_not_called()

    def test_replay_rejects_malformed_event_before_running_earlier_valid_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.WAIT, {"milliseconds": 1})
            recorder = TraceRecorder(trace, redact=False, trace_id="one")
            recorder.record(
                action,
                PolicyOutcome(Decision.ALLOW, "completed", "test"),
                ActionResult(action.id, ResultStatus.DRY_RUN),
            )
            invalid = {
                "trace_id": "one",
                "action": action.to_dict(),
                "policy": {"decision": "allow", "name": "test"},
                "result": {"status": "unknown-status"},
            }
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(invalid) + "\n")

            with patch("actionanything.cli._build_runtime") as build_runtime:
                code, _, errors = self._main(["replay", str(trace)])

        self.assertEqual(code, 2)
        self.assertIn("incomplete policy evidence", errors)
        build_runtime.assert_not_called()

    def test_replay_rejects_empty_trace_before_creating_a_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "empty.jsonl"
            trace.write_text("", encoding="utf-8")
            with patch("actionanything.cli._build_runtime") as build_runtime:
                code, _, errors = self._main(["replay", str(trace)])

        self.assertEqual(code, 2)
        self.assertIn("contains no replayable events", errors)
        build_runtime.assert_not_called()

    def test_replay_accepts_complete_unredacted_dry_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.WAIT, {"milliseconds": 1})
            TraceRecorder(trace, redact=False).record(
                action,
                PolicyOutcome(Decision.ALLOW, "completed", "test"),
                ActionResult(action.id, ResultStatus.DRY_RUN),
            )
            code, output, errors = self._main(["replay", str(trace)])

        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn('"status": "dry_run"', output)

    def test_replay_accepts_a_shallow_unsafe_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.WAIT, {"milliseconds": 1})
            TraceRecorder(trace, redact=False).record(
                action,
                PolicyOutcome(Decision.ALLOW, "test", "test"),
                ActionResult(action.id, ResultStatus.DRY_RUN),
            )

            code, output, errors = self._main(["replay", str(trace)])

        self.assertEqual(code, 0)
        self.assertIn("dry_run", output)
        self.assertEqual(errors, "")

    def test_trace_commands_reject_deep_or_invalid_trace_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deeply_nested = root / "deep.jsonl"
            deeply_nested.write_text(
                '{"action":' + '{"child":' * 2_000 + "null" + "}" * 2_000 + "}\n",
                encoding="utf-8",
            )

            inspect_code, _, inspect_errors = self._main(["inspect", str(deeply_nested)])
            replay_code, _, replay_errors = self._main(["replay", str(deeply_nested)])

            self.assertEqual(inspect_code, 2)
            self.assertEqual(replay_code, 2)
            self.assertIn("nested too deeply", inspect_errors)
            self.assertIn("nested too deeply", replay_errors)
            self.assertNotIn("RecursionError", inspect_errors)
            self.assertNotIn("RecursionError", replay_errors)

            invalid_result = root / "invalid-result.jsonl"
            invalid_result.write_text(
                '{"action": {}, "result": []}\n', encoding="utf-8"
            )
            code, _, errors = self._main(["inspect", str(invalid_result)])
            self.assertEqual(code, 2)
            self.assertIn("invalid result", errors)

    def test_replay_rechecks_a_confirmed_dry_run_with_current_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.CLICK, {"selector": "#test-control"})
            TraceRecorder(trace, redact=False).record(
                action,
                PolicyOutcome(Decision.CONFIRM, "previously approved", "test"),
                ActionResult(action.id, ResultStatus.DRY_RUN),
            )
            code, output, errors = self._main(["replay", str(trace), "--yes"])

        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn('"status": "dry_run"', output)

    def test_replay_rejects_incomplete_evidence_and_mixed_run_identity_profiles(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        valid_event = {
            "trace_id": "one",
            "sequence": 1,
            "action": action.to_dict(),
            "policy": {"decision": "allow", "reason": "completed", "name": "test"},
            "result": ActionResult(action.id, ResultStatus.DRY_RUN).to_dict(),
        }
        cases = (
            (
                {**valid_event, "policy": {"decision": "allow", "name": "test"}},
                "incomplete policy evidence",
            ),
            (
                {
                    **valid_event,
                    "result": {
                        **valid_event["result"],
                        "action_id": "other-action",
                    },
                },
                "incomplete result evidence",
            ),
            (
                {
                    **valid_event,
                    "result": {
                        **valid_event["result"],
                        "error": "unexpected",
                    },
                },
                "execution or audit errors",
            ),
            (
                {
                    **valid_event,
                    "policy": {
                        **valid_event["policy"],
                        "reason": "[REDACTED]",
                    },
                },
                "contains redacted values",
            ),
            (
                {
                    **valid_event,
                    "policy": {
                        **valid_event["policy"],
                        "decision": ["allow"],
                    },
                },
                "without an executable policy decision",
            ),
            (
                {
                    **valid_event,
                    "result": {
                        **valid_event["result"],
                        "status": ["dry_run"],
                    },
                },
                "without a completed dry-run result",
            ),
            (
                {key: value for key, value in valid_event.items() if key != "sequence"},
                "mixes current and legacy run identity fields",
            ),
            (
                {
                    **valid_event,
                    "sequence": 0,
                },
                "invalid run identity",
            ),
        )
        for event, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as directory:
                    trace = Path(directory) / "trace.jsonl"
                    trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
                    with patch("actionanything.cli._build_runtime") as build_runtime:
                        code, _, errors = self._main(["replay", str(trace)])

                self.assertEqual(code, 2)
                self.assertIn(message, errors)
                build_runtime.assert_not_called()

    def test_replay_accepts_legacy_and_gapped_current_run_identity_profiles(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        result = ActionResult(action.id, ResultStatus.DRY_RUN).to_dict()
        policy = {"decision": "allow", "reason": "completed", "name": "test"}
        current_events = (
            {
                "trace_id": "one",
                "sequence": 1,
                "action": action.to_dict(),
                "policy": policy,
                "result": result,
            },
            {
                "trace_id": "one",
                "sequence": 3,
                "action": action.to_dict(),
                "policy": policy,
                "result": result,
            },
        )
        legacy_event = {
            "action": action.to_dict(),
            "policy": policy,
            "result": result,
        }
        for events in ((legacy_event,), current_events):
            with self.subTest(events=events):
                with tempfile.TemporaryDirectory() as directory:
                    trace = Path(directory) / "trace.jsonl"
                    trace.write_text(
                        "".join(json.dumps(event) + "\n" for event in events),
                        encoding="utf-8",
                    )
                    code, output, errors = self._main(["replay", str(trace)])

                self.assertEqual(code, 0)
                self.assertEqual(errors, "")
                self.assertEqual(output.count('"status": "dry_run"'), len(events))


if __name__ == "__main__":
    unittest.main()
