"""Append-only, redacted JSONL traces for audit and deliberate replay."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .actions import Action, ActionResult
from .policy import PolicyOutcome


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "error",
        "password",
        "secret",
        "session",
        "text",
        "token",
        "value",
    }
)
SENSITIVE_SUBSTRINGS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
    "api_key",
    "apikey",
)
_SAFE_RESULT_INTEGER_KEYS = frozenset({"characters", "delta_x", "delta_y", "milliseconds"})
_SAFE_RESULT_LITERAL_VALUES = {
    "message": frozenset(
        {
            "would execute navigate",
            "would execute click",
            "would execute type",
            "would execute scroll",
            "would execute wait",
            "would execute screenshot",
        }
    ),
    "target": frozenset({"selector", "focused_input"}),
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in SENSITIVE_KEYS or any(
        substring in lowered for substring in SENSITIVE_SUBSTRINGS
    )


def _redact_url(value: str) -> str:
    """Keep only an HTTP(S) origin and redact every URL-specific value.

    URLs routinely encode account identifiers and reset tokens in path segments
    as well as query strings and fragments.  A redacted trace needs an origin
    for useful debugging, not a replayable or user-specific URL.
    """

    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return REDACTED
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        # An executor error may include a malformed URL. Do not let the trace
        # path turn that into a second failure or persist an opaque raw value.
        return REDACTED

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        # ActionAnything's navigation surface is HTTP(S)-only.  Keeping an
        # opaque URI (for example data: or a custom callback scheme) offers no
        # useful replay provenance and can disclose its opaque payload.
        return REDACTED
    if not hostname:
        return REDACTED
    if parsed.netloc and not hostname:
        return REDACTED

    netloc = ""
    if hostname is not None:
        # urlsplit().hostname removes IPv6 brackets; add them back before
        # rebuilding the authority component. Userinfo is deliberately not
        # carried forward.
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None:
            netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, "", "", ""))


def redact_value(value: Any, key: str | None = None) -> Any:
    """Recursively redact sensitive values from JSON-compatible trace data."""

    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if key is not None and isinstance(value, str):
        normalized = key.lower().replace("-", "_")
        if normalized in {"url", "uri", "href"} or normalized.endswith(
            ("_url", "_uri", "_href")
        ):
            return _redact_url(value)
    return value


def contains_redaction(value: Any) -> bool:
    """Return whether a recursively nested trace payload contains a redaction."""

    if value == REDACTED:
        return True
    if isinstance(value, Mapping):
        return any(contains_redaction(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_redaction(item) for item in value)
    return False


def _redact_action(action: Action) -> dict[str, Any]:
    """Return the fixed, non-secret portion of a canonical action for a trace.

    Action IDs, metadata, selectors, URLs, typed text, and artifact names are
    all application- or provider-controlled strings.  The default trace does
    not attempt to decide which of those strings are shareable.  ``--unsafe-
    trace`` is the explicit opt-in for local test reproduction.
    """

    safe_params: dict[str, Any] = {}
    for key, value in action.params.items():
        if key in {"x", "y", "delta_x", "delta_y", "milliseconds", "full_page", "press_enter", "button"}:
            safe_params[key] = value
        else:
            safe_params[key] = REDACTED
    return {
        "id": REDACTED,
        "kind": action.kind.value,
        "params": safe_params,
        "risk": int(action.risk),
        "metadata": {},
    }


def _redact_result_output(output: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only bounded built-in result values in default traces."""

    redacted: dict[str, Any] = {}
    for key, value in output.items():
        if key in _SAFE_RESULT_INTEGER_KEYS:
            redacted[key] = value if isinstance(value, int) and not isinstance(value, bool) else REDACTED
        elif key in _SAFE_RESULT_LITERAL_VALUES:
            redacted[key] = (
                value
                if isinstance(value, str) and value in _SAFE_RESULT_LITERAL_VALUES[key]
                else REDACTED
            )
        elif key == "status":
            redacted[key] = (
                value
                if value is None
                or (isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599)
                else REDACTED
            )
        else:
            redacted[key] = REDACTED
    return redacted


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write a complete trace event or raise instead of accepting truncation.

    ``os.write`` is allowed to report a short write.  A JSONL recorder cannot
    safely treat that as a successful event: a partially written line makes
    later inspection and replay fail after an action may already have run.
    Retrying a positive short write preserves the event for the ordinary file
    descriptor case; no forward progress is an explicit recorder failure for
    the runtime to surface as an audit error.

    This helper does not claim multi-process transactionality.  Applications
    that share a trace among writers still need a single-writer or locking
    strategy.
    """

    remaining = memoryview(payload)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except InterruptedError:
            # No bytes are reported for an interrupted write, so retry the
            # unchanged remainder rather than silently losing the event.
            continue
        if (
            not isinstance(written, int)
            or isinstance(written, bool)
            or written <= 0
            or written > len(remaining)
        ):
            raise OSError("could not write complete trace event")
        remaining = remaining[written:]


class TraceRecorder:
    """Write one self-contained JSON object per evaluated action.

    A recorder belongs to exactly one logical run. The generated ``trace_id``
    and monotonically increasing sequence make an appended file inspectable;
    they do not make a trace tamper-proof. Treat replay inputs as untrusted.
    """

    def __init__(
        self,
        path: str | Path,
        redact: bool = True,
        *,
        trace_id: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.redact = redact
        self.trace_id = trace_id or uuid4().hex
        if not self.trace_id.strip():
            raise ValueError("trace_id must not be empty")
        self._sequence = 0

    def _event(
        self,
        action: Action,
        outcome: PolicyOutcome,
        result: ActionResult,
    ) -> dict[str, Any]:
        self._sequence += 1
        event: dict[str, Any] = {
            "trace_id": self.trace_id,
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action.to_dict(),
            "policy": {
                "decision": outcome.decision.value,
                "reason": outcome.reason,
                "name": outcome.policy,
            },
            "result": result.to_dict(),
        }
        if not self.redact:
            return event
        return {
            # A trace ID is an opaque local correlation handle. Keep it out of
            # default shareable traces so an embedding application cannot
            # accidentally place a session identifier in it.
            "trace_id": REDACTED,
            "sequence": self._sequence,
            "timestamp": event["timestamp"],
            "action": _redact_action(action),
            "policy": {
                "decision": outcome.decision.value,
                "reason": REDACTED,
                "name": REDACTED,
            },
            "result": {
                "action_id": REDACTED,
                "status": result.status.value,
                "output": _redact_result_output(result.output),
                "error": REDACTED if result.error else None,
                "audit_error": REDACTED if result.audit_error else None,
            },
        }

    def _safe_trace_path(self) -> Path:
        """Create a non-symlink parent chain and return the final trace path.

        The trace location is an application-controlled filesystem boundary,
        not an action-plan parameter.  Reject dot-parent traversal and static
        symlink components rather than silently following them while creating
        directories.  A same-UID actor can still race a directory replacement
        after this check; callers needing stronger host isolation must use a
        private working directory or an executor-owned storage volume.
        """

        raw_path = self.path
        if raw_path.is_absolute():
            current = Path(raw_path.anchor)
            parts = raw_path.parent.parts[1:]
        else:
            current = Path.cwd()
            parts = raw_path.parent.parts

        for part in parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise OSError("trace path must not contain parent traversal")
            current = current / part
            try:
                details = os.lstat(current)
            except FileNotFoundError:
                try:
                    os.mkdir(current, 0o700)
                except FileExistsError:
                    pass
                details = os.lstat(current)
            if stat.S_ISLNK(details.st_mode):
                # macOS exposes its system-owned temporary directory through
                # ``/var`` -> ``/private/var``. Allow only that fixed
                # operating-system alias; arbitrary caller-provided links are
                # never followed.
                if current == Path("/var") and os.name != "nt":
                    current = current.resolve()
                    continue
                raise OSError("trace path must not traverse a symbolic link")
            if not stat.S_ISDIR(details.st_mode):
                raise OSError("trace parent path must contain only directories")
        return current / raw_path.name

    def record(
        self,
        action: Action,
        outcome: PolicyOutcome,
        result: ActionResult,
    ) -> None:
        event = self._event(action, outcome, result)
        path = self._safe_trace_path()
        encoded = (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise OSError("could not open trace file safely") from exc
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise OSError("trace path must be a regular file")
            if os.name != "nt" and details.st_mode & 0o077:
                raise OSError("existing trace file must be owner-readable only")
            write_start = details.st_size
            try:
                _write_all(descriptor, encoded)
            except BaseException:
                # A later short-write failure must not leave an unterminated
                # JSON line in front of the next event. This rollback assumes
                # the recorder has a single writer; a shared trace needs an
                # application-provided lock or stronger storage boundary.
                try:
                    os.ftruncate(descriptor, write_start)
                except OSError as exc:
                    raise OSError("could not restore trace after incomplete write") from exc
                raise
        finally:
            os.close(descriptor)


def read_trace(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield structurally validated JSON objects from an ActionAnything trace."""

    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict) or "action" not in value:
                raise ValueError(f"invalid trace event on line {line_number}")
            if not isinstance(value["action"], dict):
                raise ValueError(f"invalid action in trace event on line {line_number}")
            yield value
