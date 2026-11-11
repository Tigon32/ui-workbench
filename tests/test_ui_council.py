"""Tests for .github/skills/ui-prototype-council/council.py.

The council's stop decision is arithmetic, not judgement, so it is tested like any
other gate: the refusals as well as the verdicts.
"""

import hashlib
import copy
import contextlib
import io
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "council", ROOT / ".github/skills/ui-prototype-council/council.py")
COUNCIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COUNCIL)

ANCHORS = {"3": "poor", "5": "fair", "7": "good", "9": "excellent"}
RUBRIC = {
    "dimensions": [
        {"id": "honesty", "weight": 2, "critical": True, "anchors": ANCHORS},
        {"id": "craft", "weight": 1, "anchors": ANCHORS},
    ],
    "caps": {"max_rounds": 2, "max_reviewers": 3, "max_prototypes": 6},
    "calibration_margin": 2.0,
}
REASON = "a reason long enough to count as one"


def sheet(reviewer, order, scores):
    return {"reviewer": reviewer, "model": "m", "seed": 1, "order": order,
            "scores": {item: {"honesty": {"why": REASON, "score": h},
                              "craft": {"why": REASON, "score": c}}
                       for item, (h, c) in scores.items()}}


class CouncilTest(unittest.TestCase):
    def make(self, rounds, rubric=RUBRIC):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        run = Path(temp.name)
        (run / "rubric.json").write_text(json.dumps(rubric))
        for number, (meta, sheets) in enumerate(rounds, start=1):
            folder = run / f"round-{number}"
            folder.mkdir()
            meta = {"round": number, "model": "m", "browser": "b", "date": "d", **meta}
            (folder / "round.json").write_text(json.dumps(meta))
            for data in sheets:
                (folder / f"reviewer-{data['reviewer']}.json").write_text(json.dumps(data))
        return run

    def round_of(self, scores_by_reviewer, items=("A", "B", "C", "W", "S")):
        meta = {"items": list(items), "calibration": {"weak": "W", "strong": "S"},
                "reveal": {i: f"p-{i}" for i in items}}
        sheets = []
        for index, scores in enumerate(scores_by_reviewer):
            order = list(items[index:] + items[:index])
            sheets.append(sheet(f"r{index}", order, scores))
        return meta, sheets

    def verdict(self, run):
        COUNCIL.run(run, write=True)
        return COUNCIL.run(run, write=False)

    def test_incomplete_calibration_names_unscored_dimensions(self):
        incomplete = sheet(
            "r1", ["A", "B", "W", "S"],
            {"A": (8, 8), "B": (7, 7), "W": (2, 2), "S": (9, 9)})
        incomplete["reviewer_kind"] = "model"
        incomplete["scores"]["W"]["honesty"] = {
            "why": "The capture does not establish this criterion.",
            "score": None, "evidence_status": "not_assessed", "evidence": [],
        }
        reason = COUNCIL.calibration_exclusion_reason(
            incomplete, "W", "S", RUBRIC["dimensions"])
        self.assertEqual(reason, "incomplete calibration (weak: honesty)")

    def test_clear_lead_on_critical_dimensions_wins(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))

    def test_scope_report_is_bound_to_intake_and_separate_from_craft(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        example = ROOT / "docs/examples/concept-exploration"
        brief = json.loads((example / "project-intake-v2.json").read_text())
        direction = json.loads((example / "exploration.json").read_text())["directions"][0]
        directions = [{**direction, "id": f"p-{name}"} for name in ("A", "B", "C")]
        manifest = {}
        for key, data in (("brief", brief), ("directions", directions)):
            path = run / f"{key}.json"
            path.write_text(json.dumps(data))
            manifest[f"project/{key}"] = {
                "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        meta_path = run / "round-1/round.json"
        meta = json.loads(meta_path.read_text())
        meta.update({"evidence_manifest": manifest,
                     "scope_refs": {"brief": "project/brief", "directions": "project/directions"}})
        meta_path.write_text(json.dumps(meta))
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))
        rendered = (run / "round-1/report.md").read_text()
        self.assertIn("Scope: page", rendered)
        self.assertIn("covered 1/1", rendered)
        self.assertIn("separate from craft", rendered)
        (run / "brief.json").write_text("{}")
        with self.assertRaisesRegex(COUNCIL.RunError, "digest changed"):
            COUNCIL.run(run, write=True)

    def test_lead_inside_disagreement_continues_and_eliminates(self):
        one = {"A": (8, 8), "B": (7, 7), "C": (3, 3), "W": (2, 2), "S": (9, 9)}
        two = {"A": (6, 6), "B": (7, 7), "C": (3, 3), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([one, two])])
        status, kept = self.verdict(run)
        self.assertEqual(status, "CONTINUE")
        self.assertEqual(sorted(kept), ["p-A", "p-B"])
        self.assertIn("p-C", (run / "round-1/report.md").read_text())

    def test_reviewer_that_cannot_separate_calibration_is_excluded(self):
        good = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        blind = {"A": (1, 1), "B": (9, 9), "C": (9, 9), "W": (8, 8), "S": (8, 8)}
        run = self.make([self.round_of([good, good, blind])])
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))
        self.assertIn("| r2 | 8.00 | 8.00 | 0.00 | excluded |",
                      (run / "round-1/report.md").read_text())

    def test_too_few_calibrated_reviewers_voids_the_round(self):
        blind = {"A": (9, 9), "B": (5, 5), "C": (5, 5), "W": (8, 8), "S": (8, 8)}
        run = self.make([self.round_of([blind, blind])])
        self.assertEqual(self.verdict(run), ("VOID", []))

    def test_last_round_without_a_clear_lead_reports_no_clear_winner(self):
        tied = {"A": (7, 7), "B": (7, 7), "W": (2, 2), "S": (9, 9)}
        first = self.round_of([tied, tied], items=("A", "B", "W", "S"))
        second = self.round_of([tied, tied], items=("A", "B", "W", "S"))
        run = self.make([first, second])
        self.assertEqual(self.verdict(run), ("NO_CLEAR_WINNER", []))

    def test_refusals(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        meta, sheets = self.round_of([scores, scores])
        cases = {
            "same order": lambda m, s: s[1].update(order=s[0]["order"]),
            "score first": lambda m, s: s[0]["scores"]["A"].update(
                honesty={"score": 9, "why": REASON}),
            "short reason": lambda m, s: s[0]["scores"]["A"]["honesty"].update(why="ok"),
            "missing browser": lambda m, s: m.update(browser=""),
            "eliminated item returns": None,
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                m, s = json.loads(json.dumps(meta)), json.loads(json.dumps(sheets))
                if mutate:
                    mutate(m, s)
                    run = self.make([(m, s)])
                else:
                    drop = {"A": (8, 8), "B": (7, 7), "C": (3, 3), "W": (2, 2), "S": (9, 9)}
                    swing = {"A": (6, 6), "B": (7, 7), "C": (3, 3), "W": (2, 2), "S": (9, 9)}
                    later = self.round_of([drop, swing], items=("A", "C", "W", "S"))
                    run = self.make([self.round_of([drop, swing]), later])
                with self.assertRaises(COUNCIL.RunError):
                    COUNCIL.run(run, write=True)

    def test_rules_v2_keeps_items_within_noise_of_the_cut(self):
        rubric = {**RUBRIC, "rules_version": 2}
        one = {"A": (9, 9), "B": (7, 7), "C": (7, 6), "W": (2, 2), "S": (9, 9)}
        two = {"A": (9, 9), "B": (7, 7), "C": (7, 8), "W": (2, 2), "S": (9, 9)}
        meta, sheets = self.round_of([one, two])
        meta["keep"] = 2
        run = self.make([(meta, sheets)], rubric)
        # Without the rule, A is a clear winner on critical scores; make it not so.
        status, kept = self.verdict(run)
        self.assertEqual(status, "WINNER")
        one["A"], two["A"] = (7, 8), (7, 6)
        meta, sheets = self.round_of([one, two])
        meta["keep"] = 2
        run = self.make([(meta, sheets)], rubric)
        status, kept = self.verdict(run)
        self.assertEqual(status, "CONTINUE")
        self.assertEqual(sorted(kept), ["p-A", "p-B", "p-C"])

    def test_rules_v2_shared_top_score_is_a_tie_not_a_loss(self):
        rubric = {**RUBRIC, "rules_version": 2}
        one = {"A": (9, 9), "B": (9, 4), "C": (8, 4), "W": (2, 2), "S": (9, 9)}
        two = {"A": (9, 9), "B": (8, 4), "C": (8, 4), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([one, two])], rubric)
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))
        run = self.make([self.round_of([one, two])])
        self.assertEqual(self.verdict(run)[0], "CONTINUE")

    def test_edited_report_fails_verification(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        COUNCIL.run(run, write=True)
        report = run / "round-1/report.md"
        report.write_text(report.read_text().replace("WINNER", "WINNER (edited)"))
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.run(run, write=False)

    def _scoped_round(self, run, items=("A", "B", "C"), contract="scoped_v1",
                       with_scope_refs=True, with_design=True):
        """Shared setup mirroring test_scope_report_is_bound_to_intake_and_
        separate_from_craft, additionally marking the round scope_contract=
        scoped_v1 (or another value under test) and binding DESIGN.md evidence
        for every item, as required of any marked round."""
        example = ROOT / "docs/examples/concept-exploration"
        brief = json.loads((example / "project-intake-v2.json").read_text())
        direction = json.loads((example / "exploration.json").read_text())["directions"][0]
        directions = [{**direction, "id": f"p-{name}"} for name in items]
        meta_path = run / "round-1/round.json"
        meta = json.loads(meta_path.read_text())
        manifest = {}
        if with_scope_refs:
            for key, data in (("brief", brief), ("directions", directions)):
                path = run / f"{key}.json"
                path.write_text(json.dumps(data))
                manifest[f"project/{key}"] = {
                    "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            meta["scope_refs"] = {"brief": "project/brief", "directions": "project/directions"}
        if with_design:
            design = run / "DESIGN.md"
            design.write_text("# Design\n\nSynthetic design rationale for tests.\n")
            digest = hashlib.sha256(design.read_bytes()).hexdigest()
            for item in meta["items"]:
                manifest[f"{item}/DESIGN.md"] = {"path": str(design), "sha256": digest}
        meta["evidence_manifest"] = manifest
        if contract is not None:
            meta["scope_contract"] = contract
        meta_path.write_text(json.dumps(meta))

    def test_scope_contract_rejects_unsupported_value(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run, contract="scoped_v2")
        with self.assertRaisesRegex(COUNCIL.RunError, "unsupported scope_contract"):
            COUNCIL.run(run, write=True)

    def test_scoped_v1_without_scope_refs_fails_instead_of_becoming_legacy(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run, with_scope_refs=False)
        with self.assertRaisesRegex(COUNCIL.RunError, "scoped_v1 requires scope_refs"):
            COUNCIL.run(run, write=True)

    def test_legacy_unscoped_marker_rejects_scope_refs(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run, contract="legacy_unscoped")
        with self.assertRaisesRegex(COUNCIL.RunError, "legacy_unscoped must not declare scope_refs"):
            COUNCIL.run(run, write=True)

    def test_scoped_v1_requires_design_md_for_every_item(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run, with_design=False)
        with self.assertRaisesRegex(COUNCIL.RunError, "DESIGN.md evidence is required"):
            COUNCIL.run(run, write=True)

    def test_scoped_v1_marked_round_wins_with_scope_refs_and_design_md(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run)
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))

    def test_declared_legacy_unscoped_round_reports_a_compatibility_marker_line(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self._scoped_round(run, contract="legacy_unscoped", with_scope_refs=False)
        self.verdict(run)
        rendered = (run / "round-1/report.md").read_text()
        self.assertIn("Scope: legacy_unscoped (declared compatibility path).", rendered)

    def test_historically_unmarked_round_keeps_undeclared_legacy_wording(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self.verdict(run)
        rendered = (run / "round-1/report.md").read_text()
        self.assertIn("Scope: undeclared (legacy)", rendered)

    def test_reviewer_orders_enforces_the_assigned_order_per_reviewer(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        meta, sheets = self.round_of([scores, scores])
        meta["reviewer_orders"] = {"r0": list(sheets[0]["order"]), "r1": list(sheets[1]["order"])}
        run = self.make([(meta, sheets)])
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))
        meta_path = run / "round-1/round.json"
        stored = json.loads(meta_path.read_text())
        stored["reviewer_orders"]["r1"] = list(reversed(stored["reviewer_orders"]["r1"]))
        meta_path.write_text(json.dumps(stored))
        with self.assertRaisesRegex(COUNCIL.RunError, "did not review in its assigned order"):
            COUNCIL.run(run, write=True)

    def test_reviewer_orders_absent_preserves_the_old_distinctness_only_check(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        meta, sheets = self.round_of([scores, scores])
        sheets[1]["order"] = list(sheets[0]["order"])
        run = self.make([(meta, sheets)])
        with self.assertRaisesRegex(COUNCIL.RunError, "reviewers must see different shuffled orders"):
            COUNCIL.run(run, write=True)


class SkillDigestTest(unittest.TestCase):
    def test_skill_pins_every_bundled_script(self):
        folder = ROOT / ".github/skills/ui-prototype-council"
        table = dict(re.findall(r"\| `([a-z_]+\.py)` \| `([0-9a-f]{64})` \|",
                                (folder / "SKILL.md").read_text(encoding="utf-8")))
        scripts = sorted(p.name for p in folder.glob("*.py"))
        self.assertEqual(sorted(table), scripts)
        for name, digest in table.items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)

    def test_skill_pins_the_default_catalogue(self):
        folder = ROOT / ".github/skills/ui-prototype-council"
        asset = folder / "rubric-default.json"
        self.assertIn(f"| `rubric-default.json` | `{hashlib.sha256(asset.read_bytes()).hexdigest()}` |",
                      (folder / "SKILL.md").read_text())


class AdoptionTest(unittest.TestCase):
    make = CouncilTest.make
    verdict = CouncilTest.verdict

    def rubric(self):
        return json.loads((ROOT / ".github/skills/ui-prototype-council/rubric-default.json").read_text())

    def adoption_run(self, values=(8, 8), mutate=None):
        rubric = self.rubric()
        rubric["adoption_gate"] = {"total_min": 75, "every_dimension_min": 5, "critical_min": 7}
        rubric["adoption_decision"] = "Synthetic arithmetic thresholds for these tests, not approved project policy."
        dims = rubric["dimensions"]
        items = ("A", "B", "W", "S")
        meta = {"items": list(items), "calibration": {"weak": "W", "strong": "S"},
                "reveal": {i: f"p-{i}" for i in items}}
        sheets = []
        for index, score in enumerate(values):
            scores = {}
            for item, value in (("A", score), ("B", 5), ("W", 2), ("S", 9)):
                scores[item] = {d["id"]: {"why": REASON, "score": value,
                                        "evidence_status": "observed",
                                        "evidence": [f"{item}/capture"]}
                                for d in dims}
            sheets.append({"reviewer": f"r{index}", "reviewer_kind": "model", "model": "m",
                           "seed": index, "order": list(items[index:] + items[:index]),
                           "scores": scores})
        if mutate:
            mutate(rubric, meta, sheets)
        run = self.make([(meta, sheets)], rubric)
        folder = run / "round-1"
        capture = folder / "synthetic-evidence.txt"
        capture.write_text("Synthetic test evidence, not a real rendered observation.")
        stored = json.loads((folder / "round.json").read_text())
        target_profiles = {
            "decision": rubric["target_platform_decision"],
            "profiles": {"laptop": 1280, "desktop": 1920, "wide": 2560},
            "widths": [1280, 1920, 2560],
            "reflow": {"width": 320, "label": "zoom/reflow (not phone)"},
            "quality_checks": {"semantic_control_parity": True},
        }
        if "desktop_zoom" in rubric:
            target_profiles["desktop_zoom"] = {
                "percentages": rubric["desktop_zoom"]["percentages"],
                "evidence_type": "real_browser_zoom",
                "status": "unavailable",
                "reason": "The bundled renderer does not control or verify browser zoom.",
            }
        stored.update(
            evidence_manifest={
                f"{item}/capture": {
                    "path": capture.name,
                    "sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
                }
                for item in items
            },
            source_sha256={item: "a" * 64 for item in items},
            rubric_sha256=hashlib.sha256((run / "rubric.json").read_bytes()).hexdigest(),
            adoption_checks={item: {tier: {"status": "pass", "evidence": [f"{item}/capture"]}
                                   for tier in ("tier1", "tier2")} for item in items},
            target_profiles=target_profiles,
        )
        (folder / "round.json").write_text(json.dumps(stored))
        return run

    def report(self, run):
        self.verdict(run)
        return (run / "round-1/report.md").read_text()

    def _mark_scoped_v1(self, run):
        """Bind the minimal scope_refs + DESIGN.md evidence a scoped_v1 marker
        requires, on top of adoption_run()'s fixture, so typed-tier-evidence
        gating (forced for any scoped_v1 round, with or without
        adoption_evidence_version) can be exercised directly."""
        folder = run / "round-1"
        meta_path = folder / "round.json"
        meta = json.loads(meta_path.read_text())
        contestants = [i for i in meta["items"]
                       if i not in (meta["calibration"]["weak"], meta["calibration"]["strong"])]
        example = ROOT / "docs/examples/concept-exploration"
        brief = json.loads((example / "project-intake-v2.json").read_text())
        direction = json.loads((example / "exploration.json").read_text())["directions"][0]
        directions = [{**direction, "id": meta["reveal"][name]} for name in contestants]
        manifest = meta["evidence_manifest"]
        for key, data in (("brief", brief), ("directions", directions)):
            path = run / f"{key}.json"
            path.write_text(json.dumps(data))
            manifest[f"project/{key}"] = {
                "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        design = run / "DESIGN.md"
        design.write_text("# Design\n\nSynthetic design rationale for tests.\n")
        design_digest = hashlib.sha256(design.read_bytes()).hexdigest()
        for item in meta["items"]:
            manifest[f"{item}/DESIGN.md"] = {"path": str(design), "sha256": design_digest}
        meta["evidence_manifest"] = manifest
        meta["scope_refs"] = {"brief": "project/brief", "directions": "project/directions"}
        meta["scope_contract"] = "scoped_v1"
        meta_path.write_text(json.dumps(meta))
        return meta

    def _render_check_report(self, run, item, tier2=("pass", []), source_sha256=None,
                              source_tree_sha256=None, rubric_sha256=None, omit_rubric=False):
        """Write a typed render_check --report document (tier2 only, per the
        Issue 13 P4 final ruling: the renderer records only real tier2 render
        checks) into the run folder and bind it into item's evidence_manifest
        as f"{item}/render-report", returning the ref. Defaults the report's
        rubric_sha256 to the round's declared one so callers that don't care
        about rubric binding get a report that matches by default."""
        folder = run / "round-1"
        meta = json.loads((folder / "round.json").read_text())
        page = {
            "page": f"{item}/index.html",
            "source_sha256": source_sha256 if source_sha256 is not None else meta["source_sha256"][item],
            "tier2": {"status": tier2[0],
                      "findings": None if tier2[1] is None else list(tier2[1])},
        }
        if source_tree_sha256 is not None:
            page["source_tree_sha256"] = source_tree_sha256
        report = {"schema_version": 1, "kind": "render_check", "pages": [page]}
        if not omit_rubric:
            report["rubric_sha256"] = rubric_sha256 if rubric_sha256 is not None else meta.get("rubric_sha256")
        path = folder / f"{item}-render-check.json"
        path.write_text(json.dumps(report))
        ref = f"{item}/render-report"
        meta["evidence_manifest"][ref] = {
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (folder / "round.json").write_text(json.dumps(meta))
        return ref

    def _static_check_report(self, run, item, tier1=("pass", []), source_sha256=None,
                              source_tree_sha256=None, tool=("eslint-a11y", "1.2.3"),
                              omit_tier1=False):
        """Write a typed project_static_check tier1 report (flat, not nested
        under "pages") into the run folder and bind it into item's
        evidence_manifest as f"{item}/static-report", returning the ref."""
        folder = run / "round-1"
        meta = json.loads((folder / "round.json").read_text())
        report = {
            "schema_version": 1, "kind": "project_static_check",
            "source_sha256": source_sha256 if source_sha256 is not None else meta["source_sha256"][item],
            "tool": {"name": tool[0], "version": tool[1]} if tool is not None else {},
        }
        if source_tree_sha256 is not None:
            report["source_tree_sha256"] = source_tree_sha256
        if not omit_tier1:
            report["tier1"] = {"status": tier1[0], "findings": list(tier1[1])}
        path = folder / f"{item}-static-check.json"
        path.write_text(json.dumps(report))
        ref = f"{item}/static-report"
        meta["evidence_manifest"][ref] = {
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (folder / "round.json").write_text(json.dumps(meta))
        return ref

    def _set_adoption_evidence(self, run, item, tier1_ref=None, tier2_ref=None):
        folder = run / "round-1"
        stored = json.loads((folder / "round.json").read_text())
        if tier1_ref is not None:
            stored["adoption_checks"][item]["tier1"] = {"status": "pass", "evidence": [tier1_ref]}
        if tier2_ref is not None:
            stored["adoption_checks"][item]["tier2"] = {"status": "pass", "evidence": [tier2_ref]}
        (folder / "round.json").write_text(json.dumps(stored))

    def test_scoped_v1_forces_typed_tier_evidence_even_without_adoption_evidence_version(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        # adoption_checks still reference the plain screenshot capture, and no
        # adoption_evidence_version is set anywhere: the P4 bypass this closes.
        report = self.report(run)
        self.assertIn(
            "tier1 evidence must be a typed project_static_check report, not a screenshot reference", report)
        self.assertIn(
            "tier2 evidence must be a typed render_check report, not a screenshot reference", report)
        self.assertIn("NOT_ADOPTABLE", report)

    def test_scoped_v1_accepts_matching_typed_tier1_and_tier2_reports_as_adoption_evidence(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        for item in json.loads((run / "round-1/round.json").read_text())["items"]:
            tier1_ref = self._static_check_report(run, item)
            tier2_ref = self._render_check_report(run, item)
            self._set_adoption_evidence(run, item, tier1_ref=tier1_ref, tier2_ref=tier2_ref)
        report = self.report(run)
        self.assertIn("| A | 77.78 | ADOPTABLE |", report)

    def test_static_tier1_rejects_a_render_check_report_as_wrong_kind(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._render_check_report(run, "A")
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn(
            "tier1 evidence must be a typed project_static_check report, not a screenshot reference "
            "or wrong report kind", report)

    def test_render_tier2_rejects_a_static_check_report_as_wrong_kind(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(run, "A")
        self._set_adoption_evidence(run, "A", tier2_ref=ref)
        report = self.report(run)
        self.assertIn(
            "tier2 evidence must be a typed render_check report, not a screenshot reference "
            "or wrong report kind", report)

    def test_static_tier1_rejects_missing_tier1_block(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(run, "A", omit_tier1=True)
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn("tier1 evidence report has no valid tier1 status", report)

    def test_static_tier1_requires_tool_provenance(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(run, "A", tool=None)
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn(
            "tier1 evidence report is missing tool provenance (name plus version, command, or config)", report)

    def test_static_tier1_rejects_blocker_findings_even_when_status_claims_pass(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(
            run, "A", tier1=("pass", [{"severity": "blocker", "message": "contrast too low"}]))
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn("tier1 evidence report status contradicts its own blocker findings", report)

    def test_static_tier1_allows_review_findings_alongside_a_genuine_pass(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        for item in json.loads((run / "round-1/round.json").read_text())["items"]:
            tier1_ref = self._static_check_report(
                run, item, tier1=("pass", [{"severity": "review", "message": "consider tightening spacing"}]))
            tier2_ref = self._render_check_report(run, item)
            self._set_adoption_evidence(run, item, tier1_ref=tier1_ref, tier2_ref=tier2_ref)
        report = self.report(run)
        self.assertIn("| A | 77.78 | ADOPTABLE |", report)

    def test_static_tier1_rejects_malformed_findings(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(
            run, "A", tier1=("pass", [{"severity": "urgent", "message": "bad severity value"}]))
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn("tier1 evidence report has malformed findings", report)

    def test_scoped_v1_rejects_typed_tier_evidence_when_source_sha256_mismatched(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._static_check_report(run, "A", source_sha256="f" * 64)
        self._set_adoption_evidence(run, "A", tier1_ref=ref)
        report = self.report(run)
        self.assertIn("tier1 evidence report does not match this item's source_sha256", report)

    def test_scoped_v1_rejects_typed_tier_evidence_when_source_tree_sha256_declared_and_mismatched(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        folder = run / "round-1"
        stored = json.loads((folder / "round.json").read_text())
        stored["source_tree_sha256"] = {item: "b" * 64 for item in stored["items"]}
        (folder / "round.json").write_text(json.dumps(stored))
        tier1_ref = self._static_check_report(run, "A", source_tree_sha256="c" * 64)
        tier2_ref = self._render_check_report(run, "A", source_tree_sha256="c" * 64)
        self._set_adoption_evidence(run, "A", tier1_ref=tier1_ref, tier2_ref=tier2_ref)
        report = self.report(run)
        self.assertIn("evidence report does not match this item's source_tree_sha256", report)

    def test_render_tier2_rejects_rubric_sha256_mismatch(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._render_check_report(run, "A", rubric_sha256="e" * 64)
        self._set_adoption_evidence(run, "A", tier2_ref=ref)
        report = self.report(run)
        self.assertIn("tier2 evidence report does not match this round's rubric_sha256", report)

    def test_render_tier2_rejects_missing_rubric_sha256_when_round_declares_one(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._render_check_report(run, "A", omit_rubric=True)
        self._set_adoption_evidence(run, "A", tier2_ref=ref)
        report = self.report(run)
        self.assertIn("tier2 evidence report does not match this round's rubric_sha256", report)

    def test_render_tier2_requires_an_explicit_empty_findings_list(self):
        run = self.adoption_run()
        self._mark_scoped_v1(run)
        ref = self._render_check_report(run, "A", tier2=("pass", None))
        self._set_adoption_evidence(run, "A", tier2_ref=ref)
        self.assertIn("tier2 evidence report does not show a clean pass", self.report(run))

    def test_a_newly_created_legacy_unscoped_round_cannot_pass_on_old_handwritten_evidence(self):
        # Per the judge's final selection review: typed adoption evidence is
        # now forced for ANY round carrying a scope_contract key, including the
        # legacy_unscoped compatibility marker, not only scoped_v1. A new round
        # cannot opt into the "legacy" marker and then keep passing on a plain
        # screenshot capture the way historically-unmarked rounds still can.
        run = self.adoption_run()
        folder = run / "round-1"
        stored = json.loads((folder / "round.json").read_text())
        design = run / "DESIGN.md"
        design.write_text("# Design\n\nSynthetic design rationale for tests.\n")
        design_digest = hashlib.sha256(design.read_bytes()).hexdigest()
        for item in stored["items"]:
            stored["evidence_manifest"][f"{item}/DESIGN.md"] = {"path": str(design), "sha256": design_digest}
        stored["scope_contract"] = "legacy_unscoped"
        (folder / "round.json").write_text(json.dumps(stored))
        report = self.report(run)
        self.assertIn(
            "tier1 evidence must be a typed project_static_check report, not a screenshot reference", report)
        self.assertIn("NOT_ADOPTABLE", report)

    def test_capture_truncations_refuses_the_whole_run_not_just_the_flagged_item(self):
        # round_prep persists capture_truncations to round.json before exiting
        # nonzero on a clamped full-page screenshot; the council must never
        # adopt a round built on a truncated capture, so it refuses the run
        # outright rather than silently scoring around the flagged item.
        run = self.adoption_run()
        folder = run / "round-1"
        stored = json.loads((folder / "round.json").read_text())
        stored["capture_truncations"] = [{"item": "A", "path": "A/capture.png", "height": 6000}]
        (folder / "round.json").write_text(json.dumps(stored))
        with self.assertRaisesRegex(COUNCIL.RunError, "capture_truncations is non-empty"):
            COUNCIL.run(run, write=True)

    def test_historically_unmarked_round_adds_a_nonblocking_self_declared_note_without_flipping_outcome(self):
        # A round with no scope_contract key at all is the one case that keeps
        # its pre-Issue-13 loose, self-declared tier outcome; the new note is
        # purely informational and must not change ADOPTABLE/NOT_ADOPTABLE.
        run = self.adoption_run()
        self.assertNotIn("scope_contract", json.loads((run / "round-1/round.json").read_text()))
        report = self.report(run)
        self.assertIn("| A | 77.78 | ADOPTABLE |", report)
        self.assertIn("tier checks self-declared (legacy binding)", report)

    def test_source_tree_sha256_must_identify_every_item_when_present(self):
        run = self.adoption_run()
        folder = run / "round-1"
        stored = json.loads((folder / "round.json").read_text())
        stored["source_tree_sha256"] = {"A": "a" * 64}
        (folder / "round.json").write_text(json.dumps(stored))
        with self.assertRaisesRegex(COUNCIL.RunError, "source_tree_sha256 must identify every item"):
            COUNCIL.run(run, write=True)

    def test_default_catalogue_has_explicit_categories_and_total_weight_100(self):
        rubric = self.rubric()
        dims = COUNCIL.check_rubric(rubric)
        self.assertEqual(len(dims), 23)
        self.assertEqual(sum(d["weight"] for d in dims), 100)
        self.assertNotIn("adoption_gate", rubric)
        self.assertEqual(COUNCIL.design_total(1), 0)
        self.assertEqual(COUNCIL.design_total(10), 100)

    def test_complete_strong_design_reports_adoption_categories_groups_and_total(self):
        report = self.report(self.adoption_run())
        self.assertIn("| A | 77.78 | ADOPTABLE |", report)
        self.assertIn("| A | visual | typography | 8.00 | 77.78 | 5 |", report)
        self.assertIn("| A | visual | 77.78 |", report)
        self.assertIn("WINNER p-A", report)

    def test_declared_real_zoom_blocks_adoption_without_separately_verified_evidence(self):
        def mutate(rubric, meta, sheets):
            rubric["desktop_zoom"] = {"percentages": [100, 125, 150, 200]}
        report = self.report(self.adoption_run(mutate=mutate))
        self.assertIn("real desktop zoom evidence is unavailable or unverified", report)
        self.assertIn("NOT_ADOPTABLE", report)

    def test_css_viewport_evidence_cannot_be_relabelled_as_real_browser_zoom(self):
        run = self.adoption_run()
        rubric_path = run / "rubric.json"
        rubric = json.loads(rubric_path.read_text())
        rubric["desktop_zoom"] = {"percentages": [100, 125, 150, 200]}
        rubric_path.write_text(json.dumps(rubric))
        round_path = run / "round-1/round.json"
        meta = json.loads(round_path.read_text())
        meta["rubric_sha256"] = hashlib.sha256(rubric_path.read_bytes()).hexdigest()
        meta["target_profiles"]["desktop_zoom"] = {
            "percentages": [100, 125, 150, 200],
            "evidence_type": "real_browser_zoom",
            "status": "unavailable",
            "reason": "The bundled renderer does not control or verify browser zoom.",
        }
        for item in meta["items"]:
            capture = meta["evidence_manifest"][f"{item}/capture"]
            meta["evidence_manifest"][f"{item}/css-viewport"] = {
                **capture, "evidence_type": "css_viewport",
                "percentages": [100, 125, 150, 200], "source_sha256": "a" * 64,
            }
        for item in meta["items"]:
            meta["adoption_checks"][item]["desktop_zoom"] = {
                "status": "pass", "evidence": [f"{item}/css-viewport"],
            }
        round_path.write_text(json.dumps(meta))
        report = self.report(run)
        self.assertIn("real desktop zoom evidence does not match the declared scope or source", report)

        meta = json.loads(round_path.read_text())
        for item in meta["items"]:
            meta["adoption_checks"][item]["desktop_zoom"] = {
                "status": "pass", "evidence": [[]],
            }
        round_path.write_text(json.dumps(meta))
        report = self.report(run)
        self.assertIn("real desktop zoom evidence is unavailable or unverified", report)

    def test_relative_winner_can_be_not_adoptable(self):
        report = self.report(self.adoption_run((7, 7)))
        self.assertIn("WINNER p-A", report)
        self.assertIn("| A | 66.67 | NOT_ADOPTABLE |", report)

    def test_ungated_catalogue_reports_scores_but_cannot_claim_adoption(self):
        run = self.adoption_run(mutate=lambda rubric, meta, sheets: rubric.pop("adoption_gate"))
        report = self.report(run)
        self.assertIn("| A | 77.78 | NOT_ADOPTABLE |", report)
        self.assertIn("project adoption thresholds are not declared", report)
        self.assertIn("| A | visual | typography | 8.00 | 77.78 | 5 |", report)
        self.assertIn("| A | visual | 77.78 |", report)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(COUNCIL.main(["--verify", str(run), "--require-adoptable"]), 1)

    def test_high_total_does_not_hide_one_critical_reviewer_failure(self):
        def mutate(rubric, meta, sheets):
            sheets[0]["scores"]["A"]["accessibility"]["score"] = 6
        report = self.report(self.adoption_run((10, 10), mutate))
        self.assertIn("r0: accessibility below 7", report)
        self.assertIn("NOT_ADOPTABLE", report)
        self.assertIn("| A | 98.22 | NOT_ADOPTABLE |", report)

    def test_noncritical_dimension_floor_is_not_hidden_by_high_total(self):
        def mutate(rubric, meta, sheets):
            sheets[0]["scores"]["A"]["iconography"]["score"] = 4
        report = self.report(self.adoption_run((10, 10), mutate))
        self.assertIn("r0: iconography below 5", report)

    def test_unassessed_required_evidence_has_no_total_or_selection(self):
        def mutate(rubric, meta, sheets):
            sheets[0]["scores"]["A"]["motion"].update(score=None, evidence_status="not_assessed", evidence=[])
        run = self.adoption_run(mutate=mutate)
        report = self.report(run)
        self.assertIn("| A | unavailable | NOT_ADOPTABLE |", report)
        self.assertEqual(self.verdict(run), ("VOID", []))

    def test_generator_self_review_cannot_supply_a_council_vote(self):
        def mutate(rubric, meta, sheets):
            sheets[0]["reviewer_kind"] = "generator"
        run = self.adoption_run(mutate=mutate)
        self.assertEqual(self.verdict(run), ("VOID", []))
        self.assertIn("excluded: self-review", (run / "round-1/report.md").read_text())

    def test_failed_or_missing_gate_blocks_adoption_not_score(self):
        for check in (
            {"status": "fail", "evidence": ["A/capture"]},
            {"status": "unverified", "evidence": ["A/capture"]},
            {"status": None, "evidence": ["A/capture"]},
            {"status": "pass", "evidence": [{}]},
        ):
            with self.subTest(check=check):
                run = self.adoption_run()
                path = run / "round-1/round.json"
                meta = json.loads(path.read_text())
                meta["adoption_checks"]["A"]["tier2"] = check
                path.write_text(json.dumps(meta))
                report = self.report(run)
                self.assertIn("| A | 77.78 | NOT_ADOPTABLE |", report)
                self.assertIn("tier2 evidence is failed or unverified", report)

    def test_exclusions_must_be_declared_and_are_reported(self):
        rubric = self.rubric()
        omitted = rubric["dimensions"].pop()
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.check_rubric(rubric)
        def mutate(rubric, meta, sheets):
            entry = rubric["dimensions"].pop()
            rubric["excluded_dimensions"] = [{"id": entry["id"], "reason": REASON}]
            for sheet in sheets:
                for scores in sheet["scores"].values():
                    del scores[entry["id"]]
        report = self.report(self.adoption_run(mutate=mutate))
        self.assertIn(f"- text_resilience: {REASON}", report)
        rubric["excluded_dimensions"] = [{"id": omitted["id"], "reason": REASON}]
        COUNCIL.check_rubric(rubric)
        rubric["excluded_dimensions"].append(copy.deepcopy(rubric["excluded_dimensions"][0]))
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.check_rubric(rubric)

    def test_changed_rubric_and_evidence_refuse_stale_review(self):
        for changed in ("rubric", "evidence"):
            with self.subTest(changed=changed):
                run = self.adoption_run()
                target = run / "rubric.json" if changed == "rubric" else run / "round-1/synthetic-evidence.txt"
                target.write_text(target.read_text() + " ")
                with self.assertRaises(COUNCIL.RunError):
                    COUNCIL.run(run, write=True)

    def test_target_profile_evidence_cannot_silently_drop_declared_widths(self):
        run = self.adoption_run()
        path = run / "round-1/round.json"
        meta = json.loads(path.read_text())
        meta["target_profiles"]["widths"] = [1280]
        path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(COUNCIL.RunError, "target profile evidence"):
            COUNCIL.run(run, write=True)

    def test_invalid_evidence_and_unobserved_numeric_score_refuse(self):
        for change in (
            {"evidence": []},
            {"evidence": ["unknown"]},
            {"evidence_status": "unsupported"},
            {"score": True},
            {"score": 11},
        ):
            with self.subTest(change=change):
                def mutate(rubric, meta, sheets):
                    sheets[0]["scores"]["A"]["typography"].update(change)
                with self.assertRaises(COUNCIL.RunError):
                    self.verdict(self.adoption_run(mutate=mutate))

    def test_scoring_and_adoption_evidence_must_be_item_local(self):
        run = self.adoption_run()
        sheet_path = run / "round-1/reviewer-r0.json"
        sheet_data = json.loads(sheet_path.read_text())
        sheet_data["scores"]["A"]["typography"]["evidence"] = ["B/capture"]
        sheet_path.write_text(json.dumps(sheet_data))
        with self.assertRaisesRegex(COUNCIL.RunError, "invalid evidence status or references"):
            self.verdict(run)

        run = self.adoption_run()
        round_path = run / "round-1/round.json"
        meta = json.loads(round_path.read_text())
        meta["adoption_checks"]["A"]["tier1"]["evidence"] = ["B/capture"]
        round_path.write_text(json.dumps(meta))
        report = self.report(run)
        self.assertIn("tier1 evidence is failed or unverified", report)

    def test_nonfinite_bool_and_malformed_thresholds_refuse(self):
        for value in (float("nan"), float("inf"), True, -1, 101):
            with self.subTest(value=value):
                rubric = self.rubric()
                rubric["adoption_gate"] = {"total_min": value, "every_dimension_min": 5, "critical_min": 7}
                with self.assertRaises(COUNCIL.RunError):
                    COUNCIL.check_rubric(rubric)
                rubric = self.rubric()
                rubric["renderer"] = "native"
                with self.assertRaisesRegex(COUNCIL.RunError, "only the web renderer"):
                    COUNCIL.check_rubric(rubric)
        rubric = self.rubric()
        rubric["dimensions"][0]["weight"] = float("nan")
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.check_rubric(rubric)

    def test_duplicate_json_keys_and_reviewer_identities_refuse(self):
        run = self.adoption_run()
        path = run / "round-1/reviewer-r1.json"
        data = json.loads(path.read_text())
        data["reviewer"] = "r0"
        path.write_text(json.dumps(data))
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.run(run, write=True)
        path.write_text('{"score": 9, "score": 1}')
        with self.assertRaises(COUNCIL.RunError):
            COUNCIL.load(path)

    def test_cli_writes_and_verifies_but_rejects_modified_evidence(self):
        run = self.adoption_run()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(COUNCIL.main(["--write", str(run)]), 0)
            self.assertEqual(COUNCIL.main(["--verify", str(run)]), 0)
        self.assertIn("WINNER p-A", output.getvalue())
        (run / "round-1/synthetic-evidence.txt").write_text("Controlled stale-evidence defect.")
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(COUNCIL.main(["--verify", str(run)]), 1)
        self.assertIn("evidence A/capture changed", error.getvalue())

    def test_legacy_gate_cannot_claim_evidence_bound_adoption(self):
        rubric = {**RUBRIC, "adoption_gate": {"total_min": 70, "every_dimension_min": 5, "critical_min": 7}}
        scores = {"A": (9, 9), "B": (5, 5), "C": (4, 4), "W": (2, 2), "S": (9, 9)}
        meta, sheets = CouncilTest.round_of(self, [scores, scores])
        report = self.report(self.make([(meta, sheets)], rubric))
        self.assertIn("| A | 88.89 | NOT_ADOPTABLE |", report)
        self.assertIn("legacy run has no verified evidence manifest", report)

    def test_strict_cli_gate_rejects_a_weak_winner_and_keeps_its_report(self):
        strong = self.adoption_run()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(COUNCIL.main(["--write", str(strong), "--require-adoptable"]), 0)
        weak = self.adoption_run((7, 7))
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(COUNCIL.main(["--write", str(weak), "--require-adoptable"]), 1)
        self.assertIn("no evidence-bound ADOPTABLE winner", error.getvalue())
        self.assertIn("WINNER p-A", (weak / "round-1/report.md").read_text())


if __name__ == "__main__":
    unittest.main()
