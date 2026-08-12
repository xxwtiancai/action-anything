"""Command-line interface for running and inspecting action plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from .actions import Action, ActionValidationError, ResultStatus
from .executors import DryRunExecutor, PlaywrightExecutor
from .policy import PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder, contains_redaction, read_trace
from .runtime import ActionRuntime, ExecutionBudget


def _load_actions(path: str | Path) -> list[Action]:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except RecursionError:
        raise ValueError("action plan is nested too deeply") from None
    if isinstance(payload, dict):
        if "budget" in payload:
            raise ValueError(
                "action plans must not set budget; configure trusted runtime or CLI limits"
            )
        items = payload.get("actions")
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("action plan must be a JSON list or an object with 'actions'")
    actions: list[Action] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"action at index {index} must be an object")
        try:
            actions.append(Action.from_dict(item))
        except (ActionValidationError, TypeError) as exc:
            raise ValueError(f"invalid action at index {index}: {exc}") from exc
    return actions


def _confirm(action: Action, outcome: PolicyOutcome) -> bool:
    summary = action.to_dict()
    summary["params"].pop("text", None)
    answer = input(
        f"Confirm {action.kind.value} {json.dumps(summary['params'])} "
        f"({outcome.reason})? [y/N] "
    ).strip()
    return answer.lower() in {"y", "yes"}


def _build_runtime(args: argparse.Namespace, *, replay: bool = False) -> ActionRuntime:
    if args.execute and not args.allowed_domain:
        raise ValueError("--execute requires at least one --allowed-domain")
    executor = (
        PlaywrightExecutor(
            allowed_domains=args.allowed_domain,
            headless=not args.show_browser,
        )
        if args.execute
        else DryRunExecutor()
    )
    policy = PolicyEngine.standard(args.allowed_domain)
    recorder = None if replay else TraceRecorder(args.trace, redact=not args.unsafe_trace)
    confirmer = (lambda *_: True) if args.yes else _confirm
    return ActionRuntime(executor, policy=policy, recorder=recorder, confirm=confirmer)


def _print_results(results: Iterable[Any]) -> int:
    exit_code = 0
    for result in results:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.status in {
            ResultStatus.ERROR,
            ResultStatus.DENIED,
            ResultStatus.CANCELLED,
        }:
            exit_code = 1
    return exit_code


def _execution_budget(args: argparse.Namespace) -> ExecutionBudget | None:
    """Build trusted CLI execution limits without accepting plan-provided ones."""

    max_actions = args.max_actions
    max_total_wait_milliseconds = args.max_total_wait_milliseconds
    if max_actions is None and max_total_wait_milliseconds is None:
        return None
    return ExecutionBudget(
        max_actions=max_actions,
        max_total_wait_milliseconds=max_total_wait_milliseconds,
    )


def _run(args: argparse.Namespace) -> int:
    budget = _execution_budget(args)
    runtime = _build_runtime(args)
    try:
        return _print_results(
            runtime.execute_many(_load_actions(args.plan), budget=budget)
        )
    finally:
        close = getattr(runtime.executor, "close", None)
        if close is not None:
            close()


def _validate(args: argparse.Namespace) -> int:
    actions = _load_actions(args.plan)
    print(
        json.dumps(
            {"valid": True, "action_count": len(actions), "actions": [action.to_dict() for action in actions]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _inspect(args: argparse.Namespace) -> int:
    for event in read_trace(args.trace):
        action = event["action"]
        result = event.get("result", {})
        print(
            f"{event.get('timestamp', '-')}  "
            f"{action.get('kind', '?'):10}  "
            f"{result.get('status', '?')}"
        )
    return 0


def _validate_replay_admission(event: dict[str, Any], action: Action) -> None:
    """Reject trace events that do not represent a completed safe replay case.

    A trace is evidence, not an execution queue. In particular, replaying a
    failed, denied, or cancelled event would turn a past decision or uncertain
    partial side effect into an implicit retry. Replay is deliberately limited
    to completed dry-run evidence with an explicit allow/confirm decision; a
    real executor success is not evidence that a repeated side effect is safe.
    """

    policy = event.get("policy")
    result = event.get("result")
    if not isinstance(policy, dict) or not isinstance(result, dict):
        raise ValueError("trace contains an invalid policy or result")
    if contains_redaction(policy) or contains_redaction(result):
        raise ValueError(
            "trace contains redacted values and cannot be replayed safely; "
            "record a local test trace with --unsafe-trace"
        )
    if policy.get("name") == "ExecutionBudget":
        raise ValueError(
            "trace contains actions not admitted for execution and cannot be replayed safely"
        )
    decision = policy.get("decision")
    if not isinstance(decision, str) or decision not in {"allow", "confirm"}:
        raise ValueError(
            "trace contains an action without an executable policy decision and cannot be replayed safely"
        )
    if (
        not isinstance(policy.get("name"), str)
        or not policy["name"].strip()
        or not isinstance(policy.get("reason"), str)
        or not policy["reason"].strip()
    ):
        raise ValueError("trace contains incomplete policy evidence")
    required_result_fields = {"action_id", "status", "output", "error", "audit_error"}
    if not required_result_fields.issubset(result):
        raise ValueError("trace contains incomplete result evidence")
    status = result.get("status")
    if not isinstance(status, str) or status != ResultStatus.DRY_RUN.value:
        raise ValueError(
            "trace contains an action without a completed dry-run result and cannot be replayed safely"
        )
    if result.get("action_id") != action.id or not isinstance(result.get("output"), dict):
        raise ValueError("trace contains incomplete result evidence")
    if result.get("error") is not None or result.get("audit_error") is not None:
        raise ValueError("trace contains an action with execution or audit errors")


def _validate_replay_run_identity(
    event: dict[str, Any],
    *,
    trace_id: str | None,
    expects_identity: bool | None,
    previous_sequence: int | None,
) -> tuple[str | None, bool, int | None]:
    """Require one current trace run or one consistently legacy trace profile.

    Recorder recovery can leave intentional sequence gaps after an unrecorded
    failed attempt, so sequences need only be positive and strictly increasing.
    Trace ID and sequence are paired current-format fields; a legacy replay
    input may omit both consistently, but a mixed profile is not trustworthy.
    """

    has_trace_id = "trace_id" in event
    has_sequence = "sequence" in event
    if has_trace_id != has_sequence:
        raise ValueError("trace mixes current and legacy run identity fields")
    if expects_identity is None:
        expects_identity = has_trace_id
    elif expects_identity != has_trace_id:
        raise ValueError("trace mixes current and legacy run identity fields")
    if not has_trace_id:
        return trace_id, expects_identity, previous_sequence

    event_trace_id = event["trace_id"]
    sequence = event["sequence"]
    if (
        not isinstance(event_trace_id, str)
        or not event_trace_id
        or contains_redaction(event_trace_id)
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
    ):
        raise ValueError("trace contains an invalid run identity")
    if trace_id is not None and event_trace_id != trace_id:
        raise ValueError("trace contains multiple runs and cannot be replayed as one plan")
    if previous_sequence is not None and sequence <= previous_sequence:
        raise ValueError("trace sequence is not strictly increasing")
    return event_trace_id, expects_identity, sequence


def _replay(args: argparse.Namespace) -> int:
    budget = _execution_budget(args)
    actions: list[Action] = []
    trace_id: str | None = None
    expects_identity: bool | None = None
    previous_sequence: int | None = None
    event_count = 0
    for event in read_trace(args.trace):
        event_count += 1
        payload = event["action"]
        if contains_redaction(payload):
            raise ValueError(
                "trace contains redacted values and cannot be replayed safely; "
                "record a local test trace with --unsafe-trace"
            )
        try:
            action = Action.from_dict(payload)
        except (ActionValidationError, TypeError) as exc:
            raise ValueError(f"trace contains an invalid action: {exc}") from exc
        _validate_replay_admission(event, action)
        trace_id, expects_identity, previous_sequence = _validate_replay_run_identity(
            event,
            trace_id=trace_id,
            expects_identity=expects_identity,
            previous_sequence=previous_sequence,
        )
        actions.append(action)
    if not event_count:
        raise ValueError("trace contains no replayable events")
    runtime = _build_runtime(args, replay=True)
    try:
        return _print_results(runtime.execute_many(actions, budget=budget))
    finally:
        close = getattr(runtime.executor, "close", None)
        if close is not None:
            close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aa",
        description="Safely execute and inspect model-agnostic agent actions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_runtime_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--execute",
            action="store_true",
            help="use Playwright instead of the default dry-run executor",
        )
        command.add_argument(
            "--show-browser",
            action="store_true",
            help="show the Playwright browser window",
        )
        command.add_argument(
            "--allowed-domain",
            action="append",
            default=[],
            help="allow navigation to this domain (repeatable)",
        )
        command.add_argument(
            "--yes",
            action="store_true",
            help="automatically confirm policy-gated actions",
        )
        command.add_argument(
            "--max-actions",
            type=int,
            help="evaluate at most this many actions from the batch",
        )
        command.add_argument(
            "--max-total-wait-ms",
            "--max-total-wait-milliseconds",
            dest="max_total_wait_milliseconds",
            type=int,
            help="allow at most this many cumulative wait milliseconds at the executor",
        )

    run = subparsers.add_parser("run", help="run a JSON action plan")
    run.add_argument("plan", help="path to a JSON action plan")
    run.add_argument("--trace", default="actionanything-trace.jsonl")
    run.add_argument(
        "--unsafe-trace",
        action="store_true",
        help="store unredacted parameters; use only with non-sensitive test data",
    )
    add_runtime_options(run)
    run.set_defaults(handler=_run)

    validate = subparsers.add_parser(
        "validate", help="validate and normalize a JSON action plan without execution"
    )
    validate.add_argument("plan", help="path to a JSON action plan")
    validate.set_defaults(handler=_validate)

    inspect = subparsers.add_parser("inspect", help="summarize a JSONL trace")
    inspect.add_argument("trace")
    inspect.set_defaults(handler=_inspect)

    replay = subparsers.add_parser("replay", help="replay an unredacted test trace")
    replay.add_argument("trace")
    add_runtime_options(replay)
    replay.set_defaults(handler=_replay)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # ``ArgumentParser.error`` terminates the interpreter, which makes the
        # console script correct but makes this library entry point awkward to
        # embed or test. Keep its familiar formatting and return its status.
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
