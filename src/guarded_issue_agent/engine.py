"""Trusted controller for planning, approval, and constrained application."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from guarded_issue_agent.domain import Issue, Plan, PlanEnvelope, ProposedChange
from guarded_issue_agent.draft import draft_pr_markdown, unified_patch
from guarded_issue_agent.errors import (
    ApplyError,
    ApprovalError,
    InputValidationError,
    PlanIntegrityError,
    PolicyViolation,
    StalePlanError,
)
from guarded_issue_agent.model import DeterministicMockModel, ModelAdapter
from guarded_issue_agent.policy import WorkspacePolicy
from guarded_issue_agent.scanner import render_snippet
from guarded_issue_agent.utils import write_new_file
from guarded_issue_agent.workspace import ReadOnlyWorkspace, Workspace, rollback_changes


@dataclass(frozen=True)
class PlanResult:
    plan_path: Path
    plan_sha256: str
    change_count: int
    evidence_count: int


@dataclass(frozen=True)
class ApplyResult:
    approval_path: Path
    patch_path: Path
    draft_pr_path: Path
    plan_sha256: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class PreparedChange:
    change: ProposedChange
    before: str
    after: str
    before_sha256: str


def _validate_plan(plan: Plan, policy: WorkspacePolicy) -> None:
    if not 1 <= len(plan.changes) <= policy.max_changes:
        raise PlanIntegrityError(
            f"plan must contain 1 to {policy.max_changes} proposed changes"
        )
    evidence_by_id = {item.evidence_id: item for item in plan.evidence}
    if len(evidence_by_id) != len(plan.evidence):
        raise PlanIntegrityError("evidence identifiers must be unique")
    if not evidence_by_id:
        raise PlanIntegrityError("plan must contain evidence")

    changed_paths: set[str] = set()
    for change in plan.changes:
        normalized = policy.validate_relative_path(change.path)
        policy.validate_change_size(change.find, change.replace)
        if normalized in changed_paths:
            raise PlanIntegrityError(
                f"multiple changes to one path are prohibited: {normalized}"
            )
        changed_paths.add(normalized)
        if not change.evidence_ids:
            raise PlanIntegrityError(f"change has no evidence: {normalized}")
        for evidence_id in change.evidence_ids:
            try:
                evidence = evidence_by_id[evidence_id]
            except KeyError as exc:
                raise PlanIntegrityError(
                    f"change references missing evidence: {evidence_id}"
                ) from exc
            if evidence.path != normalized:
                raise PlanIntegrityError(
                    f"evidence {evidence_id} does not cite change path {normalized}"
                )
            if evidence.file_sha256 != change.expected_sha256:
                raise PlanIntegrityError(
                    f"evidence {evidence_id} does not match the expected file digest"
                )


def _validate_evidence_content(plan: Plan, workspace: Workspace) -> None:
    """Recompute model-supplied citations inside the trusted controller."""

    evidence_by_id = {item.evidence_id: item for item in plan.evidence}
    files = {path: workspace.read_text(path) for path in {item.path for item in plan.evidence}}
    for evidence in plan.evidence:
        source = files[evidence.path]
        if source.sha256 != evidence.file_sha256:
            raise PlanIntegrityError(f"evidence digest is false for {evidence.path}")
        try:
            actual = render_snippet(source.content, evidence.start_line, evidence.end_line)
        except Exception as exc:
            raise PlanIntegrityError(
                f"evidence range is invalid for {evidence.evidence_id}"
            ) from exc
        if actual != evidence.snippet:
            raise PlanIntegrityError(
                f"evidence snippet is false for {evidence.evidence_id}"
            )

    for change in plan.changes:
        source = workspace.read_text(change.path)
        if source.content.count(change.find) != 1:
            raise PlanIntegrityError(
                f"planned source text is not unique in {change.path}"
            )
        offset = source.content.index(change.find)
        match_start = source.content.count("\n", 0, offset) + 1
        match_end = match_start + change.find.count("\n")
        linked = [evidence_by_id[item] for item in change.evidence_ids]
        if not any(
            item.start_line <= match_start and item.end_line >= match_end for item in linked
        ):
            raise PlanIntegrityError(
                f"no cited evidence covers the replacement in {change.path}"
            )


def _prepare_run_directory(workspace: Workspace, run_directory: Path) -> Path:
    run_path = workspace.ensure_external_artifact_path(run_directory)
    if run_path.exists():
        if run_path.is_symlink() or not run_path.is_dir():
            raise InputValidationError(f"run path must be a regular directory: {run_path}")
        if any(run_path.iterdir()):
            raise InputValidationError(f"run directory must be empty: {run_path}")
    else:
        run_path.mkdir(parents=True, mode=0o700)
    return run_path


def create_plan(
    *,
    workspace_path: Path,
    issue_path: Path,
    run_directory: Path,
    policy: WorkspacePolicy | None = None,
    model: ModelAdapter | None = None,
) -> PlanResult:
    active_policy = policy or WorkspacePolicy()
    workspace = Workspace(workspace_path, active_policy)
    run_path = _prepare_run_directory(workspace, run_directory)
    issue = Issue.load(issue_path)
    active_model = model or DeterministicMockModel()
    plan = active_model.build_plan(issue, ReadOnlyWorkspace(workspace))
    _validate_plan(plan, active_policy)
    _validate_evidence_content(plan, workspace)
    envelope = PlanEnvelope.create(plan)
    plan_path = run_path / "plan.json"
    payload = (json.dumps(envelope.as_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_new_file(plan_path, payload)
    return PlanResult(
        plan_path=plan_path,
        plan_sha256=envelope.plan_sha256,
        change_count=len(plan.changes),
        evidence_count=len(plan.evidence),
    )


def _preflight(workspace: Workspace, plan: Plan) -> list[PreparedChange]:
    prepared: list[PreparedChange] = []
    for change in plan.changes:
        current = workspace.read_text(change.path)
        if current.sha256 != change.expected_sha256:
            raise StalePlanError(
                f"workspace changed after planning: {change.path}; create a new plan"
            )
        count = current.content.count(change.find)
        if count != 1:
            raise StalePlanError(
                f"approved match is no longer unique in {change.path}; found {count}"
            )
        updated = current.content.replace(change.find, change.replace, 1)
        prepared.append(
            PreparedChange(
                change=change,
                before=current.content,
                after=updated,
                before_sha256=current.sha256,
            )
        )
    return prepared


def apply_plan(
    *,
    workspace_path: Path,
    plan_path: Path,
    approved_sha256: str,
    policy: WorkspacePolicy | None = None,
) -> ApplyResult:
    active_policy = policy or WorkspacePolicy()
    workspace = Workspace(workspace_path, active_policy)
    resolved_plan = workspace.ensure_external_artifact_path(plan_path)
    if resolved_plan.name != "plan.json":
        raise InputValidationError("plan artifact must be named plan.json")
    envelope = PlanEnvelope.load(resolved_plan)
    if not hmac.compare_digest(approved_sha256.strip().lower(), envelope.plan_sha256):
        raise ApprovalError(
            "approval digest does not match this plan; review plan.json and paste its "
            "plan_sha256 value exactly"
        )
    _validate_plan(envelope.plan, active_policy)

    run_directory = resolved_plan.parent
    approval_path = run_directory / "approval.json"
    patch_path = run_directory / "changes.patch"
    draft_pr_path = run_directory / "draft-pr.md"
    for artifact in (approval_path, patch_path, draft_pr_path):
        if artifact.exists() or artifact.is_symlink():
            raise InputValidationError(f"refusing to overwrite existing artifact: {artifact}")

    prepared = _preflight(workspace, envelope.plan)
    _validate_evidence_content(envelope.plan, workspace)
    applied: list[tuple[str, str, str]] = []
    try:
        for item in prepared:
            applied_sha256 = workspace.replace_existing(
                item.change.path,
                expected_sha256=item.before_sha256,
                content=item.after,
            )
            applied.append((item.change.path, item.before, applied_sha256))
    except (PolicyViolation, StalePlanError, OSError) as exc:
        try:
            rollback_changes(workspace, applied)
        except ApplyError:
            raise
        raise ApplyError(f"approved plan was not applied: {exc}") from exc

    patch = unified_patch(
        (item.change, item.before, item.after) for item in prepared
    )
    if not patch:
        rollback_changes(workspace, applied)
        raise ApplyError("approved plan produced an empty patch")

    approval = {
        "approval_method": "operator-supplied-plan-digest",
        "approved_at": datetime.now(UTC).isoformat(),
        "plan_sha256": envelope.plan_sha256,
        "workspace_name": workspace.root.name,
    }
    created_artifacts: list[Path] = []
    try:
        write_new_file(
            approval_path,
            (json.dumps(approval, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        created_artifacts.append(approval_path)
        write_new_file(patch_path, patch.encode("utf-8"))
        created_artifacts.append(patch_path)
        write_new_file(
            draft_pr_path,
            draft_pr_markdown(envelope.plan, envelope.plan_sha256).encode("utf-8"),
        )
        created_artifacts.append(draft_pr_path)
    except Exception as exc:
        # Artifact failures should not silently leave an unrecorded workspace edit.
        for artifact in created_artifacts:
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
        rollback_changes(workspace, applied)
        raise ApplyError(f"could not record apply artifacts; changes were rolled back: {exc}") from exc

    return ApplyResult(
        approval_path=approval_path,
        patch_path=patch_path,
        draft_pr_path=draft_pr_path,
        plan_sha256=envelope.plan_sha256,
        changed_paths=tuple(item.change.path for item in prepared),
    )
