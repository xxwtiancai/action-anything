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


class FailingExecutor:
    is_dry_run = False

    def execute(self, action: Action):
        raise RuntimeError("executor failed")


class RuntimeTests(unittest.TestCase):
    def test_dry_run(self) -> None:
        runtime = ActionRuntime(DryRunExecutor())
        result = runtime.execute(Action(ActionKind.CLICK, {"selector": "button"}))
        self.assertIs(result.status, ResultStatus.DRY_RUN)

    def test_confirmation_without_handler_is_cancelled(self) -> None:
        runtime = ActionRuntime(DryRunExecutor())
        action = Action(ActionKind.CLICK, risk=RiskLevel.EXTERNAL)
        self.assertIs(runtime.execute(action).status, ResultStatus.CANCELLED)

    def test_confirmation_handler_can_allow(self) -> None:
        runtime = ActionRuntime(DryRunExecutor(), confirm=lambda *_: True)
        action = Action(ActionKind.CLICK, risk=RiskLevel.EXTERNAL)
        self.assertIs(runtime.execute(action).status, ResultStatus.DRY_RUN)

    def test_executor_error_is_normalized(self) -> None:
        runtime = ActionRuntime(FailingExecutor())
        result = runtime.execute(Action(ActionKind.CLICK))
        self.assertIs(result.status, ResultStatus.ERROR)
        self.assertEqual(result.error, "executor failed")

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

    def test_trace_redacts_typed_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            runtime = ActionRuntime(
                DryRunExecutor(),
                recorder=TraceRecorder(path),
            )
            runtime.execute(
                Action(
                    ActionKind.TYPE,
                    {"selector": "#search", "text": "private input"},
                )
            )
            event = next(read_trace(path))
            self.assertEqual(event["action"]["params"]["text"], "[REDACTED]")
            self.assertEqual(event["policy"]["decision"], Decision.ALLOW.value)


if __name__ == "__main__":
    unittest.main()

