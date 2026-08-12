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
        try:
            outcome = self.policy.evaluate(action)
        except Exception:
            outcome = PolicyOutcome(
                Decision.DENY,
                "policy engine failed; action denied",
                "ActionRuntime",
            )

        if outcome.decision is Decision.DENY:
            result = ActionResult(action.id, ResultStatus.DENIED, error=outcome.reason)
            return self._record(action, outcome, result)

        if outcome.decision is Decision.CONFIRM:
            try:
                approved = self.confirm is not None and self.confirm(action, outcome)
            except Exception:
                approved = False
            if not approved:
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
        except Exception:  # Executors normalize failures at this boundary.
            # Executor exceptions can contain URLs, page content, credentials,
            # or implementation-specific details.  Keep the public runtime and
            # CLI boundary stable without reflecting untrusted error text.
            result = ActionResult(action.id, ResultStatus.ERROR, error="executor failed")
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
            try:
                self.recorder.record(action, outcome, result)
            except Exception:
                # The action may already have executed. Preserve that fact in
                # the returned status instead of raising and encouraging an
                # unsafe caller retry.
                return ActionResult(
                    action_id=result.action_id,
                    status=result.status,
                    output=result.output,
                    error=result.error,
                    audit_error="trace recording failed",
                )
        return result
