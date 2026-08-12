"""Command-line interface for running and inspecting action plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .actions import Action, ResultStatus
from .executors import DryRunExecutor, PlaywrightExecutor
from .policy import PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder, read_trace
from .runtime import ActionRuntime


def _load_actions(path: str | Path) -> list[Action]:
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    items = payload.get("actions") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("action plan must be a JSON list or an object with 'actions'")
    return [Action.from_dict(item) for item in items]


def _confirm(action: Action, outcome: PolicyOutcome) -> bool:
    answer = input(
        f"Confirm {action.kind.value} ({outcome.reason})? [y/N] "
    ).strip()
    return answer.lower() in {"y", "yes"}


def _build_runtime(args: argparse.Namespace, *, replay: bool = False) -> ActionRuntime:
    executor = (
        PlaywrightExecutor(headless=not args.show_browser)
        if args.execute
        else DryRunExecutor()
    )
    policy = PolicyEngine.standard(args.allowed_domain or None)
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
    for event in read_trace(args.trace):
        payload = event["action"]
        if "[REDACTED]" in payload.get("params", {}).values():
            raise ValueError(
                "trace contains redacted values and cannot be replayed safely; "
                "record a local test trace with --unsafe-trace"
            )
        actions.append(Action.from_dict(payload))
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
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

