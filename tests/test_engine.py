from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from guarded_issue_agent.demo import initialize_demo
from guarded_issue_agent.domain import Plan
from guarded_issue_agent.engine import apply_plan, create_plan
from guarded_issue_agent.errors import (
    ApprovalError,
    InputValidationError,
    PlanIntegrityError,
    PlanningError,
    PolicyViolation,
    StalePlanError,
)
from guarded_issue_agent.model import DeterministicMockModel


class EngineTests(unittest.TestCase):
    def _plan(self, base: Path):
        demo = initialize_demo(base / "demo")
        planned = create_plan(
            workspace_path=demo.workspace,
            issue_path=demo.issue,
            run_directory=base / "run",
        )
        return demo, planned

    def test_plan_is_deterministic_and_contains_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _, planned_one = self._plan(Path(first))
            _, planned_two = self._plan(Path(second))
            self.assertEqual(planned_one.plan_sha256, planned_two.plan_sha256)
            self.assertEqual(planned_one.change_count, 1)
            self.assertEqual(planned_one.evidence_count, 1)
            payload = json.loads(planned_one.plan_path.read_text(encoding="utf-8"))
            evidence = payload["plan"]["evidence"][0]
            self.assertEqual(evidence["path"], "src/greeting.py")
            self.assertEqual(evidence["start_line"], 5)
            self.assertEqual(len(evidence["file_sha256"]), 64)

    def test_model_adapter_receives_no_write_method(self) -> None:
        class InspectingModel:
            saw_write_method = False

            def build_plan(self, issue, workspace):
                self.saw_write_method = hasattr(workspace, "replace_existing")
                return DeterministicMockModel().build_plan(issue, workspace)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            model = InspectingModel()
            create_plan(
                workspace_path=demo.workspace,
                issue_path=demo.issue,
                run_directory=base / "run",
                model=model,
            )
            self.assertFalse(model.saw_write_method)

    def test_controller_rejects_invented_evidence(self) -> None:
        class FalseEvidenceModel:
            def build_plan(self, issue, workspace):
                plan = DeterministicMockModel().build_plan(issue, workspace)
                false_evidence = replace(plan.evidence[0], snippet="invented evidence")
                return replace(plan, evidence=(false_evidence,))

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            with self.assertRaises(PlanIntegrityError):
                create_plan(
                    workspace_path=demo.workspace,
                    issue_path=demo.issue,
                    run_directory=base / "run",
                    model=FalseEvidenceModel(),
                )

    def test_wrong_approval_cannot_change_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo, planned = self._plan(Path(temporary))
            source = demo.workspace / "src" / "greeting.py"
            before = source.read_text(encoding="utf-8")
            with self.assertRaises(ApprovalError):
                apply_plan(
                    workspace_path=demo.workspace,
                    plan_path=planned.plan_path,
                    approved_sha256="0" * 64,
                )
            self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_approved_plan_writes_change_and_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo, planned = self._plan(Path(temporary))
            applied = apply_plan(
                workspace_path=demo.workspace,
                plan_path=planned.plan_path,
                approved_sha256=planned.plan_sha256,
            )
            source = (demo.workspace / "src" / "greeting.py").read_text(encoding="utf-8")
            self.assertIn('return f"Hello, {name}!"', source)
            namespace: dict[str, object] = {}
            exec(compile(source, "greeting.py", "exec"), namespace)
            self.assertEqual(namespace["greeting"]("Ada"), "Hello, Ada!")
            self.assertEqual(applied.changed_paths, ("src/greeting.py",))
            self.assertTrue(applied.approval_path.is_file())
            self.assertTrue(applied.patch_path.is_file())
            self.assertTrue(applied.draft_pr_path.is_file())
            self.assertIn("Tests run automatically: no", applied.draft_pr_path.read_text())
            self.assertIn("+++ b/src/greeting.py", applied.patch_path.read_text())

    def test_stale_plan_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo, planned = self._plan(Path(temporary))
            source = demo.workspace / "src" / "greeting.py"
            source.write_text(source.read_text() + "\n# concurrent edit\n", encoding="utf-8")
            before = source.read_text(encoding="utf-8")
            with self.assertRaises(StalePlanError):
                apply_plan(
                    workspace_path=demo.workspace,
                    plan_path=planned.plan_path,
                    approved_sha256=planned.plan_sha256,
                )
            self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_tampered_plan_fails_integrity_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo, planned = self._plan(Path(temporary))
            payload = json.loads(planned.plan_path.read_text(encoding="utf-8"))
            payload["plan"]["summary"] = "tampered"
            planned.plan_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PlanIntegrityError):
                apply_plan(
                    workspace_path=demo.workspace,
                    plan_path=planned.plan_path,
                    approved_sha256=planned.plan_sha256,
                )

    def test_reapproved_plan_with_false_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo, planned = self._plan(Path(temporary))
            source = demo.workspace / "src" / "greeting.py"
            before = source.read_text(encoding="utf-8")
            payload = json.loads(planned.plan_path.read_text(encoding="utf-8"))
            evidence = payload["plan"]["evidence"][0]
            evidence["start_line"] = 1
            evidence["end_line"] = 1
            evidence["snippet"] = '"""Small synthetic module used by the guarded demo."""'
            payload["plan_sha256"] = Plan.from_dict(payload["plan"]).digest
            planned.plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(PlanIntegrityError):
                apply_plan(
                    workspace_path=demo.workspace,
                    plan_path=planned.plan_path,
                    approved_sha256=payload["plan_sha256"],
                )

            self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_ambiguous_match_stops_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            source = demo.workspace / "src" / "greeting.py"
            original = source.read_text(encoding="utf-8")
            source.write_text(original + original, encoding="utf-8")
            with self.assertRaises(PlanningError):
                create_plan(
                    workspace_path=demo.workspace,
                    issue_path=demo.issue,
                    run_directory=base / "run",
                )

    def test_run_directory_must_be_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            with self.assertRaises(PolicyViolation):
                create_plan(
                    workspace_path=demo.workspace,
                    issue_path=demo.issue,
                    run_directory=demo.workspace / "src" / "run",
                )

    def test_plan_refuses_nonempty_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            demo = initialize_demo(base / "demo")
            run = base / "run"
            run.mkdir()
            (run / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(InputValidationError):
                create_plan(
                    workspace_path=demo.workspace,
                    issue_path=demo.issue,
                    run_directory=run,
                )


if __name__ == "__main__":
    unittest.main()
