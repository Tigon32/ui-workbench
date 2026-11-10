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
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

MIN_REASON = 20
MIN_VALID_REVIEWERS = 2


class RunError(Exception):
    pass


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except (OSError, ValueError) as error:
        raise RunError(f"{path}: {error}") from error


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def number(value, lower, upper):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and lower <= value <= upper)


def check_rubric(rubric):
    if not isinstance(rubric, dict):
        raise RunError("rubric: expected an object")
    dims = rubric.get("dimensions")
    if not isinstance(dims, list) or not dims:
        raise RunError("rubric: dimensions must be a non-empty list")
    seen = set()
    for dim in dims:
        if not isinstance(dim, dict):
            raise RunError("rubric: every dimension must be an object")
        ident = dim.get("id")
        if not isinstance(ident, str) or ident in seen:
            raise RunError(f"rubric: missing or duplicate dimension id: {ident!r}")
        seen.add(ident)
        if not number(dim.get("weight"), 0, 1_000_000) or dim["weight"] == 0:
            raise RunError(f"rubric: {ident}: weight must be positive")
        anchors = dim.get("anchors", {})
        if (not isinstance(anchors, dict) or sorted(anchors) != ["3", "5", "7", "9"]
                or not all(isinstance(v, str) and v.strip() for v in anchors.values())):
            raise RunError(f"rubric: {ident}: anchors 3, 5, 7 and 9 are all required")
    if not any(dim.get("critical") for dim in dims):
        raise RunError("rubric: at least one dimension must be critical")
    caps = rubric.get("caps", {})
    if not isinstance(caps, dict):
        raise RunError("rubric: caps must be an object")
    for key in ("max_rounds", "max_reviewers", "max_prototypes"):
        if not isinstance(caps.get(key), int) or isinstance(caps[key], bool) or caps[key] < 1:
            raise RunError(f"rubric: caps.{key} must be a positive integer")
    if not number(rubric.get("calibration_margin"), 0, 9):
        raise RunError("rubric: calibration_margin is required")
    if type(rubric.get("rules_version", 1)) is not int or rubric.get("rules_version", 1) not in (1, 2, 3):
        raise RunError("rubric: rules_version must be 1, 2 or 3")
    gate = rubric.get("adoption_gate")
    if gate is not None:
        if not isinstance(gate, dict) or set(gate) != {"total_min", "every_dimension_min", "critical_min"}:
            raise RunError("rubric: adoption_gate requires total_min, every_dimension_min and critical_min")
        for key, lower, upper in (("total_min", 0, 100), ("every_dimension_min", 1, 10), ("critical_min", 1, 10)):
            if not number(gate[key], lower, upper):
                raise RunError(f"rubric: adoption_gate.{key} must be finite and in {lower}..{upper}")
    if rubric.get("rules_version", 1) >= 3:
        check_catalogue(rubric, seen)
    return dims


def check_catalogue(rubric, seen):
    if type(rubric.get("catalogue_version")) is not int or rubric["catalogue_version"] != 1:
        raise RunError("rubric: catalogue_version must be 1")
    if rubric.get("renderer") != "web":
        raise RunError("rubric: only the web renderer is supported; native evidence needs a separate qualification")
    defaults = load(Path(__file__).with_name("rubric-default.json"))
    expected = {d["id"] for d in defaults["dimensions"]}
    excluded = rubric.get("excluded_dimensions", [])
    if not isinstance(excluded, list):
        raise RunError("rubric: excluded_dimensions must be a list")
    omitted = set()
    for entry in excluded:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] not in expected
                or entry["id"] in seen or entry["id"] in omitted
                or not isinstance(entry.get("reason"), str) or len(entry["reason"].strip()) < MIN_REASON):
            raise RunError("rubric: each exclusion needs one omitted default id and a substantive reason")
        omitted.add(entry["id"])
    if expected - seen != omitted:
        raise RunError(f"rubric: justify omitted default dimensions: {sorted(expected - seen - omitted)}")
    for dim in rubric["dimensions"]:
        if (not isinstance(dim.get("group"), str) or not dim["group"].strip()
                or not isinstance(dim.get("title"), str) or not dim["title"].strip()
                or not number(dim.get("floor"), 1, 10) or type(dim.get("critical")) is not bool):
            raise RunError(f"rubric: {dim['id']} needs title, group, floor and boolean critical")
    if not isinstance(rubric.get("adoption_decision"), str) or len(rubric["adoption_decision"].strip()) < MIN_REASON:
        raise RunError("rubric: record the adoption threshold decision before scoring")


