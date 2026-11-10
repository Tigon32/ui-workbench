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
import importlib.util
import json
import random
import shutil
import string
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("render_check", HERE / "render_check.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)

VIEWS = (("light", False, 1280), ("dark", False, 1280))
CAPTURE_STATE_WIDTH = 1280
SHEET = (("high-contrast-dark", False, 1280), ("light", True, 1280), ("light", False, 320))


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


def contact_sheet(browser, images, target):
    """Lay three captures side by side at reduced scale and capture that page."""
    cells = "".join(
        f'<figure><img src="{path.resolve().as_uri()}" alt=""><figcaption>{label}</figcaption></figure>'
        for label, path in images)
    page = target.with_suffix(".html")
    page.write_text(
        "<!doctype html><meta charset=utf-8><style>body{margin:0;display:flex;gap:16px;"
        "padding:16px;background:#808080;font:16px system-ui;align-items:flex-start}"
        "figure{margin:0}img{display:block;height:675px}figcaption{color:#fff;padding-top:4px}"
        f"</style>{cells}", encoding="utf-8")
    browser.call("Emulation.setDeviceMetricsOverride", width=2200, height=720,
                 deviceScaleFactor=1, mobile=False)
    browser.call("Emulation.setEmulatedMedia", features=[])
    browser.call("Page.navigate", wait_event="Page.loadEventFired", url=page.as_uri())
    browser.screenshot(target)
    page.unlink()


def prepare(args):
    items = dict(item.split("=", 1) for item in args.items)
    for name in (args.strong, args.weak):
        if name not in items:
            raise SystemExit(f"round-prep: calibration item {name} is not listed")
    ensure_round_is_new(args.run, args.round)
    prepare_blind_directory(args.blind)
    rng = random.Random(args.seed)
    ids = blind_ids(rng, len(items))
    mapping = dict(zip(ids, items))
    browser = RENDER.Browser(args.chrome)
    try:
        with tempfile.TemporaryDirectory() as temp:
            for ident, name in mapping.items():
                folder = Path(items[name])
                page = folder / "index.html"
                out = create_item_directory(args.blind, ident)
                for theme, forced, width in VIEWS:
                    browser.load(page.resolve().as_uri(), width, theme, forced)
                    browser.screenshot(out / f"{theme}-{width}.png", full_page=True)
                shots = []
                for theme, forced, width in SHEET:
                    browser.load(page.resolve().as_uri(), width, theme, forced)
                    path = Path(temp) / f"{ident}-{theme}-{forced}-{width}.png"
                    browser.screenshot(path)
                    shots.append((f"{theme}{' forced colors' if forced else ''} {width}px", path))
                contact_sheet(browser, shots, out / "sheet.png")
                for label, fragment in args.state:
                    # A fragment-only change is a same-document navigation with no load
                    # event, so leave the page first and every state loads fresh.
                    browser.call("Page.navigate", wait_event="Page.loadEventFired", url="about:blank")
                    browser.load(page.resolve().as_uri() + fragment, CAPTURE_STATE_WIDTH, "light", False)
                    browser.screenshot(out / f"state-{label}.png", full_page=True)
                shutil.copyfile(folder / "DESIGN.md", out / "DESIGN.md")
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
    (round_dir / "round.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (args.blind / "sealed.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    # Rotations of one seeded shuffle: every reviewer sees a different order, and each
    # item moves through the positions, which spreads position bias across reviewers.
    base = list(ids)
    random.Random(args.seed + 1).shuffle(base)
    for reviewer in range(args.reviewers):
        shift = reviewer * len(base) // args.reviewers
        order = base[shift:] + base[:shift]
        print(json.dumps({"reviewer": f"r{reviewer + 1}", "seed": args.seed, "order": order}))
    print(f"round-prep: {version}; {len(ids)} items blinded into {args.blind}", file=sys.stderr)


def reveal(args):
    round_file = args.run / f"round-{args.round}" / "round.json"
    meta = json.loads(round_file.read_text(encoding="utf-8"))
    meta["reveal"] = json.loads((args.blind / "sealed.json").read_text(encoding="utf-8"))
    round_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


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
    prep.add_argument("--state", action="append", default=[], type=lambda v: tuple(v.split("=", 1)),
                      metavar="LABEL=#FRAGMENT",
                      help="also capture the page opened at this URL fragment, in light at 1280 pixels")
    prep.add_argument("items", nargs="+", metavar="NAME=FOLDER")
    args = parser.parse_args(argv)
    prepare(args) if args.command == "prepare" else reveal(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
