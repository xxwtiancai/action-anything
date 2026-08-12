import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from actionanything import Action, ActionKind, Decision, DryRunExecutor, TraceRecorder
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

    def test_replay_accepts_a_shallow_unsafe_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.WAIT, {"milliseconds": 1})
            TraceRecorder(trace, redact=False).record(
                action,
                PolicyOutcome(Decision.ALLOW, "test", "test"),
                __import__("actionanything").ActionResult(
                    action.id,
                    __import__("actionanything").ResultStatus.DRY_RUN,
                ),
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


if __name__ == "__main__":
    unittest.main()
