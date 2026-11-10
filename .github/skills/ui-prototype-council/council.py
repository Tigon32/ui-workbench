#!/usr/bin/env python3
"""Score a prototype council round and decide, deterministically, what happens next.

The reviewers judge; this script does the arithmetic and makes the stop decision, so
no model decides whether a model's scores were good enough. Python standard library only.

Run layout, all JSON:
  <run>/rubric.json                 dimensions, weights, anchors, caps, calibration margin
  <run>/round-N/round.json          items, calibration pair, keep count, model, browser
  <run>/round-N/reviewer-<id>.json  one independent, blind score sheet per reviewer

  council.py --write  <run>   compute and write <run>/round-N/report.md for every round
  council.py --verify <run>   recompute, require byte-identical reports, print the verdict

Exit 0 and print WINNER <id>, NO_CLEAR_WINNER, VOID or CONTINUE <ids>. Exit 1 on an
invalid run or a report that does not match its inputs.
"""

import argparse
import json
import math
import sys
from pathlib import Path

MIN_REASON = 20
MIN_VALID_REVIEWERS = 2


class RunError(Exception):
    pass


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RunError(f"{path}: {error}") from error


def check_rubric(rubric):
    dims = rubric.get("dimensions")
    if not isinstance(dims, list) or not dims:
        raise RunError("rubric: dimensions must be a non-empty list")
    seen = set()
    for dim in dims:
        ident = dim.get("id")
        if not isinstance(ident, str) or ident in seen:
            raise RunError(f"rubric: missing or duplicate dimension id: {ident!r}")
        seen.add(ident)
        if not isinstance(dim.get("weight"), (int, float)) or dim["weight"] <= 0:
            raise RunError(f"rubric: {ident}: weight must be positive")
        anchors = dim.get("anchors", {})
        if sorted(anchors) != ["3", "5", "7", "9"] or not all(anchors.values()):
            raise RunError(f"rubric: {ident}: anchors 3, 5, 7 and 9 are all required")
    if not any(dim.get("critical") for dim in dims):
        raise RunError("rubric: at least one dimension must be critical")
    caps = rubric.get("caps", {})
    for key in ("max_rounds", "max_reviewers", "max_prototypes"):
        if not isinstance(caps.get(key), int) or caps[key] < 1:
            raise RunError(f"rubric: caps.{key} must be a positive integer")
    if not isinstance(rubric.get("calibration_margin"), (int, float)):
        raise RunError("rubric: calibration_margin is required")
    if rubric.get("rules_version", 1) not in (1, 2):
        raise RunError("rubric: rules_version must be 1 or 2")
    return dims


def check_sheet(sheet, items, dims, name):
    for key in ("reviewer", "model", "seed"):
        if key not in sheet:
            raise RunError(f"{name}: '{key}' is required")
    order = sheet.get("order")
    if not isinstance(order, list) or sorted(order) != sorted(items) or len(set(order)) != len(order):
        raise RunError(f"{name}: order must list every item exactly once")
    scores = sheet.get("scores", {})
    if sorted(scores) != sorted(items):
        raise RunError(f"{name}: scores must cover every item and nothing else")
    for item in items:
        for dim in dims:
            entry = scores[item].get(dim["id"])
            if not isinstance(entry, dict):
                raise RunError(f"{name}: {item}: missing dimension {dim['id']}")
            # The reason comes first and must say something, so a score cannot be
            # produced without a stated justification.
            if list(entry)[:2] != ["why", "score"]:
                raise RunError(f"{name}: {item}.{dim['id']}: 'why' must precede 'score'")
            if not isinstance(entry["why"], str) or len(entry["why"].strip()) < MIN_REASON:
                raise RunError(f"{name}: {item}.{dim['id']}: reason too short")
            score = entry["score"]
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
                raise RunError(f"{name}: {item}.{dim['id']}: score must be an integer 1-10")


def weighted(entry, dims, only_critical=False):
    chosen = [d for d in dims if d.get("critical") or not only_critical]
    total = sum(d["weight"] for d in chosen)
    return sum(entry[d["id"]]["score"] * d["weight"] for d in chosen) / total


def fmt(value):
    return f"{value:.2f}"


