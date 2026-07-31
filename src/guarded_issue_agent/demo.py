"""Synthetic, public-safe fixture used by the README and tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from guarded_issue_agent.errors import InputValidationError


@dataclass(frozen=True)
class DemoPaths:
    root: Path
    workspace: Path
    issue: Path


DEMO_FILES = {
    "repo/README.md": """# Greeting service fixture

This intentionally small repository has one failing behavior for the guarded
issue-agent demo. All names, code, and tasks are synthetic.
""",
    "repo/src/greeting.py": '''"""Small synthetic module used by the guarded demo."""


def greeting(name: str) -> str:
    return f"Hello {name}!"
''',
    "repo/tests/test_greeting.py": '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from greeting import greeting


class GreetingTests(unittest.TestCase):
    def test_greeting_uses_expected_punctuation(self) -> None:
        self.assertEqual(greeting("Ada"), "Hello, Ada!")


if __name__ == "__main__":
    unittest.main()
''',
}

DEMO_ISSUE = {
    "id": "DEMO-001",
    "title": "Add the missing comma to the greeting",
    "description": (
        "The greeting currently renders 'Hello Ada!'. It should render "
        "'Hello, Ada!' without changing the public function signature."
    ),
    "acceptance_criteria": [
        "greeting('Ada') returns 'Hello, Ada!'",
        "The existing unit test passes",
        "No files outside src are changed",
    ],
    "mock_plan": {
        "changes": [
            {
                "path": "src/greeting.py",
                "find": '    return f"Hello {name}!"',
                "replace": '    return f"Hello, {name}!"',
                "rationale": "Match the punctuation required by the issue and existing test.",
            }
        ],
        "test_recommendations": ["python -m unittest discover -s tests -v"],
    },
}


def initialize_demo(output: Path) -> DemoPaths:
    requested = output.expanduser()
    if requested.exists() or requested.is_symlink():
        raise InputValidationError(f"demo output must not already exist: {requested}")
    root = requested.resolve(strict=False)
    root.mkdir(parents=True, mode=0o700)
    for relative, content in DEMO_FILES.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    issue = root / "issue.json"
    issue.write_text(json.dumps(DEMO_ISSUE, indent=2) + "\n", encoding="utf-8")
    return DemoPaths(root=root, workspace=root / "repo", issue=issue)
