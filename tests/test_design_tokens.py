"""Tests for .github/skills/ui-prototype-council/design_tokens.py.

One DESIGN.md must produce CSS and Swift that agree, a hand edit to either output must
fail the check, and anything outside the supported subset must be refused, not guessed.
The Swift check needs swiftc with SwiftUI. It skips where that is absent, except when
UI_CHECK_REQUIRED=1, which the host lane sets.
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "design_tokens", ROOT / ".github/skills/ui-prototype-council/design_tokens.py")
TOKENS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOKENS)

DESIGN = """---
version: alpha
name: Sample
colors:
  primary: "#1F2A33"
  primary-dark: "#E6E8EA"
  primary-contrast: "#000000"
  primary-contrast-dark: "#FFFFFF"
  ground: "#FFFFFF"
  ground-dark: "#121417"
  ground-contrast: "#FFFFFF"
  ground-contrast-dark: "#000000"
typography:
  body-md: {fontFamily: system-ui, fontSize: 13px, fontWeight: 400, lineHeight: 1.4}
  figures: {fontFamily: system-ui, fontSize: 0.8125rem, fontWeight: 500, lineHeight: 1.3, fontFeature: "tnum"}
spacing:
  sm: 8px
rounded:
  sm: 4px
components:
  button:
    textColor: "{colors.primary}"
---
## Overview
Sample.
"""


class DesignTokensTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def write(self, text):
        design = self.dir / "DESIGN.md"
        design.write_text(text, encoding="utf-8")
        return design

    def test_generates_matching_css_and_swift(self):
        design = self.write(DESIGN)
        self.assertEqual(TOKENS.main([str(design)]), 0)
        css = (self.dir / "tokens.css").read_text()
        swift = (self.dir / "Tokens.swift").read_text()
        self.assertIn("--color-primary: #1f2a33;", css)
        self.assertIn('@media (prefers-color-scheme: dark) and (prefers-contrast: more)', css)
        self.assertIn(':root[data-theme="contrast-dark"]', css)
        self.assertIn("--type-figures-numeric: tabular-nums;", css)
        self.assertIn("public static let contrastDark = DesignPalette(", swift)
        self.assertIn("size: 13, weight: .medium", swift)
        self.assertIn("tabularDigits: true", swift)
        self.assertEqual(TOKENS.main(["--check", str(design)]), 0)

    @unittest.skipUnless(shutil.which("swiftc") or os.environ.get("UI_CHECK_REQUIRED") == "1",
                         "swiftc with SwiftUI is required")
    def test_swift_output_type_checks(self):
        # UI_CHECK_REQUIRED=1 is set by the host lane, so a missing compiler fails there.
        self.assertTrue(shutil.which("swiftc"), "swiftc is absent")
        design = self.write(DESIGN)
        TOKENS.main([str(design)])
        result = subprocess.run(["swiftc", "-typecheck", str(self.dir / "Tokens.swift")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hand_edit_fails_the_check(self):
        design = self.write(DESIGN)
        TOKENS.main([str(design)])
        css = self.dir / "tokens.css"
        css.write_text(css.read_text().replace("#1f2a33", "#000001"))
        self.assertEqual(TOKENS.main(["--check", str(design)]), 1)

    def test_refusals(self):
        cases = {
            "missing theme variant": DESIGN.replace('  primary-contrast-dark: "#FFFFFF"\n', ""),
            "list": DESIGN.replace("spacing:\n  sm: 8px", "spacing:\n  - 8px"),
            "web font": DESIGN.replace("{fontFamily: system-ui, fontSize: 13px",
                                       "{fontFamily: Inter, fontSize: 13px"),
            "broken reference": DESIGN.replace("{colors.primary}", "{colors.missing}"),
            "non-hex colour": DESIGN.replace('primary: "#1F2A33"', "primary: rebeccapurple"),
            "trailing comment": DESIGN.replace("sm: 4px", "sm: 4px # corner"),
            "wrong version": DESIGN.replace("version: alpha", "version: beta"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertEqual(TOKENS.main([str(self.write(text))]), 1)


if __name__ == "__main__":
    unittest.main()
