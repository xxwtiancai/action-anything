import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from actionanything.cli import main


class CliTests(unittest.TestCase):
    def test_run_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            trace = root / "trace.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "actions": [
                            {
                                "kind": "navigate",
                                "params": {"url": "https://example.com"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "run",
                        str(plan),
                        "--trace",
                        str(trace),
                        "--allowed-domain",
                        "example.com",
                    ]
                )
                inspect_code = main(["inspect", str(trace)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(inspect_code, 0)
            self.assertIn("dry_run", output.getvalue())
            self.assertIn("navigate", output.getvalue())


if __name__ == "__main__":
    unittest.main()

