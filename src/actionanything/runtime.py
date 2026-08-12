"""Policy-gated action execution runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .actions import Action, ActionKind, ActionResult, ResultStatus
from .executors import Executor
from .policy import Decision, PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder


ConfirmationHandler = Callable[[Action, PolicyOutcome], bool]


@dataclass(frozen=True)
class ExecutionBudget:
    """A trusted, per-batch bound for ``ActionRuntime.execute_many``.

    ``None`` leaves a limit unbounded. ``max_actions`` limits the number of
    batch items that may enter policy evaluation, so it also bounds calls to
    ``Executor.execute`` even when a caller chooses ``stop_on_error=False``.
    To leave auditable evidence when more input exists, a capped batch reads at
    most one additional candidate and records it as denied; that candidate is
    not evaluated, confirmed, or executed. Cumulative *requested* wait time is
    reserved only after policy and confirmation pass, immediately before the
    runtime calls an executor.

    The budget is reset for every ``execute_many`` call. It is intentionally
    not an input-size, cross-process, cross-call, rate-limiting, or transaction
    mechanism. Applications with side-effecting producers should bound or
    materialize them upstream.
    """

    max_actions: int | None = None
    max_total_wait_milliseconds: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_actions", self.max_actions),
            ("max_total_wait_milliseconds", self.max_total_wait_milliseconds),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass
class _ExecutionBudgetState:
    """Mutable accounting kept private to one ``execute_many`` invocation."""

    budget: ExecutionBudget
    admitted_actions: int = 0
    reserved_wait_milliseconds: int = 0
    exhausted: bool = False

    def admit(self) -> PolicyOutcome | None:
        """Allow one batch item to enter policy evaluation or deny it."""

        if (
            self.budget.max_actions is not None
            and self.admitted_actions >= self.budget.max_actions
        ):
            self.exhausted = True
            return PolicyOutcome(
                Decision.DENY,
                "execution budget reached its maximum action count",
                ExecutionBudget.__name__,
            )
        self.admitted_actions += 1
        return None

    def reserve_execution(self, action: Action) -> PolicyOutcome | None:
        """Reserve a permitted action's executor-side wait time."""

        wait_milliseconds = (
            int(action.params["milliseconds"])
            if action.kind is ActionKind.WAIT
            else 0
        )
        if (
            self.budget.max_total_wait_milliseconds is not None
            and self.reserved_wait_milliseconds + wait_milliseconds
            > self.budget.max_total_wait_milliseconds
        ):
            self.exhausted = True
            return PolicyOutcome(
                Decision.DENY,
                "execution budget reached its maximum cumulative wait time",
                ExecutionBudget.__name__,
            )

        self.reserved_wait_milliseconds += wait_milliseconds
        return None


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
        """Evaluate and execute one action without a batch budget."""

        return self._execute(action)

    def _execute(
        self,
        action: Action,
        budget_state: _ExecutionBudgetState | None = None,
    ) -> ActionResult:
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

        if budget_state is not None:
            budget_outcome = budget_state.reserve_execution(action)
            if budget_outcome is not None:
                result = ActionResult(
                    action.id,
                    ResultStatus.DENIED,
                    error=budget_outcome.reason,
                )
                return self._record(action, budget_outcome, result)

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
        budget: ExecutionBudget | None = None,
    ) -> list[ActionResult]:
        """Evaluate a batch, optionally limiting executor attempts and waits.

        ``budget`` is trusted application configuration, not an action-plan
        field. Its action limit is checked before policy evaluation; permitted
        waits reserve their duration immediately before the executor. A budget
        denial is recorded like any other policy denial and always stops the
        batch, even when ``stop_on_error`` is false, so the budget cannot be
        bypassed with an unbounded iterable. To record that denial, the action
        cap may read one candidate beyond the admission limit; it never sends
        that candidate through policy, confirmation, or an executor.
        """

        if budget is not None and not isinstance(budget, ExecutionBudget):
            raise TypeError("budget must be an ExecutionBudget or None")
        if budget is None:
            # Preserve the public virtual ``execute`` boundary for existing
            # embedding subclasses. A batch without a budget must retain the
            # same override behavior it had before ExecutionBudget existed.
            return self._execute_unbudgeted_many(actions, stop_on_error)

        # A legacy override can add approval, auditing, or other safety logic
        # around either execution hook. Budget reservation must sit between
        # policy/confirmation and an executor call, so silently routing a
        # budgeted batch through an override would bypass that hook. Reject the
        # combination before consuming input or recording anything instead.
        execute_hook = getattr(self.execute, "__func__", self.execute)
        internal_execute_hook = getattr(self._execute, "__func__", self._execute)
        if (
            execute_hook is not ActionRuntime.execute
            or internal_execute_hook is not ActionRuntime._execute
        ):
            raise TypeError(
                "budgeted batches require the base ActionRuntime execution pipeline; "
                "use policy/executor composition or run the legacy override without a budget"
            )

        budget_state = _ExecutionBudgetState(budget)
        results: list[ActionResult] = []
        for action in actions:
            budget_outcome = budget_state.admit() if budget_state is not None else None
            if budget_outcome is not None:
                result = self._record(
                    action,
                    budget_outcome,
                    ActionResult(
                        action.id,
                        ResultStatus.DENIED,
                        error=budget_outcome.reason,
                    ),
                )
                results.append(result)
                break
            result = self._execute(action, budget_state)
            results.append(result)
            if budget_state is not None and budget_state.exhausted:
                break
            if stop_on_error and result.status in {
                ResultStatus.ERROR,
                ResultStatus.DENIED,
                ResultStatus.CANCELLED,
            }:
                break
        return results

    def _execute_unbudgeted_many(
        self,
        actions: Iterable[Action],
        stop_on_error: bool,
    ) -> list[ActionResult]:
        """Run a legacy-compatible batch through the public ``execute`` hook."""

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
