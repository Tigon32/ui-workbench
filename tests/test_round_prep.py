import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "round_prep", ROOT / ".github/skills/ui-prototype-council/round_prep.py")
ROUND_PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUND_PREP)


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


if __name__ == "__main__":
    unittest.main()
