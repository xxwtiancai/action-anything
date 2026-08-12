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
from .runtime import ActionRuntime


def _load_actions(path: str | Path) -> list[Action]:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except RecursionError as exc:
        raise ValueError("action plan is nested too deeply") from exc
    items = payload.get("actions") if isinstance(payload, dict) else payload
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


def _run(args: argparse.Namespace) -> int:
    runtime = _build_runtime(args)
    try:
        return _print_results(runtime.execute_many(_load_actions(args.plan)))
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


def _replay(args: argparse.Namespace) -> int:
    actions: list[Action] = []
    trace_id: str | None = None
    for event in read_trace(args.trace):
        payload = event["action"]
        if contains_redaction(payload):
            raise ValueError(
                "trace contains redacted values and cannot be replayed safely; "
                "record a local test trace with --unsafe-trace"
            )
        event_trace_id = event.get("trace_id")
        if event_trace_id is not None:
            if not isinstance(event_trace_id, str) or not event_trace_id:
                raise ValueError("trace contains an invalid trace_id")
            if trace_id is None:
                trace_id = event_trace_id
            elif event_trace_id != trace_id:
                raise ValueError(
                    "trace contains multiple runs and cannot be replayed as one plan"
                )
        try:
            actions.append(Action.from_dict(payload))
        except (ActionValidationError, TypeError) as exc:
            raise ValueError(f"trace contains an invalid action: {exc}") from exc
    runtime = _build_runtime(args, replay=True)
    try:
        return _print_results(runtime.execute_many(actions))
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
