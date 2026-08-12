import tempfile
import unittest
import os
from pathlib import Path

from actionanything import Action, ActionKind, ActionResult, Decision, ResultStatus, TraceRecorder, read_trace
from actionanything.policy import PolicyOutcome
from actionanything.recorder import REDACTED, redact_value


class TraceRedactionTests(unittest.TestCase):
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
