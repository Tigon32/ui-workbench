#!/usr/bin/env python3
"""Prepare one blind council round: identifiers, seeded orders, captures and sealed mapping.

Python standard library and the installed Chrome only. It reuses render_check.py.

  round_prep.py prepare --run RUN --round N --blind DIR --seed S --model M --keep K \
      --strong NAME --weak NAME [--state LABEL=#FRAGMENT ...] NAME=FOLDER [NAME=FOLDER ...]
  round_prep.py reveal --run RUN --round N --blind DIR

`prepare` writes RUN/round-N/round.json without the mapping. It writes the captures for
reviewers into DIR/<blind id>/ and the mapping into DIR/sealed.json. Keep DIR out of every
reviewer's context except its own blind item folders, and never give a reviewer
sealed.json. It prints one seeded item order per reviewer. `reveal` copies the sealed
mapping into round.json after every sheet is in.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import random
import re
import shutil
import string
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("render_check", HERE / "render_check.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)
SPEC = importlib.util.spec_from_file_location("scope_intake", HERE / "intake.py")
INTAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTAKE)

VIEWS = (("light", False, 1280), ("dark", False, 1280))
CAPTURE_STATE_WIDTH = 1280
SHEET = (("high-contrast-dark", False, 1280), ("light", True, 1280), ("light", False, 320))


def hash_source_tree(folder):
    """Folder-wide source identity: sha256 over every local file's relative path and
    bytes under `folder` (DESIGN.md and all other source assets), sorted for a stable
    result. This deliberately reuses render_check.py's own `_folder_digest` algorithm
    verbatim (rather than reimplementing the same idea slightly differently) so a
    round's source_tree_sha256 and a render_check --report's source_tree_sha256 for
    the same folder are byte-identical and directly comparable. render_check.py owns
    that helper; round_prep.py only calls it (now the public `RENDER.folder_digest`).
    Generated captures/outputs written outside `folder` are naturally excluded.
    """
    return RENDER.folder_digest(folder)


def blind_ids(rng, count):
    ids = set()
    while len(ids) < count:
        ids.add("".join(rng.choice(string.ascii_uppercase) for _ in range(3)))
    return sorted(ids, key=lambda _: rng.random())


def create_item_directory(blind, ident):
    out = blind / ident
    try:
        out.mkdir()
    except FileExistsError as error:
        raise SystemExit(
            f"round-prep: output ID {ident} already exists; choose a fresh blind directory"
        ) from error
    return out


def prepare_blind_directory(blind):
    blind.mkdir(parents=True, exist_ok=True)
    if next(blind.iterdir(), None) is not None:
        raise SystemExit(
            "round-prep: blind directory is not empty; choose a fresh output directory"
        )


def ensure_round_is_new(run, round_number):
    round_file = run / f"round-{round_number}" / "round.json"
    if round_file.exists():
        raise SystemExit(
            "round-prep: round metadata already exists; choose a new run directory or round number"
        )


def capture_full_page(browser, path, truncations, ident):
    """Full-page screenshot() now reports {"truncated": bool, "height": int} instead
    of silently clamping at 6000px; a truncated capture is an evidence integrity
    finding (part of the image is missing), not a cosmetic detail, so every full-page
    call site routes through here to record it for a hard failure at the end of
    `prepare`, rather than letting the return value be silently discarded."""
    result = browser.screenshot(path, full_page=True) or {}
    if result.get("truncated"):
        truncations.append({"item": ident, "path": path.name, "height": result.get("height")})


def contact_sheet(browser, images, target):
    """Lay three captures side by side at reduced scale and capture that page. The
    page and its <img> sources commonly live in different trusted folders (the
    round's own output folder, plus each item's temp capture folder), so every
    folder involved is added to the guard's allow-list rather than replacing it
    with a single folder."""
    cells = "".join(
        f'<figure><img src="{path.resolve().as_uri()}" alt=""><figcaption>{label}</figcaption></figure>'
        for label, path in images)
    page = target.with_suffix(".html")
    page.write_text(
        "<!doctype html><meta charset=utf-8><style>body{margin:0;display:flex;gap:16px;"
        "padding:16px;background:#808080;font:16px system-ui;align-items:flex-start}"
        "figure{margin:0}img{display:block;height:675px}figcaption{color:#fff;padding-top:4px}"
        f"</style>{cells}", encoding="utf-8")
    browser.add_allowed_folder(target.parent)
    for _, path in images:
        browser.add_allowed_folder(path.parent)
    browser.call("Emulation.setDeviceMetricsOverride", width=2200, height=720,
                 deviceScaleFactor=1, mobile=False)
    browser.call("Emulation.setEmulatedMedia", features=[])
    browser.call("Page.navigate", wait_event="Page.loadEventFired", url=page.as_uri())
    browser.last_ready = RENDER.wait_ready(browser)
    browser.screenshot(target)
    page.unlink()


def prepare(args):
    profiles = RENDER.PROFILES.load_rubric(args.rubric) if args.rubric else None
    try:
        pairs = [item.split("=", 1) for item in args.items]
        if any(len(pair) != 2 or not all(pair) for pair in pairs):
            raise ValueError
        items = dict(pairs)
    except ValueError as error:
        raise SystemExit("round-prep: each item must be NAME=FOLDER") from error
    if len(items) != len(args.items):
        raise SystemExit("round-prep: item names must be unique")
    if args.legacy_unscoped and (args.brief or args.directions):
        raise SystemExit(
            "round-prep: --legacy-unscoped cannot be combined with --brief/--directions")
    if not args.legacy_unscoped and not args.brief:
        raise SystemExit(
            "round-prep: pass --brief and --directions, or explicitly set --legacy-unscoped")
    scoped_files = {}
    if args.brief:
        if not args.directions:
            raise SystemExit("round-prep: --brief requires --directions with scope/KEEP evidence")
        brief = json.loads(args.brief.read_text(encoding="utf-8"))
        directions = json.loads(args.directions.read_text(encoding="utf-8"))
        if not isinstance(directions, list) or not all(isinstance(row, dict) for row in directions):
            raise SystemExit("round-prep: --directions must contain a direction list")
        expected = set(items) - {args.strong, args.weak}
        if {row.get("id") for row in directions} != expected or len(directions) != len(expected):
            raise SystemExit("round-prep: directions must name every non-calibration item exactly once")
        scope_report = INTAKE.validate(
            brief, root=args.brief.parent, current_brief_path=args.brief, directions=directions)
        blockers = [row["message"] for row in scope_report["findings"] if row["severity"] == "blocker"]
        if blockers:
            raise SystemExit("round-prep: " + "; ".join(blockers))
        scoped_files = {"project/brief": args.brief, "project/directions": args.directions}
    elif args.directions:
        raise SystemExit("round-prep: --directions requires --brief")
    for name in (args.strong, args.weak):
        if name not in items:
            raise SystemExit(f"round-prep: calibration item {name} is not listed")
    if profiles and len(args.state) > 5:
        raise SystemExit("round-prep: at most five state captures are allowed with a rubric")
    for label, fragment in args.state:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", label) or not fragment.startswith("#"):
            raise SystemExit("round-prep: state must use LABEL=#FRAGMENT with a safe label")
    sources = {}
    for name, folder in items.items():
        folder = Path(folder)
        page, design = folder / "index.html", folder / "DESIGN.md"
        if not page.is_file() or not design.is_file():
            raise SystemExit(f"round-prep: {folder} must contain index.html and DESIGN.md")
        sources[name] = (page, design, hashlib.sha256(page.read_bytes()).hexdigest(),
                         hash_source_tree(folder))
    if not Path(args.chrome).is_file():
        raise SystemExit(f"round-prep: Chrome not found at {args.chrome}")
    ensure_round_is_new(args.run, args.round)
    prepare_blind_directory(args.blind)
    rng = random.Random(args.seed)
    ids = blind_ids(rng, len(items))
    mapping = dict(zip(ids, items))
    browser = RENDER.Browser(args.chrome)
    truncations = []
    try:
        with tempfile.TemporaryDirectory() as temp:
            for ident, name in mapping.items():
                page, design, _, _ = sources[name]
                out = create_item_directory(args.blind, ident)
                for theme, forced, width in VIEWS:
                    browser.load(page.resolve().as_uri(), width, theme, forced)
                    capture_full_page(browser, out / f"{theme}-{width}.png", truncations, ident)
                if profiles:
                    by_width = {}
                    for profile, width in profiles["profiles"].items():
                        by_width.setdefault(width, []).append(profile)
                    for width, names in by_width.items():
                        label = "-".join(names)
                        for theme in ("light", "dark"):
                            browser.load(page.resolve().as_uri(), width, theme, False)
                            capture_full_page(
                                browser, out / f"profile-{label}-{theme}-{width}.png",
                                truncations, ident)
                    if RENDER.CHECK_WIDTH not in by_width:
                        browser.load(page.resolve().as_uri(), RENDER.CHECK_WIDTH, "light", True)
                        capture_full_page(
                            browser, out / f"high-contrast-forced-{RENDER.CHECK_WIDTH}.png",
                            truncations, ident)
                    browser.load(page.resolve().as_uri(), profiles["reflow_width"], "light", False)
                    capture_full_page(
                        browser, out / f"reflow-zoom-{profiles['reflow_width']}.png",
                        truncations, ident)
                shots = []
                for theme, forced, width in SHEET:
                    browser.load(page.resolve().as_uri(), width, theme, forced)
                    path = Path(temp) / f"{ident}-{theme}-{forced}-{width}.png"
                    browser.screenshot(path)
                    label = f"{theme}{' forced colors' if forced else ''} {width}px"
                    if profiles and width == RENDER.REFLOW_WIDTH:
                        label = f"{theme} {profiles['reflow_label']} {width}px"
                    shots.append((label, path))
                contact_sheet(browser, shots, out / "sheet.png")
                if profiles:
                    for label, fragment in args.state:
                        for width, names in by_width.items():
                            browser.call("Page.navigate", wait_event="Page.loadEventFired",
                                         url="about:blank")
                            browser.load(page.resolve().as_uri() + fragment, width, "light", False)
                            profile_label = "-".join(names)
                            capture_full_page(
                                browser, out / f"state-{label}-{profile_label}-{width}.png",
                                truncations, ident)
                else:
                    for label, fragment in args.state:
                        # A fragment-only change is a same-document navigation with no load
                        # event, so leave the page first and every state loads fresh.
                        browser.call("Page.navigate", wait_event="Page.loadEventFired", url="about:blank")
                        browser.load(page.resolve().as_uri() + fragment, CAPTURE_STATE_WIDTH, "light", False)
                        capture_full_page(browser, out / f"state-{label}.png", truncations, ident)
                shutil.copyfile(design, out / "DESIGN.md")
                references = {
                    f"{ident}/{capture.name}": {
                        "path": capture.name,
                        "sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
                    }
                    for capture in sorted(out.glob("*.png"))
                }
                (out / "evidence-manifest.json").write_text(
                    json.dumps({"references": references}, indent=2) + "\n",
                    encoding="utf-8")
            version = browser.version
    finally:
        browser.close()
    round_dir = args.run / f"round-{args.round}"
    round_dir.mkdir(parents=True, exist_ok=True)
    meta = {"round": args.round, "date": datetime.date.today().isoformat(), "model": args.model,
            "browser": version, "items": ids,
            "calibration": {"strong": next(i for i, n in mapping.items() if n == args.strong),
                            "weak": next(i for i, n in mapping.items() if n == args.weak)},
            "keep": args.keep, "seed": args.seed}
    if profiles:
        meta["rubric_sha256"] = profiles["digest"]
        meta["target_profiles"] = RENDER.PROFILES.metadata(profiles)
        meta["source_sha256"] = {
            ident: sources[name][2] for ident, name in mapping.items()
        }
        meta["source_tree_sha256"] = {
            ident: sources[name][3] for ident, name in mapping.items()
        }
        meta["evidence_manifest"] = {
            f"{path.parent.name}/{path.name}": {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(args.blind.glob("*/*.png"))
        }
    # DESIGN.md is bound into the evidence manifest for every item so adoption
    # review can always resolve each item's design rationale, independent of
    # whether a rubric ran.
    meta.setdefault("evidence_manifest", {}).update({
        f"{ident}/DESIGN.md": {
            "path": str(sources[name][1].resolve()),
            "sha256": hashlib.sha256(sources[name][1].read_bytes()).hexdigest(),
        }
        for ident, name in mapping.items()
    })
    if scoped_files:
        meta.setdefault("evidence_manifest", {}).update({
            reference: {"path": str(path.resolve()),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for reference, path in scoped_files.items()
        })
        meta["scope_refs"] = {"brief": "project/brief", "directions": "project/directions"}
        meta["scope_contract"] = "scoped_v1"
    else:
        meta["scope_contract"] = "legacy_unscoped"
    # Rotations of one seeded shuffle: every reviewer sees a different order, and each
    # item moves through the positions, which spreads position bias across reviewers.
    base = list(ids)
    random.Random(args.seed + 1).shuffle(base)
    reviewer_orders = {}
    for reviewer in range(args.reviewers):
        shift = reviewer * len(base) // args.reviewers
        reviewer_orders[f"r{reviewer + 1}"] = base[shift:] + base[:shift]
    meta["reviewer_orders"] = reviewer_orders
    if truncations:
        # A truncated full-page capture is missing evidence (clamped at 6000px), not
        # a cosmetic detail, so it is recorded prominently in round metadata for
        # forensics *and* treated as a hard failure, mirroring the guard's own
        # "nonzero on violation, not a silent/soft finding" rule.
        meta["capture_truncations"] = truncations
    (round_dir / "round.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (args.blind / "sealed.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    for reviewer, order in reviewer_orders.items():
        print(json.dumps({"reviewer": reviewer, "seed": args.seed, "order": order}))
    print(f"round-prep: {version}; {len(ids)} items blinded into {args.blind}", file=sys.stderr)
    if truncations:
        names = ", ".join(f"{t['item']}/{t['path']} ({t['height']}px)" for t in truncations)
        raise SystemExit(f"round-prep: full-page capture(s) truncated at the 6000px clamp: {names}")


def reveal(args):
    round_file = args.run / f"round-{args.round}" / "round.json"
    meta = json.loads(round_file.read_text(encoding="utf-8"))
    meta["reveal"] = json.loads((args.blind / "sealed.json").read_text(encoding="utf-8"))
    round_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def parse_state(value):
    label, separator, fragment = value.partition("=")
    if not separator or not fragment.startswith("#") or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", label):
        raise argparse.ArgumentTypeError("state must be LABEL=#FRAGMENT with a safe label")
    return label, fragment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "reveal"):
        command = sub.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--round", type=int, required=True)
        command.add_argument("--blind", type=Path, required=True)
    prep = sub.choices["prepare"]
    prep.add_argument("--seed", type=int, required=True)
    prep.add_argument("--model", required=True)
    prep.add_argument("--keep", type=int, required=True)
    prep.add_argument("--reviewers", type=int, default=3)
    prep.add_argument("--strong", required=True)
    prep.add_argument("--weak", required=True)
    prep.add_argument("--chrome", default=RENDER.DEFAULT_CHROME)
    prep.add_argument("--rubric", type=Path,
                      help="shared JSON rubric with bounded web target profiles and optional quality checks")
    prep.add_argument("--brief", type=Path, help="canonical sponsor-confirmed scoped project brief")
    prep.add_argument("--directions", type=Path,
                      help="JSON list of non-calibration directions with view coverage and KEEP dispositions")
    prep.add_argument("--legacy-unscoped", action="store_true",
                      help="explicit compatibility path for a round with no brief/directions scope; "
                           "records scope_contract=legacy_unscoped instead of scoped_v1")
    prep.add_argument("--state", action="append", default=[], type=parse_state,
                      metavar="LABEL=#FRAGMENT",
                      help="also capture the page opened at this URL fragment, in light at 1280 pixels")
    prep.add_argument("items", nargs="+", metavar="NAME=FOLDER")
    args = parser.parse_args(argv)
    try:
        prepare(args) if args.command == "prepare" else reveal(args)
    except (RENDER.PROFILES.RubricError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"round-prep: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
