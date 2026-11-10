"""Contract tests for the machine-checked, evidence-bound refinement ledger."""

import hashlib
import importlib.util
import json
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
        record["after_artifacts"] = {
            key: ledger["artifacts"][attempt["after"][key]]["sha256"]
            for key in ("source_ref", "scores_ref", "checks_ref")
        }
        record["before_artifacts"] = {
            key: ledger["artifacts"][attempt["before"][key]]["sha256"]
            for key in ("source_ref", "scores_ref", "checks_ref")
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
