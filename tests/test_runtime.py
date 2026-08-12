import os
import tempfile
import unittest
from pathlib import Path

from actionanything import (
    Action,
    ActionKind,
    ActionRuntime,
    Decision,
    DryRunExecutor,
    PolicyEngine,
    ResultStatus,
    RiskLevel,
    TraceRecorder,
    read_trace,
)
from actionanything.recorder import REDACTED, contains_redaction


class FailingExecutor:
    is_dry_run = False

    def execute(self, action: Action):
        raise RuntimeError("executor failed")


class SecretFailingExecutor:
    is_dry_run = False

    def execute(self, action: Action):
        raise RuntimeError("https://example.com/reset/runtime-secret-token")


class MutatingConfirmation:
    def __call__(self, action, outcome):
        with self.assertRaises(TypeError):
            action.params["selector"] = "#evil"  # type: ignore[index]
        return True

    def __init__(self, test_case):
        self.assertRaises = test_case.assertRaises


class FailingRecorder:
    def record(self, action, outcome, result):
        raise OSError("disk unavailable")


class RuntimeTests(unittest.TestCase):
    def test_dry_run(self) -> None:
        runtime = ActionRuntime(DryRunExecutor())
        result = runtime.execute(Action(ActionKind.WAIT, {"milliseconds": 1}))
        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertNotIn("params", result.output)

    def test_confirmation_without_handler_is_cancelled(self) -> None:
        runtime = ActionRuntime(DryRunExecutor())
        action = Action(
            ActionKind.CLICK,
            {"selector": "button"},
            risk=RiskLevel.EXTERNAL,
        )
        self.assertIs(runtime.execute(action).status, ResultStatus.CANCELLED)

    def test_confirmation_handler_can_allow(self) -> None:
        runtime = ActionRuntime(DryRunExecutor(), confirm=lambda *_: True)
        action = Action(
            ActionKind.CLICK,
            {"selector": "button"},
            risk=RiskLevel.EXTERNAL,
        )
        self.assertIs(runtime.execute(action).status, ResultStatus.DRY_RUN)

    def test_action_is_immutable_through_confirmation(self) -> None:
        runtime = ActionRuntime(DryRunExecutor(), confirm=MutatingConfirmation(self))
        action = Action(
            ActionKind.CLICK,
            {"selector": "#approved"},
            risk=RiskLevel.EXTERNAL,
        )
        self.assertIs(runtime.execute(action).status, ResultStatus.DRY_RUN)
        self.assertEqual(action.params["selector"], "#approved")

    def test_executor_error_is_normalized(self) -> None:
        runtime = ActionRuntime(FailingExecutor(), confirm=lambda *_: True)
        result = runtime.execute(Action(ActionKind.CLICK, {"selector": "button"}))
        self.assertIs(result.status, ResultStatus.ERROR)
        self.assertEqual(result.error, "executor failed")

    def test_executor_error_does_not_reflect_exception_text(self) -> None:
        result = ActionRuntime(SecretFailingExecutor(), confirm=lambda *_: True).execute(
            Action(ActionKind.CLICK, {"selector": "button"})
        )
        self.assertIs(result.status, ResultStatus.ERROR)
        self.assertEqual(result.error, "executor failed")
        self.assertNotIn("runtime-secret-token", result.error or "")

    def test_denied_action_stops_batch(self) -> None:
        runtime = ActionRuntime(
            DryRunExecutor(),
            policy=PolicyEngine.standard(["example.com"]),
        )
        results = runtime.execute_many(
            [
                Action(ActionKind.NAVIGATE, {"url": "https://blocked.test"}),
                Action(ActionKind.CLICK, {"selector": "button"}),
            ]
        )
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].status, ResultStatus.DENIED)

    def test_trace_recursively_redacts_complete_event(self) -> None:
        secret = "private input should never appear"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            runtime = ActionRuntime(
                DryRunExecutor(),
                recorder=TraceRecorder(path, trace_id="run-1"),
                confirm=lambda *_: True,
            )
            runtime.execute(
                Action(
                    ActionKind.TYPE,
                    {"selector": "#search", "text": secret},
                    metadata={"nested": {"token": secret}},
                )
            )
            raw_trace = path.read_text(encoding="utf-8")
            event = next(read_trace(path))
            self.assertNotIn(secret, raw_trace)
            self.assertEqual(event["action"]["params"]["text"], REDACTED)
            self.assertEqual(event["action"]["metadata"], {})
            self.assertEqual(event["trace_id"], REDACTED)
            self.assertEqual(event["sequence"], 1)
            self.assertTrue(contains_redaction(event))
            self.assertEqual(event["policy"]["decision"], Decision.CONFIRM.value)

    def test_trace_redacts_url_query_and_userinfo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            runtime = ActionRuntime(
                DryRunExecutor(),
                policy=PolicyEngine.standard(["example.com"]),
                recorder=TraceRecorder(path),
            )
            runtime.execute(
                Action(ActionKind.NAVIGATE, {"url": "https://example.com/path?token=visible"})
            )
            event = next(read_trace(path))
            self.assertEqual(
                event["action"]["params"]["url"],
                REDACTED,
            )

    def test_trace_redacts_unknown_metadata_and_executor_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            secret = "custom executor secret"
            action = Action(
                ActionKind.CLICK,
                {"selector": "#safe"},
                metadata={"provider": "test", "raw_payload": {"text": secret}},
            )
            TraceRecorder(path).record(
                action,
                __import__("actionanything").PolicyOutcome(Decision.ALLOW, "test", "test"),
                __import__("actionanything").ActionResult(
                    action.id,
                    ResultStatus.SUCCESS,
                    output={"url": "https://example.com?secret=visible", "raw": secret},
                    error=secret,
                ),
            )
            raw_trace = path.read_text(encoding="utf-8")
            event = next(read_trace(path))
            self.assertNotIn(secret, raw_trace)
            self.assertEqual(event["action"]["metadata"], {})
            self.assertEqual(event["result"]["output"]["raw"], REDACTED)
            self.assertEqual(
                event["result"]["output"]["url"],
                REDACTED,
            )
            self.assertEqual(event["result"]["error"], REDACTED)

    def test_new_trace_is_owner_readable_only_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            runtime = ActionRuntime(DryRunExecutor(), recorder=TraceRecorder(path))
            runtime.execute(Action(ActionKind.CLICK, {"selector": "button"}))
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_recorder_failure_does_not_hide_completed_action(self) -> None:
        result = ActionRuntime(
            DryRunExecutor(), recorder=FailingRecorder(), confirm=lambda *_: True
        ).execute(
            Action(ActionKind.CLICK, {"selector": "button"})
        )
        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(result.audit_error, "trace recording failed")


if __name__ == "__main__":
    unittest.main()
