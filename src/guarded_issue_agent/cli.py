"""Command-line interface with an explicit plan-digest approval gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from guarded_issue_agent.demo import initialize_demo
from guarded_issue_agent.engine import apply_plan, create_plan
from guarded_issue_agent.errors import GuardedAgentError
from guarded_issue_agent.policy import WorkspacePolicy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guarded-issue-agent",
        description=(
            "Create an evidence-backed change plan, require approval of its exact "
            "SHA-256 digest, then write a local patch and draft PR."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    demo = subcommands.add_parser("init-demo", help="create a synthetic demo workspace")
    demo.add_argument("--output", type=Path, required=True)

    plan = subcommands.add_parser("plan", help="build a deterministic evidence-backed plan")
    plan.add_argument("--workspace", type=Path, required=True)
    plan.add_argument("--issue", type=Path, required=True)
    plan.add_argument("--out", type=Path, required=True, help="new or empty run directory")
    plan.add_argument(
        "--allow-root",
        action="append",
        default=None,
        help="workspace root a plan may edit; repeat as needed (default: src, tests, docs)",
    )

    apply = subcommands.add_parser("apply", help="apply an explicitly approved plan")
    apply.add_argument("--workspace", type=Path, required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument(
        "--approve",
        required=True,
        metavar="PLAN_SHA256",
        help="exact digest copied from the reviewed plan output",
    )
    apply.add_argument(
        "--allow-root",
        action="append",
        default=None,
        help="must match the roots used during planning",
    )
    return parser


def _policy(roots: list[str] | None) -> WorkspacePolicy:
    return WorkspacePolicy(allowed_roots=tuple(roots)) if roots else WorkspacePolicy()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init-demo":
            demo = initialize_demo(arguments.output)
            result = {
                "issue": str(demo.issue),
                "next": "Run the plan command; init-demo never approves or applies changes.",
                "workspace": str(demo.workspace),
            }
        elif arguments.command == "plan":
            planned = create_plan(
                workspace_path=arguments.workspace,
                issue_path=arguments.issue,
                run_directory=arguments.out,
                policy=_policy(arguments.allow_root),
            )
            result = {
                "change_count": planned.change_count,
                "evidence_count": planned.evidence_count,
                "next": (
                    "Review plan.json, then run apply with --approve set to this exact "
                    "plan_sha256."
                ),
                "plan_path": str(planned.plan_path),
                "plan_sha256": planned.plan_sha256,
            }
        else:
            applied = apply_plan(
                workspace_path=arguments.workspace,
                plan_path=arguments.plan,
                approved_sha256=arguments.approve,
                policy=_policy(arguments.allow_root),
            )
            result = {
                "approval_path": str(applied.approval_path),
                "changed_paths": list(applied.changed_paths),
                "draft_pr_path": str(applied.draft_pr_path),
                "patch_path": str(applied.patch_path),
                "plan_sha256": applied.plan_sha256,
                "remote_actions": "none",
                "tests_run": False,
            }
    except GuardedAgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: operating system failure: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
