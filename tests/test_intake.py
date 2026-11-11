"""Scope-intake gate regression cases, using only synthetic local evidence."""

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "scope_intake", ROOT / ".github/skills/ui-prototype-council/intake.py")
INTAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTAKE)


class ScopeIntakeTest(unittest.TestCase):
    def setUp(self):
        self.brief = json.loads(
            (ROOT / "docs/examples/concept-exploration/project-intake-v2.json").read_text())

    def test_exact_gate_messages(self):
        cases = [
            ("scope_unconfirmed", lambda b: b["intake"]["scope"].pop("sponsor_confirmation"),
             "Scope level or sponsor confirmation missing. Generation blocked."),
            ("keep_list_missing", lambda b: b["intake"].pop("keep"),
             "No KEEP/CHANGE/DROP list (or explicit 'none' with reason). Directions must state a disposition per keep item."),
            ("scope_question_parked", lambda b: b.update(unresolved_questions=[
                {"id": "job", "topic": "primary_job", "blocks": "nothing"}]),
             "Question job concerns scope or primary job and cannot be marked 'blocks nothing'."),
        ]
        for code, mutate, message in cases:
            with self.subTest(code=code):
                brief = copy.deepcopy(self.brief)
                mutate(brief)
                self.assertIn({"code": code, "severity": "blocker", "message": message},
                              INTAKE.validate(brief)["findings"])
        view_id = next(v["id"] for v in self.brief["intake"]["views"] if v["disposition"] == "in")
        report = INTAKE.validate(self.brief, directions=[
            {"id": "missing", "view_coverage": [], "keep_dispositions": []}])
        self.assertIn({"code": "scope_coverage", "severity": "blocker",
                       "message": f"In-scope view {view_id} is not covered and has no sponsor-signed deferral."},
                      report["findings"])

    def test_byte_identical_prior_requires_reconfirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            raw = json.dumps(self.brief).encode()
            path.write_bytes(raw)
            self.brief["intake"]["prior_briefs"] = [{
                "id": "old", "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "round": 4, "purpose": "page refinement",
                "date": "2026-11-11", "confirmation_ref": "scope-approval"}]
            report = INTAKE.validate(self.brief, current_brief_path=path)
            self.assertIn({
                "code": "brief_stale", "severity": "blocker",
                "message": "Brief old is identical to round 4's brief written for page refinement. Sponsor must reconfirm scope before reuse."},
                report["findings"])
            edited = Path(directory) / "edited.json"
            edited.write_text(json.dumps(self.brief, indent=4))
            self.assertIn("brief_stale", {
                f["code"] for f in INTAKE.validate(self.brief, current_brief_path=edited)["findings"]})

    def test_untyped_input_is_blocked_without_crashing(self):
        for parent, key, value in [
            ("scope", "level", []), ("scope", "stage", {}), ("scope", "decision_id", []),
            ("sponsor_confirmation", "source_ref", []),
            ("intake", "journeys", [{"id": "bad", "view_ids": [["bad"]]}]),
            ("intake", "artifacts", [{"path": "opaque", "data_class": []}]),
            ("intake", "prior_briefs", [{"id": "old", "sha256": [], "round": 1, "purpose": "test"}]),
            ("intake", "views", [{"id": "bad", "disposition": []}]),
            ("intake", "claim_level", "product"),
        ]:
            with self.subTest(parent=parent, key=key):
                brief = copy.deepcopy(self.brief)
                target = brief["intake"]
                if parent == "scope":
                    target = target["scope"]
                elif parent == "sponsor_confirmation":
                    target = target["scope"]["sponsor_confirmation"]
                target[key] = value
                self.assertTrue(INTAKE.validate(brief)["findings"])
        for direction in [
            {"id": "bad", "view_coverage": [{"view_id": [], "status": "covered"}]},
            {"id": "bad", "view_coverage": [{"view_id": self.brief["intake"]["views"][0]["id"],
                                           "status": [], "evidence_refs": [{}]}]},
            {"id": "bad", "keep_dispositions": [{"id": "bad", "disposition": [],
                                                "evidence_refs": [[]]}]},
        ]:
            self.assertTrue(INTAKE.validate(self.brief, directions=[direction])["findings"])

    def test_repeated_journey_is_not_two_product_journeys(self):
        self.brief["intake"]["scope"]["level"] = "product"
        self.brief["intake"]["journeys"] = [
            {"id": "same", "view_ids": ["one", "two"]}] * 2
        codes = {f["code"] for f in INTAKE.validate(self.brief)["findings"]}
        self.assertIn("journeys_missing", codes)

    def test_inventory_and_shell_stage_require_explicit_sponsor_snapshot(self):
        self.brief["intake"]["views"].append({
            "id": "architecture", "disposition": "out", "reason": "Agent cut to P0."})
        self.assertIn("scope_unconfirmed", {
            f["code"] for f in INTAKE.validate(self.brief)["findings"]})
        self.brief["intake"]["scope"]["stage"] = "shell"
        self.assertIn("invalid_scope_stage", {
            f["code"] for f in INTAKE.validate(self.brief)["findings"]})

    def test_unmeasured_coverage_is_not_reported_as_zero(self):
        header = INTAKE.validate(self.brief)["scope_header"]
        self.assertIn("coverage not assessed", header)
        self.assertNotIn("covered 0/", header)

    def test_deferral_cannot_reuse_an_unrelated_sponsor_approval(self):
        direction = {"id": "deferred", "view_coverage": [{
            "view_id": "evidence", "status": "deferred", "deferral_decision_ref": "scope"}],
            "keep_dispositions": [{
                "id": "provenance", "disposition": "keep", "evidence_refs": ["synthetic-job-record"]}]}
        report = INTAKE.validate(self.brief, directions=[direction])
        self.assertIn("scope_coverage", {f["code"] for f in report["findings"]})
        self.brief["decision_authority"]["decisions"][0]["subject_ids"] = ["evidence"]
        report = INTAKE.validate(self.brief, directions=[direction])
        self.assertNotIn("scope_coverage", {f["code"] for f in report["findings"]})

    def test_declared_history_requires_reason_and_prior_provenance(self):
        self.brief["intake"].pop("prior_briefs_none_reason")
        self.assertIn("prior_brief_history_missing", {
            f["code"] for f in INTAKE.validate(self.brief)["findings"]})
        prior = {"id": "old", "sha256": "a" * 64, "round": 1,
                 "purpose": "page refinement", "date": "2026-11-11",
                 "confirmation_ref": "scope-approval"}
        self.brief["intake"]["prior_briefs"] = [prior]
        for field in ("date", "confirmation_ref"):
            with self.subTest(field=field):
                value = prior.pop(field)
                self.assertIn("invalid_prior_briefs", {
                    f["code"] for f in INTAKE.validate(self.brief)["findings"]})
                prior[field] = value
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.json"
            path.write_text(json.dumps(self.brief, indent=4))
            report = INTAKE.validate(self.brief, current_brief_path=path)
            self.assertIn("prior_brief_unavailable", {f["code"] for f in report["findings"]})
