"""Model adapter interface and deterministic offline demonstration adapter."""

from __future__ import annotations

from typing import Protocol

from guarded_issue_agent.domain import Issue, Plan, ProposedChange
from guarded_issue_agent.scanner import collect_exact_match_evidence
from guarded_issue_agent.workspace import ReadOnlyWorkspace


class ModelAdapter(Protocol):
    name: str

    def build_plan(self, issue: Issue, workspace: ReadOnlyWorkspace) -> Plan:
        """Return a proposed plan. The trusted controller validates it again."""


class DeterministicMockModel:
    """Converts explicit synthetic fixture hints into a stable plan.

    This adapter deliberately does not call a model, network, shell, git, or PR
    provider. It exists so the safety controller can be tested offline.
    """

    name = "deterministic-mock-v1"

    def build_plan(self, issue: Issue, workspace: ReadOnlyWorkspace) -> Plan:
        evidence = []
        changes = []
        for index, hint in enumerate(issue.mock_changes, start=1):
            evidence_id = f"E{index}"
            citation = collect_exact_match_evidence(
                workspace,
                evidence_id=evidence_id,
                path=hint.path,
                needle=hint.find,
            )
            evidence.append(citation)
            changes.append(
                ProposedChange(
                    path=citation.path,
                    operation="replace_once",
                    find=hint.find,
                    replace=hint.replace,
                    expected_sha256=citation.file_sha256,
                    evidence_ids=(evidence_id,),
                    rationale=hint.rationale,
                )
            )

        noun = "replacement" if len(changes) == 1 else "replacements"
        return Plan(
            issue_id=issue.issue_id,
            issue_title=issue.title,
            acceptance_criteria=issue.acceptance_criteria,
            summary=(
                f"Address {issue.issue_id}: {issue.title} with "
                f"{len(changes)} scoped {noun}."
            ),
            evidence=tuple(evidence),
            changes=tuple(changes),
            test_recommendations=issue.test_recommendations,
            generated_by=self.name,
        )
