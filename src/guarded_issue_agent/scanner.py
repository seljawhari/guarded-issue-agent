"""Evidence collection from exact, policy-approved repository locations."""

from __future__ import annotations

from guarded_issue_agent.domain import Evidence
from guarded_issue_agent.errors import PlanningError
from guarded_issue_agent.workspace import ReadOnlyWorkspace

MAX_SNIPPET_CHARACTERS = 1_500


def render_snippet(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines()
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise PlanningError("evidence line range is outside the cited file")
    snippet = "\n".join(lines[start_line - 1 : end_line])
    if len(snippet) > MAX_SNIPPET_CHARACTERS:
        snippet = snippet[: MAX_SNIPPET_CHARACTERS - 3] + "..."
    return snippet


def collect_exact_match_evidence(
    workspace: ReadOnlyWorkspace,
    *,
    evidence_id: str,
    path: str,
    needle: str,
) -> Evidence:
    source = workspace.read_text(path)
    occurrence_count = source.content.count(needle)
    if occurrence_count != 1:
        raise PlanningError(
            f"expected exactly one match in {source.path}, found {occurrence_count}"
        )
    offset = source.content.index(needle)
    start_line = source.content.count("\n", 0, offset) + 1
    end_line = start_line + needle.count("\n")
    snippet = render_snippet(source.content, start_line, end_line)
    return Evidence(
        evidence_id=evidence_id,
        path=source.path,
        start_line=start_line,
        end_line=end_line,
        snippet=snippet,
        file_sha256=source.sha256,
    )
