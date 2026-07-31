"""Validated domain objects and the stable on-disk plan format."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guarded_issue_agent.errors import PlanIntegrityError
from guarded_issue_agent.utils import (
    canonical_json_bytes,
    expect_keys,
    load_json_file,
    require_object,
    require_string,
    require_string_list,
    sha256_bytes,
)

PLAN_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MockChangeHint:
    path: str
    find: str
    replace: str
    rationale: str

    @classmethod
    def from_dict(cls, value: Any, *, label: str) -> "MockChangeHint":
        data = require_object(value, label)
        expect_keys(
            data,
            required={"path", "find", "replace", "rationale"},
            label=label,
        )
        return cls(
            path=require_string(data["path"], f"{label}.path", max_length=300),
            find=require_string(data["find"], f"{label}.find", max_length=8_000),
            replace=require_string(
                data["replace"],
                f"{label}.replace",
                min_length=0,
                max_length=32_000,
            ),
            rationale=require_string(
                data["rationale"], f"{label}.rationale", max_length=1_000
            ),
        )


@dataclass(frozen=True)
class Issue:
    issue_id: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    mock_changes: tuple[MockChangeHint, ...]
    test_recommendations: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> "Issue":
        data = load_json_file(path, label="issue file")
        expect_keys(
            data,
            required={"id", "title", "description", "acceptance_criteria", "mock_plan"},
            label="issue",
        )
        mock_plan = require_object(data["mock_plan"], "issue.mock_plan")
        expect_keys(
            mock_plan,
            required={"changes", "test_recommendations"},
            label="issue.mock_plan",
        )
        raw_changes = mock_plan["changes"]
        if not isinstance(raw_changes, list) or not 1 <= len(raw_changes) <= 8:
            raise PlanIntegrityError("issue.mock_plan.changes must contain 1 to 8 changes")
        return cls(
            issue_id=require_string(data["id"], "issue.id", max_length=100),
            title=require_string(data["title"], "issue.title", max_length=200),
            description=require_string(
                data["description"], "issue.description", max_length=8_000
            ),
            acceptance_criteria=require_string_list(
                data["acceptance_criteria"],
                "issue.acceptance_criteria",
                max_items=20,
                item_max_length=500,
            ),
            mock_changes=tuple(
                MockChangeHint.from_dict(item, label=f"issue.mock_plan.changes[{index}]")
                for index, item in enumerate(raw_changes)
            ),
            test_recommendations=require_string_list(
                mock_plan["test_recommendations"],
                "issue.mock_plan.test_recommendations",
                max_items=10,
                item_max_length=500,
            ),
        )


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    file_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.evidence_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "snippet": self.snippet,
            "file_sha256": self.file_sha256,
        }

    @classmethod
    def from_dict(cls, value: Any, *, label: str) -> "Evidence":
        data = require_object(value, label)
        expect_keys(
            data,
            required={"id", "path", "start_line", "end_line", "snippet", "file_sha256"},
            label=label,
        )
        start_line = data["start_line"]
        end_line = data["end_line"]
        if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
            raise PlanIntegrityError(f"{label}.start_line must be a positive integer")
        if not isinstance(end_line, int) or isinstance(end_line, bool) or end_line < start_line:
            raise PlanIntegrityError(f"{label}.end_line must not precede start_line")
        digest = require_string(data["file_sha256"], f"{label}.file_sha256", max_length=64)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise PlanIntegrityError(f"{label}.file_sha256 must be lowercase SHA-256 hex")
        return cls(
            evidence_id=require_string(data["id"], f"{label}.id", max_length=50),
            path=require_string(data["path"], f"{label}.path", max_length=300),
            start_line=start_line,
            end_line=end_line,
            snippet=require_string(
                data["snippet"], f"{label}.snippet", min_length=0, max_length=2_000
            ),
            file_sha256=digest,
        )


@dataclass(frozen=True)
class ProposedChange:
    path: str
    operation: str
    find: str
    replace: str
    expected_sha256: str
    evidence_ids: tuple[str, ...]
    rationale: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "operation": self.operation,
            "find": self.find,
            "replace": self.replace,
            "expected_sha256": self.expected_sha256,
            "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, value: Any, *, label: str) -> "ProposedChange":
        data = require_object(value, label)
        expect_keys(
            data,
            required={
                "path",
                "operation",
                "find",
                "replace",
                "expected_sha256",
                "evidence_ids",
                "rationale",
            },
            label=label,
        )
        operation = require_string(data["operation"], f"{label}.operation", max_length=50)
        if operation != "replace_once":
            raise PlanIntegrityError(f"{label}.operation must be replace_once")
        digest = require_string(data["expected_sha256"], f"{label}.expected_sha256", max_length=64)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise PlanIntegrityError(f"{label}.expected_sha256 must be lowercase SHA-256 hex")
        return cls(
            path=require_string(data["path"], f"{label}.path", max_length=300),
            operation=operation,
            find=require_string(data["find"], f"{label}.find", max_length=8_000),
            replace=require_string(
                data["replace"],
                f"{label}.replace",
                min_length=0,
                max_length=32_000,
            ),
            expected_sha256=digest,
            evidence_ids=require_string_list(
                data["evidence_ids"],
                f"{label}.evidence_ids",
                max_items=20,
                item_max_length=50,
            ),
            rationale=require_string(
                data["rationale"], f"{label}.rationale", max_length=1_000
            ),
        )


@dataclass(frozen=True)
class Plan:
    issue_id: str
    issue_title: str
    acceptance_criteria: tuple[str, ...]
    summary: str
    evidence: tuple[Evidence, ...]
    changes: tuple[ProposedChange, ...]
    test_recommendations: tuple[str, ...]
    generated_by: str
    schema_version: int = PLAN_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "issue": {
                "id": self.issue_id,
                "title": self.issue_title,
                "acceptance_criteria": list(self.acceptance_criteria),
            },
            "summary": self.summary,
            "evidence": [item.as_dict() for item in self.evidence],
            "changes": [item.as_dict() for item in self.changes],
            "test_recommendations": list(self.test_recommendations),
            "generated_by": self.generated_by,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.as_dict()))

    @classmethod
    def from_dict(cls, value: Any) -> "Plan":
        data = require_object(value, "plan")
        expect_keys(
            data,
            required={
                "schema_version",
                "issue",
                "summary",
                "evidence",
                "changes",
                "test_recommendations",
                "generated_by",
            },
            label="plan",
        )
        if data["schema_version"] != PLAN_SCHEMA_VERSION:
            raise PlanIntegrityError(
                f"unsupported plan schema version: {data['schema_version']!r}"
            )
        issue = require_object(data["issue"], "plan.issue")
        expect_keys(
            issue,
            required={"id", "title", "acceptance_criteria"},
            label="plan.issue",
        )
        raw_evidence = data["evidence"]
        raw_changes = data["changes"]
        if not isinstance(raw_evidence, list):
            raise PlanIntegrityError("plan.evidence must be a list")
        if not isinstance(raw_changes, list):
            raise PlanIntegrityError("plan.changes must be a list")
        return cls(
            issue_id=require_string(issue["id"], "plan.issue.id", max_length=100),
            issue_title=require_string(
                issue["title"], "plan.issue.title", max_length=200
            ),
            acceptance_criteria=require_string_list(
                issue["acceptance_criteria"],
                "plan.issue.acceptance_criteria",
                max_items=20,
                item_max_length=500,
            ),
            summary=require_string(data["summary"], "plan.summary", max_length=2_000),
            evidence=tuple(
                Evidence.from_dict(item, label=f"plan.evidence[{index}]")
                for index, item in enumerate(raw_evidence)
            ),
            changes=tuple(
                ProposedChange.from_dict(item, label=f"plan.changes[{index}]")
                for index, item in enumerate(raw_changes)
            ),
            test_recommendations=require_string_list(
                data["test_recommendations"],
                "plan.test_recommendations",
                max_items=10,
                item_max_length=500,
            ),
            generated_by=require_string(
                data["generated_by"], "plan.generated_by", max_length=100
            ),
        )


@dataclass(frozen=True)
class PlanEnvelope:
    plan: Plan
    plan_sha256: str

    @classmethod
    def create(cls, plan: Plan) -> "PlanEnvelope":
        return cls(plan=plan, plan_sha256=plan.digest)

    def as_dict(self) -> dict[str, object]:
        return {"plan": self.plan.as_dict(), "plan_sha256": self.plan_sha256}

    @classmethod
    def load(cls, path: Path) -> "PlanEnvelope":
        data = load_json_file(path, label="plan file")
        expect_keys(data, required={"plan", "plan_sha256"}, label="plan envelope")
        plan = Plan.from_dict(data["plan"])
        recorded = require_string(
            data["plan_sha256"], "plan envelope.plan_sha256", max_length=64
        )
        if not hmac.compare_digest(recorded, plan.digest):
            raise PlanIntegrityError("plan contents do not match the recorded SHA-256 digest")
        return cls(plan=plan, plan_sha256=recorded)
