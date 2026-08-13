import tempfile
import threading
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from actionanything import Action, ActionKind, ActionResult, Decision, ResultStatus, TraceRecorder, read_trace
from actionanything.policy import PolicyOutcome
from actionanything.recorder import REDACTED, TraceRecorder, contains_redaction, redact_value

if os.name == "posix":
    import fcntl


class TraceRedactionTests(unittest.TestCase):
    def test_contains_redaction_handles_deep_trace_values_without_recursion(self) -> None:
        value: dict[str, object] = {}
        cursor = value
        for _ in range(1_000):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child
        cursor["value"] = REDACTED

        self.assertTrue(contains_redaction(value))

        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        self.assertFalse(contains_redaction(cyclic))
        cyclic["value"] = REDACTED
        self.assertTrue(contains_redaction(cyclic))

    def test_read_trace_rejects_deep_or_invalid_event_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deeply_nested = root / "deep.jsonl"
            deeply_nested.write_text(
                '{"action":' + '{"child":' * 2_000 + "null" + "}" * 2_000 + "}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "nested too deeply"):
                list(read_trace(deeply_nested))

            invalid_result = root / "invalid-result.jsonl"
            invalid_result.write_text(
                '{"action": {}, "result": []}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "invalid result"):
                list(read_trace(invalid_result))

    def test_unsafe_trace_writer_rejects_events_its_reader_would_reject(self) -> None:
        metadata: dict[str, object] = {}
        cursor = metadata
        for _ in range(200):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child
        action = Action(ActionKind.WAIT, {"milliseconds": 1}, metadata=metadata)
        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        result = ActionResult(action.id, ResultStatus.DRY_RUN)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            with self.assertRaisesRegex(ValueError, "nested too deeply"):
                TraceRecorder(path, redact=False).record(action, outcome, result)
            self.assertFalse(path.exists())

    def test_redact_value_handles_nested_url_suffixes_and_sensitive_keys(self) -> None:
        secret = "nested-secret"
        redacted = redact_value(
            {
                "outer": [
                    {
                        "callback_url": (
                            "https://user:password@example.com/callback?token="
                            f"{secret}#access_token={secret}"
                        ),
                        "set-cookie": secret,
                    }
                ]
            }
        )

        nested = redacted["outer"][0]
        self.assertEqual(
            nested["callback_url"],
            "https://example.com",
        )
        self.assertEqual(nested["set-cookie"], REDACTED)

    def test_trace_redacts_nested_metadata_and_result_output(self) -> None:
        metadata_secret = "metadata-secret"
        result_secret = "result-secret"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            action = Action(
                ActionKind.CLICK,
                {"selector": "#safe"},
                metadata={
                    "provider": "test",
                    "source": (
                        "https://example.com/source?token="
                        f"{metadata_secret}#access_token={metadata_secret}"
                    ),
                    "nested": {
                        "callback_url": f"https://example.com/?token={metadata_secret}",
                        "authorization": metadata_secret,
                    },
                },
            )
            result = ActionResult(
                action.id,
                ResultStatus.SUCCESS,
                output={
                    "url": (
                        "https://example.com/complete?code="
                        f"{result_secret}#access_token={result_secret}"
                    ),
                    "message": {"api_key": result_secret},
                    "custom": {"token": result_secret},
                },
                error=result_secret,
            )
            TraceRecorder(path).record(
                action,
                PolicyOutcome(Decision.ALLOW, "test", "test"),
                result,
            )

            raw = path.read_text(encoding="utf-8")
            event = next(read_trace(path))

        self.assertNotIn(metadata_secret, raw)
        self.assertNotIn(result_secret, raw)
        self.assertEqual(event["action"]["metadata"], {})
        self.assertEqual(event["result"]["output"]["url"], REDACTED)
        self.assertEqual(event["result"]["output"]["message"], REDACTED)
        self.assertEqual(event["result"]["output"]["custom"], REDACTED)
        self.assertEqual(event["result"]["error"], REDACTED)

    def test_malformed_url_value_is_not_written_raw(self) -> None:
        secret = "bad-port-secret"
        self.assertEqual(
            redact_value({"redirect_url": f"https://example.com:not-a-port/?token={secret}"}),
            {"redirect_url": REDACTED},
        )

    def test_default_trace_does_not_keep_untrusted_provenance_or_error_text(self) -> None:
        secret = "trace-sentinel-must-not-persist"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            action = Action(
                ActionKind.CLICK,
                {"selector": f"button.{secret}"},
                metadata={
                    "provider": "openai",
                    "provider_call_id": secret,
                    "source": f"https://example.com/reset/{secret}",
                },
            )
            TraceRecorder(path, trace_id=secret).record(
                action,
                PolicyOutcome(Decision.DENY, f"blocked {secret}", secret),
                ActionResult(
                    action.id,
                    ResultStatus.ERROR,
                    output={"url": f"https://example.com/reset/{secret}"},
                    error=secret,
                    audit_error=secret,
                ),
            )
            raw = path.read_text(encoding="utf-8")
            event = next(read_trace(path))

        self.assertNotIn(secret, raw)
        self.assertEqual(event["trace_id"], REDACTED)
        self.assertEqual(event["action"]["params"]["selector"], REDACTED)
        self.assertEqual(event["action"]["metadata"], {})
        self.assertEqual(event["policy"]["reason"], REDACTED)
        self.assertEqual(event["policy"]["name"], REDACTED)
        self.assertEqual(event["result"]["output"]["url"], REDACTED)
        self.assertEqual(event["result"]["error"], REDACTED)
        self.assertEqual(event["result"]["audit_error"], REDACTED)

    def test_short_write_is_completed_before_record_returns(self) -> None:
        """A positive short write must not leave a truncated JSONL event."""

        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        result = ActionResult(action.id, ResultStatus.DRY_RUN)
        real_write = os.write
        write_lengths: list[int] = []

        def short_write(descriptor: int, payload: bytes | memoryview) -> int:
            chunk = bytes(payload)[:17]
            write_lengths.append(len(chunk))
            return real_write(descriptor, chunk)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            with patch("actionanything.recorder.os.write", side_effect=short_write):
                TraceRecorder(path).record(action, outcome, result)

            events = list(read_trace(path))

        self.assertGreater(len(write_lengths), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["sequence"], 1)

    def test_zero_progress_write_is_a_recorder_failure(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        result = ActionResult(action.id, ResultStatus.DRY_RUN)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            with patch("actionanything.recorder.os.write", return_value=0):
                with self.assertRaisesRegex(OSError, "could not write complete trace event"):
                    TraceRecorder(path).record(action, outcome, result)

    def test_partial_write_then_failure_rolls_back_before_next_event(self) -> None:
        """A failed later write cannot poison a following valid JSONL event."""

        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        failed = Action(ActionKind.WAIT, {"milliseconds": 2})
        final = Action(ActionKind.WAIT, {"milliseconds": 3})
        real_write = os.write
        calls = 0

        def partial_then_stall(descriptor: int, payload: bytes | memoryview) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_write(descriptor, bytes(payload)[:17])
            return 0

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            recorder = TraceRecorder(path)
            recorder.record(first, outcome, ActionResult(first.id, ResultStatus.DRY_RUN))
            with patch(
                "actionanything.recorder.os.write", side_effect=partial_then_stall
            ):
                with self.assertRaisesRegex(OSError, "could not write complete trace event"):
                    recorder.record(failed, outcome, ActionResult(failed.id, ResultStatus.DRY_RUN))
            recorder.record(final, outcome, ActionResult(final.id, ResultStatus.DRY_RUN))
            events = list(read_trace(path))

        self.assertEqual([event["sequence"] for event in events], [1, 3])

    def test_interrupted_write_preserves_interrupt_when_rollback_fails(self) -> None:
        """A rollback diagnostic must not replace a process-control exception."""

        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        result = ActionResult(action.id, ResultStatus.DRY_RUN)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            with patch(
                "actionanything.recorder._write_all", side_effect=KeyboardInterrupt()
            ), patch(
                "actionanything.recorder.os.ftruncate", side_effect=OSError("rollback failed")
            ) as truncate:
                with self.assertRaises(KeyboardInterrupt) as captured:
                    TraceRecorder(path).record(action, outcome, result)

        self.assertTrue(truncate.called)
        notes = getattr(captured.exception, "__notes__", ())
        legacy_notes = getattr(captured.exception, "_actionanything_recovery_notes", ())
        self.assertTrue(any("could not restore trace" in note for note in (*notes, *legacy_notes)))

    @unittest.skipUnless(os.name == "posix", "fcntl advisory locks require POSIX")
    def test_cooperating_writer_survives_another_writers_rollback(self) -> None:
        """A locked rollback cannot truncate a second cooperating writer."""

        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        first = Action(ActionKind.WAIT, {"milliseconds": 1})
        second = Action(ActionKind.WAIT, {"milliseconds": 2})
        partial_written = threading.Event()
        second_lock_attempted = threading.Event()
        first_identifier: list[int | None] = [None]
        second_identifier: list[int | None] = [None]
        first_error: list[BaseException] = []
        second_error: list[BaseException] = []
        real_write = os.write
        real_flock = fcntl.flock

        def write_first_event_partially(descriptor: int, payload: bytes | memoryview) -> int:
            if threading.get_ident() != first_identifier[0]:
                return real_write(descriptor, payload)
            if not partial_written.is_set():
                written = real_write(descriptor, bytes(payload)[:17])
                partial_written.set()
                if not second_lock_attempted.wait(timeout=5):
                    raise TimeoutError("second writer did not attempt the trace lock")
                return written
            return 0

        def observe_second_lock(descriptor: int, operation: int) -> None:
            if (
                threading.get_ident() == second_identifier[0]
                and operation & fcntl.LOCK_EX
            ):
                second_lock_attempted.set()
            real_flock(descriptor, operation)

        def record_first() -> None:
            first_identifier[0] = threading.get_ident()
            try:
                TraceRecorder(path).record(first, outcome, ActionResult(first.id, ResultStatus.DRY_RUN))
            except BaseException as exc:
                first_error.append(exc)

        def record_second() -> None:
            if not partial_written.wait(timeout=5):
                second_error.append(TimeoutError("first writer did not make partial progress"))
                return
            second_identifier[0] = threading.get_ident()
            try:
                TraceRecorder(path).record(second, outcome, ActionResult(second.id, ResultStatus.DRY_RUN))
            except BaseException as exc:
                second_error.append(exc)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            first_thread = threading.Thread(target=record_first)
            second_thread = threading.Thread(target=record_second)
            with patch(
                "actionanything.recorder.os.write", side_effect=write_first_event_partially
            ), patch("fcntl.flock", side_effect=observe_second_lock):
                first_thread.start()
                second_thread.start()
                first_thread.join(timeout=10)
                second_thread.join(timeout=10)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(len(first_error), 1)
            self.assertIsInstance(first_error[0], OSError)
            self.assertEqual(second_error, [])
            events = list(read_trace(path))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"]["params"]["milliseconds"], 2)

    @unittest.skipIf(os.name == "nt", "symlink permission semantics differ on Windows")
    def test_trace_refuses_symlink_or_group_readable_existing_file(self) -> None:
        action = Action(ActionKind.WAIT, {"milliseconds": 1})
        outcome = PolicyOutcome(Decision.ALLOW, "test", "test")
        result = ActionResult(action.id, ResultStatus.DRY_RUN)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination.jsonl"
            destination.write_text("existing\n", encoding="utf-8")
            linked = root / "trace.jsonl"
            linked.symlink_to(destination)
            with self.assertRaises(OSError):
                TraceRecorder(linked).record(action, outcome, result)

            regular = root / "regular.jsonl"
            regular.write_text("existing\n", encoding="utf-8")
            regular.chmod(0o644)
            with self.assertRaisesRegex(OSError, "owner-readable only"):
                TraceRecorder(regular).record(action, outcome, result)

            outside = root / "outside"
            outside.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "symbolic link"):
                TraceRecorder(linked_parent / "trace.jsonl").record(action, outcome, result)
            self.assertFalse((outside / "trace.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
