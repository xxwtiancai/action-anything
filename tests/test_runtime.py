import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actionanything import (
    Action,
    ActionKind,
    ActionRuntime,
    Decision,
    DryRunExecutor,
    ExecutionBudget,
    PolicyEngine,
    ResultStatus,
    RiskLevel,
    TraceRecorder,
    read_trace,
)
from actionanything.recorder import REDACTED, contains_redaction
from actionanything.policy import RiskPolicy


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


class DenyActionIdPolicy:
    def __init__(self, denied_action_id: str) -> None:
        self.denied_action_id = denied_action_id

    def evaluate(self, action: Action):
        if action.id == self.denied_action_id:
            return __import__("actionanything").PolicyOutcome(
                Decision.DENY,
                "test policy denial",
                type(self).__name__,
            )
        return None


class RecordingPolicy:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def evaluate(self, action: Action):
        self.actions.append(action)
        return None


class RiskDowngradingPolicy:
    def evaluate(self, action: Action):
        object.__setattr__(action, "risk", RiskLevel.NONE)
        return None


class RecordingRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[Action, object, object]] = []

    def record(self, action, outcome, result) -> None:
        self.events.append((action, outcome, result))


class OverrideRuntime(ActionRuntime):
    def execute(self, action: Action):
        return __import__("actionanything").ActionResult(
            action.id,
            ResultStatus.DENIED,
            error="embedding override",
        )


class InternalOverrideRuntime(ActionRuntime):
    def _execute(self, action: Action, budget_state=None):
        return super()._execute(action, budget_state=None)


class CountingOverrideRuntime(ActionRuntime):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.execute_calls: list[object] = []

    def execute(self, action: Action):
        self.execute_calls.append(action)
        return __import__("actionanything").ActionResult(
            action.id,
            ResultStatus.DENIED,
            error="embedding override",
        )


class TruthyConfirmation:
    def __bool__(self) -> bool:
        raise AssertionError("confirmation result must not be truth-tested")


class SwitchText(str):
    def __str__(self) -> str:
        return "x" * 60_000


class UnderstatedRisk(int):
    def __int__(self) -> int:
        return 0


