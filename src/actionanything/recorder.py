"""Append-only JSONL traces for audit and replay."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .actions import Action, ActionResult
from .policy import PolicyOutcome


SENSITIVE_KEYS = frozenset({"password", "secret", "token", "text", "value"})


def _redact(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else value
        for key, value in mapping.items()
    }


class TraceRecorder:
    """Write one self-contained JSON object per evaluated action."""

    def __init__(self, path: str | Path, redact: bool = True) -> None:
        self.path = Path(path)
        self.redact = redact

    def record(
        self,
        action: Action,
        outcome: PolicyOutcome,
        result: ActionResult,
    ) -> None:
        payload = action.to_dict()
        if self.redact:
            payload["params"] = _redact(payload["params"])
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": payload,
            "policy": {
                "decision": outcome.decision.value,
                "reason": outcome.reason,
                "name": outcome.policy,
            },
            "result": result.to_dict(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def read_trace(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield validated JSON objects from an ActionAnything trace."""

    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict) or "action" not in value:
                raise ValueError(f"invalid trace event on line {line_number}")
            yield value

