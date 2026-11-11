"""Contract tests for the local what-council concept handoff."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".github/skills/what-council-exploration"
EXAMPLE = ROOT / "docs/examples/concept-exploration"
SPEC = importlib.util.spec_from_file_location("what_council", SKILL / "what_council.py")
WHAT_COUNCIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WHAT_COUNCIL)


class WhatCouncilTest(unittest.TestCase):
    def setUp(self):
        self.brief = json.loads((EXAMPLE / "project-intake-v2.json").read_text())
        self.exploration = json.loads((EXAMPLE / "exploration.json").read_text())

    @staticmethod
    def codes(report):
        return {finding["code"] for finding in report["findings"]}

    def test_synthetic_example_is_local_exploratory_and_preserves_distinctions(self):
        schema = json.loads((SKILL / "exploration.schema.json").read_text())
        self.assertEqual(self.exploration["format_version"],
                         schema["properties"]["format_version"]["const"])
        self.assertFalse(set(schema["required"]) - set(self.exploration))
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertEqual(report["handoff_status"], "exploratory")
        self.assertTrue(report["prototype_selection_ready"])
        self.assertFalse(report["acceptance_claim"])
        self.assertTrue(report["refinement_handoff_permitted_after_selection"])
        self.assertFalse(report["complete_what_handoff"])
        self.assertEqual(report["direction_ids"], ["chronological-stream", "evidence-workspace"])
        self.assertEqual(report["unassessed_states"]["chronological-stream"], ["empty"])
        self.assertEqual(report["review_evidence_by_kind"]["generator_self_score"][0]["reviewer"],
                         "synthetic-generator")
        self.assertEqual(report["review_evidence_by_kind"]["model_review"][0]["reviewer"], "not-run")
        self.assertEqual(report["review_evidence_by_kind"]["human_evidence"][0]["reviewer"],
                         "not-collected")
        self.assertIn("unsourced_layout_prescription", self.codes(report))
        self.assertIn("color_only_direction", self.codes(report))
        self.assertIn("incomplete_brief", self.codes(report))
        self.assertNotIn("unsupported_design_constraint", self.codes(report))
        self.assertEqual(report["canonical_brief_ref"], "project-intake-v2.json")
        self.assertTrue(report["open_questions"])
        self.assertTrue(report["council"]["members"])
        self.assertTrue(report["council"]["objections"])
        self.assertTrue(report["council"]["rulings"])
        self.assertTrue(report["sources"])
        self.assertEqual(report["assumptions"][0]["confidence"], "low")
        self.assertIn("intake-v2",
                      report["direction_input_versions"]["chronological-stream"]["brief"]["revision"])

    def test_missing_role_and_unresolved_critical_objection_block(self):
        brief = copy.deepcopy(self.brief)
        brief["what_council"]["members"] = [
            member for member in brief["what_council"]["members"]
            if member["role"] != "adversary"
        ]
        brief["what_council"]["rulings"][1]["status"] = "unresolved"
        report = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("missing_council_role", self.codes(report))
        self.assertIn("unresolved_critical_objection", self.codes(report))
        self.assertFalse(report["prototype_selection_ready"])

    def test_claimed_sponsor_approval_needs_an_approval_source(self):
        brief = copy.deepcopy(self.brief)
        decision = next(item for item in brief["decision_authority"]["decisions"]
                        if item["id"] == "project-quality-goal")
        decision["status"] = "approved"
        report = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("unsupported_sponsor_approval", self.codes(report))

    def test_incomplete_handoff_cannot_claim_acceptance(self):
        exploration = copy.deepcopy(self.exploration)
        exploration["acceptance_claim"] = True
        report = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertFalse(report["acceptance_claim"])
        self.assertIn("unsupported_acceptance_claim", self.codes(report))

    def test_sourced_sponsor_decision_allows_selection_handoff_not_acceptance(self):
        brief = copy.deepcopy(self.brief)
        brief["status"] = "complete"
        brief["critical_unknowns"] = []
        brief["unresolved_questions"] = []
        brief["sources"].append({
            "id": "synthetic-sponsor-approval",
            "kind": "sponsor_approval",
            "reference": "synthetic approval record",
            "description": "A fictional, local example approval.",
            "quote": "Fictional sponsor accepts this example target.",
            "date": "2026-11-11",
            "actor": "fictional-example-sponsor",
        })
        decision = next(item for item in brief["decision_authority"]["decisions"]
                        if item["id"] == "project-quality-goal")
        decision.update({
            "status": "approved",
            "approval_source_ref": "synthetic-sponsor-approval",
        })
        brief["quality_goal"]["status"] = "approved"
        report = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(report["handoff_status"], "ready_for_selection")
        self.assertTrue(report["refinement_handoff_permitted_after_selection"])
        self.assertTrue(report["complete_what_handoff"])
        self.assertFalse(report["acceptance_claim"])

    def test_judge_cannot_approve_a_sponsor_decision(self):
        brief = copy.deepcopy(self.brief)
        brief["what_council"]["rulings"][1].update({
            "decision_id": "project-quality-goal",
            "decision_owner": "sponsor",
            "decision_status": "approved",
        })
        report = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("judge_exceeded_authority", self.codes(report))

    def test_delegated_assumption_cannot_be_promoted_to_fact(self):
        brief = copy.deepcopy(self.brief)
        brief["assumptions"][0]["treatment"] = "accepted"
        brief["assumptions"][0]["promoted_to_fact"] = True
        report = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("delegated_assumption_promoted", self.codes(report))

    def test_color_only_direction_is_not_eligible_for_comparison(self):
        exploration = copy.deepcopy(self.exploration)
        exploration["directions"][2]["eligible"] = True
        report = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("color_only_direction", self.codes(report))

    def test_color_only_pairwise_review_is_not_material_distinctness(self):
        exploration = copy.deepcopy(self.exploration)
        exploration["comparison_review"]["pairwise_reviews"][0]["color_only"] = True
        report = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("color_only_comparison", self.codes(report))

    def test_changed_versions_are_visible_and_incompatible_candidates_are_blocked(self):
        exploration = copy.deepcopy(self.exploration)
        revision = exploration["input_revisions"]["fixture"]
        revision.update({
            "revision": "synthetic-fixture-v2",
            "parent_revision": "synthetic-fixture-v1",
            "change": "Added one synthetic empty-state record.",
        })
        for direction in exploration["directions"]:
            direction["inputs"]["fixture"] = copy.deepcopy(revision)
        visible = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(visible["input_revisions"]["fixture"]["revision"], "synthetic-fixture-v2")
        exploration["directions"][1]["inputs"]["fixture"]["revision"] = "synthetic-fixture-v1"
        incompatible = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(incompatible["handoff_status"], "blocked")
        self.assertIn("incompatible_comparison_inputs", self.codes(incompatible))

    def test_directions_keep_shared_tasks(self):
        exploration = copy.deepcopy(self.exploration)
        exploration["directions"][1]["tasks"] = ["different-task-set"]
        report = WHAT_COUNCIL.validate(self.brief, exploration)
        self.assertEqual(report["handoff_status"], "blocked")
        self.assertIn("incompatible_comparison_tasks", self.codes(report))

    def test_selected_candidate_routes_to_existing_format_2_refinement(self):
        route = WHAT_COUNCIL.refinement_route(self.exploration, "evidence-workspace", self.brief)
        self.assertEqual(route["skill"], "ui-prototype-council")
        self.assertEqual(route["format_version"], 2)
        self.assertEqual(route["canonical_brief_ref"], "project-intake-v2.json")
        with self.assertRaises(WHAT_COUNCIL.HandoffError):
            WHAT_COUNCIL.refinement_route(self.exploration, "color-only-variant", self.brief)

    def test_same_model_council_requires_disclosure_and_reports_limitation(self):
        brief = copy.deepcopy(self.brief)
        for member in brief["what_council"]["members"]:
            member["model_id"] = "same-model-v1"
        blocked = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertEqual(blocked["handoff_status"], "blocked")
        self.assertIn("same_model_limitation_missing", self.codes(blocked))
        brief["what_council"]["same_model_limitation_disclosed"] = True
        disclosed = WHAT_COUNCIL.validate(brief, self.exploration)
        self.assertTrue(disclosed["same_model_roles"])
        self.assertIn("same_model_roles", self.codes(disclosed))

    def test_local_cli_runs_without_services_or_confidential_fixture(self):
        result = subprocess.run(
            [sys.executable, str(SKILL / "what_council.py"), "validate",
             "--brief", str(EXAMPLE / "project-intake-v2.json"),
             "--exploration", str(EXAMPLE / "exploration.json")],
            capture_output=True, text=True, timeout=10, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"handoff_status": "exploratory"', result.stdout)
        self.assertIn('"acceptance_claim": false', result.stdout)

    def test_external_preflight_denies_unapproved_provider_and_data_actions(self):
        for action, data_class in (
            ("provider-call", "private"),
            ("data-sharing", "confidential"),
        ):
            with self.subTest(action=action):
                result = subprocess.run(
                    [sys.executable, str(SKILL / "what_council.py"), "preflight",
                     "--action", action, "--data-class", data_class],
                    capture_output=True, text=True, timeout=10, cwd=ROOT,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('"status": "denied"', result.stdout)
                self.assertIn('"action_executed": false', result.stdout)

    def test_approval_reference_preflight_never_executes_the_action(self):
        result = WHAT_COUNCIL.preflight("provider-call", "synthetic-approval-record", "synthetic")
        self.assertEqual(result["status"], "preflight-passed")
        self.assertFalse(result["action_executed"])

    def test_scoped_intake_cannot_be_omitted_and_legacy_cannot_route(self):
        del self.brief["intake"]
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertIn("scope_unconfirmed", self.codes(report))
        self.exploration["format_version"] = 1
        legacy = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertFalse(legacy["prototype_selection_ready"])
        with self.assertRaises(WHAT_COUNCIL.HandoffError):
            WHAT_COUNCIL.refinement_route(self.exploration, "evidence-workspace", self.brief)

    def test_scope_and_primary_job_questions_cannot_be_parked(self):
        self.brief["unresolved_questions"] = [
            {"id": "job", "topic": "primary_job", "blocks": "nothing"}]
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertIn("scope_question_parked", self.codes(report))

    def test_missing_keep_and_uncovered_views_have_explicit_gate_messages(self):
        del self.brief["intake"]["keep"]
        self.exploration["directions"][0]["view_coverage"][0]["status"] = "placeholder"
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertIn("keep_list_missing", self.codes(report))
        self.assertIn("scope_coverage", self.codes(report))
        self.assertEqual(report["direction_coverage"]["chronological-stream"]["covered"], 0)
        self.assertIn("Scope: page", report["scope_header"])

    def test_keep_dispositions_cannot_drop_preserved_behavior(self):
        self.exploration["directions"][0]["keep_dispositions"][0]["disposition"] = "drop"
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertIn("invalid_keep_disposition", self.codes(report))

    def test_component_intake_remains_lightweight_and_artifacts_are_not_opened(self):
        intake = self.brief["intake"]
        intake["scope"]["level"] = "component"
        intake["views"] = []
        intake["quality_targets"] = {"component": "Preserve the labelled action."}
        intake["artifacts"] = [{"path": "/not/read/secret.bpmn", "data_class": "confidential"}]
        for direction in self.exploration["directions"]:
            direction["view_coverage"] = []
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertEqual(report["handoff_status"], "exploratory")
        self.assertIn("Scope: component", report["scope_header"])

    def test_product_shell_stubs_are_reachable_but_never_content_coverage(self):
        intake = self.brief["intake"]
        intake["scope"].update({"level": "product", "stage": "shell"})
        intake["views"].append({"id": "settings", "disposition": "in", "capture_refs": ["synthetic-job-record"]})
        intake["journeys"] = [{"id": name, "view_ids": ["evidence", "settings"]} for name in ("inspect", "configure")]
        intake["no_artifacts_reason"] = "Synthetic example has no domain diagrams."
        intake["quality_targets"]["product"] = "Both journeys remain reachable."
        for direction in self.exploration["directions"]:
            if direction["eligible"]:
                direction["view_coverage"].append({"view_id": "settings", "status": "labelled_stub", "evidence_refs": ["synthetic-job-record"]})
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertEqual(report["coverage"]["covered"], 1)
        self.assertEqual(report["coverage"]["reachable"], 2)
        self.assertEqual(report["handoff_status"], "exploratory")

    def test_version_bump_does_not_hide_stale_brief_and_reconfirmation_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.json"
            path.write_text(json.dumps(self.brief))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.brief["brief_version"] = "2.1"
            self.exploration["brief_version"] = "2.1"
            self.brief["intake"]["prior_briefs"] = [{
                "id": "prior", "path": str(path), "sha256": digest,
                "round": 1, "purpose": "page exploration", "date": "2026-11-10",
                "confirmation_ref": "old-scope"}]
            report = WHAT_COUNCIL.validate(self.brief, self.exploration)
            self.assertIn("brief_stale", self.codes(report))
            self.brief["intake"]["scope"]["sponsor_confirmation"]["reconfirms"] = [digest]
            self.assertNotIn("brief_stale", self.codes(WHAT_COUNCIL.validate(self.brief, self.exploration)))

    def test_agent_scope_narrowing_and_enum_bypass_are_blocked(self):
        self.brief["what_council"]["objections"][0]["topic"] = "scope"
        ruling = self.brief["what_council"]["rulings"][0]
        ruling.update({"status": "deferred_noncritical", "decision_owner": "agent"})
        self.brief["decision_authority"]["decisions"][1]["owner"] = "Sponsor"
        report = WHAT_COUNCIL.validate(self.brief, self.exploration)
        self.assertIn("judge_exceeded_authority", self.codes(report))
        self.assertIn("invalid_authority_enum", self.codes(report))

    def test_preflight_has_no_synthetic_or_unknown_class_fallback(self):
        for data_class in (None, "whatever"):
            result = WHAT_COUNCIL.preflight("data-sharing", "declared-approval", data_class)
            self.assertEqual(result["status"], "denied")


if __name__ == "__main__":
    unittest.main()