def check_meta(meta, round_dir, caps, previous_keep):
    items = meta.get("items", [])
    calibration = meta.get("calibration", {})
    weak, strong = calibration.get("weak"), calibration.get("strong")
    if not items or len(set(items)) != len(items):
        raise RunError(f"{round_dir}: items must be a non-empty list of unique ids")
    if weak not in items or strong not in items or weak == strong:
        raise RunError(f"{round_dir}: calibration weak and strong must be two listed items")
    contestants = [i for i in items if i not in (weak, strong)]
    if not contestants or len(contestants) > caps["max_prototypes"]:
        raise RunError(f"{round_dir}: prototype count must be 1..{caps['max_prototypes']}")
    if meta.get("round", 0) > caps["max_rounds"]:
        raise RunError(f"{round_dir}: round {meta.get('round')} exceeds the cap")
    for key in ("model", "browser", "date"):
        if not meta.get(key):
            raise RunError(f"{round_dir}: round.json must record '{key}'")
    reveal = meta.get("reveal", {})
    if sorted(reveal) != sorted(items):
        raise RunError(f"{round_dir}: reveal must map every blind id after scoring")
    if previous_keep is not None:
        entered = {reveal[i] for i in contestants}
        if not entered <= previous_keep:
            raise RunError(f"{round_dir}: {sorted(entered - previous_keep)} were eliminated earlier")
    return items, weak, strong, contestants, reveal


def score_round(rubric, dims, round_dir, previous_keep):
    meta = load(round_dir / "round.json")
    caps = rubric["caps"]
    rules = rubric.get("rules_version", 1)
    items, weak, strong, contestants, reveal = check_meta(meta, round_dir, caps, previous_keep)

    sheets = sorted(round_dir.glob("reviewer-*.json"))
    if not sheets or len(sheets) > caps["max_reviewers"]:
        raise RunError(f"{round_dir}: reviewer count must be 1..{caps['max_reviewers']}")
    loaded = []
    for path in sheets:
        sheet = load(path)
        check_sheet(sheet, items, dims, path.name)
        loaded.append(sheet)
    orders = [tuple(s["order"]) for s in loaded]
    if len(items) > 2 and len(set(orders)) != len(orders):
        raise RunError(f"{round_dir}: reviewers must see different shuffled orders")

    lines = [f"# Round {meta['round']}", "",
             f"Model: {meta['model']}. Browser: {meta['browser']}. Date: {meta['date']}.",
             f"Reviewers: {len(loaded)}. Calibration margin required: "
             f"{fmt(rubric['calibration_margin'])}.", "", "## Calibration", "",
             "| Reviewer | Strong | Weak | Margin | Result |", "|---|---|---|---|---|"]
    valid = []
    for sheet in loaded:
        high = weighted(sheet["scores"][strong], dims)
        low = weighted(sheet["scores"][weak], dims)
        ok = high - low >= rubric["calibration_margin"]
        lines.append(f"| {sheet['reviewer']} | {fmt(high)} | {fmt(low)} | {fmt(high - low)} | "
                     f"{'kept' if ok else 'excluded'} |")
        if ok:
            valid.append(sheet)
    lines.append("")
    if len(valid) < MIN_VALID_REVIEWERS:
        lines += [f"Only {len(valid)} reviewer(s) separated the calibration pair. "
                  "The round is void and decides nothing.", "", "## Verdict", "", "VOID", ""]
        return "\n".join(lines), ("VOID", [])

    stats = {}
    for item in contestants:
        totals = [weighted(s["scores"][item], dims) for s in valid]
        critical = [weighted(s["scores"][item], dims, only_critical=True) for s in valid]
        per_dim = {d["id"]: [s["scores"][item][d["id"]]["score"] for s in valid] for d in dims}
        stats[item] = {"mean": sum(totals) / len(totals), "spread": max(totals) - min(totals),
                       "critical": critical, "dims": per_dim}
    ranked = sorted(contestants, key=lambda i: (-stats[i]["mean"], reveal[i]))

    lines += ["## Scores", "",
              "Weighted mean and spread (maximum minus minimum) across kept reviewers.", "",
              "| Item | Revealed | Mean | Spread | " + " | ".join(d["id"] for d in dims) + " |",
              "|---|---|---|---|" + "---|" * len(dims)]
    for item in ranked:
        s = stats[item]
        cells = [f"{fmt(sum(v) / len(v))} ±{max(v) - min(v)}" for v in s["dims"].values()]
        lines.append(f"| {item} | {reveal[item]} | {fmt(s['mean'])} | {fmt(s['spread'])} | "
                     + " | ".join(cells) + " |")
    lines.append("")

    leader = ranked[0]
    lines += ["## Stop condition", ""]
    if len(ranked) == 1:
        lines += ["One prototype remains and nothing is compared.", ""]
        verdict = ("WINNER", [leader])
    else:
        second = ranked[1]
        disagreement = max(stats[leader]["spread"], stats[second]["spread"])
        lead = stats[leader]["mean"] - stats[second]["mean"]
        if rules >= 2:
            # A shared top-anchor score is a tie, not a loss: the leader must not trail any
            # rival for any reviewer, and must lead the runner-up on the critical mean.
            leads_every = all(
                stats[leader]["critical"][r] >= max(stats[o]["critical"][r] for o in ranked[1:])
                for r in range(len(valid))) and (
                sum(stats[leader]["critical"]) > sum(stats[second]["critical"]))
        else:
            leads_every = all(
                stats[leader]["critical"][r] > max(stats[o]["critical"][r] for o in ranked[1:])
                for r in range(len(valid)))
        lines += [f"Leader {leader} ({reveal[leader]}) leads {second} ({reveal[second]}) by "
                  f"{fmt(lead)}. Measured disagreement is {fmt(disagreement)}.",
                  f"Leads every kept reviewer on the critical dimensions: "
                  f"{'yes' if leads_every else 'no'}.", ""]
        verdict = ("WINNER", [leader]) if leads_every and lead > disagreement else None

    if verdict is None and meta["round"] >= caps["max_rounds"]:
        verdict = ("NO_CLEAR_WINNER", [])
    if verdict is None:
        keep = meta.get("keep", min(len(ranked), max(2, math.ceil(len(ranked) / 2))))
        if not isinstance(keep, int) or not 2 <= keep <= len(ranked):
            raise RunError(f"{round_dir}: keep must be 2..{len(ranked)}")
        cut = stats[ranked[keep - 1]]["mean"]
        if rules >= 2:
            # An item within the measured disagreement of the cut is not distinguishable
            # from the last kept item, so it is kept too.
            noise = stats[ranked[keep - 1]]["spread"]
            cut -= max(noise, max(stats[i]["spread"] for i in ranked[keep:]) if ranked[keep:] else 0)
        # A tie at the cut keeps both, so elimination never turns on sort order.
        kept = [i for i in ranked if stats[i]["mean"] >= cut]
        dropped = [i for i in ranked if i not in kept]
        if dropped:
            lines += ["## Eliminated", ""]
            for item in dropped:
                worst = sorted(stats[item]["dims"].items(), key=lambda kv: (sum(kv[1]), kv[0]))[:2]
                lines.append(f"- {item} ({reveal[item]}): mean {fmt(stats[item]['mean'])}; weakest "
                             + ", ".join(f"{k} {fmt(sum(v) / len(v))}" for k, v in worst))
            lines.append("")
        verdict = ("CONTINUE", kept)
    names = [reveal[i] for i in verdict[1]]
    lines += ["## Verdict", "", f"{verdict[0]} {' '.join(names)}".rstrip(), "",
              "Scores are directional. Model scoring is noisy and order-sensitive, and a win "
              "must also be visible in the annotated screenshots.", ""]
    return "\n".join(lines), (verdict[0], names)


