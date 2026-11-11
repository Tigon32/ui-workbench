import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "round_prep", ROOT / ".github/skills/ui-prototype-council/round_prep.py")
ROUND_PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUND_PREP)
CHROME = os.environ.get("CHROME", ROUND_PREP.RENDER.DEFAULT_CHROME)


class RoundPrepTest(unittest.TestCase):
    def test_accepts_an_empty_blind_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            blind = Path(temp) / "blind"
            ROUND_PREP.prepare_blind_directory(blind)
            self.assertTrue(blind.is_dir())

    def test_refuses_a_nonempty_blind_directory_without_changing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            blind = Path(temp) / "blind"
            blind.mkdir()
            sentinel = blind / "sealed.json"
            sentinel.write_text('{"keep": true}', encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "choose a fresh output directory"):
                ROUND_PREP.prepare_blind_directory(blind)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"keep": true}')

    def test_refuses_to_replace_existing_round_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            round_dir = Path(temp) / "run" / "round-1"
            round_dir.mkdir(parents=True)
            round_file = round_dir / "round.json"
            round_file.write_text('{"keep": true}', encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "round metadata already exists"):
                ROUND_PREP.ensure_round_is_new(round_dir.parent, 1)

            self.assertEqual(round_file.read_text(encoding="utf-8"), '{"keep": true}')

    def test_creates_a_new_blind_item_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            blind = Path(temp)
            result = ROUND_PREP.create_item_directory(blind, "ABC")
            self.assertEqual(result, blind / "ABC")
            self.assertTrue(result.is_dir())

    def test_refuses_to_replace_existing_output_and_preserves_its_files(self):
        with tempfile.TemporaryDirectory() as temp:
            blind = Path(temp)
            existing = blind / "ABC"
            existing.mkdir()
            sentinel = existing / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "choose a fresh blind directory"):
                ROUND_PREP.create_item_directory(blind, "ABC")

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_invalid_rubric_is_rejected_before_output_directories_are_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps({
                "renderer": "native",
                "target_platforms": {
                    "mobile": True, "tablet": False, "laptop": False,
                    "desktop": False, "wide": False,
                },
                "target_platform_decision": "Unsupported renderer.",
            }), encoding="utf-8")
            run, blind = root / "run", root / "blind"

            result = ROUND_PREP.main([
                "prepare", "--run", str(run), "--round", "1",
                "--blind", str(blind), "--seed", "1", "--model", "test",
                "--keep", "1", "--strong", "item", "--weak", "item",
                "--rubric", str(rubric), "item=missing",
            ])

            self.assertEqual(result, 2)
            self.assertFalse(run.exists())
            self.assertFalse(blind.exists())

    def test_scoped_prepare_refuses_missing_direction_evidence_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_args = [
                "prepare", "--run", str(root / "run"), "--round", "1",
                "--blind", str(root / "blind"), "--seed", "1", "--model", "test",
                "--keep", "1", "--strong", "item", "--weak", "item",
                "--brief", "project.json", "item=missing"]
            with self.assertRaisesRegex(SystemExit, "requires --directions"):
                ROUND_PREP.main(result_args)
            self.assertFalse((root / "blind").exists())

    @unittest.skipUnless(Path(CHROME).exists(), "installed Chrome is required")
    def test_rubric_prepare_records_local_capture_and_source_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = root / "item"
            item.mkdir()
            page = item / "index.html"
            page.write_text(
                '<!doctype html><html lang="en"><title>One</title><body>'
                '<main id="ready"><h1>Review</h1><button type="button">Reset</button></main>'
                '</body></html>', encoding="utf-8")
            (item / "DESIGN.md").write_text("Local design.", encoding="utf-8")
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps({
                "target_platforms": {
                    "mobile": True, "tablet": False, "laptop": False,
                    "desktop": False, "wide": False,
                },
                "target_platform_decision": "Check the mobile CSS profile.",
            }), encoding="utf-8")
            run, blind = root / "run", root / "blind"
            result = ROUND_PREP.main([
                "prepare", "--run", str(run), "--round", "1",
                "--blind", str(blind), "--seed", "1", "--model", "test",
                "--keep", "1", "--strong", "item", "--weak", "item",
                "--chrome", CHROME, "--rubric", str(rubric),
                "--state", "ready=#ready", f"item={item}",
            ])

            self.assertEqual(result, 0)
            metadata = json.loads((run / "round-1" / "round.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["target_profiles"]["profiles"], {"mobile": 390})
            self.assertEqual(metadata["target_profiles"]["widths"], [390])
            self.assertEqual(metadata["target_profiles"]["reflow"], {
                "width": 320, "label": "zoom/reflow (not phone)",
            })
            self.assertEqual(metadata["source_sha256"][metadata["items"][0]],
                             hashlib.sha256(page.read_bytes()).hexdigest())
            self.assertEqual(metadata["rubric_sha256"],
                             hashlib.sha256(rubric.read_bytes()).hexdigest())
            self.assertTrue(metadata["evidence_manifest"])
            for record in metadata["evidence_manifest"].values():
                capture = Path(record["path"])
                self.assertTrue(capture.is_file())
                self.assertEqual(record["sha256"], hashlib.sha256(capture.read_bytes()).hexdigest())
            for ident in metadata["items"]:
                item_dir = blind / ident
                manifest = json.loads(
                    (item_dir / "evidence-manifest.json").read_text(encoding="utf-8"))
                self.assertTrue(manifest["references"])
                for reference, record in manifest["references"].items():
                    self.assertEqual(reference, f"{ident}/{record['path']}")
                    self.assertEqual(
                        record["sha256"], metadata["evidence_manifest"][reference]["sha256"])
            self.assertTrue(any("reflow-zoom-320.png" in ref
                                for ref in metadata["evidence_manifest"]))
            self.assertTrue(any("state-ready-mobile-390.png" in ref
                                for ref in metadata["evidence_manifest"]))


if __name__ == "__main__":
    unittest.main()
