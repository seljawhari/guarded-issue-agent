from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from guarded_issue_agent.demo import initialize_demo
from guarded_issue_agent.errors import PolicyViolation
from guarded_issue_agent.policy import WorkspacePolicy
from guarded_issue_agent.workspace import Workspace


class WorkspacePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = WorkspacePolicy()

    def test_accepts_scoped_source_path(self) -> None:
        self.assertEqual(
            self.policy.validate_relative_path("src/package/module.py"),
            "src/package/module.py",
        )

    def test_rejects_path_traversal(self) -> None:
        for path in ("../secret.py", "src/../../secret.py", "/tmp/secret.py"):
            with self.subTest(path=path), self.assertRaises(PolicyViolation):
                self.policy.validate_relative_path(path)

    def test_rejects_hidden_and_unapproved_paths(self) -> None:
        for path in (".git/config", "src/.env", ".github/workflows/ci.yml", "README.md"):
            with self.subTest(path=path), self.assertRaises(PolicyViolation):
                self.policy.validate_relative_path(path)

    def test_rejects_windows_separator_and_unapproved_extension(self) -> None:
        for path in ("src\\module.py", "src/tool.sh"):
            with self.subTest(path=path), self.assertRaises(PolicyViolation):
                self.policy.validate_relative_path(path)


class WorkspaceTests(unittest.TestCase):
    def test_rejects_symlink_in_planned_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            outside = base / "outside.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            link = demo.workspace / "src" / "linked.py"
            try:
                link.symlink_to(outside)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks are not available on this platform")

            workspace = Workspace(demo.workspace, WorkspacePolicy())
            with self.assertRaises(PolicyViolation):
                workspace.read_text("src/linked.py")

    def test_rejects_run_artifact_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = initialize_demo(Path(temporary) / "demo")
            workspace = Workspace(demo.workspace, WorkspacePolicy())
            with self.assertRaises(PolicyViolation):
                workspace.ensure_external_artifact_path(demo.workspace / "src" / "run")


if __name__ == "__main__":
    unittest.main()