def run(run_dir, write):
    rubric = load(run_dir / "rubric.json")
    dims = check_rubric(rubric)
    rounds = sorted((p for p in run_dir.glob("round-*") if p.is_dir()),
                    key=lambda p: int(p.name.split("-")[1]))
    if not rounds:
        raise RunError(f"{run_dir}: no rounds")
    keep, verdict = None, None
    for expected, round_dir in enumerate(rounds, start=1):
        if round_dir.name != f"round-{expected}":
            raise RunError(f"{round_dir}: rounds must be numbered 1, 2, 3 without gaps")
        if verdict and verdict[0] in ("WINNER", "NO_CLEAR_WINNER"):
            raise RunError(f"{round_dir}: the run already ended")
        if load(round_dir / "round.json").get("round") != expected:
            raise RunError(f"{round_dir}: round.json round number does not match the folder")
        report, verdict = score_round(rubric, dims, round_dir, keep)
        target = round_dir / "report.md"
        if write:
            target.write_text(report, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != report:
            raise RunError(f"{target}: does not match its inputs; rerun with --write and review")
        if verdict[0] == "CONTINUE":
            keep = set(verdict[1])
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path, metavar="RUN")
    mode.add_argument("--verify", type=Path, metavar="RUN")
    args = parser.parse_args(argv)
    try:
        status, names = run(args.write or args.verify, write=bool(args.write))
    except RunError as error:
        print(f"council: {error}", file=sys.stderr)
        return 1
    print(f"{status} {' '.join(names)}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
