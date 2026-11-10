"""Tests for .github/skills/ui-prototype-council/council.py.

The council's stop decision is arithmetic, not judgement, so it is tested like any
other gate: the refusals as well as the verdicts.
"""

import hashlib
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


if __name__ == "__main__":
    unittest.main()
