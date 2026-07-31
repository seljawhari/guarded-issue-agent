from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from guarded_issue_agent.cli import main


class CliTests(unittest.TestCase):
    def test_demo_plan_approval_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo_root = base / "demo"

            standard_output = io.StringIO()
            with redirect_stdout(standard_output):
                self.assertEqual(main(["init-demo", "--output", str(demo_root)]), 0)
            initialized = json.loads(standard_output.getvalue())

            standard_output = io.StringIO()
            with redirect_stdout(standard_output):
                self.assertEqual(
                    main(
                        [
                            "plan",
                            "--workspace",
                            initialized["workspace"],
                            "--issue",
                            initialized["issue"],
                            "--out",
                            str(base / "run"),
                        ]
                    ),
                    0,
                )
            planned = json.loads(standard_output.getvalue())

            error_output = io.StringIO()
            with redirect_stderr(error_output):
                self.assertEqual(
                    main(
                        [
                            "apply",
                            "--workspace",
                            initialized["workspace"],
                            "--plan",
                            planned["plan_path"],
                            "--approve",
                            "f" * 64,
                        ]
                    ),
                    2,
                )
            self.assertIn("approval digest does not match", error_output.getvalue())

            standard_output = io.StringIO()
            with redirect_stdout(standard_output):
                self.assertEqual(
                    main(
                        [
                            "apply",
                            "--workspace",
                            initialized["workspace"],
                            "--plan",
                            planned["plan_path"],
                            "--approve",
                            planned["plan_sha256"],
                        ]
                    ),
                    0,
                )
            applied = json.loads(standard_output.getvalue())
            self.assertEqual(applied["remote_actions"], "none")
            self.assertFalse(applied["tests_run"])


if __name__ == "__main__":
    unittest.main()
