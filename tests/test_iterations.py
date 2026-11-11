"""Contract tests for the machine-checked, evidence-bound refinement ledger."""

import hashlib
import importlib.util
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
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

    def png_capture(self, color, width=2, height=2):
        def chunk(kind, payload):
            body = kind + payload
            return (struct.pack(">I", len(payload)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        rows = (b"\x00" + bytes(color) * width) * height
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows))
                + chunk(b"IEND", b""))

    def add_visual_evidence(self, ledger):
        attempt = ledger["iterations"][0]
        before_capture = self.artifact(
            "attempt-1/before.png",
            self.png_capture((20, 40, 60, 255), width=144, height=400), json_file=False)
        after_capture = self.artifact(
            "attempt-1/after.png",
            self.png_capture((60, 40, 20, 255), width=400, height=144), json_file=False)
        visual_ref = self.artifact("attempt-1/visual.json", {
            "schema_version": 1,
            "coordinate_space": "normalized",
            "attempt_id": 1,
            "before_source_ref": attempt["before"]["source_ref"],
            "after_source_ref": attempt["after"]["source_ref"],
            "before_capture_ref": before_capture,
            "before_capture_sha256": self.artifacts[before_capture]["sha256"],
            "after_capture_ref": after_capture,
            "after_capture_sha256": self.artifacts[after_capture]["sha256"],
            "changes": [{
                "id": "header",
                "label": "Header hierarchy",
                "description": "Moved the primary action beside the heading.",
                "before": {"start": {"x": 0.1, "y": 0.2},
                           "end": {"x": 0.5, "y": 0.3}},
                "after": {"start": {"x": 0.1, "y": 0.2},
                          "end": {"x": 0.6, "y": 0.3}},
            }],
        })
        attempt["visual_ref"] = visual_ref
        if ledger.get("format_version") == 2:
            attempt["actual_evidence"].extend(
                [visual_ref, before_capture, after_capture])
        self.refresh_decision(ledger)
        (self.root / "iterations.json").write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        return visual_ref

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

    def multi_gain_ledger(self):
        path, ledger = self.create_v2_ledger()
        attempt = ledger["iterations"][0]
        example = json.loads((ROOT / "docs/examples/concept-exploration/project-intake-v2.json").read_text())
        def scope_brief(data):
            data["intake"] = example["intake"]
            data["intake"]["scope"]["level"] = "component"
            data["intake"]["views"] = []
            data["intake"]["keep"] = {"none_reason": "This fixture has no preserved behavior."}
            data["sources"] = example["sources"]
            data["unresolved_questions"] = []
            data["decision_authority"]["sponsor_decisions"].append("scope")
            data["decision_authority"]["decisions"].append(example["decision_authority"]["decisions"][0])
            snapshot = {"level": "component", "stage": "content", "view_dispositions": {}}
            data["intake"]["scope"]["sponsor_confirmation"]["scope_snapshot"] = snapshot
            data["sources"][0]["scope_snapshot"] = snapshot
        self.rewrite_json_artifact(ledger, ledger["contract"]["brief_ref"], scope_brief)
        ledger["contract"]["scope_contract_version"] = 1
        rule = {
            "id": "multi_gain_v2", "min_improved": 3, "min_gain": 1, "noise_band": 0.5,
            "panel": {"reviewers": [{"id": "fixture-panel", "kind": "generator_self_assessment",
                                      "model": "synthetic-not-run"}], "repeats": 2}}
        ledger["contract"]["keep_rule"] = rule
        attempt["dimensions"] = ["p1", "p2", "p3", "p4"]
        attempt["expected_gain"] = {key: 1 for key in attempt["dimensions"]}
        attempt["affected_points"] = [f"p{i}" for i in range(1, 6)]
        values = {"p1": 8, "p2": 7, "p3": 7, "p4": 6, "p5": 6}
        for refs, after in ((attempt["before"], False), (attempt["after"], True)):
            def update(data):
                for key, point in data["points"].items():
                    point.update({
                        "score": values[key] if after else 6,
                        "evidence_status": "observed", "reason": "Synthetic paired fixture.",
                        "evidence": ["evidence.txt"], "assessed_source_ref": refs["source_ref"],
                        "assessment_state": "fresh", "review_required": False,
                        "evidence_coverage": {"evidence.txt": {
                            "point_ids": [key], "scenario_ids": ["dense-dark-desktop"],
                            "declaration": "Synthetic fixture coverage."}}})
            self.rewrite_json_artifact(ledger, refs["scores_ref"], update)
        paired_ref = self.artifact("attempt-1/paired.json", {
            "schema_version": 1, "attempt_id": 1, "rule_id": "multi_gain_v2",
            "panel_id": "synthetic-pair-1", "panel": rule["panel"],
            "before_source_ref": attempt["before"]["source_ref"],
            "after_source_ref": attempt["after"]["source_ref"],
            "points": {key: {"baseline": [6, 6], "candidate": [value, value]}
                       for key, value in values.items()}})
        attempt["paired_scores_ref"] = paired_ref
        attempt["actual_evidence"].append(paired_ref)
        self.rewrite_json_artifact(ledger, attempt["proposal_ref"], lambda data: data.update({
            "dimensions": attempt["dimensions"], "expected_gain": attempt["expected_gain"],
            "affected_points": attempt["affected_points"], "keep_rule": rule}))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger))
        return path, ledger

    def test_multi_gain_keeps_concept_c_with_unmet_spacing_target(self):
        path, _ = self.multi_gain_ledger()
        result = ITERATIONS.report(ITERATIONS.verify(path))
        attempt = result["attempt_reports"][0]
        self.assertEqual(attempt["unmet_targets"], ["p4"])
        self.assertEqual(attempt["paired_panel"]["points"]["p1"]["delta"], 2)
        self.assertIn("Baseline drift", ITERATIONS.html_report(ITERATIONS.verify(path)))

    def test_multi_gain_rejects_noise_regression_and_missing_panel_scores(self):
        mutations = [
            (lambda data: data["points"]["p5"].update({"candidate": [5, 6]}), "paired score regression"),
            (lambda data: data["points"]["p1"].update({"candidate": [6, 7]}), "meaningful gains"),
            (lambda data: data["points"]["p1"].update({"candidate": [None, 8]}), "unassessed paired"),
            (lambda data: data.update({"after_source_ref": "baseline/source.json"}), "before/after sources"),
            (lambda data: data["panel"].update({"repeats": 1}), "panel roster"),
        ]
        for mutation, error in mutations:
            with self.subTest(error=error):
                path, ledger = self.multi_gain_ledger()
                self.rewrite_json_artifact(ledger, ledger["iterations"][0]["paired_scores_ref"], mutation)
                self.refresh_decision(ledger)
                path.write_text(json.dumps(ledger))
                with self.assertRaisesRegex(ITERATIONS.LedgerError, error):
                    ITERATIONS.verify(path)

    def test_multi_gain_rule_cannot_be_changed_after_proposal_or_decision(self):
        path, ledger = self.multi_gain_ledger()
        ledger["contract"]["keep_rule"]["noise_band"] = 0
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "proposal must freeze"):
            ITERATIONS.verify(path)

    def test_paired_baseline_drift_is_not_counted_as_candidate_gain(self):
        path, ledger = self.multi_gain_ledger()
        ref = ledger["iterations"][0]["paired_scores_ref"]
        self.rewrite_json_artifact(ledger, ref, lambda data: data["points"]["p5"].update({
            "baseline": [5, 6], "candidate": [5, 6]}))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger))
        result = ITERATIONS.report(ITERATIONS.verify(path))["attempt_reports"][0]
        self.assertEqual(result["paired_panel"]["points"]["p5"]["baseline_drift"], -0.5)
        self.assertEqual(result["score_changes"]["p5"]["delta"], 0)

    def test_scope_challenge_requires_bound_sponsor_feedback_and_inventory(self):
        path, ledger = self.multi_gain_ledger()
        def add_view(data):
            data["intake"]["views"].append({"id": "missing-settings", "disposition": "in", "capture_refs": []})
            snapshot = {"level": "component", "stage": "content",
                        "view_dispositions": {"missing-settings": "in"}}
            data["intake"]["scope"]["sponsor_confirmation"]["scope_snapshot"] = snapshot
            data["sources"][0]["scope_snapshot"] = snapshot
        self.rewrite_json_artifact(ledger, ledger["contract"]["brief_ref"], add_view)
        ledger["stop"].update({"reason": "scope_challenge", "missing_scope": ["missing-settings"]})
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "unknown artifact reference"):
            ITERATIONS.verify(path)
        feedback = self.artifact("scope-feedback.json", {
            "quote": "Synthetic sponsor says settings was omitted.",
            "actor": "synthetic-sponsor", "date": "2026-11-11",
            "missing_scope": ["missing-settings"]})
        ledger["stop"]["sponsor_feedback_ref"] = feedback
        path.write_text(json.dumps(ledger))
        self.assertEqual(ITERATIONS.report(ITERATIONS.verify(path))["stop"]["reason"], "scope_challenge")

    def test_v2_goal_stop_uses_documented_selected_denominator(self):
        path, ledger = self.create_v2_ledger()
        for point in ledger["contract"]["points"]:
            point["selected"] = point["id"] == "p1"
        ledger["contract"]["version_history"][-1]["selected_point_ids"] = ["p1"]
        ledger["stop"]["reason"] = "target_provisionally_met"
        ledger["stop"]["final_review_status"] = "not_adoptable"
        ledger["stop"]["final_review_ref"] = self.artifact("goal-review.json", {
            "source_ref": "attempt-1/source.json", "scope_id": "scope-1",
            "build_id": "redesign-build", "status": "not_adoptable",
            "reviewer": {"kind": "independent_qualified_review", "id": "reviewer-1"},
        })
        path.write_text(json.dumps(ledger))
        result = ITERATIONS.report(ITERATIONS.verify(path))
        self.assertEqual(result["stop"]["reason"], "target_provisionally_met")

    def test_new_scope_marker_cannot_silently_become_legacy(self):
        path, ledger = self.create_v2_ledger()
        ledger["contract"]["scope_contract_version"] = 1
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "requires a sponsor-confirmed"):
            ITERATIONS.verify(path)
        path, ledger = self.create_ledger()
        ledger["contract"]["scope_contract_version"] = 1
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "marker is format-2 only"):
            ITERATIONS.verify(path)

    def test_paired_rule_rejects_small_regression_and_noise_band_gains(self):
        for regression in (True, False):
            with self.subTest(regression=regression):
                path, ledger = self.multi_gain_ledger()
                attempt = ledger["iterations"][0]
                if regression:
                    self.rewrite_json_artifact(ledger, attempt["paired_scores_ref"], lambda data:
                        data["points"]["p5"].update({"candidate": [5, 6]}))
                else:
                    ledger["contract"]["keep_rule"]["noise_band"] = 1
                    self.rewrite_json_artifact(ledger, attempt["proposal_ref"], lambda data:
                        data.update(keep_rule=ledger["contract"]["keep_rule"]))
                self.refresh_decision(ledger)
                path.write_text(json.dumps(ledger))
                with self.assertRaisesRegex(ITERATIONS.LedgerError,
                                            "paired score regression|lacks meaningful gains"):
                    ITERATIONS.verify(path)

    def test_visual_evidence_and_per_attempt_score_changes_are_reported(self):
        path, ledger = self.create_ledger()
        visual_ref = self.add_visual_evidence(ledger)

        verified = ITERATIONS.verify(path)
        result = ITERATIONS.report(verified)
        attempt = result["attempt_reports"][0]
        self.assertEqual(attempt["visual_evidence"]["status"], "provided")
        self.assertEqual(attempt["visual_evidence"]["reference"], visual_ref)
        self.assertEqual(attempt["visual_evidence"]["changes"][0]["id"], "header")
        self.assertEqual(attempt["score_changes"]["p1"]["before_score"], 8)
        self.assertEqual(attempt["score_changes"]["p1"]["after_score"], 9)
        self.assertEqual(attempt["score_changes"]["p1"]["delta"], 1)
        self.assertTrue(attempt["score_changes"]["p1"]["targeted"])
        self.assertEqual(attempt["score_changes"]["p1"]["expected_gain"], 1)
        self.assertEqual(attempt["score_changes"]["p1"]["gain_status"], "met")
        self.assertEqual(attempt["visual_evidence"]["before_capture_sha256"],
                         ledger["artifacts"]["attempt-1/before.png"]["sha256"])
        self.assertEqual(attempt["visual_evidence"]["before_capture_dimensions"],
                         {"width": 144, "height": 400})
        rendered = ITERATIONS.html_report(verified, attempt_id=1)
        self.assertIn("data:image/png;base64,", rendered)
        self.assertIn('marker-end="url(#arrow-1-before-1)"', rendered)
        self.assertIn('viewBox="0 0 144 400"', rendered)
        self.assertIn('viewBox="0 0 400 144"', rendered)
        self.assertNotIn('preserveAspectRatio="none"', rendered)
        self.assertIn('<circle cx="17.532" cy="62.000"', rendered)
        self.assertIn("Header hierarchy", rendered)
        self.assertIn("Moved the primary action beside the heading.", rendered)
        self.assertIn("What changed in the scores", rendered)
        self.assertIn("Target +1 (met)", rendered)
        self.assertIn('mobile-cell-label">Delta</span>', rendered)
        self.assertIn("Reviewer labels are declared provenance", rendered)
        self.assertIn("Attempt 1 · generator_self_assessment", rendered)
        self.assertIn("Not recorded. A kept attempt is provisional progress", rendered)
        self.assertIn("Keep (provisional)", rendered)
        self.assertIn('aria-describedby="changes-1"', rendered)

    def test_html_report_escapes_ledger_text_and_marks_missing_visual_evidence(self):
        path, ledger = self.create_ledger()
        attempt = ledger["iterations"][0]
        injection = '<img src=x onerror="alert(1)">'
        attempt["hypothesis"] = injection
        attempt["reason"] = injection
        self.rewrite_json_artifact(
            ledger, attempt["proposal_ref"], lambda data: data.update({"hypothesis": injection}))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")

        rendered = ITERATIONS.html_report(ITERATIONS.verify(path))
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", rendered)
        self.assertNotIn(injection, rendered)
        self.assertIn("No captures or annotations were supplied", rendered)
        self.assertIn("No arrows were inferred", rendered)
        self.assertIn('<h3 id="visual-1">No captures supplied</h3>', rendered)
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "attempt 2 does not exist"):
            ITERATIONS.html_report(ITERATIONS.verify(path), attempt_id=2)

    def test_html_report_cap_checks_embedded_capture_total(self):
        path, ledger = self.create_ledger()
        self.add_visual_evidence(ledger)
        original_limit = ITERATIONS.MAX_HTML_REPORT_BYTES
        ITERATIONS.MAX_HTML_REPORT_BYTES = 100
        try:
            with self.assertRaisesRegex(ITERATIONS.LedgerError, "embedded captures exceed"):
                ITERATIONS.html_report(ITERATIONS.verify(path))
        finally:
            ITERATIONS.MAX_HTML_REPORT_BYTES = original_limit

    def test_html_report_cap_checks_aggregate_capture_pixels(self):
        path, ledger = self.create_ledger()
        self.add_visual_evidence(ledger)
        original_limit = ITERATIONS.MAX_HTML_REPORT_PIXELS
        ITERATIONS.MAX_HTML_REPORT_PIXELS = 100_000
        try:
            with self.assertRaisesRegex(ITERATIONS.LedgerError, "100,000-pixel"):
                ITERATIONS.html_report(ITERATIONS.verify(path))
        finally:
            ITERATIONS.MAX_HTML_REPORT_PIXELS = original_limit

    def test_png_capture_pixel_cap_rejects_extreme_dimensions(self):
        reference = self.artifact(
            "oversized.png", self.png_capture((20, 40, 60, 255)), json_file=False)
        item = self.artifacts[reference]
        capture_path = self.root / item["path"]
        data = bytearray(capture_path.read_bytes())
        data[16:24] = struct.pack(">II", 50_000, 900)
        chunk = data[12:16] + data[16:29]
        data[29:33] = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        capture_path.write_bytes(data)
        item["sha256"] = hashlib.sha256(data).hexdigest()
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "excessive dimensions"):
            ITERATIONS._capture_png(self.root, self.artifacts, reference)

    def test_empty_visual_annotations_do_not_claim_arrows_in_alt_text(self):
        path, ledger = self.create_ledger()
        visual_ref = self.add_visual_evidence(ledger)
        self.rewrite_json_artifact(ledger, visual_ref, lambda data: data.update({"changes": []}))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        rendered = ITERATIONS.html_report(ITERATIONS.verify(path), attempt_id=1)
        self.assertIn('alt="Before capture; no visual annotations were supplied"', rendered)
        self.assertIn("No changes were annotated in this attempt", rendered)
        self.assertNotIn('marker-end="url(#arrow-1-before-1)"', rendered)

    def test_short_edge_arrowhead_stays_clear_of_numbered_badge(self):
        path, ledger = self.create_ledger()
        visual_ref = self.add_visual_evidence(ledger)
        self.rewrite_json_artifact(ledger, visual_ref, lambda data: (
            data["changes"][0]["before"].update({
                "start": {"x": 0, "y": 0.5},
                "end": {"x": 0.01, "y": 0.5},
            })
        ))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        attempt = ITERATIONS.report(ITERATIONS.verify(path))["attempt_reports"][0]
        overlay = ITERATIONS._render_arrow_overlay(attempt["visual_evidence"], "before", 1)
        line = re.search(r'<line x1="[\d.]+" y1="[\d.]+" x2="([\d.]+)"', overlay)
        marker = re.search(r'<marker id="arrow-1-before-1" markerWidth="([\d.]+)"', overlay)
        badge = re.search(
            r'<circle cx="([\d.]+)" cy="[\d.]+" r="([\d.]+)" '
            r'class="arrow-number" stroke-width="([\d.]+)"',
            overlay,
        )
        self.assertIsNotNone(line)
        self.assertIsNotNone(marker)
        self.assertIsNotNone(badge)
        badge_right = float(badge[1]) + float(badge[2]) + float(badge[3]) / 2
        arrowhead_start = float(line[1]) - float(marker[1])
        self.assertGreater(arrowhead_start, badge_right)

    def test_visual_evidence_rejects_out_of_range_arrows_and_changed_capture_digests(self):
        path, ledger = self.create_ledger()
        visual_ref = self.add_visual_evidence(ledger)
        self.rewrite_json_artifact(ledger, visual_ref, lambda data: (
            data["changes"][0]["after"]["end"].update({"x": 1.01})
        ))
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "invalid normalized after end"):
            ITERATIONS.verify(path)

        path, ledger = self.create_ledger()
        self.add_visual_evidence(ledger)
        capture = ledger["artifacts"]["attempt-1/before.png"]
        capture_path = self.root / capture["path"]
        capture_path.write_bytes(self.png_capture((90, 90, 90, 255)))
        capture["sha256"] = hashlib.sha256(capture_path.read_bytes()).hexdigest()
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "capture digests do not match"):
            ITERATIONS.verify(path)

    def test_visual_evidence_rejects_corrupt_png_chunks_even_when_rehashed(self):
        path, ledger = self.create_ledger()
        visual_ref = self.add_visual_evidence(ledger)
        capture_ref = "attempt-1/before.png"
        capture = ledger["artifacts"][capture_ref]
        capture_path = self.root / capture["path"]
        corrupted = bytearray(capture_path.read_bytes())
        corrupted[24] ^= 1
        capture_path.write_bytes(corrupted)
        capture["sha256"] = hashlib.sha256(corrupted).hexdigest()
        self.rewrite_json_artifact(ledger, visual_ref, lambda data: data.update({
            "before_capture_sha256": capture["sha256"],
        }))
        self.refresh_decision(ledger)
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ITERATIONS.LedgerError, "corrupt PNG chunk"):
            ITERATIONS.verify(path)

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
        html_path = self.root / "attempt-report.html"
        rendered = subprocess.run(
            [sys.executable, str(script), "html", str(path),
             "--attempt", "1", "--output", str(html_path)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("HTML report written to", rendered.stdout)
        document = html_path.read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", document)
        self.assertIn("No captures or annotations were supplied", document)
        original_ledger = path.read_bytes()
        collision = subprocess.run(
            [sys.executable, str(script), "html", str(path), "--output", str(path)],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("must not overwrite", collision.stderr)
        self.assertEqual(path.read_bytes(), original_ledger)

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
        visual_ref = attempt.get("visual_ref")
        if visual_ref is None:
            record.pop("visual_ref", None)
            record.pop("visual_sha256", None)
        else:
            record["visual_ref"] = visual_ref
            record["visual_sha256"] = ledger["artifacts"][visual_ref]["sha256"]
        if ledger.get("format_version") == 2:
            record["attempt_summary"] = {
                key: attempt[key] for key in (
                    "expected_outcomes", "actual_outcomes", "actual_evidence",
                    "affected_points", "dependencies", "guardrails", "regressions",
                    "effort_minutes", "decision_actor", "decision_records",
                )
            }
            if visual_ref is not None:
                record["attempt_summary"].update({
                    "visual_ref": visual_ref,
                    "visual_sha256": ledger["artifacts"][visual_ref]["sha256"],
                })
            if ledger["contract"].get("keep_rule"):
                paired_ref = attempt["paired_scores_ref"]
                record["attempt_summary"].update({
                    "keep_rule": ledger["contract"]["keep_rule"],
                    "paired_scores_ref": paired_ref,
                    "paired_scores_sha256": ledger["artifacts"][paired_ref]["sha256"],
                })
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
