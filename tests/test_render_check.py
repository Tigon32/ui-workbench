"""Tests for .github/skills/ui-prototype-council/render_check.py.

Each check gets a page that must fail it and a page that must pass every check, so a
checker that only ever passes cannot hide. The checks need the installed Chrome. Where
Chrome is absent these tests skip, except when UI_CHECK_REQUIRED=1, which the host
lane sets so a missing browser fails instead of passing silently.
"""

import contextlib
import io
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_check", ROOT / ".github/skills/ui-prototype-council/render_check.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)

CHROME = os.environ.get("CHROME", RENDER.DEFAULT_CHROME)
REQUIRED = os.environ.get("UI_CHECK_REQUIRED") == "1"

STYLE = """
:root{--ink:#1b1d21;--ground:#ffffff;--edge:#5a5f66;--focus:#0b57d0}
@media (prefers-color-scheme:dark){:root{--ink:#eceae6;--ground:#16181c;--edge:#9aa0a8;--focus:#8ab4f8}}
body{margin:0;padding:16px;color:var(--ink);background:var(--ground);font:14px/1.4 system-ui}
button{min-width:32px;min-height:32px;color:var(--ink);background:var(--ground);border:1px solid var(--edge)}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
@media (forced-colors:active){:focus-visible{outline-color:Highlight}}
"""
GOOD = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>
<style>{STYLE}</style></head><body><main><h1>Review</h1><p>not measured</p>
<button type="button">Reset</button></main></body></html>"""

BAD = {
    "contrast": ("<p>not measured</p>", "p{color:var(--weak)}", ":root{--weak:#c8c8c8}"),
    "target-size": ('<button type="button" style="min-width:0;min-height:0;width:12px;height:12px;padding:0">a</button>'
                    '<button type="button" style="min-width:0;min-height:0;width:12px;height:12px;padding:0">b</button>', "", ""),
    "reflow": ('<div style="width:900px">wide</div>', "", ""),
    "focus": ('<button type="button" class="plain">Plain</button>', ".plain:focus-visible{outline:none}", ""),
    "literal": ("<p>x</p>", "p{border:1px solid #777777}", ""),
    "hover-only": ("<p>x</p>", "button:hover{text-decoration:underline}", ""),
    "network": ('<img alt="" src="https://example.invalid/x.png">', "", ""),
    "text": ("<p>nothing here</p>", "", ""),
}


@unittest.skipUnless(Path(CHROME).exists() or REQUIRED, "installed Chrome is required")
class RenderCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(CHROME).exists():
            raise AssertionError(f"UI_CHECK_REQUIRED=1 but Chrome is absent at {CHROME}")
        cls.browser = RENDER.Browser(CHROME)
        cls.temp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.temp.cleanup()

    def check(self, name, html, expect=("not measured",), forbid=(), budget=0):
        page = Path(self.temp.name) / f"{name}.html"
        page.write_text(html, encoding="utf-8")
        return {item["check"] for item in RENDER.check_page(self.browser, page, list(expect), forbid, budget)}

    def profile_check(self, name, html, quality):
        page = Path(self.temp.name) / f"{name}.html"
        page.write_text(html, encoding="utf-8")
        profiles = {
            "widths": [390],
            "profiles": {"mobile": 390},
            "reflow_width": 320,
            "quality_checks": quality,
        }
        return RENDER.check_page_profiles(self.browser, page, ["not measured"], [], 0, profiles)

    def test_click_tasks_count_clicks_and_refuse_modals(self):
        page = Path(self.temp.name) / "tasks.html"
        page.write_text(GOOD.replace('<button type="button">Reset</button>',
            '<button type="button" id="o">Open group</button><div id="d" hidden><p>Folder evidence</p>'
            '<button type="button" id="m">Move</button></div><dialog id="g"><p>Preview</p></dialog>'
            '<script>o.onclick=()=>d.hidden=false;m.onclick=()=>g.showModal();if(location.hash==="#later")d.hidden=false;</script>'), encoding="utf-8")
        tasks = [{"name": "evidence", "clicks": ["Open group"], "goal": "Folder evidence", "max_clicks": 1},
                 {"name": "too many", "clicks": ["Open group"], "goal": "Folder evidence", "max_clicks": 0},
                 {"name": "modal", "clicks": ["Open group", "Move"], "goal": "Preview", "max_clicks": 2},
                 {"name": "missing", "clicks": ["Nowhere"], "goal": "x", "max_clicks": 1},
                 {"name": "from state", "start": "#later", "clicks": [], "goal": "Folder evidence", "max_clicks": 0}]
        found, counts = RENDER.run_tasks(self.browser, page, tasks)
        self.assertEqual(sorted((f["where"], f["check"]) for f in found),
                         [("missing", "clicks"), ("modal", "modal"), ("too many", "clicks")])
        self.assertEqual(counts[0], ("evidence", 1, 1))

    def test_forbidden_wording_and_word_budget(self):
        self.assertEqual(self.check("words-ok", GOOD, forbid=[r"\bsafe\b"], budget=10), set())
        wordy = GOOD.replace("<h1>Review</h1>", "<h1>Review</h1><p>" + "word " * 40 + "safe</p>")
        self.assertEqual(self.check("words-bad", wordy, forbid=[r"\bsafe\b"], budget=10),
                         {"forbid", "budget"})

    def test_good_page_passes_every_check(self):
        self.assertEqual(self.check("good", GOOD), set())

    def test_each_check_rejects_its_defect(self):
        for check, (body, rule, root) in BAD.items():
            with self.subTest(check):
                html = GOOD.replace("<button type=\"button\">Reset</button>", body).replace(
                    "</style>", f"{root}{rule}</style>")
                if check == "text":
                    html = html.replace("<p>not measured</p>", "")
                self.assertIn(check, self.check(check, html))

    def test_semantic_control_parity_rejects_theme_specific_control_loss(self):
        html = GOOD.replace("</style>",
            "@media(prefers-color-scheme:dark){button{display:none}}</style>")
        problems, _ = self.profile_check(
            "theme-control-loss", html, {"semantic_control_parity": True})
        self.assertIn("semantic-control-parity", {item["check"] for item in problems})

    def test_semantic_parity_includes_disabled_state_and_uses_labelledby_first(self):
        disabled = GOOD.replace("</body>", """
            <script>
              if (matchMedia("(prefers-color-scheme: dark)").matches) {
                const button = document.querySelector("button");
                button.disabled = true;
                button.setAttribute("aria-disabled", "true");
              }
            </script></body>""")
        problems, _ = self.profile_check(
            "theme-disabled", disabled, {"semantic_control_parity": True})
        self.assertIn("semantic-control-parity", {item["check"] for item in problems})

        labelled = GOOD.replace("</main>",
            '<span id="control-name">Primary</span>'
            '<button aria-label="Fallback" aria-labelledby="control-name">Action</button></main>')
        labelled = labelled.replace("</body>", """
            <script>
              if (matchMedia("(prefers-color-scheme: dark)").matches)
                document.getElementById("control-name").textContent = "Dark name";
            </script></body>""")
        problems, _ = self.profile_check(
            "theme-labelledby-name", labelled, {"semantic_control_parity": True})
        self.assertIn("semantic-control-parity", {item["check"] for item in problems})

    def test_semantic_control_parity_passes_when_names_and_roles_match(self):
        problems, unknown = self.profile_check(
            "theme-control-match", GOOD, {"semantic_control_parity": True})
        self.assertNotIn("semantic-control-parity", {item["check"] for item in problems})
        self.assertFalse(unknown)

    def test_reduced_motion_limit_checks_computed_durations(self):
        html = GOOD.replace("</style>", """
            @keyframes pulse{to{opacity:.5}}
            @media(prefers-reduced-motion:reduce){button{animation:pulse 200ms infinite}}
            </style>""")
        problems, _ = self.profile_check(
            "reduced-motion-duration", html, {"reduced_motion_max_ms": 100})
        self.assertIn("reduced-motion-duration", {item["check"] for item in problems})

    def test_declared_typography_and_spacing_scales_check_rendered_values_and_tokens(self):
        html = GOOD.replace("--focus:#0b57d0",
            "--focus:#0b57d0;--font-size-body:14px;--font-size-heading:28px;--space-small:8px")
        html = html.replace("button{min-width", "button{font-size:inherit;min-width")
        quality = {"typography_scale_px": [14, 28], "spacing_scale_px": [4, 8, 16]}
        problems, _ = self.profile_check("scales-pass", html, quality)
        self.assertNotIn("typography-scale", {item["check"] for item in problems})
        self.assertNotIn("spacing-token-scale", {item["check"] for item in problems})

        invalid = html.replace("--space-small:8px", "--space-small:9px")
        problems, _ = self.profile_check("scales-fail", invalid, quality)
        self.assertIn("spacing-token-scale", {item["check"] for item in problems})

    def test_spacing_scale_allows_automatic_centering_without_accepting_off_scale_gaps(self):
        html = GOOD.replace("--focus:#0b57d0", "--focus:#0b57d0;--space-small:8px")
        html = html.replace("</style>", "main{width:128px;margin-inline:auto;display:flex;gap:8px}</style>")
        problems, unknown = self.profile_check("automatic-spacing", html, {"spacing_scale_px": [4, 8, 16]})
        self.assertNotIn("spacing-scale", {item["check"] for item in problems})
        self.assertFalse(unknown)
        problems, _ = self.profile_check(
            "automatic-spacing-bad-gap", html.replace("gap:8px", "gap:9px"),
            {"spacing_scale_px": [4, 8, 16]},
        )
        self.assertIn("spacing-scale", {item["check"] for item in problems})

    def test_computed_spacing_rejects_off_scale_gap_despite_valid_token(self):
        html = GOOD.replace("padding:16px", "padding:0")
        html = html.replace("</style>", ".layout{display:flex;gap:8px}</style>")
        html = html.replace("</main>",
            '<div class="layout"><span>Left</span><span>Right</span></div></main>')
        html = html.replace("--focus:#0b57d0",
            "--focus:#0b57d0;--space-small:8px")
        quality = {"spacing_scale_px": [8]}
        problems, _ = self.profile_check("gap-eight", html, quality)
        self.assertNotIn("spacing-scale", {item["check"] for item in problems})

        invalid = html.replace("gap:8px", "gap:9px")
        problems, _ = self.profile_check("gap-nine", invalid, quality)
        self.assertIn("spacing-scale", {item["check"] for item in problems})

    def test_computed_spacing_accepts_zero_auto_and_normal_values(self):
        html = GOOD.replace("padding:16px", "padding:0")
        html = html.replace("</style>",
            ".layout{display:flex;gap:normal;margin-left:auto;padding:0}</style>")
        html = html.replace("</main>",
            '<div class="layout"><span>Left</span><span>Right</span></div></main>')
        html = html.replace("--focus:#0b57d0",
            "--focus:#0b57d0;--space-zero:0px;--space-small:8px")
        problems, unknown = self.profile_check(
            "spacing-keywords", html, {"spacing_scale_px": [0, 8]})
        self.assertNotIn("spacing-scale", {item["check"] for item in problems})
        self.assertFalse(unknown)

    def test_opt_in_text_expansion_reports_clipping_and_unknown_fixture(self):
        html = GOOD.replace("</main>",
            '<div data-text-expansion style="width:80px;height:20px;overflow:hidden">'
            '<span>Long text that clips when expanded.</span></div></main>')
        problems, unknown = self.profile_check(
            "expanded-clipped", html, {"text_expansion_factor": 2})
        self.assertIn("text-expansion-clipping", {item["check"] for item in problems})
        self.assertFalse(unknown)

        _, unknown = self.profile_check(
            "expanded-no-fixture", GOOD, {"text_expansion_factor": 2})
        self.assertTrue(any("no [data-text-expansion] fixture" in item for item in unknown))

    def test_rubric_cli_checks_and_captures_target_and_reflow_widths(self):
        page = Path(self.temp.name) / "cli.html"
        page.write_text(GOOD, encoding="utf-8")
        rubric = Path(self.temp.name) / "rubric.json"
        rubric.write_text(json.dumps({
            "target_platforms": {
                "mobile": True, "tablet": True, "laptop": False,
                "desktop": False, "wide": False,
            },
            "target_platform_decision": "Check the mobile CSS profile.",
        }), encoding="utf-8")
        captures = Path(self.temp.name) / "captures"
        tasks = Path(self.temp.name) / "tasks.json"
        tasks.write_text(json.dumps([{
            "name": "review", "clicks": ["Reset"], "goal": "Review", "max_clicks": 1,
        }]), encoding="utf-8")
        output_text = io.StringIO()
        with contextlib.redirect_stdout(output_text):
            result = RENDER.main([
                str(page), "--rubric", str(rubric), "--chrome", CHROME,
                "--capture", str(captures), "--tasks", str(tasks),
            ])
        self.assertEqual(result, 0)
        output = captures / page.parent.name
        self.assertTrue((output / "profile-mobile-light-390.png").is_file())
        self.assertTrue((output / "profile-mobile-dark-390.png").is_file())
        self.assertTrue((output / "profile-tablet-light-768.png").is_file())
        self.assertTrue((output / "reflow-zoom-320.png").is_file())
        self.assertFalse((output / "profile-mobile-light-320.png").exists())
        self.assertIn("[390px]", output_text.getvalue())
        self.assertIn("[768px]", output_text.getvalue())

        unsupported = Path(self.temp.name) / "native-rubric.json"
        unsupported.write_text(json.dumps({
            "renderer": "native",
            "target_platforms": {
                "mobile": True, "tablet": False, "laptop": False,
                "desktop": False, "wide": False,
            },
            "target_platform_decision": "Native capture is not supported.",
        }), encoding="utf-8")
        untouched = Path(self.temp.name) / "must-not-be-created"
        self.assertEqual(RENDER.main([
            str(page), "--rubric", str(unsupported), "--capture", str(untouched),
        ]), 2)
        self.assertFalse(untouched.exists())

    def test_cli_returns_incomplete_for_missing_opted_in_fixture(self):
        page = Path(self.temp.name) / "unknown.html"
        page.write_text(GOOD, encoding="utf-8")
        rubric = Path(self.temp.name) / "fixture-rubric.json"
        rubric.write_text(json.dumps({
            "target_platforms": {
                "mobile": True, "tablet": False, "laptop": False,
                "desktop": False, "wide": False,
            },
            "target_platform_decision": "Check marked text expansion.",
            "quality_checks": {"text_expansion_factor": 1.5},
        }), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = RENDER.main([str(page), "--rubric", str(rubric), "--chrome", CHROME])
        self.assertEqual(result, 3)
        self.assertIn("quality unknown: light 390: text expansion: no [data-text-expansion]",
                      output.getvalue())
        self.assertIn(": INCOMPLETE (0 finding(s))", output.getvalue())
        self.assertNotIn(": ok (", output.getvalue())


if __name__ == "__main__":
    unittest.main()
