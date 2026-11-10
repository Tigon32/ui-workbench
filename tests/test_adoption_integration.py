"""Exercise captured evidence through the real preparation and scoring CLIs."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_render_check import CHROME, GOOD


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".github/skills/ui-prototype-council"


@unittest.skipUnless(Path(CHROME).exists(), "installed Chrome is required")
class CapturedAdoptionTest(unittest.TestCase):
    def test_refinement_example_checks_both_alternatives_under_one_scope(self):
        example = ROOT / "docs/examples/refinement"
        result = subprocess.run(
            [sys.executable, str(TOOLS / "render_check.py"),
             "--rubric", str(example / "rubric.json"),
             "--expect", str(example / "expected.json"),
             "--tasks", str(example / "tasks.json"),
             str(example / "alternatives/baseline/index.html"),
             str(example / "alternatives/redesign/index.html")],
            capture_output=True, text=True, timeout=120, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("baseline/index.html: ok (0 finding(s))", result.stdout)
        self.assertIn("redesign/index.html: ok (0 finding(s))", result.stdout)
        self.assertEqual(result.stdout.count("open-held-out-error: 1 (budget 1)"), 2)

    def test_prepared_captures_score_but_missing_project_gate_prevents_adoption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, blind = root / "run", root / "blind"
            run.mkdir()
            rubric = json.loads((TOOLS / "rubric-default.json").read_text())
            rubric["adoption_gate"] = {"total_min": 75, "every_dimension_min": 5, "critical_min": 7}
            rubric["adoption_decision"] = "Synthetic arithmetic thresholds, not approved project policy."
            rubric["target_platforms"] = {
                "mobile": True, "tablet": False, "laptop": False, "desktop": False, "wide": False,
            }
            rubric["target_platform_decision"] = "One owned synthetic browser fixture, not device qualification."
            rubric_path = run / "rubric.json"
            rubric_path.write_text(json.dumps(rubric))
            items = []
            for name in ("candidate", "weak", "strong"):
                folder = root / name
                folder.mkdir()
                (folder / "index.html").write_text(GOOD)
                (folder / "DESIGN.md").write_text("Owned synthetic fixture design.")
                items.append(f"{name}={folder}")

            def invoke(script, *arguments):
                return subprocess.run(
                    [sys.executable, str(TOOLS / script), *map(str, arguments)],
                    capture_output=True, text=True, timeout=120, cwd=ROOT,
                )

            rendered = invoke("render_check.py", root / "candidate/index.html",
                              "--rubric", rubric_path, "--chrome", CHROME)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            prepared = invoke(
                "round_prep.py", "prepare", "--run", run, "--round", 1, "--blind", blind,
                "--seed", 7, "--model", "synthetic-vector", "--strong", "strong",
                "--weak", "weak", "--keep", 2, "--reviewers", 2,
                "--rubric", rubric_path, "--chrome", CHROME, *items,
            )
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            revealed = invoke("round_prep.py", "reveal", "--run", run, "--round", 1, "--blind", blind)
            self.assertEqual(revealed.returncode, 0, revealed.stdout + revealed.stderr)
            round_dir = run / "round-1"
            meta_path = round_dir / "round.json"
            meta = json.loads(meta_path.read_text())
            for index in range(2):
                order = meta["items"][index:] + meta["items"][:index]
                scores = {}
                for ident, name in meta["reveal"].items():
                    value = {"candidate": 8, "weak": 2, "strong": 9}[name]
                    ref = next(ref for ref in meta["evidence_manifest"] if ref.startswith(ident + "/"))
                    scores[ident] = {
                        dim["id"]: {
                            "why": "Synthetic arithmetic vector; this is not an expert or human assessment.",
                            "score": value, "evidence_status": "observed", "evidence": [ref],
                        } for dim in rubric["dimensions"]
                    }
                sheet = {
                    "reviewer": f"r{index}", "reviewer_kind": "model", "model": "synthetic-vector",
                    "seed": index, "order": order, "scores": scores,
                }
                (round_dir / f"reviewer-r{index}.json").write_text(json.dumps(sheet))
            log = round_dir / "render-report.txt"
            log.write_text(rendered.stdout + rendered.stderr)
            meta["evidence_manifest"]["render-report"] = {
                "path": str(log), "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
            candidate = next(ident for ident, name in meta["reveal"].items() if name == "candidate")
            meta["adoption_checks"] = {
                candidate: {"tier2": {"status": "pass", "evidence": ["render-report"]}},
            }
            meta_path.write_text(json.dumps(meta))

            written = invoke("council.py", "--write", run)
            self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
            self.assertIn("WINNER candidate", written.stdout)
            report = (round_dir / "report.md").read_text()
            self.assertIn("77.78 | NOT_ADOPTABLE", report)
            self.assertIn("tier1 evidence is failed or unverified", report)
            strict = invoke("council.py", "--verify", run, "--require-adoptable")
            self.assertEqual(strict.returncode, 1)

            capture = Path(next(iter(meta["evidence_manifest"].values()))["path"])
            capture.write_bytes(b"Controlled stale-capture negative control.")
            stale = invoke("council.py", "--verify", run)
            self.assertEqual(stale.returncode, 1)
            self.assertIn("changed", stale.stderr)
