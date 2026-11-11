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
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_check", ROOT / ".github/skills/ui-prototype-council/render_check.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)

CHROME = os.environ.get("CHROME", RENDER.DEFAULT_CHROME)
REQUIRED = os.environ.get("UI_CHECK_REQUIRED") == "1"

TOKENS = """
:root{--ink:#1b1d21;--ground:#ffffff;--edge:#5a5f66;--focus:#0b57d0}
@media (prefers-color-scheme:dark){:root{--ink:#eceae6;--ground:#16181c;--edge:#9aa0a8;--focus:#8ab4f8}}
"""
STYLE = """
body{margin:0;padding:16px;color:var(--ink);background:var(--ground);font:14px/1.4 system-ui}
button{min-width:32px;min-height:32px;color:var(--ink);background:var(--ground);border:1px solid var(--edge)}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
@media (forced-colors:active){:focus-visible{outline-color:Highlight}}
"""
GOOD = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>
<link rel="stylesheet" href="tokens.css">
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
    # Declarative (not script-initiated) so the browser-level guard does not turn this
    # into a hard CdpError; it only exercises the pre-existing DOM/performance scan.
    "network": ('<a href="https://example.invalid/x">external link</a>', "", ""),
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
        (Path(cls.temp.name) / "tokens.css").write_text(
            TOKENS,
            encoding="utf-8")

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

    def test_color_mix_custom_property_passes_and_direct_color_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tokens.css").write_text(
                TOKENS.replace("--ink:#1b1d21", "--ink:color-mix(in srgb, black 90%, white)"),
                encoding="utf-8")
            page = Path(folder) / "color-mix-token.html"
            page.write_text(GOOD, encoding="utf-8")
            self.assertEqual(RENDER.check_page(self.browser, page, ["not measured"]), [])

        direct = GOOD.replace(
            "</style>", "p{color:color-mix(in srgb, black 90%, white)}</style>")
        self.assertIn("literal", self.check("color-mix-direct", direct))

    def test_each_check_rejects_its_defect(self):
        for check, (body, rule, root) in BAD.items():
            with self.subTest(check):
                html = GOOD.replace("<button type=\"button\">Reset</button>", body).replace(
                    "</style>", f"{root}{rule}</style>")
                if check == "text":
                    html = html.replace("<p>not measured</p>", "")
                self.assertIn(check, self.check(check, html))

    def test_out_of_folder_file_request_is_blocked_before_navigation_completes(self):
        # A fresh Browser isolates the socket stream from the CdpError raised mid-load;
        # the shared cls.browser is reserved for tests that complete every load normally.
        browser = RENDER.Browser(CHROME)
        try:
            with tempfile.TemporaryDirectory() as outside:
                secret = Path(outside) / "secret.png"
                secret.write_bytes(b"not a real image")
                page = Path(self.temp.name) / "outside-file.html"
                # img/src is a declarative load, unaffected by --allow-file-access-from-files,
                # so this exercises the folder guard itself, not Chrome's own file-origin CORS.
                page.write_text(GOOD.replace(
                    "</main>", f'<img alt="" src="file://{secret}"></main>'), encoding="utf-8")
                with self.assertRaises(RENDER.CdpError):
                    RENDER.check_page(browser, page, ["not measured"])
                self.assertTrue(any("secret.png" in u for u in browser.blocked_requests))
        finally:
            browser.close()

    def test_add_allowed_folder_permits_a_page_composed_from_several_trusted_folders(self):
        # Mirrors round_prep.py's contact_sheet(): one page in its own output folder
        # references images that live in separate per-item folders, navigated via a
        # direct browser.call("Page.navigate", ...) rather than browser.load(), so the
        # single-folder auto-guard from load() never runs for it.
        browser = RENDER.Browser(CHROME)
        try:
            with tempfile.TemporaryDirectory() as sheet_dir, \
                 tempfile.TemporaryDirectory() as item_dir:
                asset = Path(item_dir) / "shot.png"
                asset.write_bytes(b"not a real image")
                page = Path(sheet_dir) / "sheet.html"
                page.write_text(
                    f'<!doctype html><img alt="" src="file://{asset}">', encoding="utf-8")
                # Without opting the item folder in, the composed page is blocked even
                # though its own folder (sheet_dir) was separately allowed.
                browser.set_allowed_folder(None)
                browser.add_allowed_folder(sheet_dir)
                with self.assertRaises(RENDER.CdpError):
                    browser.call("Page.navigate", wait_event="Page.loadEventFired",
                                 url=page.as_uri())
        finally:
            browser.close()
        browser = RENDER.Browser(CHROME)
        try:
            with tempfile.TemporaryDirectory() as sheet_dir, \
                 tempfile.TemporaryDirectory() as item_dir:
                asset = Path(item_dir) / "shot.png"
                asset.write_bytes(b"not a real image")
                page = Path(sheet_dir) / "sheet.html"
                page.write_text(
                    f'<!doctype html><img alt="" src="file://{asset}">', encoding="utf-8")
                browser.set_allowed_folder(None)
                browser.add_allowed_folder(sheet_dir)
                browser.add_allowed_folder(item_dir)
                browser.call("Page.navigate", wait_event="Page.loadEventFired",
                             url=page.as_uri())
                self.assertEqual(browser.blocked_requests, [])
        finally:
            browser.close()

    def test_blocked_network_request_raises_and_cli_exits_nonzero(self):
        page = Path(self.temp.name) / "network-defect.html"
        page.write_text(GOOD.replace(
            "</main>", '<img alt="" src="https://example.invalid/x.png"></main>'), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = RENDER.main([str(page), "--chrome", CHROME])
        self.assertEqual(result, 2)
        self.assertIn("blocked request", output.getvalue())

    def test_raw_websocket_to_loopback_never_reaches_a_real_server(self):
        # Fetch-domain interception does not see raw WebSocket upgrades; this proves
        # the separate whole-process offline proxy guard actually stops them: a real
        # TCP server on loopback must receive zero connections even though it is a
        # perfectly reachable address, because the page never gets a route to it.
        accepted = []
        ready = threading.Event()

        def serve():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port_holder["port"] = sock.getsockname()[1]
            sock.listen(1)
            sock.settimeout(6)
            ready.set()
            try:
                conn, _ = sock.accept()
                accepted.append(True)
                conn.close()
            except socket.timeout:
                pass
            sock.close()

        port_holder = {}
        server_thread = threading.Thread(target=serve, daemon=True)
        server_thread.start()
        ready.wait(timeout=5)
        port = port_holder["port"]

        page = Path(self.temp.name) / "websocket-defect.html"
        page.write_text(GOOD.replace("</main>", f"""<script>
window.wsResult = "pending";
try {{
  const ws = new WebSocket("ws://127.0.0.1:{port}/");
  ws.onopen = () => window.wsResult = "opened";
  ws.onerror = () => window.wsResult = "error";
}} catch (e) {{ window.wsResult = "threw"; }}
</script></main>"""), encoding="utf-8")

        browser = RENDER.Browser(CHROME)
        try:
            browser.call("Network.disable")
            browser.set_allowed_folder(page.parent)
            browser.load(page.resolve().as_uri(), 1280, "light", False)
            deadline = time.monotonic() + 5
            result = "pending"
            while result == "pending" and time.monotonic() < deadline:
                result = browser.evaluate("window.wsResult")
                time.sleep(0.1)
            self.assertEqual(result, "error")
        finally:
            browser.close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = RENDER.main([str(page), "--chrome", CHROME])
        self.assertEqual(result, 2)
        self.assertIn("blocked WebSocket", output.getvalue())
        server_thread.join(timeout=7)
        self.assertEqual(accepted, [])

    def test_local_sibling_assets_still_load_under_the_guard(self):
        # Own temp directory so this test's tokens.css (declaring --color-accent only)
        # cannot clobber the shared cls.temp/tokens.css that GOOD's other callers rely
        # on for their own (--ink/--ground/--edge/--focus) colour provenance.
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tokens.css").write_text(
                TOKENS + ":root{--color-accent:tomato}", encoding="utf-8")
            page = Path(folder) / "sibling-asset.html"
            page.write_text(GOOD, encoding="utf-8")
            problems = {item["check"] for item in RENDER.check_page(
                self.browser, page, ["not measured"])}
            self.assertEqual(problems, set())

    def test_color_custom_property_from_sibling_tokens_css_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tokens.css").write_text(
                TOKENS + ":root{--color-accent:tomato}", encoding="utf-8")
            page = Path(folder) / "color-token-tokens-css.html"
            page.write_text(GOOD, encoding="utf-8")
            problems = {item["check"] for item in RENDER.check_page(
                self.browser, page, ["not measured"])}
            self.assertNotIn("literal", problems)

    def test_color_custom_property_declared_outside_tokens_css_is_rejected(self):
        html = GOOD.replace("</style>", ":root{--color-accent:tomato}</style>")
        self.assertIn("literal", self.check("color-token-inline", html))

    def test_existing_token_name_does_not_authorize_an_inline_color_override(self):
        html = GOOD.replace("</style>", ":root{--ink:tomato}</style>")
        self.assertIn("literal", self.check("existing-color-token-override", html))

    def test_arbitrarily_named_custom_property_cannot_evade_the_colour_gate(self):
        # The provenance gate must key off the VALUE being a colour literal, not the
        # property name starting with --color-, or renaming the property evades it.
        html = GOOD.replace("</style>", ":root{--my-surface:tomato}</style>")
        self.assertIn("literal", self.check("renamed-color-token-inline", html))
        # Numeric/spacing custom properties under an arbitrary name remain unaffected.
        spacing = GOOD.replace("</style>", ":root{--my-gap:8px}</style>")
        self.assertNotIn("literal", self.check("renamed-spacing-token", spacing))

    def test_named_color_keyword_is_rejected_like_a_hex_literal(self):
        html = GOOD.replace("</style>", "p{color:tomato}</style>")
        self.assertIn("literal", self.check("named-color", html))

    def test_system_color_keyword_is_allowed_only_inside_forced_colors(self):
        outside = GOOD.replace("</style>", "p{color:Highlight}</style>")
        self.assertIn("literal", self.check("system-color-bare", outside))
        scoped = GOOD.replace("</style>", "@media (forced-colors:active){p{color:Highlight}}</style>")
        self.assertNotIn("literal", self.check("system-color-scoped", scoped))

    def test_currentcolor_and_transparent_keywords_remain_allowed(self):
        html = GOOD.replace("</style>", "p{color:currentcolor;background:transparent}</style>")
        self.assertNotIn("literal", self.check("allowed-keywords", html))

    def test_typography_scale_accepts_generated_type_convention_and_rem_em_units(self):
        html = GOOD.replace("</style>",
            ":root{--type-body-size:0.875rem;--type-heading-size:1.75em}</style>")
        html = html.replace("button{min-width", "button{font-size:inherit;min-width")
        quality = {"typography_scale_px": [14, 28]}
        problems, _ = self.profile_check("type-tokens-rem-em", html, quality)
        self.assertNotIn("font-size-token-scale", {item["check"] for item in problems})

        invalid = html.replace("--type-heading-size:1.75em", "--type-heading-size:1.8em")
        problems, _ = self.profile_check("type-tokens-rem-em-bad", invalid, quality)
        self.assertIn("font-size-token-scale", {item["check"] for item in problems})

    def test_full_page_screenshot_reports_truncation_instead_of_silently_clamping(self):
        # round_prep.py (not owned by this change) is the only current caller that
        # passes full_page=True, so this exercises Browser.screenshot directly rather
        # than render_check's own --capture flag, which only takes fixed-viewport shots.
        page = Path(self.temp.name) / "tall.html"
        page.write_text(GOOD.replace("<main>", '<main><div style="height:7000px">tall</div>'),
                        encoding="utf-8")
        self.browser.load(page.resolve().as_uri(), RENDER.CHECK_WIDTH, "light", False)
        result = self.browser.screenshot(Path(self.temp.name) / "tall.png", full_page=True)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["height"], RENDER.FULL_PAGE_HEIGHT_LIMIT)

        short_page = Path(self.temp.name) / "short.html"
        short_page.write_text(GOOD, encoding="utf-8")
        self.browser.load(short_page.resolve().as_uri(), RENDER.CHECK_WIDTH, "light", False)
        result = self.browser.screenshot(Path(self.temp.name) / "short.png", full_page=True)
        self.assertFalse(result["truncated"])

    def test_declared_ready_signal_that_never_becomes_true_is_a_timeout_finding(self):
        html = GOOD.replace('<html lang="en">', '<html lang="en" data-ready="false">')
        self.assertIn("ready-timeout", self.check("never-ready", html))

    def test_declared_ready_signal_that_becomes_true_quickly_is_not_a_finding(self):
        html = GOOD.replace('<html lang="en">', '<html lang="en" data-ready="false">')
        html = html.replace("</body>",
            '<script>document.documentElement.setAttribute("data-ready","true")</script></body>')
        self.assertNotIn("ready-timeout", self.check("ready-fast", html))

    def test_report_json_has_schema_version_and_tier2_only_findings(self):
        page = Path(self.temp.name) / "report.html"
        page.write_text(GOOD, encoding="utf-8")
        report_path = Path(self.temp.name) / "report.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = RENDER.main([str(page), "--chrome", CHROME, "--report", str(report_path)])
        self.assertEqual(result, 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["kind"], "render_check")
        # No --rubric was given, so the report is explicitly unscoped, not silently
        # substitutable for a rubric-scoped run.
        self.assertIsNone(report["rubric_sha256"])
        entry = report["pages"][0]
        self.assertEqual(entry["source_sha256"], RENDER.hashlib.sha256(page.read_bytes()).hexdigest())
        self.assertNotIn("tier1", entry)
        self.assertEqual(entry["tier2"]["status"], "pass")
        self.assertEqual(entry["tier2"]["findings"], [])

    def test_report_tier2_fails_on_a_rendered_defect_and_binds_rubric_digest(self):
        page = Path(self.temp.name) / "report-bad.html"
        page.write_text(GOOD.replace("</style>", "p{color:tomato}</style>"), encoding="utf-8")
        rubric_path = Path(self.temp.name) / "rubric.json"
        rubric_path.write_text(json.dumps({
            "target_platforms": {
                "mobile": False, "tablet": False, "laptop": False,
                "desktop": True, "wide": False,
            },
            "target_platform_decision": "Check the desktop CSS profile.",
        }), encoding="utf-8")
        report_path = Path(self.temp.name) / "report-bad.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            RENDER.main([str(page), "--chrome", CHROME, "--rubric", str(rubric_path),
                         "--report", str(report_path)])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        entry = report["pages"][0]
        self.assertNotIn("tier1", entry)
        self.assertEqual(entry["tier2"]["status"], "fail")
        self.assertIn("literal", {item["check"] for item in entry["tier2"]["findings"]})
        # A rubric-scoped run's report carries the rubric's own digest, binding the
        # report to the rubric it was actually evaluated against.
        self.assertIsNotNone(report["rubric_sha256"])
        self.assertEqual(len(report["rubric_sha256"]), 64)

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
        html = GOOD.replace("</style>",
            ":root{--font-size-body:14px;--font-size-heading:28px;--space-small:8px}</style>")
        html = html.replace("button{min-width", "button{font-size:inherit;min-width")
        quality = {"typography_scale_px": [14, 28], "spacing_scale_px": [4, 8, 16]}
        problems, _ = self.profile_check("scales-pass", html, quality)
        self.assertNotIn("typography-scale", {item["check"] for item in problems})
        self.assertNotIn("spacing-token-scale", {item["check"] for item in problems})

        invalid = html.replace("--space-small:8px", "--space-small:9px")
        problems, _ = self.profile_check("scales-fail", invalid, quality)
        self.assertIn("spacing-token-scale", {item["check"] for item in problems})

    def test_spacing_scale_allows_automatic_centering_without_accepting_off_scale_gaps(self):
        html = GOOD.replace("</style>", ":root{--space-small:8px}</style>")
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
        html = html.replace("</style>", ":root{--space-small:8px}</style>")
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
        html = html.replace("</style>", ":root{--space-zero:0px;--space-small:8px}</style>")
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
