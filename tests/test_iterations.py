"""Contract tests for the machine-checked, evidence-bound refinement ledger."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "iterations", ROOT / ".github/skills/ui-prototype-council/iterations.py")
ITERATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ITERATIONS)


class IterationLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = {}

    def tearDown(self):
        self.temporary.cleanup()

    def test_documented_example_is_valid_and_keeps_self_scores_separate(self):
        path = ROOT / "docs/examples/refinement/iterations.json"
        result = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["goal"]["denominator"], 5)
        self.assertEqual(result["goal"]["claim_scope"], "all_declared_points")
        self.assertEqual(result["goal"]["selected_point_count"], 5)
        self.assertEqual(result["goal"]["achieved_selected_points"], 2)
        self.assertEqual(result["goal"]["required_selected_points"], 4)
        self.assertEqual(result["goal"]["excluded_points"], [])
        self.assertEqual(result["goal"]["unassessed_selected_points"], ["accessibility"])
        self.assertEqual(result["reviewer"]["kind"], "generator_self_assessment")
        self.assertEqual(result["progress_by_reviewer_kind"]["independent_qualified_review"], 0)
        self.assertEqual(result["stop"]["reason"], "iteration_cap")
        self.assertEqual(result["feasibility"]["status"], "unknown")

    def artifact(self, name, value, *, json_file=True):
        path = self.root / name
        data = (json.dumps(value, sort_keys=True) + "\n").encode() if json_file else value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.artifacts[name] = {
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return name

    def source(self, name, build):
        file_ref = self.artifact(f"{name}.html", f"owned source {build}\n".encode(),
                                 json_file=False)
        return self.artifact(name, {
            "scope_id": "scope-1", "build_id": build,
            "files": {"synthetic-source": {
                "path": self.artifacts[file_ref]["path"],
                "sha256": self.artifacts[file_ref]["sha256"],
            }},
        })

    def scores(self, name, source_ref, build_id, values, reviewer=None):
        reviewer = reviewer or {"kind": "generator_self_assessment", "id": "fixture-generator"}
        points = {}
        for point, value in values.items():
            points[point] = {
                "score": value,
                "evidence_status": "observed" if value is not None else "not_assessed",
                "evidence": ["evidence.txt"] if value is not None else [],
            }
            if value is not None:
                points[point].update({
                    "reason": "Illustrative fixture score, not a measured design result.",
                    "assessed_source_ref": source_ref,
                })
                if value >= 9:
                    points[point]["anchor"] = "Illustrative rubric anchor for score 9."
        return self.artifact(name, {
            "scope_id": "scope-1", "build_id": build_id,
            "reviewer": reviewer, "points": points,
        })

    def checks(self, name, build_id, findings=None, task_clicks=1, observations=None):
        return self.artifact(name, {
            "status": "pass", "full_coverage": True,
            "commands": [{"command": "python3 verify-fixture.py", "status": "pass",
                          "exit_code": 0}],
            "scenarios": ["dense-dark-desktop", "held-out-error-state"],
            "scenario_evidence": [
                {"id": "dense-dark-desktop", "status": "pass",
                 "evidence_type": "rendered_check", "build_id": build_id},
                {"id": "held-out-error-state", "status": "pass",
                 "evidence_type": "rendered_check", "build_id": build_id},
            ],
            "findings": findings or [],
            "tasks": {"open-evidence": {
                "status": "pass", "clicks": task_clicks, "budget": 3,
            }},
            "observations": observations or [],
        })

    def create_ledger(self):
        evidence = self.artifact("evidence.txt", b"Owned synthetic fixture evidence.\n",
                                 json_file=False)
        baseline_source = self.source("baseline/source.json", "baseline-build")
        after_source = self.source("attempt-1/source.json", "redesign-build")
        before_values = {"p1": 8, "p2": 7, "p3": None, "p4": 8, "p5": None}
        after_values = {"p1": 9, "p2": 8, "p3": None, "p4": 8, "p5": None}
        before_scores = self.scores("baseline/scores.json", baseline_source,
                                    "baseline-build", before_values)
        after_scores = self.scores("attempt-1/scores.json", after_source,
                                   "redesign-build", after_values)
        before_checks = self.checks("baseline/checks.json", "baseline-build", observations=[
            {"profile": "desktop-dark", "finding_id": "known-label", "outcome": "fail",
             "evidence_kind": "automated_check"},
            {"profile": "desktop-zoom-200", "finding_id": "known-label", "outcome": "fail",
             "evidence_kind": "automated_check"},
        ])
        after_checks = self.checks("attempt-1/checks.json", "redesign-build", observations=[
            {"profile": "desktop-dark", "finding_id": "known-label", "outcome": "fail",
             "evidence_kind": "automated_check"},
            {"profile": "desktop-zoom-200", "finding_id": "known-label", "outcome": "fail",
             "evidence_kind": "automated_check"},
        ])
        proposal = self.artifact("attempt-1/proposal.json", {
            "recorded_before_edit": True,
            "hypothesis": "A coherent navigation and content redesign will improve p1 and p2.",
            "dimensions": ["p1", "p2"],
            "expected_gain": {"p1": 1, "p2": 1},
        })
        decision_reason = "Illustrative measured fixture change; keep is provisional."
        decision = self.artifact("attempt-1/decision.json", {
            "attempt_id": 1,
            "decision": "keep",
            "reason": decision_reason,
            "before_artifacts": {
                "source_ref": self.artifacts[baseline_source]["sha256"],
                "scores_ref": self.artifacts[before_scores]["sha256"],
                "checks_ref": self.artifacts[before_checks]["sha256"],
            },
            "after_artifacts": {
                "source_ref": self.artifacts[after_source]["sha256"],
                "scores_ref": self.artifacts[after_scores]["sha256"],
                "checks_ref": self.artifacts[after_checks]["sha256"],
            },
        })
        ledger = {
            "format_version": 1,
            "contract": {
                "scope_id": "scope-1",
                "points": [{"id": f"p{i}", "selected": i != 4} for i in range(1, 6)],
                "goal": {"score": 9, "fraction": 0.8},
                "feasibility": {
                    "status": "unknown",
                    "assumptions": ["No bounded gain model is declared."],
                },
                "required_scenarios": [
                    {"id": "dense-dark-desktop", "theme": "dark", "viewport": "desktop-1280-css",
                     "state": "dense", "evidence_type": "rendered_check"},
                    {"id": "held-out-error-state", "theme": "light",
                     "viewport": "desktop-1280-css", "state": "error-long-text",
                     "evidence_type": "rendered_check"},
                ],
                "task_budgets": {"open-evidence": 3},
                "attempt_limit": 1,
                "no_gain_limit": 2,
                "elapsed_minutes": None,
                "review_effort_minutes": None,
                "verification_elapsed_seconds": None,
            },
            "artifacts": self.artifacts,
            "baseline": {
                "source_ref": baseline_source, "scores_ref": before_scores,
                "build_id": "baseline-build",
                "checks_ref": before_checks, "scope_id": "scope-1",
            },
            "iterations": [{
                "id": 1,
                "proposal_ref": proposal,
                "decision_ref": decision,
                "hypothesis": "A coherent navigation and content redesign will improve p1 and p2.",
                "dimensions": ["p1", "p2"],
                "expected_gain": {"p1": 1, "p2": 1},
                "before": {
                    "source_ref": baseline_source, "scores_ref": before_scores,
                    "checks_ref": before_checks,
                },
                "after": {
                    "source_ref": after_source, "scores_ref": after_scores,
                    "checks_ref": after_checks,
                },
                "reviewer_kind": "generator_self_assessment",
                "decision": "keep", "provisional": True,
                "reason": decision_reason,
                "retained_source_ref": after_source,
            }],
            "stop": {
                "reason": "iteration_cap", "reason_text": "The declared one-attempt cap was reached.",
                "retained_source_ref": after_source,
            },
        }
        path = self.root / "iterations.json"
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        return path, ledger

    def rewrite_json_artifact(self, ledger, reference, update):
        item = ledger["artifacts"][reference]
        artifact_path = self.root / item["path"]
        value = json.loads(artifact_path.read_text(encoding="utf-8"))
        update(value)
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        artifact_path.write_bytes(encoded)
        item["sha256"] = hashlib.sha256(encoded).hexdigest()

    def create_v2_ledger(self):
        path, ledger = self.create_ledger()
        ledger["format_version"] = 2
        contract = ledger["contract"]
        contract["goal"] = {"score": 7, "fraction": 0.5}
        contract["points"] = [
            {"id": "p1", "selected": True,
             "scopes": ["component-a", "region-header", "page-overview"]},
            {"id": "p2", "selected": True,
             "scopes": ["component-b", "region-header", "page-overview", "journey-onboard"]},
            {"id": "p3", "selected": True,
             "scopes": ["page-overview", "journey-onboard"]},
            {"id": "p4", "selected": True,
             "scopes": ["page-settings"]},
            {"id": "p5", "selected": True,
             "scopes": ["component-c", "page-settings"]},
        ]
        contract["scopes"] = [
            {"id": "component-a", "kind": "component", "name": "Search summary"},
            {"id": "component-b", "kind": "component", "name": "Result card"},
            {"id": "component-c", "kind": "component", "name": "Filter control"},
            {"id": "region-header", "kind": "region", "name": "Overview header"},
            {"id": "page-overview", "kind": "page", "name": "Overview"},
            {"id": "page-settings", "kind": "page", "name": "Settings"},
            {"id": "journey-onboard", "kind": "journey", "name": "Find and save",
             "task_ids": ["open-evidence"]},
        ]
        brief = {
            "brief_version": "1.0",
            "status": "incomplete",
            "users_and_jobs": ["Synthetic analyst finding a record."],
            "problem": "Synthetic fixture problem.",
            "desired_outcomes": ["Find a record without losing its source."],
            "platforms": ["desktop browser"],
            "scenarios": ["dense overview", "long-text error"],
            "constraints": ["local-only evidence"],
            "quality_goal": {
                "score": 7, "fraction": 0.5, "status": "proposed",
                "decision_id": "goal",
            },
            "available_evidence": ["synthetic render checks"],
            "budget": {"limit_minutes": 20},
            "stop_conditions": ["one no-gain round"],
            "non_goals": ["No human usability claim."],
            "unresolved_questions": ["Sponsor has not approved the goal."],
            "critical_unknowns": ["Sponsor approval of the project goal."],
            "decision_authority": {
                "sponsor_decisions": ["goal"],
                "agent_delegated_decisions": ["layout"],
                "decisions": [
                    {"id": "goal", "owner": "sponsor", "status": "proposed",
                     "decision": "7/10 for half the declared points"},
                    {"id": "layout", "owner": "agent", "status": "proposed",
                     "decision": "May propose an alternate page layout"},
                ],
            },
        }
        brief_ref = self.artifact("intake/brief.json", brief)
        decision_ref = self.artifact("contract/decisions-v1.json", {
            "decision": "Synthetic initial measurement contract.",
        })
        contract.update({
            "brief_ref": brief_ref,
            "version_history": [{
                "id": "v1", "parent": None,
                "goal": {"score": 7, "fraction": 0.5},
                "point_ids": ["p1", "p2", "p3", "p4", "p5"],
                "selected_point_ids": ["p1", "p2", "p3", "p4", "p5"],
                "scope_ids": [scope["id"] for scope in contract["scopes"]],
                "point_scopes": {
                    point["id"]: point["scopes"] for point in contract["points"]
                },
                "rubric_revision": "rubric-v1",
                "inventory_revision": "inventory-v1",
                "scope_revision": "scope-v1",
                "material_decisions_ref": decision_ref,
            }],
            "version_mappings": [],
        })
        for snapshot in (ledger["baseline"], ledger["iterations"][0]["before"],
                         ledger["iterations"][0]["after"]):
            snapshot["version_id"] = "v1"
        attempt = ledger["iterations"][0]
        attempt.update({
            "version_id": "v1",
            "expected_outcomes": ["Improve the two named component points."],
            "actual_outcomes": ["Both named scores rose by one illustrative point."],
            "actual_evidence": ["evidence.txt"],
            "affected_points": ["p1", "p2"],
            "dependencies": ["Use the frozen synthetic fixture."],
            "guardrails": ["Keep task and state checks passing."],
            "regressions": [],
            "effort_minutes": 4,
            "decision_actor": "agent",
            "decision_records": [{
                "id": "layout", "actor": "agent", "status": "proposed",
                "decision": "Try a coherent alternate page layout.",
            }],
        })
        self.rewrite_json_artifact(ledger, attempt["proposal_ref"], lambda data: data.update({
            "expected_outcomes": attempt["expected_outcomes"],
            "affected_points": attempt["affected_points"],
            "dependencies": attempt["dependencies"],
            "guardrails": attempt["guardrails"],
        }))
        contract["points"][-1]["selected"] = True
        self.rewrite_json_artifact(ledger, "baseline/scores.json", lambda data: (
            data["points"]["p5"].update({
                "score": 8, "evidence_status": "observed",
                "reason": "Synthetic baseline score.",
                "assessed_source_ref": "baseline/source.json",
                "evidence": ["evidence.txt"],
            })
        ))

        def annotate_scores(data, source_ref, *, after=False):
            for point_id, score in data["points"].items():
                if score["score"] is None:
                    score["assessment_state"] = "unassessed"
                    continue
                score["assessment_state"] = "fresh"
                score["review_required"] = False
                score["assessed_source_ref"] = source_ref
                score["evidence_coverage"] = {
                    ref: {
                        "point_ids": (
                            ["p1", "p2"] if point_id in {"p1", "p2"}
                            else [point_id]
                        ),
                        "scenario_ids": ["dense-dark-desktop"],
                        "declaration": "Synthetic evidence covers this declared point.",
                    }
                    for ref in score["evidence"]
                }
                if after and point_id == "p4":
                    score["assessment_state"] = "stale"
                    score["review_required"] = True
                    score["assessed_source_ref"] = "baseline/source.json"
                if after and point_id == "p5":
                    score["assessment_state"] = "carried_forward"
                    score["assessed_source_ref"] = "baseline/source.json"
        self.rewrite_json_artifact(
            ledger, "baseline/scores.json",
            lambda data: annotate_scores(data, "baseline/source.json"))
        self.rewrite_json_artifact(
            ledger, "attempt-1/scores.json",
            lambda data: (
                data["points"]["p5"].update({
                    "score": 8, "evidence_status": "observed",
                    "reason": "Synthetic carried score source.",
                    "assessed_source_ref": "baseline/source.json",
                    "evidence": ["evidence.txt"],
                }),
                annotate_scores(data, "attempt-1/source.json", after=True),
            ))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        return path, ledger

    def test_valid_ledger_reports_full_denominator_unknowns_and_finding_recurrence(self):
        path, _ = self.create_ledger()
        result = ITERATIONS.verify(path)
        report = ITERATIONS.report(result)
        self.assertEqual(report["goal"]["denominator"], 5)
        self.assertEqual(report["goal"]["claim_scope"], "selected_subset")
        self.assertEqual(report["goal"]["selected_point_count"], 4)
        self.assertEqual(report["goal"]["excluded_points"], ["p4"])
        self.assertEqual(report["goal"]["required_selected_points"], 4)
        self.assertEqual(report["goal"]["achieved_selected_points"], 1)
        self.assertEqual(report["goal"]["missing_or_below_goal"], ["p2", "p3", "p5"])
        self.assertEqual(report["goal"]["missing_evidence"], ["p3", "p5"])
        self.assertEqual(report["goal"]["unassessed_selected_points"], ["p3", "p5"])
        self.assertEqual(report["points"][0]["change"], 1)
        self.assertEqual(report["attempt_reports"][0]["dimension_changes"],
                         {"p1": 1, "p2": 1, "p3": None, "p4": 0, "p5": None})
        self.assertEqual(report["build_id"], "redesign-build")
        self.assertEqual(report["attempts"], 1)
        self.assertIsNone(report["elapsed_minutes"])
        self.assertEqual(report["unknown_costs"],
                         ["elapsed_minutes", "review_effort_minutes",
                          "verification_elapsed_seconds"])
        self.assertEqual(report["findings"]["distinct_observation_identities"], 1)
        self.assertEqual(report["findings"]["distinct_finding_identities"], 1)
        self.assertEqual(report["findings"]["recurring_observation_identities"], 1)
        self.assertEqual(report["findings"]["recurring_finding_identities"], 1)
        self.assertEqual(report["progress_by_reviewer_kind"]["generator_self_assessment"], 1)

    def test_v2_uses_project_goal_and_reports_overlapping_scopes_and_freshness(self):
        path, ledger = self.create_v2_ledger()
        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["goal"]["score"], 7)
        self.assertEqual(report["goal"]["fraction"], 0.5)
        self.assertEqual(report["goal"]["denominator"], 5)
        self.assertEqual(report["goal"]["selected_denominator"], 5)
        self.assertEqual(report["goal"]["required_selected_points"], 3)
        self.assertEqual(report["goal"]["achieved_selected_points"], 2)
        self.assertEqual(report["goal"]["unassessed_selected_points"], ["p3"])
        self.assertEqual(report["goal"]["carried_selected_points"], ["p5"])
        self.assertEqual(report["goal"]["stale_selected_points"], ["p4"])
        scopes = {scope["id"]: scope for scope in report["scopes"]}
        self.assertEqual(scopes["region-header"]["point_ids"], ["p1", "p2"])
        self.assertEqual(scopes["region-header"]["denominator"], 2)
        self.assertEqual(scopes["region-header"]["achieved_fresh_points"], 2)
        self.assertTrue(scopes["journey-onboard"]["failed_journey"])
        self.assertEqual(scopes["journey-onboard"]["unassessed_points"], ["p3"])
        self.assertEqual(report["version_comparison"]["status"], "compatible")
        self.assertEqual(report["brief"]["status"], "incomplete")
        self.assertEqual(report["points"][4]["assessment_state"], "carried_forward")
        self.assertEqual(report["points"][3]["assessed_source_ref"], "baseline/source.json")
        self.assertEqual(report["evidence_coverage_gaps"], [])
        attempt = report["attempt_reports"][0]
        self.assertIn("Improve the two named component points.",
                      attempt["expected_outcomes"][0])
        self.assertIn("Both named scores rose", attempt["actual_outcomes"][0])
        self.assertEqual(attempt["actual_evidence"], ["evidence.txt"])
        self.assertEqual(attempt["regressions"], [])
        self.assertEqual(attempt["effort_minutes"], 4)
        self.assertIn("provisional", attempt["decision_reason"])

    def test_v2_rejects_an_acceptance_claim_from_an_incomplete_brief(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, "attempt-1/scores.json", lambda data: (
            data["points"]["p3"].update({
                "score": 8, "evidence_status": "observed",
                "reason": "Synthetic fresh assessment.",
                "assessment_state": "fresh", "review_required": False,
                "assessed_source_ref": "attempt-1/source.json",
                "evidence": ["evidence.txt"],
                "evidence_coverage": {
                    "evidence.txt": {
                        "point_ids": ["p3"], "scenario_ids": ["dense-dark-desktop"],
                        "declaration": "Synthetic evidence covers p3.",
                    }
                },
            })
        ))
        self.refresh_decision(ledger)
        final_ref = self.artifact("attempt-1/final-review.json", {
            "source_ref": "attempt-1/source.json",
            "scope_id": "scope-1",
            "build_id": "redesign-build",
            "status": "adoptable",
            "reviewer": {"kind": "independent_qualified_review", "id": "reviewer-1"},
        })
        ledger["stop"] = {
            "reason": "target_provisionally_met",
            "reason_text": "The declared illustrative target was reached.",
            "retained_source_ref": "attempt-1/source.json",
            "final_review_status": "adoptable",
            "final_review_ref": final_ref,
        }
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "incomplete brief"):
            ITERATIONS.verify(path)

    def test_v2_report_keeps_generator_independent_human_and_at_provenance_distinct(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, "attempt-1/scores.json", lambda data: (
            data["points"]["p3"].update({
                "score": 8, "evidence_status": "observed",
                "reason": "Synthetic fresh assessment.",
                "assessment_state": "fresh", "review_required": False,
                "assessed_source_ref": "attempt-1/source.json",
                "evidence": ["evidence.txt"],
                "evidence_coverage": {
                    "evidence.txt": {
                        "point_ids": ["p3"], "scenario_ids": ["dense-dark-desktop"],
                        "declaration": "Synthetic evidence covers p3.",
                    }
                },
            })
        ))
        self.rewrite_json_artifact(ledger, "attempt-1/checks.json", lambda data: (
            data.update({"observations": [
                {"profile": "desktop", "finding_id": "generator-note", "outcome": "pass",
                 "evidence_kind": "generator_self_assessment"},
                {"profile": "desktop", "finding_id": "independent-note", "outcome": "pass",
                 "evidence_kind": "independent_qualified_review"},
                {"profile": "desktop", "finding_id": "human-task", "outcome": "unknown",
                 "evidence_kind": "human_review"},
                {"profile": "desktop", "finding_id": "at-task", "outcome": "unknown",
                 "evidence_kind": "assistive_technology_evidence"},
            ]})
        ))
        self.refresh_decision(ledger)
        self.rewrite_json_artifact(ledger, "intake/brief.json", lambda data: (
            data.update({
                "status": "complete", "unresolved_questions": [],
                "critical_unknowns": [],
            }),
            data["quality_goal"].update({"status": "approved"}),
            data["decision_authority"]["decisions"][0].update({"status": "approved"}),
        ))
        final_ref = self.artifact("attempt-1/final-review.json", {
            "source_ref": "attempt-1/source.json",
            "scope_id": "scope-1",
            "build_id": "redesign-build",
            "status": "not_adoptable",
            "reviewer": {"kind": "independent_qualified_review", "id": "reviewer-1"},
        })
        ledger["stop"] = {
            "reason": "target_provisionally_met",
            "reason_text": "The synthetic project-owned goal and gates were reached.",
            "retained_source_ref": "attempt-1/source.json",
            "final_review_status": "not_adoptable",
            "final_review_ref": final_ref,
        }
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["reviewer"]["kind"], "generator_self_assessment")
        self.assertEqual(report["final_review"]["reviewer"]["kind"],
                         "independent_qualified_review")
        self.assertEqual(report["final_review"]["status"], "not_adoptable")
        self.assertEqual(
            report["check_evidence_kinds"],
            ["assistive_technology_evidence", "generator_self_assessment",
             "human_review", "independent_qualified_review"],
        )
        self.assertEqual(
            report["findings"]["outcomes_by_evidence_kind"]["human_review"]["unknown"], 1)
        self.assertEqual(
            report["findings"]["outcomes_by_evidence_kind"]
            ["assistive_technology_evidence"]["unknown"], 1)

    def test_agent_cannot_mark_a_sponsor_decision_approved(self):
        path, ledger = self.create_v2_ledger()
        ledger["iterations"][0]["decision_records"] = [{
            "id": "goal", "actor": "agent", "status": "approved",
            "decision": "Approve the project goal.",
        }]
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "exceeds delegated authority"):
            ITERATIONS.verify(path)

    def test_pre_change_proposal_binds_expected_outcomes(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, ledger["iterations"][0]["proposal_ref"],
                                   lambda data: data.update({
                                       "expected_outcomes": ["Change the goal after seeing scores."]
                                   }))
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "bind expected outcomes"):
            ITERATIONS.verify(path)

    def test_affected_stale_point_cannot_support_a_keep(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, "attempt-1/scores.json", lambda data: (
            data["points"]["p1"].update({
                "assessment_state": "stale", "review_required": True,
                "assessed_source_ref": "baseline/source.json",
            })
        ))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "fresh review of every affected"):
            ITERATIONS.verify(path)

    def test_missing_shared_evidence_coverage_is_visible(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, "attempt-1/scores.json", lambda data: (
            data["points"]["p3"].update({
                "evidence": ["evidence.txt"],
                "evidence_coverage": {
                    "evidence.txt": {
                        "point_ids": [], "scenario_ids": ["dense-dark-desktop"],
                        "declaration": "Evidence file does not establish coverage for p3.",
                    }
                },
            })
        ))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["evidence_coverage_gaps"],
                         [{"point_id": "p3", "evidence_ref": "evidence.txt"}])
        self.assertIn("p3", report["goal"]["unassessed_selected_points"])

    def test_failed_journey_remains_visible_beside_high_scoring_components(self):
        path, ledger = self.create_v2_ledger()
        for reference in ("baseline/checks.json", "attempt-1/checks.json"):
            self.rewrite_json_artifact(ledger, reference, lambda data: (
                data.update({"status": "fail"}),
                data["tasks"]["open-evidence"].update({"status": "fail"}),
            ))
        attempt = ledger["iterations"][0]
        attempt.update({
            "decision": "blocked",
            "provisional": False,
            "reason": "The synthetic journey task failed.",
            "retained_source_ref": None,
        })
        self.refresh_decision(ledger)
        ledger["stop"] = {
            "reason": "blocked",
            "reason_text": "The synthetic journey task failed.",
            "retained_source_ref": "baseline/source.json",
        }
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        report = ITERATIONS.report(ITERATIONS.verify(path))
        scopes = {scope["id"]: scope for scope in report["scopes"]}
        self.assertEqual(scopes["component-a"]["achieved_fresh_points"], 1)
        self.assertTrue(scopes["journey-onboard"]["failed_journey"])
        self.assertEqual(scopes["journey-onboard"]["task_outcomes"][0]["status"], "fail")

    def test_v2_incompatible_inventory_and_goal_mapping_is_reported_not_compared(self):
        path, ledger = self.create_v2_ledger()
        contract = ledger["contract"]
        old_scopes = [scope["id"] for scope in contract["scopes"]]
        contract["goal"] = {"score": 8, "fraction": 0.5}
        contract["points"] = [
            point for point in contract["points"] if point["id"] != "p2"
        ]
        contract["points"].append({
            "id": "p6", "selected": True, "scopes": ["page-overview", "state-loading"],
        })
        contract["scopes"].append({
            "id": "state-loading", "kind": "state", "name": "Long loading state",
        })
        self.rewrite_json_artifact(ledger, "intake/brief.json", lambda data: (
            data["quality_goal"].update({"score": 8})
        ))
        decision_v2 = self.artifact("contract/decisions-v2.json", {
            "decision": "Changed synthetic point inventory and goal.",
        })
        contract["version_history"].append({
            "id": "v2", "parent": "v1",
            "goal": {"score": 8, "fraction": 0.5},
            "point_ids": ["p1", "p3", "p4", "p5", "p6"],
            "selected_point_ids": ["p1", "p3", "p4", "p5", "p6"],
            "scope_ids": old_scopes + ["state-loading"],
            "point_scopes": {
                point["id"]: point["scopes"] for point in contract["points"]
            },
            "rubric_revision": "rubric-v1",
            "inventory_revision": "inventory-v2",
            "scope_revision": "scope-v2",
            "material_decisions_ref": decision_v2,
        })
        contract["version_mappings"].append({
            "from": "v1", "to": "v2", "compatible": False,
            "reason": "The target and point inventory changed; totals cannot be compared.",
            "points": [
                {"from": "p1", "to": "p1", "relation": "same",
                 "from_scopes": ["component-a", "region-header", "page-overview"],
                 "to_scopes": ["component-a", "region-header", "page-overview"]},
                {"from": "p2", "to": None, "relation": "removed",
                 "from_scopes": ["component-b", "region-header", "page-overview",
                                 "journey-onboard"], "to_scopes": []},
                {"from": "p3", "to": "p3", "relation": "same",
                 "from_scopes": ["page-overview", "journey-onboard"],
                 "to_scopes": ["page-overview", "journey-onboard"]},
                {"from": "p4", "to": "p4", "relation": "same",
                 "from_scopes": ["page-settings"], "to_scopes": ["page-settings"]},
                {"from": "p5", "to": "p5", "relation": "same",
                 "from_scopes": ["component-c", "page-settings"],
                 "to_scopes": ["component-c", "page-settings"]},
                {"from": None, "to": "p6", "relation": "added",
                 "from_scopes": [], "to_scopes": ["page-overview", "state-loading"]},
            ],
            "scopes": [
                {"from": scope_id, "to": scope_id, "relation": "same"}
                for scope_id in old_scopes
            ] + [{"from": None, "to": "state-loading", "relation": "added"}],
        })
        attempt = ledger["iterations"][0]
        attempt["version_id"] = "v2"
        attempt["after"]["version_id"] = "v2"
        attempt["dimensions"] = ["p1"]
        attempt["expected_gain"] = {"p1": 1}
        attempt["affected_points"] = ["p1"]
        attempt["decision"] = "blocked"
        attempt["provisional"] = False
        attempt["reason"] = "Do not retain a cross-version result as a comparable keep."
        attempt["retained_source_ref"] = None
        self.rewrite_json_artifact(ledger, attempt["proposal_ref"], lambda data: (
            data.update({
                "dimensions": ["p1"], "expected_gain": {"p1": 1},
                "affected_points": ["p1"],
            })
        ))

        def revise_after(data):
            data["points"].pop("p2")
            data["points"]["p1"]["evidence_coverage"]["evidence.txt"]["point_ids"] = ["p1"]
            data["points"]["p6"] = dict(data["points"]["p1"])
            data["points"]["p6"]["assessed_source_ref"] = "attempt-1/source.json"
            data["points"]["p6"]["reason"] = "Synthetic new point assessment."
            data["points"]["p6"]["evidence_coverage"] = {
                "evidence.txt": {
                    "point_ids": ["p6"], "scenario_ids": ["dense-dark-desktop"],
                    "declaration": "Synthetic evidence covers p6.",
                }
            }
        self.rewrite_json_artifact(ledger, "attempt-1/scores.json", revise_after)
        self.refresh_decision(ledger)
        ledger["stop"] = {
            "reason": "blocked",
            "reason_text": "A new baseline is required after the incompatible contract change.",
            "retained_source_ref": "baseline/source.json",
        }
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["version_mappings"][0]["compatible"], False)
        self.assertEqual(report["version_comparison"]["status"], "incompatible")
        self.assertEqual(report["attempt_reports"][0]["comparison_status"], "incompatible")
        self.assertIsNone(report["attempt_reports"][0]["dimension_changes"]["p1"])
        self.assertIsNone(report["points"][-1]["current_score"])
        self.assertIsNone(report["points"][-1]["change"])

    def test_v2_budget_stop_requires_actionable_local_next_round(self):
        path, ledger = self.create_v2_ledger()
        self.rewrite_json_artifact(ledger, "intake/brief.json", lambda data: (
            data["budget"].update({"limit_minutes": 4})
        ))
        ledger["stop"].update({
            "reason": "budget",
            "reason_text": "The declared four-minute synthetic budget was reached.",
            "next_round": {
                "trigger": "budget",
                "action": "stop_with_reason",
                "hypothesis": "Do not start another round without sponsor-approved budget.",
                "rationale": "The available synthetic budget is exhausted.",
                "budget_remaining_minutes": 0,
                "proposed_effort_minutes": 0,
            },
        })
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        result = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(result["total_effort_minutes"], 4)
        self.assertEqual(result["next_round"]["action"], "stop_with_reason")

    def test_v2_plateau_suggests_revision_without_changing_the_project_goal(self):
        path, ledger = self.create_v2_ledger()
        attempt = ledger["iterations"][0]
        reason = "The change was reverted despite its illustrative score increase."
        restore_ref = self.artifact("attempt-1/restore.json", {
            "verified": True, "retained_source_ref": "baseline/source.json",
        })
        attempt.update({
            "decision": "revert",
            "provisional": False,
            "reason": reason,
            "retained_source_ref": "baseline/source.json",
            "restore_verification_ref": restore_ref,
        })
        self.refresh_decision(ledger)
        ledger["contract"]["no_gain_limit"] = 1
        ledger["stop"] = {
            "reason": "no_gain",
            "reason_text": "The declared no-gain plateau was reached.",
            "retained_source_ref": "baseline/source.json",
            "next_round": {
                "trigger": "no_gain",
                "action": "revisit_brief",
                "hypothesis": "Check whether the project brief misses the journey bottleneck.",
                "rationale": "Revisit the brief instead of lowering the goal or inflating scores.",
                "budget_remaining_minutes": 16,
                "proposed_effort_minutes": 0,
            },
        }
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["goal"]["score"], 7)
        self.assertEqual(report["next_round"]["action"], "revisit_brief")
        self.assertEqual(report["attempt_reports"][0]["decision_reason"], reason)
        self.assertEqual(report["attempt_reports"][0]["effort_minutes"], 4)

        ledger["stop"]["next_round"]["score"] = 6
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "cannot change scores or lower"):
            ITERATIONS.verify(path)

    def test_v2_cli_verifies_synthetic_local_fixture_without_external_services(self):
        path, _ = self.create_v2_ledger()
        script = ROOT / ".github/skills/ui-prototype-council/iterations.py"
        verified = subprocess.run(
            [sys.executable, str(script), "verify", str(path)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        report = subprocess.run(
            [sys.executable, str(script), "report", str(path)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)["goal"]["score"], 7)

    def test_all_point_goal_keeps_unassessed_points_in_overall_denominator(self):
        path, ledger = self.create_ledger()
        baseline = ledger["baseline"]
        attempt = ledger["iterations"][0]
        before_values = {"p1": 8, "p2": 8}
        after_values = {"p1": 9, "p2": 9}
        before_values.update({f"p{i}": 9 for i in range(3, 19)})
        after_values.update({f"p{i}": 9 for i in range(3, 19)})
        before_values.update({f"p{i}": None for i in range(19, 24)})
        after_values.update({f"p{i}": None for i in range(19, 24)})

        before_scores = self.scores(
            "baseline/scores.json", baseline["source_ref"], baseline["build_id"], before_values)
        after_scores = self.scores(
            "attempt-1/scores.json", attempt["after"]["source_ref"], "redesign-build",
            after_values)
        before_checks = attempt["before"]["checks_ref"]
        after_checks = attempt["after"]["checks_ref"]
        decision_reason = "Illustrative fixture change; keep is provisional."
        decision = self.artifact("attempt-1/decision.json", {
            "attempt_id": 1,
            "decision": "keep",
            "reason": decision_reason,
            "before_artifacts": {
                "source_ref": self.artifacts[baseline["source_ref"]]["sha256"],
                "scores_ref": self.artifacts[before_scores]["sha256"],
                "checks_ref": self.artifacts[before_checks]["sha256"],
            },
            "after_artifacts": {
                "source_ref": self.artifacts[attempt["after"]["source_ref"]]["sha256"],
                "scores_ref": self.artifacts[after_scores]["sha256"],
                "checks_ref": self.artifacts[after_checks]["sha256"],
            },
        })
        ledger["contract"]["points"] = [
            {"id": f"p{i}", "selected": True} for i in range(1, 24)
        ]
        ledger["baseline"]["scores_ref"] = before_scores
        attempt["before"]["scores_ref"] = before_scores
        attempt["after"]["scores_ref"] = after_scores
        attempt["decision_ref"] = decision
        attempt["reason"] = decision_reason
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

        report = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(report["goal"]["claim_scope"], "all_declared_points")
        self.assertEqual(report["goal"]["selected_point_count"], 23)
        self.assertEqual(report["goal"]["denominator"], 23)
        self.assertEqual(report["goal"]["achieved_selected_points"], 18)
        self.assertEqual(report["goal"]["required_selected_points"], 19)
        self.assertEqual(report["goal"]["excluded_points"], [])
        self.assertEqual(report["goal"]["unassessed_selected_points"],
                         [f"p{i}" for i in range(19, 24)])
        self.assertEqual(report["goal"]["missing_evidence"],
                         [f"p{i}" for i in range(19, 24)])
        self.assertEqual(report["progress_by_reviewer_kind"]["independent_qualified_review"], 0)

    def test_keep_blocks_new_finding_even_when_finding_count_is_unchanged(self):
        path, ledger = self.create_ledger()
        ledger["artifacts"]["baseline/checks.json"] = self.rewrite_checks(
            ledger, "baseline/checks.json", [{"id": "old", "severity": 1}])
        ledger["artifacts"]["attempt-1/checks.json"] = self.rewrite_checks(
            ledger, "attempt-1/checks.json", [{"id": "new", "severity": 1}])
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "new finding identity"):
            ITERATIONS.verify(path)

    def test_keep_blocks_task_click_increase_and_unknown_check_status(self):
        path, ledger = self.create_ledger()
        ledger["artifacts"]["attempt-1/checks.json"] = self.rewrite_checks(
            ledger, "attempt-1/checks.json", [], task_clicks=2)
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "task-click regression"):
            ITERATIONS.verify(path)

        path, ledger = self.create_ledger()
        self.rewrite_checks(ledger, "attempt-1/checks.json", [], status="unknown")
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "failed, unknown or incomplete"):
            ITERATIONS.verify(path)

    def test_unavailable_real_zoom_cannot_be_substituted_by_css_viewport_evidence(self):
        path, ledger = self.create_ledger()
        item = ledger["artifacts"]["attempt-1/checks.json"]
        checks = json.loads((self.root / item["path"]).read_text())
        checks["scenario_evidence"][1]["evidence_type"] = "css_viewport"
        checks["scenario_evidence"][1]["status"] = "unavailable"
        checks["status"] = "incomplete"
        checks["full_coverage"] = False
        encoded = (json.dumps(checks, sort_keys=True) + "\n").encode()
        (self.root / item["path"]).write_bytes(encoded)
        item["sha256"] = hashlib.sha256(encoded).hexdigest()
        ledger["contract"]["required_scenarios"][1]["evidence_type"] = "real_browser_zoom"
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "misidentified evidence"):
            ITERATIONS.verify(path)

    def test_passing_report_cannot_hide_a_failed_or_unknown_command(self):
        path, ledger = self.create_ledger()
        item = ledger["artifacts"]["attempt-1/checks.json"]
        checks = json.loads((self.root / item["path"]).read_text())
        checks["commands"] = [
            {"command": "render-check", "status": "fail", "exit_code": 1},
            {"command": "unknown-check", "status": "unknown", "exit_code": None},
        ]
        encoded = (json.dumps(checks, sort_keys=True) + "\n").encode()
        (self.root / item["path"]).write_bytes(encoded)
        item["sha256"] = hashlib.sha256(encoded).hexdigest()
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "failed or unknown command"):
            ITERATIONS.verify(path)

    def rewrite_checks(self, ledger, reference, findings, task_clicks=1, status="pass"):
        item = ledger["artifacts"][reference]
        path = self.root / item["path"]
        data = json.loads(path.read_text())
        data["findings"] = findings
        data["tasks"]["open-evidence"]["clicks"] = task_clicks
        data["status"] = status
        encoded = (json.dumps(data, sort_keys=True) + "\n").encode()
        path.write_bytes(encoded)
        item["sha256"] = hashlib.sha256(encoded).hexdigest()
        return item

    def refresh_decision(self, ledger):
        attempt = ledger["iterations"][0]
        decision_artifact = ledger["artifacts"][attempt["decision_ref"]]
        decision_path = self.root / decision_artifact["path"]
        record = json.loads(decision_path.read_text())
        record["attempt_id"] = attempt["id"]
        record["decision"] = attempt["decision"]
        record["reason"] = attempt["reason"]
        record["after_artifacts"] = {
            key: ledger["artifacts"][attempt["after"][key]]["sha256"]
            for key in ("source_ref", "scores_ref", "checks_ref")
        }
        record["before_artifacts"] = {
            key: ledger["artifacts"][attempt["before"][key]]["sha256"]
            for key in ("source_ref", "scores_ref", "checks_ref")
        }
        if ledger.get("format_version") == 2:
            record["attempt_summary"] = {
                key: attempt[key] for key in (
                    "expected_outcomes", "actual_outcomes", "actual_evidence",
                    "affected_points", "dependencies", "guardrails", "regressions",
                    "effort_minutes", "decision_actor", "decision_records",
                )
            }
        encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
        decision_path.write_bytes(encoded)
        decision_artifact["sha256"] = hashlib.sha256(encoded).hexdigest()

    def test_modified_evidence_and_stale_rescore_are_rejected(self):
        path, ledger = self.create_ledger()
        (self.root / "evidence.txt").write_text("changed evidence")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "digest changed"):
            ITERATIONS.verify(path)

        path, ledger = self.create_ledger()
        baseline = json.loads((self.root / "baseline/source.json").read_text())
        source_file = self.root / baseline["files"]["synthetic-source"]["path"]
        source_file.write_text("changed source")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "source file .* changed"):
            ITERATIONS.verify(path)

        path, ledger = self.create_ledger()
        score_item = ledger["artifacts"]["attempt-1/scores.json"]
        scores = json.loads((self.root / score_item["path"]).read_text())
        scores["points"]["p1"]["assessed_source_ref"] = "baseline/source.json"
        encoded = (json.dumps(scores, sort_keys=True) + "\n").encode()
        (self.root / score_item["path"]).write_bytes(encoded)
        score_item["sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "stale for the current source"):
            ITERATIONS.verify(path)

    def test_post_decision_rescore_is_rejected_by_frozen_decision_artifact(self):
        path, ledger = self.create_ledger()
        score_item = ledger["artifacts"]["attempt-1/scores.json"]
        scores = json.loads((self.root / score_item["path"]).read_text())
        scores["points"]["p1"]["reason"] = "Changed after the keep decision."
        encoded = (json.dumps(scores, sort_keys=True) + "\n").encode()
        (self.root / score_item["path"]).write_bytes(encoded)
        score_item["sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "decision record does not bind"):
            ITERATIONS.verify(path)

    def test_infeasible_goal_requires_explicit_bound_for_every_selected_point(self):
        path, ledger = self.create_ledger()
        upper_bounds = {"p1": 8, "p2": 8, "p3": 8, "p5": 8}
        proof = self.artifact("ceiling.json", {
            "rubric_revision": "frozen-v1", "upper_bounds": upper_bounds,
        })
        ledger["contract"]["feasibility"] = {
            "status": "infeasible",
            "assumptions": ["Frozen rubric caps every selected point below 9."],
            "proof": {
                "type": "immutable_score_ceiling",
                "upper_bounds": upper_bounds,
                "evidence_ref": proof,
            },
        }
        path.write_text(json.dumps(ledger), encoding="utf-8")
        infeasible = ITERATIONS.report(ITERATIONS.verify(path))["feasibility"]
        self.assertEqual(infeasible["status"], "infeasible")
        self.assertEqual(infeasible["assumptions"],
                         ["Frozen rubric caps every selected point below 9."])
        ledger["contract"]["feasibility"]["proof"]["upper_bounds"]["p5"] = 9
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "every selected point"):
            ITERATIONS.verify(path)

    def test_9_requires_anchor_and_unknown_points_cannot_be_removed(self):
        path, ledger = self.create_ledger()
        score_item = ledger["artifacts"]["attempt-1/scores.json"]
        scores = json.loads((self.root / score_item["path"]).read_text())
        del scores["points"]["p1"]["anchor"]
        encoded = (json.dumps(scores, sort_keys=True) + "\n").encode()
        (self.root / score_item["path"]).write_bytes(encoded)
        score_item["sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "needs its rubric anchor"):
            ITERATIONS.verify(path)

        path, ledger = self.create_ledger()
        score_item = ledger["artifacts"]["attempt-1/scores.json"]
        scores = json.loads((self.root / score_item["path"]).read_text())
        del scores["points"]["p3"]
        encoded = (json.dumps(scores, sort_keys=True) + "\n").encode()
        (self.root / score_item["path"]).write_bytes(encoded)
        score_item["sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "every declared measurement point"):
            ITERATIONS.verify(path)


if __name__ == "__main__":
    unittest.main()
