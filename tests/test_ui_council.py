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

    def test_clear_lead_on_critical_dimensions_wins(self):
        scores = {"A": (9, 8), "B": (5, 6), "C": (4, 5), "W": (2, 2), "S": (9, 9)}
        run = self.make([self.round_of([scores, scores])])
        self.assertEqual(self.verdict(run), ("WINNER", ["p-A"]))

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
                                        "evidence_status": "observed", "evidence": ["capture"]}
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
            evidence_manifest={"capture": {"path": capture.name, "sha256": hashlib.sha256(capture.read_bytes()).hexdigest()}},
            source_sha256={item: "a" * 64 for item in items},
            rubric_sha256=hashlib.sha256((run / "rubric.json").read_bytes()).hexdigest(),
            adoption_checks={item: {tier: {"status": "pass", "evidence": ["capture"]}
                                   for tier in ("tier1", "tier2")} for item in items},
            target_profiles=target_profiles,
        )
        (folder / "round.json").write_text(json.dumps(stored))
        return run

    def report(self, run):
        self.verdict(run)
        return (run / "round-1/report.md").read_text()

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
        capture = meta["evidence_manifest"]["capture"]
        meta["evidence_manifest"]["css-viewport"] = {
            **capture, "evidence_type": "css_viewport",
            "percentages": [100, 125, 150, 200], "source_sha256": "a" * 64,
        }
        for item in meta["items"]:
            meta["adoption_checks"][item]["desktop_zoom"] = {
                "status": "pass", "evidence": ["css-viewport"],
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
            {"status": "fail", "evidence": ["capture"]},
            {"status": "unverified", "evidence": ["capture"]},
            {"status": None, "evidence": ["capture"]},
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
        self.assertIn("evidence capture changed", error.getvalue())

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
