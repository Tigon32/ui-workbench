import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_profiles", ROOT / ".github/skills/ui-prototype-council/profiles.py")
PROFILES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILES)


class ProfilesTest(unittest.TestCase):
    def write_rubric(self, folder, data):
        path = Path(folder) / "rubric.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    @staticmethod
    def base():
        return {
            "target_platforms": {
                "mobile": True, "tablet": True, "laptop": False,
                "desktop": True, "wide": False,
            },
            "target_platform_decision": "Validate current supported layouts.",
        }

    def test_loads_enabled_profiles_deduplicates_widths_and_retains_reflow(self):
        rubric = self.base()
        rubric["target_widths"] = {"mobile": 768, "desktop": 1920}
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_rubric(temp, rubric)
            result = PROFILES.load_rubric(path)

        self.assertEqual(result["profiles"], {"mobile": 768, "tablet": 768, "desktop": 1920})
        self.assertEqual(result["widths"], [768, 1920])
        self.assertEqual(result["reflow_width"], 320)
        self.assertEqual(result["reflow_label"], "zoom/reflow (not phone)")
        self.assertEqual(len(result["digest"]), 64)

    def test_rejects_bad_profile_shape_and_unsupported_renderer(self):
        with tempfile.TemporaryDirectory() as temp:
            invalid = self.base()
            invalid["target_platforms"].pop("wide")
            with self.assertRaisesRegex(PROFILES.RubricError, "exactly"):
                PROFILES.load_rubric(self.write_rubric(temp, invalid))

            invalid = self.base()
            invalid["target_platforms"]["mobile"] = False
            invalid["target_platforms"]["tablet"] = False
            invalid["target_platforms"]["desktop"] = False
            with self.assertRaisesRegex(PROFILES.RubricError, "at least one"):
                PROFILES.load_rubric(self.write_rubric(temp, invalid))

            invalid = self.base()
            invalid["renderer"] = "native"
            with self.assertRaisesRegex(PROFILES.RubricError, "native rendering"):
                PROFILES.load_rubric(self.write_rubric(temp, invalid))

    def test_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text(
                '{"target_platforms":{"mobile":true,"mobile":false},'
                '"target_platform_decision":"Conflicting profile."}',
                encoding="utf-8")
            with self.assertRaisesRegex(PROFILES.RubricError, "duplicate JSON key"):
                PROFILES.load_rubric(path)

    def test_rejects_disabled_or_unbounded_width_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            invalid = self.base()
            invalid["target_widths"] = {"laptop": 1280}
            with self.assertRaisesRegex(PROFILES.RubricError, "enabled profiles"):
                PROFILES.load_rubric(self.write_rubric(temp, invalid))

            invalid["target_widths"] = {"mobile": True}
            with self.assertRaisesRegex(PROFILES.RubricError, "integer"):
                PROFILES.load_rubric(self.write_rubric(temp, invalid))

    def test_validates_and_normalizes_declared_quality_checks(self):
        rubric = self.base()
        rubric["quality_checks"] = {
            "semantic_control_parity": True,
            "reduced_motion_max_ms": 150,
            "typography_scale_px": [16, 12, 24],
            "spacing_scale_px": [8, 4, 0, 16],
            "text_expansion_factor": 1.5,
        }
        with tempfile.TemporaryDirectory() as temp:
            result = PROFILES.load_rubric(self.write_rubric(temp, rubric))
        self.assertEqual(result["quality_checks"], {
            "semantic_control_parity": True,
            "reduced_motion_max_ms": 150,
            "typography_scale_px": [12, 16, 24],
            "spacing_scale_px": [0, 4, 8, 16],
            "text_expansion_factor": 1.5,
        })

    def test_rejects_unknown_quality_checks(self):
        rubric = self.base()
        rubric["quality_checks"] = {"animation_compliance": True}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PROFILES.RubricError, "unsupported"):
                PROFILES.load_rubric(self.write_rubric(temp, rubric))


if __name__ == "__main__":
    unittest.main()
