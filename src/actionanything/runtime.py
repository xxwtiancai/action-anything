"""Policy-gated action execution runtime."""

from __future__ import annotations

from typing import Callable, Iterable

from .actions import Action, ActionResult, ResultStatus
from .executors import Executor
from .policy import Decision, PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder


ConfirmationHandler = Callable[[Action, PolicyOutcome], bool]


class ActionRuntime:
    """Evaluate policy, request confirmation, execute, and record actions."""

    def __init__(
        self,
        executor: Executor,
        policy: PolicyEngine | None = None,
        recorder: TraceRecorder | None = None,
        confirm: ConfirmationHandler | None = None,
    ) -> None:
        self.executor = executor
        self.policy = policy or PolicyEngine.standard()
        self.recorder = recorder
        self.confirm = confirm

    def execute(self, action: Action) -> ActionResult:
        outcome = self.policy.evaluate(action)

        if outcome.decision is Decision.DENY:
            result = ActionResult(action.id, ResultStatus.DENIED, error=outcome.reason)
            return self._record(action, outcome, result)

        if outcome.decision is Decision.CONFIRM:
            if self.confirm is None or not self.confirm(action, outcome):
                result = ActionResult(
                    action.id,
                    ResultStatus.CANCELLED,
                    error="action was not confirmed",
                )
                return self._record(action, outcome, result)

        try:
            output = self.executor.execute(action)
            status = (
                ResultStatus.DRY_RUN
                if getattr(self.executor, "is_dry_run", False)
                else ResultStatus.SUCCESS
            )
            result = ActionResult(action.id, status, output=output)
        except Exception as exc:  # Executors normalize failures at this boundary.
            result = ActionResult(action.id, ResultStatus.ERROR, error=str(exc))
        return self._record(action, outcome, result)

    def execute_many(
        self,
        actions: Iterable[Action],
        stop_on_error: bool = True,
    ) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in actions:
            result = self.execute(action)
            results.append(result)
            if stop_on_error and result.status in {
                ResultStatus.ERROR,
                ResultStatus.DENIED,
                ResultStatus.CANCELLED,
            }:
                break
        return results

    def _record(
        self,
        action: Action,
        outcome: PolicyOutcome,
        result: ActionResult,
    ) -> ActionResult:
        if self.recorder is not None:
            self.recorder.record(action, outcome, result)
        return result

