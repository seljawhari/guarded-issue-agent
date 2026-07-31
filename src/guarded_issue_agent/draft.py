"""Human-reviewable patch and draft PR rendering."""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from guarded_issue_agent.domain import Plan, ProposedChange


def unified_patch(changes: Iterable[tuple[ProposedChange, str, str]]) -> str:
    sections: list[str] = []
    for change, before, after in changes:
        diff = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
        )
        sections.extend(diff)
    return "".join(sections)


def draft_pr_markdown(plan: Plan, plan_sha256: str) -> str:
    lines = [
        f"# Draft PR: {plan.issue_title}",
        "",
        "> Local draft only. This tool did not create a branch, push code, run commands,",
        "> or contact a source-control provider.",
        "",
        "## Summary",
        "",
        plan.summary,
        "",
        "## Evidence reviewed",
        "",
    ]
    for item in plan.evidence:
        lines.append(
            f"- `{item.evidence_id}` `{item.path}:{item.start_line}-{item.end_line}` "
            f"(file SHA-256 `{item.file_sha256}`)"
        )
    lines.extend(["", "## Changes", ""])
    for change in plan.changes:
        citations = ", ".join(f"`{item}`" for item in change.evidence_ids)
        lines.append(f"- `{change.path}` - {change.rationale} Evidence: {citations}.")

    lines.extend(["", "## Acceptance criteria", ""])
    if plan.acceptance_criteria:
        lines.extend(f"- [ ] {item}" for item in plan.acceptance_criteria)
    else:
        lines.append("- [ ] Confirm expected behavior with the issue owner.")

    lines.extend(["", "## Recommended validation", ""])
    if plan.test_recommendations:
        lines.extend(f"- [ ] `{item}`" for item in plan.test_recommendations)
    else:
        lines.append("- [ ] Select and run an appropriate test suite manually.")

    lines.extend(
        [
            "",
            "## Approval record",
            "",
            f"- Approved plan SHA-256: `{plan_sha256}`",
            f"- Planner: `{plan.generated_by}`",
            "- Tests run automatically: no",
            "- Remote actions performed: none",
            "",
        ]
    )
    return "\n".join(lines)