def check_sheet(sheet, items, dims, name, rules=1, references=None):
    if not isinstance(sheet, dict):
        raise RunError(f"{name}: expected an object")
    for key in ("reviewer", "model", "seed"):
        if key not in sheet:
            raise RunError(f"{name}: '{key}' is required")
    if rules >= 3 and (
            any(not isinstance(sheet[k], str) or not sheet[k].strip() for k in ("reviewer", "model"))
            or type(sheet["seed"]) is not int or not 0 <= sheet["seed"] < 2**64):
        raise RunError(f"{name}: reviewer/model must be named and seed must be a nonnegative 64-bit integer")
    order = sheet.get("order")
    if (not isinstance(order, list) or any(not isinstance(v, str) for v in order)
            or sorted(order) != sorted(items) or len(set(order)) != len(order)):
        raise RunError(f"{name}: order must list every item exactly once")
    scores = sheet.get("scores", {})
    if not isinstance(scores, dict) or sorted(scores) != sorted(items):
        raise RunError(f"{name}: scores must cover every item and nothing else")
    if rules >= 3 and sheet.get("reviewer_kind") not in ("human", "model", "generator"):
        raise RunError(f"{name}: reviewer_kind must be human, model or generator")
    for item in items:
        if not isinstance(scores[item], dict):
            raise RunError(f"{name}: {item}: expected dimension scores")
        if rules >= 3 and set(scores[item]) != {d["id"] for d in dims}:
            raise RunError(f"{name}: {item}: scores must cover exactly the declared dimensions")
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
            if rules >= 3:
                status = entry.get("evidence_status")
                refs = entry.get("evidence")
                if (status not in ("observed", "not_assessed", "blocked", "unsupported")
                        or not isinstance(refs, list)
                        or any(not isinstance(ref, str) or ref not in (references or {}) for ref in refs)):
                    raise RunError(f"{name}: {item}.{dim['id']}: invalid evidence status or references")
                if status != "observed":
                    if score is not None:
                        raise RunError(f"{name}: {item}.{dim['id']}: unobserved evidence must have a null score")
                    continue
                if not refs:
                    raise RunError(f"{name}: {item}.{dim['id']}: observed scores need evidence")
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
                raise RunError(f"{name}: {item}.{dim['id']}: score must be an integer 1-10")


def design_total(raw):
    return 100 * (raw - 1) / 9


