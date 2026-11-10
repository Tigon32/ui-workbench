"""Tests for .github/skills/ui-prototype-council/render_check.py.

Each check gets a page that must fail it and a page that must pass every check, so a
checker that only ever passes cannot hide. The checks need the installed Chrome. Where
Chrome is absent these tests skip, except when UI_CHECK_REQUIRED=1, which the host
lane sets so a missing browser fails instead of passing silently.
"""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