class RecordingExecutor:
    """A dry-run executor whose calls expose runtime budget boundaries."""

    is_dry_run = True

    def __init__(self) -> None:
        self.actions: list[Action] = []

    def execute(self, action: Action):
        self.actions.append(action)
        return {"message": "recorded"}


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

    def test_confirmation_requires_literal_builtin_true(self) -> None:
        action = Action(ActionKind.CLICK, {"selector": "#approve"})
        for response in (False, "yes", "no", 1, object(), TruthyConfirmation()):
            with self.subTest(response_type=type(response).__name__):
                executor = RecordingExecutor()
                result = ActionRuntime(
                    executor, confirm=lambda *_: response
                ).execute(action)
                self.assertIs(result.status, ResultStatus.CANCELLED)
                self.assertEqual(executor.actions, [])

    def test_runtime_rejects_noncanonical_action_before_any_hook(self) -> None:
        forged = SimpleNamespace(
            id="forged-click",
            kind=ActionKind.CLICK,
            params={"selector": "#submit"},
            risk=RiskLevel.NONE,
        )
        executor = RecordingExecutor()
        policy = RecordingPolicy()
        confirmations: list[object] = []
        runtime = ActionRuntime(
            executor,
            policy=PolicyEngine([policy]),
            confirm=lambda *_: confirmations.append(object()) or True,
        )

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime.execute(forged)  # type: ignore[arg-type]

        self.assertEqual(policy.actions, [])
        self.assertEqual(confirmations, [])
        self.assertEqual(executor.actions, [])

    def test_runtime_rejects_action_subclasses_before_any_hook(self) -> None:
        class DerivedAction(Action):
            pass

        derived = DerivedAction(ActionKind.WAIT, {"milliseconds": 1})
        executor = RecordingExecutor()
        policy = RecordingPolicy()
        runtime = ActionRuntime(executor, policy=PolicyEngine([policy]))

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime.execute(derived)

        self.assertEqual(policy.actions, [])
        self.assertEqual(executor.actions, [])

    def test_runtime_recanonicalizes_tampered_exact_action_before_any_hook(self) -> None:
        action = Action(ActionKind.CLICK, {"selector": "#submit"})
        object.__setattr__(action, "risk", RiskLevel.NONE)
        executor = RecordingExecutor()
        runtime = ActionRuntime(executor)

        result = runtime.execute(action)

        self.assertIs(result.status, ResultStatus.CANCELLED)
        self.assertEqual(executor.actions, [])

    def test_runtime_recanonicalizes_unconstructed_exact_action(self) -> None:
        action = object.__new__(Action)
        object.__setattr__(action, "id", "unconstructed-click")
        object.__setattr__(action, "kind", ActionKind.CLICK)
        object.__setattr__(action, "params", {"selector": "#submit"})
        object.__setattr__(action, "risk", RiskLevel.NONE)
        object.__setattr__(action, "metadata", {})
        executor = RecordingExecutor()

        result = ActionRuntime(executor).execute(action)

        self.assertIs(result.status, ResultStatus.CANCELLED)
        self.assertEqual(executor.actions, [])

    def test_runtime_private_execute_rejects_noncanonical_action_before_any_hook(self) -> None:
        forged = SimpleNamespace(
            id="forged-click",
            kind=ActionKind.CLICK,
            params={"selector": "#submit"},
            risk=RiskLevel.NONE,
        )
        executor = RecordingExecutor()
        policy = RecordingPolicy()
        runtime = ActionRuntime(executor, policy=PolicyEngine([policy]))

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime._execute(forged)  # type: ignore[arg-type]

        self.assertEqual(policy.actions, [])
        self.assertEqual(executor.actions, [])

    def test_confirmation_cannot_mutate_the_execution_snapshot(self) -> None:
        action = Action(ActionKind.CLICK, {"selector": "#submit"})
        executor = RecordingExecutor()

        def mutate_confirmation(candidate, outcome):
            object.__setattr__(candidate, "kind", ActionKind.NAVIGATE)
            object.__setattr__(candidate, "params", {"url": "http://127.0.0.1"})
            object.__setattr__(candidate, "risk", RiskLevel.NONE)
            return True

        result = ActionRuntime(executor, confirm=mutate_confirmation).execute(action)

        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(len(executor.actions), 1)
        executed = executor.actions[0]
        self.assertIs(executed.kind, ActionKind.CLICK)
        self.assertEqual(executed.params, {"selector": "#submit"})
        self.assertIs(executed.risk, RiskLevel.REVERSIBLE)

    def test_policy_cannot_mutate_another_policy_input(self) -> None:
        executor = RecordingExecutor()
        runtime = ActionRuntime(
            executor,
            policy=PolicyEngine([RiskDowngradingPolicy(), RiskPolicy()]),
        )

        result = runtime.execute(Action(ActionKind.CLICK, {"selector": "#submit"}))

        self.assertIs(result.status, ResultStatus.CANCELLED)
        self.assertEqual(executor.actions, [])

    def test_runtime_snapshot_normalizes_scalar_subclasses(self) -> None:
        action = Action(ActionKind.TYPE, {"text": SwitchText("safe")})
        executor = RecordingExecutor()

        result = ActionRuntime(executor, confirm=lambda *_: True).execute(action)

        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(len(executor.actions), 1)
        text = executor.actions[0].params["text"]
        self.assertIs(type(text), str)
        self.assertEqual(text, "safe")

    def test_runtime_snapshot_uses_base_scalar_values(self) -> None:
        class SwitchInteger(int):
            def __int__(self) -> int:
                return 60_000

        action = Action(ActionKind.WAIT, {"milliseconds": SwitchInteger(1)})
        executor = RecordingExecutor()

        result = ActionRuntime(executor).execute(action)

        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(executor.actions[0].params["milliseconds"], 1)

    def test_runtime_snapshot_does_not_trust_tampered_to_dict_or_risk(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        object.__setattr__(
            action,
            "to_dict",
            lambda: {
                "kind": "navigate",
                "params": {"url": "https://example.com"},
            },
        )
        executor = RecordingExecutor()

        result = ActionRuntime(executor).execute(action)

        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertIs(executor.actions[0].kind, ActionKind.WAIT)
        self.assertEqual(executor.actions[0].params, {"milliseconds": 1})

        critical = Action(
            ActionKind.NAVIGATE,
            {"url": "https://example.com"},
            risk=RiskLevel.CRITICAL,
        )
        object.__setattr__(critical, "risk", UnderstatedRisk(4))
        guarded = ActionRuntime(
            RecordingExecutor(),
            policy=PolicyEngine([RiskPolicy()]),
        )

        self.assertIs(guarded.execute(critical).status, ResultStatus.CANCELLED)

    def test_runtime_snapshot_preserves_large_valid_metadata_integers(self) -> None:
        large_value = 10**5_000
        action = Action(
            ActionKind.WAIT,
            {"milliseconds": 1},
            metadata={"large_value": large_value},
        )
        executor = RecordingExecutor()

        result = ActionRuntime(executor).execute(action)

        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(executor.actions[0].metadata["large_value"], large_value)

    def test_budgeted_batch_rejects_noncanonical_action_before_budget_hooks(self) -> None:
        forged = SimpleNamespace(
            id="forged-wait",
            kind=ActionKind.WAIT,
            params={"milliseconds": 1},
            risk=RiskLevel.NONE,
        )
        executor = RecordingExecutor()
        policy = RecordingPolicy()
        runtime = ActionRuntime(executor, policy=PolicyEngine([policy]))

        with patch(
            "actionanything.runtime._ExecutionBudgetState.admit",
            side_effect=AssertionError("budget must not see a forged action"),
        ):
            with self.assertRaisesRegex(TypeError, "canonical Action"):
                runtime.execute_many(
                    [forged], budget=ExecutionBudget(max_actions=0)  # type: ignore[list-item]
                )

        self.assertEqual(policy.actions, [])
        self.assertEqual(executor.actions, [])

    def test_budgeted_batch_rejects_noncanonical_extra_candidate_before_denial(self) -> None:
        class DerivedAction(Action):
            pass

        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        derived = DerivedAction(ActionKind.WAIT, {"milliseconds": 1})
        executor = RecordingExecutor()
        runtime = ActionRuntime(executor)

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime.execute_many(
                [first, derived], budget=ExecutionBudget(max_actions=1)
            )

        self.assertEqual(executor.actions, [first])

    def test_unbudgeted_batch_rejects_noncanonical_action_before_any_hook(self) -> None:
        forged = SimpleNamespace(
            id="forged-wait",
            kind=ActionKind.WAIT,
            params={"milliseconds": 1},
            risk=RiskLevel.NONE,
        )
        executor = RecordingExecutor()
        policy = RecordingPolicy()
        recorder = RecordingRecorder()
        runtime = ActionRuntime(
            executor,
            policy=PolicyEngine([policy]),
            recorder=recorder,
        )

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime.execute_many([forged])  # type: ignore[list-item]

        self.assertEqual(policy.actions, [])
        self.assertEqual(executor.actions, [])
        self.assertEqual(recorder.events, [])

    def test_unbudgeted_batch_rejects_noncanonical_action_before_execute_override(self) -> None:
        forged = SimpleNamespace(
            id="forged-wait",
            kind=ActionKind.WAIT,
            params={"milliseconds": 1},
            risk=RiskLevel.NONE,
        )
        runtime = CountingOverrideRuntime(RecordingExecutor())

        with self.assertRaisesRegex(TypeError, "canonical Action"):
            runtime.execute_many([forged])  # type: ignore[list-item]

        self.assertEqual(runtime.execute_calls, [])

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

    def test_executor_output_must_be_a_mapping(self) -> None:
        class ListOutputExecutor:
            is_dry_run = True

            def execute(self, action: Action):
                return ["not-a-mapping"]

        result = ActionRuntime(ListOutputExecutor()).execute(
            Action(ActionKind.WAIT, {"milliseconds": 1})
        )
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

    def test_execution_budget_limits_batch_evaluation_before_the_executor(self) -> None:
        executor = RecordingExecutor()
        runtime = ActionRuntime(executor)
        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        second = Action(ActionKind.WAIT, {"milliseconds": 1})

        third = Action(ActionKind.WAIT, {"milliseconds": 1})
        results = runtime.execute_many(
            [first, second, third],
            stop_on_error=False,
            budget=ExecutionBudget(max_actions=1),
        )

        self.assertEqual(
            [result.status for result in results],
            [ResultStatus.DRY_RUN, ResultStatus.DENIED],
        )
        self.assertEqual(executor.actions, [first])
        self.assertEqual(len(results), 2)
        self.assertEqual(
            results[1].error,
            "execution budget reached its maximum action count",
        )

    def test_execution_budget_does_not_evaluate_action_over_the_count_limit(self) -> None:
        policy = RecordingPolicy()
        runtime = ActionRuntime(RecordingExecutor(), policy=PolicyEngine([policy]))
        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        second = Action(ActionKind.WAIT, {"milliseconds": 1})

        results = runtime.execute_many(
            [first, second],
            budget=ExecutionBudget(max_actions=1),
        )

        self.assertEqual(policy.actions, [first])
        self.assertEqual(
            [result.status for result in results],
            [ResultStatus.DRY_RUN, ResultStatus.DENIED],
        )

    def test_action_budget_reads_only_one_extra_candidate_for_a_traceable_denial(self) -> None:
        policy = RecordingPolicy()
        executor = RecordingExecutor()
        runtime = ActionRuntime(executor, policy=PolicyEngine([policy]))
        yielded: list[Action] = []
        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        denied = Action(ActionKind.WAIT, {"milliseconds": 1})
        never_read = Action(ActionKind.WAIT, {"milliseconds": 1})

        def candidates():
            for action in (first, denied, never_read):
                yielded.append(action)
                yield action

        results = runtime.execute_many(candidates(), budget=ExecutionBudget(max_actions=1))

        self.assertEqual(yielded, [first, denied])
        self.assertEqual(policy.actions, [first])
        self.assertEqual(executor.actions, [first])
        self.assertEqual(
            [result.status for result in results],
            [ResultStatus.DRY_RUN, ResultStatus.DENIED],
        )

    def test_budget_state_resets_and_runtime_override_behavior_is_explicit(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        runtime = ActionRuntime(RecordingExecutor())
        budget = ExecutionBudget(max_actions=1)

        first = runtime.execute_many([action], budget=budget)
        second = runtime.execute_many([action], budget=budget)

        self.assertEqual([result.status for result in first], [ResultStatus.DRY_RUN])
        self.assertEqual([result.status for result in second], [ResultStatus.DRY_RUN])

        overridden = OverrideRuntime(RecordingExecutor()).execute_many([action])
        self.assertEqual([result.status for result in overridden], [ResultStatus.DENIED])
        self.assertEqual(overridden[0].error, "embedding override")

        overridden_executor = RecordingExecutor()
        overridden_runtime = OverrideRuntime(overridden_executor)
        with self.assertRaisesRegex(TypeError, "budgeted batches require"):
            overridden_runtime.execute_many(
                [action], budget=ExecutionBudget(max_actions=1)
            )
        self.assertEqual(overridden_executor.actions, [])

        internal_executor = RecordingExecutor()
        internal_override = InternalOverrideRuntime(internal_executor)
        with self.assertRaisesRegex(TypeError, "budgeted batches require"):
            internal_override.execute_many(
                [action], budget=ExecutionBudget(max_total_wait_milliseconds=0)
            )
        self.assertEqual(internal_executor.actions, [])

    def test_execution_budget_allows_exact_wait_limit_and_rejects_the_next_wait(self) -> None:
        executor = RecordingExecutor()
        runtime = ActionRuntime(executor)
        first = Action(ActionKind.WAIT, {"milliseconds": 400})
        second = Action(ActionKind.WAIT, {"milliseconds": 600})
        over_limit = Action(ActionKind.WAIT, {"milliseconds": 1})
        unrelated = Action(ActionKind.SCREENSHOT, {})

        results = runtime.execute_many(
            [first, second, over_limit, unrelated],
            stop_on_error=False,
            budget=ExecutionBudget(max_total_wait_milliseconds=1_000),
        )

        self.assertEqual(
            [result.status for result in results],
            [
                ResultStatus.DRY_RUN,
                ResultStatus.DRY_RUN,
                ResultStatus.DENIED,
            ],
        )
        self.assertEqual(executor.actions, [first, second])
        self.assertEqual(
            results[2].error,
            "execution budget reached its maximum cumulative wait time",
        )

    def test_denied_and_cancelled_actions_still_count_toward_batch_evaluation_budget(self) -> None:
        with self.subTest("policy denial"):
            executor = RecordingExecutor()
            runtime = ActionRuntime(
                executor,
                policy=PolicyEngine.standard(["example.com"]),
            )
            denied = Action(ActionKind.NAVIGATE, {"url": "https://blocked.test"})
            allowed = Action(ActionKind.WAIT, {"milliseconds": 1})
            over_limit = Action(ActionKind.WAIT, {"milliseconds": 1})

            results = runtime.execute_many(
                [denied, allowed, over_limit],
                stop_on_error=False,
                budget=ExecutionBudget(max_actions=1),
            )

            self.assertEqual(
                [result.status for result in results],
                [ResultStatus.DENIED, ResultStatus.DENIED],
            )
            self.assertEqual(executor.actions, [])

        with self.subTest("confirmation cancellation"):
            executor = RecordingExecutor()
            runtime = ActionRuntime(executor, confirm=lambda *_: False)
            cancelled = Action(ActionKind.CLICK, {"selector": "#confirm"})
            allowed = Action(ActionKind.WAIT, {"milliseconds": 1})
            over_limit = Action(ActionKind.WAIT, {"milliseconds": 1})

            results = runtime.execute_many(
                [cancelled, allowed, over_limit],
                stop_on_error=False,
                budget=ExecutionBudget(max_actions=1),
            )

            self.assertEqual(
                [result.status for result in results],
                [ResultStatus.CANCELLED, ResultStatus.DENIED],
            )
            self.assertEqual(executor.actions, [])

    def test_execution_budget_is_opt_in_and_strictly_validated(self) -> None:
        for kwargs in (
            {"max_actions": -1},
            {"max_actions": True},
            {"max_actions": 1.5},
            {"max_total_wait_milliseconds": -1},
            {"max_total_wait_milliseconds": False},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    ExecutionBudget(**kwargs)

        executor = RecordingExecutor()
        runtime = ActionRuntime(executor)
        actions = [
            Action(ActionKind.WAIT, {"milliseconds": 1}),
            Action(ActionKind.WAIT, {"milliseconds": 1}),
        ]
        results = runtime.execute_many(actions)
        self.assertEqual([result.status for result in results], [ResultStatus.DRY_RUN] * 2)
        self.assertEqual(executor.actions, actions)
        with self.assertRaisesRegex(TypeError, "ExecutionBudget"):
            runtime.execute_many([], budget=object())  # type: ignore[arg-type]

    def test_wait_budget_ignores_policy_denial_but_reserves_failed_execution(self) -> None:
        denied_wait = Action(ActionKind.WAIT, {"milliseconds": 60_000}, id="denied")
        permitted_wait = Action(ActionKind.WAIT, {"milliseconds": 1}, id="permitted")
        policy_runtime = ActionRuntime(
            RecordingExecutor(),
            policy=PolicyEngine([DenyActionIdPolicy(denied_wait.id)]),
        )
        policy_results = policy_runtime.execute_many(
            [denied_wait, permitted_wait],
            stop_on_error=False,
            budget=ExecutionBudget(max_total_wait_milliseconds=1),
        )
        self.assertEqual(
            [result.status for result in policy_results],
            [ResultStatus.DENIED, ResultStatus.DRY_RUN],
        )

        failed_wait = Action(ActionKind.WAIT, {"milliseconds": 1})
        after_failure = Action(ActionKind.WAIT, {"milliseconds": 1})
        failed_results = ActionRuntime(FailingExecutor()).execute_many(
            [failed_wait, after_failure],
            stop_on_error=False,
            budget=ExecutionBudget(max_total_wait_milliseconds=1),
        )
        self.assertEqual(
            [result.status for result in failed_results],
            [ResultStatus.ERROR, ResultStatus.DENIED],
        )
        self.assertEqual(
            failed_results[1].error,
            "execution budget reached its maximum cumulative wait time",
        )

    def test_execution_budget_denial_is_traceable_before_execution(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            executor = RecordingExecutor()
            results = ActionRuntime(
                executor,
                recorder=TraceRecorder(path, redact=False),
            ).execute_many([action], budget=ExecutionBudget(max_actions=0))
            events = list(read_trace(path))

        self.assertEqual([result.status for result in results], [ResultStatus.DENIED])
        self.assertEqual(executor.actions, [])
        self.assertEqual(events[0]["policy"]["decision"], Decision.DENY.value)
        self.assertEqual(events[0]["policy"]["name"], "ExecutionBudget")
        self.assertEqual(events[0]["result"]["status"], ResultStatus.DENIED.value)

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