def check_evidence(meta, items, round_dir):
    manifest = meta.get("evidence_manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise RunError(f"{round_dir}: evidence_manifest is required for rules_version 3")
    sources = meta.get("source_sha256")
    if (not isinstance(sources, dict) or set(sources) != set(items)
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in sources.values())):
        raise RunError(f"{round_dir}: source_sha256 must identify every item")
    for ref, artifact in manifest.items():
        if (not isinstance(ref, str) or not ref or not isinstance(artifact, dict)
                or not isinstance(artifact.get("path"), str)
                or not isinstance(artifact.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
            raise RunError(f"{round_dir}: invalid evidence manifest entry")
        path = Path(artifact["path"])
        if not path.is_absolute():
            path = round_dir / path
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise RunError(f"{round_dir}: evidence {ref} is unavailable") from error
        if actual != artifact["sha256"]:
            raise RunError(f"{round_dir}: evidence {ref} changed")
    return manifest


def check_profile_evidence(meta, round_dir):
    spec = importlib.util.spec_from_file_location("council_profiles", Path(__file__).with_name("profiles.py"))
    profiles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profiles)
    try:
        expected = profiles.metadata(profiles.load_rubric(round_dir.parent / "rubric.json"))
    except profiles.RubricError as error:
        raise RunError(f"{round_dir}: invalid rendered profile: {error}") from error
    if meta.get("target_profiles") != expected:
        raise RunError(f"{round_dir}: target profile evidence is missing or differs from the rubric")


def adoption_report(rubric, dims, contestants, valid, stats, meta):
    gate = rubric.get("adoption_gate")
    rules = rubric.get("rules_version", 1)
    if gate is None and rules < 3:
        return [], {}
    outcomes = {}
    lines = ["## Expert-design adoption", "",
             "Total /100 = 100 * (weighted raw mean - 1) / 9. Raw scores use 1-10.",
             "This is expert judgment, not measured usability, a percentage of compliance, or release approval.",
             "Floors apply to every kept reviewer, not only the average. Missing scores never become zero.", ""]
    lines += ["| Item | Design total /100 | Adoption | Reasons |", "|---|---|---|---|"]
    for item in contestants:
        s = stats[item]
        reasons = []
        if gate is None:
            reasons.append("project adoption thresholds are not declared")
        if s["mean"] is None:
            reasons.append("required evidence is unassessed")
        elif gate is not None:
            for sheet in valid:
                if design_total(weighted(sheet["scores"][item], dims)) < gate["total_min"]:
                    reasons.append(f"{sheet['reviewer']}: total below {gate['total_min']}")
                for dim in dims:
                    floor = max(gate["every_dimension_min"], dim.get("floor", 1),
                                gate["critical_min"] if dim.get("critical") else 1)
                    if sheet["scores"][item][dim["id"]]["score"] < floor:
                        reasons.append(f"{sheet['reviewer']}: {dim['id']} below {floor}")
        if rules < 3:
            reasons.append("legacy run has no verified evidence manifest")
        else:
            declared = meta.get("adoption_checks", {})
            checks = declared.get(item, {}) if isinstance(declared, dict) else {}
            for tier in ("tier1", "tier2"):
                check = checks.get(tier, {}) if isinstance(checks, dict) else {}
                if (not isinstance(check, dict) or check.get("status") != "pass"
                        or not isinstance(check.get("evidence"), list) or not check["evidence"]
                        or any(not isinstance(ref, str) or ref not in meta["evidence_manifest"]
                               for ref in check["evidence"])):
                    reasons.append(f"{tier} evidence is failed or unverified")
            zoom = meta.get("target_profiles", {}).get("desktop_zoom")
            if zoom and zoom.get("percentages"):
                check = checks.get("desktop_zoom", {}) if isinstance(checks, dict) else {}
                refs = check.get("evidence", []) if isinstance(check, dict) else []
                if (not isinstance(check, dict) or check.get("status") != "pass"
                        or not isinstance(refs, list) or not refs
                        or any(not isinstance(ref, str) or ref not in meta["evidence_manifest"]
                               for ref in refs)):
                    reasons.append("real desktop zoom evidence is unavailable or unverified")
                elif any(
                    not isinstance(meta["evidence_manifest"][ref], dict)
                    or meta["evidence_manifest"][ref].get("evidence_type") != "real_browser_zoom"
                    or meta["evidence_manifest"][ref].get("percentages") != zoom["percentages"]
                    or meta["evidence_manifest"][ref].get("source_sha256") != meta["source_sha256"][item]
                    for ref in refs
                ):
                    reasons.append("real desktop zoom evidence does not match the declared scope or source")
        total = "unavailable" if s["mean"] is None else fmt(design_total(s["mean"]))
        status = "NOT_ADOPTABLE" if reasons else "ADOPTABLE"
        outcomes[meta["reveal"][item]] = status
        lines.append(f"| {item} | {total} | {status} | {'; '.join(reasons) or 'Declared gates and score floors met'} |")
    if rules >= 3:
        lines += ["", "### Category scores", "",
                  "| Item | Group | Dimension | Raw mean /10 | Score /100 | Required floor /10 |",
                  "|---|---|---|---|---|---|"]
        for item in contestants:
            for dim in dims:
                values = stats[item]["dims"][dim["id"]]
                raw = None if any(v is None for v in values) else sum(values) / len(values)
                floor = dim["floor"] if gate is None else max(
                    gate["every_dimension_min"], dim["floor"],
                    gate["critical_min"] if dim.get("critical") else 1)
                lines.append(f"| {item} | {dim['group']} | {dim['id']} | "
                             f"{'unassessed' if raw is None else fmt(raw)} | "
                             f"{'unavailable' if raw is None else fmt(design_total(raw))} | {floor} |")
        lines += ["", "### Group subtotals", "",
                  "| Item | Group | Subtotal /100 |", "|---|---|---|"]
        for item in contestants:
            for group in dict.fromkeys(d["group"] for d in dims):
                chosen = [d for d in dims if d["group"] == group]
                complete = all(sheet["scores"][item][d["id"]]["score"] is not None
                               for sheet in valid for d in chosen)
                value = (sum(design_total(weighted(sheet["scores"][item], chosen))
                             for sheet in valid) / len(valid)) if complete else None
                lines.append(f"| {item} | {group} | {'unavailable' if value is None else fmt(value)} |")
        lines += ["", "### Declared exclusions", ""]
        lines += [f"- {entry['id']}: {entry['reason']}" for entry in rubric.get("excluded_dimensions", [])] or ["None."]
        lines += ["", "Exclusions and declared gate records require human review. File hashes establish identity, not truth.",
                  "Native behavior, screen-reader use and human outcomes are not qualified by browser prototypes."]
    return lines + [""], outcomes


def weighted(entry, dims, only_critical=False):
    chosen = [d for d in dims if d.get("critical") or not only_critical]
    total = sum(d["weight"] for d in chosen)
    return sum(entry[d["id"]]["score"] * d["weight"] for d in chosen) / total


def fmt(value):
    return f"{value:.2f}"


def check_meta(meta, round_dir, caps, previous_keep):
    if not isinstance(meta, dict):
        raise RunError(f"{round_dir}: round.json must contain an object")
    items = meta.get("items", [])
    calibration = meta.get("calibration", {})
    if not isinstance(calibration, dict):
        raise RunError(f"{round_dir}: calibration must be an object")
    weak, strong = calibration.get("weak"), calibration.get("strong")
    if (not isinstance(items, list) or not items or any(not isinstance(i, str) or not i for i in items)
            or len(set(items)) != len(items)):
        raise RunError(f"{round_dir}: items must be a non-empty list of unique ids")
    if weak not in items or strong not in items or weak == strong:
        raise RunError(f"{round_dir}: calibration weak and strong must be two listed items")
    contestants = [i for i in items if i not in (weak, strong)]
    if not contestants or len(contestants) > caps["max_prototypes"]:
        raise RunError(f"{round_dir}: prototype count must be 1..{caps['max_prototypes']}")
    if type(meta.get("round")) is not int or not 1 <= meta["round"] <= caps["max_rounds"]:
        raise RunError(f"{round_dir}: round {meta.get('round')} exceeds the cap")
    for key in ("model", "browser", "date"):
        if not meta.get(key):
            raise RunError(f"{round_dir}: round.json must record '{key}'")
    reveal = meta.get("reveal", {})
    if (not isinstance(reveal, dict) or sorted(reveal) != sorted(items)
            or any(not isinstance(v, str) or not v for v in reveal.values())
            or len(set(reveal.values())) != len(reveal)):
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
    references = check_evidence(meta, items, round_dir) if rules >= 3 else None
    if rules >= 3:
        check_profile_evidence(meta, round_dir)

    sheets = sorted(round_dir.glob("reviewer-*.json"))
    if not sheets or len(sheets) > caps["max_reviewers"]:
        raise RunError(f"{round_dir}: reviewer count must be 1..{caps['max_reviewers']}")
    loaded = []
    for path in sheets:
        sheet = load(path)
        check_sheet(sheet, items, dims, path.name, rules, references)
        loaded.append(sheet)
    if len({s["reviewer"] for s in loaded}) != len(loaded):
        raise RunError(f"{round_dir}: reviewer identities must be unique")
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
        if rules >= 3 and (sheet["reviewer_kind"] == "generator" or any(
                sheet["scores"][item][d["id"]]["score"] is None
                for item in (weak, strong) for d in dims)):
            lines.append(f"| {sheet['reviewer']} | - | - | - | excluded: self-review or incomplete calibration |")
            continue
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
        return "\n".join(lines), ("VOID", []), {}
    if rules >= 3:
        lines += ["## Reviewer provenance", "",
                  "| Reviewer | Kind | Model/version | Seed |", "|---|---|---|---|"]
        lines += [f"| {s['reviewer']} | {s['reviewer_kind']} | {s['model']} | {s['seed']} |"
                  for s in loaded]
        lines += ["", "Same-model reviewers measure within-model variation, not independent human agreement.", ""]
        lines += ["## Evidence scope", "",
                  f"Rubric SHA-256: `{meta['rubric_sha256']}`.",
                  f"Declared browser targets: {meta['target_profiles']['profiles']}.",
                  "The independent 320 CSS pixel view is zoom/reflow, not a phone qualification.", "",
                  "| Item | Source page SHA-256 |", "|---|---|"]
        zoom = meta["target_profiles"].get("desktop_zoom")
        if zoom and zoom["percentages"]:
            lines.insert(-3, (
                f"Declared real browser zoom: {zoom['percentages']}; "
                f"bundled renderer status: {zoom['status']}."
            ))
        lines += [f"| {item} | `{meta['source_sha256'][item]}` |" for item in contestants]
        lines += [""]

    stats = {}
    for item in contestants:
        per_dim = {d["id"]: [s["scores"][item][d["id"]]["score"] for s in valid] for d in dims}
        if any(value is None for values in per_dim.values() for value in values):
            stats[item] = {"mean": None, "spread": None, "critical": None, "dims": per_dim}
            continue
        totals = [weighted(s["scores"][item], dims) for s in valid]
        critical = [weighted(s["scores"][item], dims, only_critical=True) for s in valid]
        per_dim = {d["id"]: [s["scores"][item][d["id"]]["score"] for s in valid] for d in dims}
        stats[item] = {"mean": sum(totals) / len(totals), "spread": max(totals) - min(totals),
                       "critical": critical, "dims": per_dim}
    adoption_lines, outcomes = adoption_report(rubric, dims, contestants, valid, stats, meta)
    lines += adoption_lines
    if any(stats[item]["mean"] is None for item in contestants):
        lines += ["## Verdict", "", "VOID", "",
                  "Candidate evidence is incomplete. No comparison or elimination is justified.", ""]
        return "\n".join(lines), ("VOID", []), outcomes
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
    return "\n".join(lines), (verdict[0], names), outcomes


def run(run_dir, write, require_adoptable=False):
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
        meta = load(round_dir / "round.json")
        if not isinstance(meta, dict) or meta.get("round") != expected:
            raise RunError(f"{round_dir}: round.json round number does not match the folder")
        if rubric.get("rules_version", 1) >= 3:
            digest = hashlib.sha256((run_dir / "rubric.json").read_bytes()).hexdigest()
            if meta.get("rubric_sha256") != digest:
                raise RunError(f"{round_dir}: rubric changed or its digest is missing")
        report, verdict, outcomes = score_round(rubric, dims, round_dir, keep)
        target = round_dir / "report.md"
        if write:
            target.write_text(report, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != report:
            raise RunError(f"{target}: does not match its inputs; rerun with --write and review")
        if verdict[0] == "CONTINUE":
            keep = set(verdict[1])
    if require_adoptable and (verdict[0] != "WINNER"
                             or any(outcomes.get(name) != "ADOPTABLE" for name in verdict[1])):
        raise RunError("no evidence-bound ADOPTABLE winner; inspect the round report")
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path, metavar="RUN")
    mode.add_argument("--verify", type=Path, metavar="RUN")
    parser.add_argument("--require-adoptable", action="store_true",
                        help="fail unless the final winner also meets the evidence-bound adoption gate")
    args = parser.parse_args(argv)
    try:
        status, names = run(args.write or args.verify, write=bool(args.write),
                            require_adoptable=args.require_adoptable)
    except RunError as error:
        print(f"council: {error}", file=sys.stderr)
        return 1
    print(f"{status} {' '.join(names)}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
