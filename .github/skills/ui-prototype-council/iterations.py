#!/usr/bin/env python3
"""Verify and report a hash-bound, project-local refinement ledger."""

import argparse
import base64
import hashlib
import html
import importlib.util
import json
import math
import sys
import zlib
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("scope_intake", Path(__file__).with_name("intake.py"))
INTAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTAKE)

class LedgerError(ValueError):
    """A ledger or one of its referenced artifacts is invalid."""


REVIEWER_KINDS = {
    "generator_self_assessment",
    "independent_qualified_review",
    "human_review",
    "assistive_technology_evidence",
}
DECISIONS = {"keep", "revert", "blocked"}
STOP_REASONS = {
    "target_provisionally_met", "no_gain", "iteration_cap", "blocked", "budget",
    "scope_challenge",
}
SPONSOR_ATTESTATIONS = {"sponsor", "delegate_with_sponsor_reference"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_PIXELS = 40_000_000
MAX_HTML_REPORT_BYTES = 32 * 1024 * 1024
MAX_HTML_REPORT_PIXELS = 40_000_000


def _read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LedgerError(f"cannot read {label} {path}: {error}") from error


def _require(condition, message):
    if not condition:
        raise LedgerError(message)


def _bytes(root, artifacts, reference):
    _require(isinstance(reference, str) and reference in artifacts,
             f"unknown artifact reference: {reference!r}")
    item = artifacts[reference]
    _require(isinstance(item, dict) and set(item) == {"path", "sha256"},
             f"artifact {reference!r} must contain path and sha256")
    path = Path(item["path"])
    if not path.is_absolute():
        path = root / path
    try:
        data = path.read_bytes()
    except OSError as error:
        raise LedgerError(f"artifact {reference!r} is unavailable: {error}") from error
    digest = hashlib.sha256(data).hexdigest()
    _require(item["sha256"] == digest, f"artifact {reference!r} digest changed")
    return data


def _artifact(root, artifacts, reference):
    data = _bytes(root, artifacts, reference)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LedgerError(f"artifact {reference!r} must contain JSON: {error}") from error


def _capture_png(root, artifacts, reference):
    data = _bytes(root, artifacts, reference)
    _require(len(data) <= MAX_CAPTURE_BYTES,
             f"capture {reference!r} exceeds the self-contained HTML size limit")
    _require(len(data) >= 24 and data.startswith(PNG_SIGNATURE)
             and data[12:16] == b"IHDR",
             f"capture {reference!r} must be a PNG image")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    _require(width > 0 and height > 0 and width * height <= MAX_CAPTURE_PIXELS,
             f"capture {reference!r} has invalid or excessive dimensions")
    offset = 8
    saw_ihdr = saw_idat = saw_iend = False
    while offset < len(data):
        _require(offset + 12 <= len(data),
                 f"capture {reference!r} has a truncated PNG chunk")
        length = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 12 + length
        _require(end <= len(data), f"capture {reference!r} has a truncated PNG chunk")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        checksum = int.from_bytes(data[offset + 8 + length:end], "big")
        _require(zlib.crc32(kind + payload) & 0xFFFFFFFF == checksum,
                 f"capture {reference!r} has a corrupt PNG chunk")
        if not saw_ihdr:
            _require(kind == b"IHDR" and length == 13,
                     f"capture {reference!r} has an invalid PNG header")
            saw_ihdr = True
        elif kind == b"IHDR":
            raise LedgerError(f"capture {reference!r} has multiple PNG headers")
        if kind == b"IDAT":
            saw_idat = True
        if kind == b"IEND":
            _require(length == 0 and end == len(data),
                     f"capture {reference!r} has an invalid PNG end chunk")
            saw_iend = True
            break
        offset = end
    _require(saw_ihdr and saw_idat and saw_iend,
             f"capture {reference!r} is an incomplete PNG image")
    return width, height


def _visual_evidence(root, artifacts, reference, attempt_id,
                     before_source_ref, after_source_ref):
    evidence = _artifact(root, artifacts, reference)
    required = {
        "schema_version", "coordinate_space", "attempt_id",
        "before_source_ref", "after_source_ref", "before_capture_sha256",
        "after_capture_sha256",
        "before_capture_ref", "after_capture_ref", "changes",
    }
    _require(isinstance(evidence, dict) and set(evidence) == required,
             f"visual evidence {reference!r} has an invalid shape")
    _require(type(evidence["schema_version"]) is int and evidence["schema_version"] == 1
             and evidence["coordinate_space"] == "normalized"
             and type(evidence["attempt_id"]) is int
             and evidence["attempt_id"] == attempt_id,
             f"visual evidence {reference!r} has an unsupported version or attempt identity")
    _require(evidence["before_source_ref"] == before_source_ref
             and evidence["after_source_ref"] == after_source_ref,
             f"visual evidence {reference!r} does not match the attempt's source snapshots")
    capture_dimensions = {}
    for side in ("before", "after"):
        key = f"{side}_capture_ref"
        _require(isinstance(evidence[key], str) and evidence[key] in artifacts,
                 f"visual evidence {reference!r} needs a bound {key}")
        width, height = _capture_png(root, artifacts, evidence[key])
        capture_dimensions[side] = {"width": width, "height": height}
    _require(evidence["before_capture_sha256"]
             == artifacts[evidence["before_capture_ref"]]["sha256"]
             and evidence["after_capture_sha256"]
             == artifacts[evidence["after_capture_ref"]]["sha256"],
             f"visual evidence {reference!r} capture digests do not match their artifacts")

    changes = evidence["changes"]
    _require(isinstance(changes, list) and len(changes) <= 100,
             f"visual evidence {reference!r} changes must be a list of at most 100 items")
    change_ids = set()
    for change in changes:
        _require(isinstance(change, dict)
                 and set(change) == {"id", "label", "description", "before", "after"}
                 and isinstance(change.get("id"), str) and change["id"].strip()
                 and len(change["id"]) <= 80 and change["id"] not in change_ids
                 and isinstance(change.get("label"), str) and change["label"].strip()
                 and len(change["label"]) <= 160
                 and isinstance(change.get("description"), str)
                 and change["description"].strip() and len(change["description"]) <= 2000,
                 f"visual evidence {reference!r} contains an invalid change description")
        change_ids.add(change["id"])
        for side in ("before", "after"):
            arrow = change[side]
            _require(isinstance(arrow, dict) and set(arrow) == {"start", "end"},
                     f"visual evidence {reference!r} change {change['id']!r} needs {side} arrow points")
            for point_name in ("start", "end"):
                point = arrow[point_name]
                _require(isinstance(point, dict) and set(point) == {"x", "y"}
                         and all(type(point[key]) in (int, float)
                                 and math.isfinite(point[key]) and 0 <= point[key] <= 1
                                 for key in ("x", "y")),
                         f"visual evidence {reference!r} change {change['id']!r} "
                         f"has an invalid normalized {side} {point_name} point")
            _require(math.hypot(
                arrow["end"]["x"] - arrow["start"]["x"],
                arrow["end"]["y"] - arrow["start"]["y"],
            ) > 0,
                     f"visual evidence {reference!r} change {change['id']!r} "
                     f"has a zero-length {side} arrow")
    return {
        **evidence,
        "before_capture_dimensions": capture_dimensions["before"],
        "after_capture_dimensions": capture_dimensions["after"],
    }


def _source(root, artifacts, reference, scope_id):
    source = _artifact(root, artifacts, reference)
    _require(isinstance(source, dict) and source.get("scope_id") == scope_id
             and isinstance(source.get("build_id"), str) and source["build_id"].strip(),
             f"source {reference!r} does not match frozen scope or lacks build identity")
    files = source.get("files")
    _require(isinstance(files, dict) and files,
             f"source {reference!r} must bind its inputs and source files")
    for name, item in files.items():
        _require(isinstance(name, str) and name.strip()
                 and isinstance(item, dict) and set(item) == {"path", "sha256"},
                 f"source {reference!r} contains an invalid file identity")
        file_path = Path(item["path"])
        if not file_path.is_absolute():
            file_path = root / file_path
        try:
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        except OSError as error:
            raise LedgerError(f"source file {name!r} is unavailable: {error}") from error
        _require(item["sha256"] == digest,
                 f"source file {name!r} changed since its source identity was recorded")
    return source


def _scores(root, artifacts, reference, points, scope_id, build_id, source_ref,
            *, format_version=1, known_sources=None, affected_points=(),
            known_scenarios=()):
    data = _artifact(root, artifacts, reference)
    _require(isinstance(data, dict), f"scores {reference!r} must be an object")
    _require(data.get("scope_id") == scope_id and data.get("build_id") == build_id,
             f"scores {reference!r} do not match the declared scope/build")
    reviewer = data.get("reviewer")
    _require(isinstance(reviewer, dict)
             and reviewer.get("kind") in REVIEWER_KINDS
             and isinstance(reviewer.get("id"), str) and reviewer["id"].strip(),
             f"scores {reference!r} need reviewer kind and identity")
    _require(isinstance(data.get("points"), dict)
             and set(data["points"]) == set(points),
             f"scores {reference!r} must retain every declared measurement point")
    for point_id, score in data["points"].items():
        _require(isinstance(score, dict), f"score {point_id!r} must be an object")
        value = score.get("score")
        _require(value is None or type(value) is int and 1 <= value <= 10,
                 f"score {point_id!r} must be an integer from 1 to 10 or null")
        _require(score.get("evidence_status") in
                 {"observed", "not_assessed", "unsupported", "blocked"},
                 f"score {point_id!r} has an invalid evidence status")
        refs = score.get("evidence")
        _require(isinstance(refs, list) and all(ref in artifacts for ref in refs),
                 f"score {point_id!r} has missing evidence references")
        for ref in refs:
            _bytes(root, artifacts, ref)
        if value is None:
            _require(score["evidence_status"] != "observed",
                     f"null score {point_id!r} cannot be observed")
            if format_version == 2:
                _require(score.get("assessment_state") == "unassessed"
                         and score.get("evidence_status") in
                         {"not_assessed", "unsupported", "blocked"},
                         f"unscored point {point_id!r} must be explicitly unassessed")
        else:
            _require(score["evidence_status"] == "observed" and bool(refs),
                     f"scored point {point_id!r} needs observed evidence")
            _require(isinstance(score.get("reason"), str) and score["reason"].strip(),
                     f"scored point {point_id!r} needs a reason")
            _require(isinstance(score.get("assessed_source_ref"), str),
                     f"scored point {point_id!r} needs assessed_source_ref")
            if format_version == 1:
                _require(score["assessed_source_ref"] == source_ref,
                         f"score {point_id!r} is stale for the current source; reassess it")
            else:
                state = score.get("assessment_state")
                _require(state in {"fresh", "carried_forward", "stale"},
                         f"scored point {point_id!r} needs an explicit freshness state")
                assessed_source = score["assessed_source_ref"]
                _require(isinstance(assessed_source, str)
                         and (known_sources is None or assessed_source in known_sources),
                         f"score {point_id!r} cites an unknown historical source")
                _require((state == "fresh") == (assessed_source == source_ref),
                         f"score {point_id!r} freshness does not match its assessed source")
                if state == "stale":
                    _require(score.get("review_required") is True,
                             f"stale point {point_id!r} must be flagged for re-review")
                if point_id in affected_points and state != "fresh":
                    _require(state == "stale" and score.get("review_required") is True,
                             f"affected carried point {point_id!r} must be stale and flagged for re-review")
                coverage = score.get("evidence_coverage")
                _require(isinstance(coverage, dict) and set(coverage) == set(refs),
                         f"score {point_id!r} must declare coverage for every evidence reference")
                for evidence_ref, declaration in coverage.items():
                    _require(isinstance(declaration, dict)
                             and isinstance(declaration.get("point_ids"), list)
                             and isinstance(declaration.get("scenario_ids"), list)
                             and isinstance(declaration.get("declaration"), str)
                             and declaration["declaration"].strip(),
                             f"score {point_id!r} has incomplete evidence coverage")
                    _require(all(isinstance(item, str) for item in
                                 declaration["point_ids"] + declaration["scenario_ids"]),
                             f"score {point_id!r} has invalid evidence coverage identities")
                    _require(set(declaration["point_ids"]) <= set(points)
                             and set(declaration["scenario_ids"]) <= set(known_scenarios),
                             f"score {point_id!r} evidence coverage cites undeclared points or scenarios")
                    if point_id not in declaration["point_ids"]:
                        _require(state != "fresh",
                                 f"fresh score {point_id!r} lacks declared evidence coverage")
                _require(score.get("review_required") in (True, False),
                         f"scored point {point_id!r} must declare whether re-review is required")
            if value >= 9:
                _require(isinstance(score.get("anchor"), str) and score["anchor"].strip(),
                         f"score {point_id!r} at 9 or above needs its rubric anchor")
    return data


def _validate_v2_contract(root, contract, artifacts, points):
    goal = contract.get("goal")
    _require(isinstance(goal, dict) and type(goal.get("score")) is int
             and 1 <= goal["score"] <= 10
             and type(goal.get("fraction")) in (int, float)
             and math.isfinite(goal["fraction"]) and 0 < goal["fraction"] <= 1,
             "format-2 goal must declare a score from 1 to 10 and a fraction in (0, 1]")
    scopes = contract.get("scopes")
    _require(isinstance(scopes, list) and scopes
             and all(isinstance(item, dict)
                     and isinstance(item.get("id"), str) and item["id"].strip()
                     and item.get("kind") in {"component", "region", "page", "state", "journey"}
                     and isinstance(item.get("name"), str) and item["name"].strip()
                     for item in scopes)
             and len({item["id"] for item in scopes}) == len(scopes),
             "format-2 contract needs uniquely identified component, region, page, state or journey scopes")
    scope_ids = {item["id"] for item in scopes}
    for point in points:
        memberships = point.get("scopes")
        _require(isinstance(memberships, list) and memberships
                 and all(isinstance(item, str) for item in memberships)
                 and len(set(memberships)) == len(memberships)
                 and set(memberships) <= scope_ids,
                 f"point {point['id']!r} needs valid, unique scope memberships")
    brief_ref = contract.get("brief_ref")
    brief = _artifact(root, artifacts, brief_ref)
    _require(isinstance(brief, dict) and brief.get("brief_version")
             and brief.get("status") in {"complete", "incomplete"},
             "format-2 contract needs a versioned complete or explicitly incomplete brief")
    required_brief = (
        "users_and_jobs", "problem", "desired_outcomes", "platforms", "scenarios",
        "constraints", "quality_goal", "available_evidence", "budget",
        "stop_conditions", "non_goals", "unresolved_questions", "critical_unknowns",
        "decision_authority",
    )
    _require(all(key in brief for key in required_brief),
             "brief must record users/jobs, problem, outcomes, platforms, scenarios, constraints, goal, evidence, budget, stops, non-goals, unknowns and authority")
    for field in ("users_and_jobs", "desired_outcomes", "platforms", "scenarios",
                  "constraints", "available_evidence", "stop_conditions", "non_goals",
                  "unresolved_questions", "critical_unknowns"):
        _require(isinstance(brief[field], list)
                 and all(isinstance(value, str) for value in brief[field]),
                 f"brief.{field} must be an explicit list (empty means unknown or none)")
    _require(brief.get("problem") is None or isinstance(brief.get("problem"), str),
             "brief.problem must be text or null")
    _require(isinstance(brief["quality_goal"], dict)
             and brief["quality_goal"].get("score") == goal["score"]
             and brief["quality_goal"].get("fraction") == goal["fraction"]
             and brief["quality_goal"].get("status") in {"approved", "proposed", "unknown"}
             and isinstance(brief["quality_goal"].get("decision_id"), str),
             "brief quality goal must match the contract and declare approval status")
    _require(isinstance(brief["budget"], dict)
             and (brief["budget"].get("limit_minutes") is None
                  or type(brief["budget"]["limit_minutes"]) in (int, float)
                  and math.isfinite(brief["budget"]["limit_minutes"])
                  and brief["budget"]["limit_minutes"] >= 0),
             "brief budget must declare a nonnegative minute limit or null")
    authority = brief["decision_authority"]
    _require(isinstance(authority, dict)
             and isinstance(authority.get("sponsor_decisions"), list)
             and isinstance(authority.get("agent_delegated_decisions"), list)
             and isinstance(authority.get("decisions"), list)
             and all(isinstance(item, dict)
                     and isinstance(item.get("id"), str) and item["id"].strip()
                     and item.get("owner") in {"sponsor", "agent"}
                     and item.get("status") in {"approved", "proposed", "unknown"}
                     and isinstance(item.get("decision"), str)
                     for item in authority["decisions"]),
             "brief must distinguish sponsor-owned and delegated agent decisions")
    for item in authority["decisions"]:
        if item["owner"] == "sponsor":
            _require(item["id"] in authority["sponsor_decisions"],
                     f"sponsor decision {item['id']!r} is not listed as sponsor-owned")
        else:
            _require(item["id"] in authority["agent_delegated_decisions"],
                     f"agent decision {item['id']!r} is not listed as delegated")
    sponsor_ids = {item["id"] for item in authority["decisions"]
                   if item["owner"] == "sponsor"}
    delegated_ids = {item["id"] for item in authority["decisions"]
                     if item["owner"] == "agent"}
    _require(set(authority["sponsor_decisions"]) == sponsor_ids
             and set(authority["agent_delegated_decisions"]) == delegated_ids
             and not (sponsor_ids & delegated_ids),
             "brief authority lists must exactly match sponsor-owned and delegated decisions")
    goal_decision_id = brief["quality_goal"]["decision_id"]
    _require(goal_decision_id in sponsor_ids,
             "project quality goal needs an explicit sponsor-owned decision")
    goal_decision = next(item for item in authority["decisions"]
                         if item["id"] == goal_decision_id)
    if brief["quality_goal"]["status"] == "approved":
        _require(goal_decision["status"] == "approved",
                 "an approved project goal needs its sponsor decision marked approved")
    if brief["status"] == "complete":
        _require(bool(brief["users_and_jobs"])
                 and isinstance(brief["problem"], str) and brief["problem"].strip()
                 and bool(brief["desired_outcomes"]) and bool(brief["platforms"])
                 and bool(brief["scenarios"]) and bool(brief["stop_conditions"])
                 and not brief["critical_unknowns"],
                 "a complete brief needs users/jobs, problem, outcomes, platforms, scenarios, stop conditions and no critical unknowns")
    history = contract.get("version_history")
    mappings = contract.get("version_mappings")
    _require(isinstance(history, list) and history and isinstance(mappings, list),
             "format-2 contract needs append-only version history and explicit mappings")
    seen = {}
    for index, version in enumerate(history):
        _require(isinstance(version, dict) and isinstance(version.get("id"), str)
                 and version["id"] not in seen
                 and version.get("parent") == (history[index - 1]["id"] if index else None)
                 and isinstance(version.get("goal"), dict)
                 and type(version["goal"].get("score")) is int
                 and 1 <= version["goal"]["score"] <= 10
                 and type(version["goal"].get("fraction")) in (int, float)
                 and math.isfinite(version["goal"]["fraction"])
                 and 0 < version["goal"]["fraction"] <= 1
                 and isinstance(version.get("point_ids"), list)
                 and isinstance(version.get("selected_point_ids"), list)
                 and isinstance(version.get("scope_ids"), list)
                 and isinstance(version.get("point_scopes"), dict)
                 and isinstance(version.get("rubric_revision"), str)
                 and isinstance(version.get("inventory_revision"), str)
                 and isinstance(version.get("scope_revision"), str)
                 and isinstance(version.get("material_decisions_ref"), str)
                 and version["material_decisions_ref"] in artifacts,
                 "version history must be uniquely ordered and bind goal, rubric, inventory, scope and decisions")
        decisions = _artifact(root, artifacts, version["material_decisions_ref"])
        _require(isinstance(decisions, dict),
                 f"version {version['id']!r} material decisions must be a JSON object")
        seen[version["id"]] = version
        _require(len(version["point_ids"]) == len(set(version["point_ids"]))
                 and len(version["selected_point_ids"])
                 == len(set(version["selected_point_ids"]))
                 and set(version["selected_point_ids"]) <= set(version["point_ids"])
                 and len(version["scope_ids"]) == len(set(version["scope_ids"]))
                 and set(version["point_scopes"]) == set(version["point_ids"])
                 and all(isinstance(memberships, list)
                         and len(memberships) == len(set(memberships))
                         and set(memberships) <= set(version["scope_ids"])
                         for memberships in version["point_scopes"].values()),
                 f"version {version['id']!r} needs unique points, scopes and complete point-to-scope mappings")
    expected_points = {point["id"] for point in points}
    expected_scopes = scope_ids
    _require(history[-1]["goal"] == goal
             and set(history[-1]["point_ids"]) == expected_points
             and set(history[-1]["selected_point_ids"]) == {
                 point["id"] for point in points if point["selected"]
             }
             and set(history[-1]["scope_ids"]) == expected_scopes
             and history[-1]["point_scopes"] == {
                 point["id"]: point["scopes"] for point in points
             },
             "latest version inventory and scopes must match the current contract")
    _require(len(mappings) == len(history) - 1,
             "every appended version needs exactly one point/scope mapping")
    for index, mapping in enumerate(mappings, 1):
        old, new = history[index - 1], history[index]
        _require(isinstance(mapping, dict) and mapping.get("from") == old["id"]
                 and mapping.get("to") == new["id"]
                 and isinstance(mapping.get("reason"), str) and mapping["reason"].strip()
                 and type(mapping.get("compatible")) is bool,
                 "version mappings must connect adjacent versions and label comparability")
        for field in ("points", "scopes"):
            old_ids = old["point_ids"] if field == "points" else old["scope_ids"]
            new_ids = new["point_ids"] if field == "points" else new["scope_ids"]
            rows = mapping.get(field)
            _require(isinstance(rows, list) and rows
                     and all(isinstance(row, dict)
                             and row.get("relation") in
                             {"same", "renamed", "split", "merged", "added", "removed"}
                             and (row.get("from") is None or row.get("from") in old_ids)
                             and (row.get("to") is None or row.get("to") in new_ids)
                             and (field != "points" or
                                  (isinstance(row.get("from_scopes"), list)
                                   and isinstance(row.get("to_scopes"), list)
                                   and (row.get("from") is None
                                        and row["from_scopes"] == []
                                        or row.get("from") is not None
                                        and row["from_scopes"] == old["point_scopes"].get(
                                            row["from"], []))
                                   and (row.get("to") is None
                                        and row["to_scopes"] == []
                                        or row.get("to") is not None
                                        and row["to_scopes"] == new["point_scopes"].get(
                                            row["to"], []))))
                             and not (row.get("from") is None and row.get("to") is None)
                             for row in rows),
                     f"version mapping must document {field} identity changes")
            pairs = [(row.get("from"), row.get("to")) for row in rows]
            _require(len(pairs) == len(set(pairs)),
                     f"version mapping has duplicate {field} identity pairs")
            for row in rows:
                relation = row["relation"]
                old_id, new_id = row.get("from"), row.get("to")
                if relation == "same":
                    _require(old_id is not None and old_id == new_id,
                             f"same {field[:-1]} mapping must retain its identity")
                elif relation == "renamed":
                    _require(old_id is not None and new_id is not None
                             and old_id != new_id,
                             f"renamed {field[:-1]} mapping needs distinct old and new identities")
                elif relation == "added":
                    _require(old_id is None and new_id is not None,
                             f"added {field[:-1]} mapping must have only a new identity")
                elif relation == "removed":
                    _require(old_id is not None and new_id is None,
                             f"removed {field[:-1]} mapping must have only an old identity")
                else:
                    _require(old_id is not None and new_id is not None,
                             f"{relation} {field[:-1]} mapping needs old and new identities")
            _require({row["from"] for row in rows if row["from"] is not None}
                     == set(old_ids)
                     and {row["to"] for row in rows if row["to"] is not None}
                     == set(new_ids),
                     f"version mapping must account for every old and new {field[:-1]}")
        changed = (
            old["goal"] != new["goal"]
            or set(old["point_ids"]) != set(new["point_ids"])
            or set(old["selected_point_ids"]) != set(new["selected_point_ids"])
            or old["point_scopes"] != new["point_scopes"]
            or set(old["scope_ids"]) != set(new["scope_ids"])
            or old["rubric_revision"] != new["rubric_revision"]
            or old["inventory_revision"] != new["inventory_revision"]
            or old["scope_revision"] != new["scope_revision"]
        )
        _require(not (mapping["compatible"] and changed),
                 "changed goal, inventory, rubric or scope cannot be silently compared as compatible")
        _require(not (changed and not mapping["reason"]),
                 "incompatible comparisons need an explicit reason")
    if "intake" in brief:
        intake_report = INTAKE.validate(
            brief, root=root, current_brief_path=root / artifacts[brief_ref]["path"])
        blockers = [row["message"] for row in intake_report["findings"] if row["severity"] == "blocker"]
        _require(not blockers, "invalid scoped intake: " + "; ".join(blockers))
    return brief, history, mappings


KEEP_RULE_IDS = {"multi_gain_v2"}


def _validate_keep_rule_contract(contract):
    """Validate the opt-in format-2 ``contract.keep_rule`` block, if present.

    Absence preserves the strict, all-declared-targets keep semantics. When
    present, it declares the ``multi_gain_v2`` rule: keep a candidate that
    clears ``min_gain`` and ``noise_band`` on at least ``min_improved`` of its
    declared targets, with no paired regression anywhere, as measured by a
    fixed reviewer panel re-scoring both sources together.
    """
    rule = contract.get("keep_rule")
    if rule is None:
        return None
    _require(isinstance(rule, dict) and rule.get("id") in KEEP_RULE_IDS,
             "contract.keep_rule must declare a supported rule id")
    _require(type(rule.get("min_improved")) is int and rule["min_improved"] >= 1,
             "keep_rule.min_improved must be a positive integer")
    _require(type(rule.get("min_gain")) in (int, float) and math.isfinite(rule["min_gain"])
             and rule["min_gain"] > 0,
             "keep_rule.min_gain must be a finite positive number")
    _require(type(rule.get("noise_band")) in (int, float) and math.isfinite(rule["noise_band"])
             and rule["noise_band"] >= 0,
             "keep_rule.noise_band must be a finite nonnegative number")
    panel = rule.get("panel")
    _require(isinstance(panel, dict), "keep_rule.panel must be an object")
    reviewers = panel.get("reviewers")
    _require(isinstance(reviewers, list) and reviewers
             and all(isinstance(item, dict) and set(item) == {"id", "kind", "model"}
                     and isinstance(item.get("id"), str) and item["id"].strip()
                     and item.get("kind") in REVIEWER_KINDS
                     and isinstance(item.get("model"), str) and item["model"].strip()
                     for item in reviewers),
             "keep_rule.panel.reviewers must declare an id, kind and model for each reviewer")
    _require(len({item["id"] for item in reviewers}) == len(reviewers),
             "keep_rule.panel.reviewers must have unique reviewer ids")
    _require(type(panel.get("repeats")) is int and panel["repeats"] >= 1,
             "keep_rule.panel.repeats must be a positive integer")
    return rule


def _paired_scores(root, artifacts, reference, attempt_id, keep_rule,
                   before_source_ref, after_source_ref, affected_points):
    """Validate a hash-bound paired reassessment artifact for ``multi_gain_v2``.

    Both the retained (baseline) and candidate sources are re-scored in the
    same panel session, so the artifact binds one shared ``panel_id`` and the
    exact declared reviewer roster (id, kind, model, order) and repeat count.
    Scores stay integer 1-10 or null (unassessed); null anywhere blocks keep.
    """
    data = _artifact(root, artifacts, reference)
    _require(isinstance(data, dict) and data.get("schema_version") == 1,
             f"paired scores {reference!r} must be a schema-version-1 object")
    _require(data.get("attempt_id") == attempt_id,
             f"paired scores {reference!r} attempt identity does not match")
    _require(data.get("rule_id") == keep_rule["id"],
             f"paired scores {reference!r} does not cite the contract's keep_rule id")
    _require(isinstance(data.get("panel_id"), str) and data["panel_id"].strip(),
             f"paired scores {reference!r} needs a shared panel_id for both sources")
    panel = data.get("panel")
    _require(isinstance(panel, dict)
             and panel.get("reviewers") == keep_rule["panel"]["reviewers"]
             and panel.get("repeats") == keep_rule["panel"]["repeats"],
             f"paired scores {reference!r} panel roster, order, kind, model or repeats "
             "does not match the declared contract panel exactly")
    _require(data.get("before_source_ref") == before_source_ref
             and data.get("after_source_ref") == after_source_ref,
             f"paired scores {reference!r} does not match this attempt's before/after sources")
    repeats_total = len(keep_rule["panel"]["reviewers"]) * keep_rule["panel"]["repeats"]
    points = data.get("points")
    _require(isinstance(points, dict) and set(points) == set(affected_points),
             f"paired scores {reference!r} must cover exactly the attempt's affected points")
    parsed = {}
    for point_id, pair in points.items():
        _require(isinstance(pair, dict) and set(pair) == {"baseline", "candidate"},
                 f"paired scores {reference!r} point {point_id!r} needs baseline and "
                 "candidate arrays")
        parsed[point_id] = {}
        for side in ("baseline", "candidate"):
            values = pair[side]
            _require(isinstance(values, list) and len(values) == repeats_total,
                     f"paired scores {reference!r} point {point_id!r} {side} needs exactly "
                     f"{repeats_total} reviewer-repeat entries")
            for value in values:
                _require(value is None or type(value) is int and 1 <= value <= 10,
                         f"paired scores {reference!r} point {point_id!r} {side} entries must "
                         "be an integer from 1 to 10 or null")
            parsed[point_id][side] = values
    return data, parsed


def _pair_statistics(parsed):
    """Derive floating paired means, deltas and variance independently of
    the integer snapshot scores; any null entry invalidates that point."""
    stats = {}
    for point_id, pair in parsed.items():
        baseline, candidate = pair["baseline"], pair["candidate"]
        if any(value is None for value in baseline + candidate):
            stats[point_id] = {
                "baseline_mean": None, "candidate_mean": None, "delta": None,
                "baseline_variance": None, "candidate_variance": None, "has_null": True,
            }
            continue
        baseline_mean = sum(baseline) / len(baseline)
        candidate_mean = sum(candidate) / len(candidate)

        def variance(values, mean):
            return sum((value - mean) ** 2 for value in values) / len(values)

        stats[point_id] = {
            "baseline_mean": baseline_mean,
            "candidate_mean": candidate_mean,
            "delta": candidate_mean - baseline_mean,
            "baseline_variance": variance(baseline, baseline_mean),
            "candidate_variance": variance(candidate, candidate_mean),
            "has_null": False,
        }
    return stats


def _checks(root, artifacts, reference, required_scenarios, task_budgets, build_id):
    data = _artifact(root, artifacts, reference)
    _require(isinstance(data, dict), f"checks {reference!r} must be an object")
    _require(data.get("status") in {"pass", "fail", "unknown", "incomplete"},
             f"checks {reference!r} has an invalid status")
    _require(type(data.get("full_coverage")) is bool,
             f"checks {reference!r} must declare full_coverage")
    expected_scenarios = {item["id"]: item for item in required_scenarios}
    scenarios = data.get("scenarios")
    _require(isinstance(scenarios, list)
             and all(isinstance(item, str) for item in scenarios)
             and len(scenarios) == len(set(scenarios))
             and set(scenarios) == set(expected_scenarios),
             f"checks {reference!r} lost or changed required scenario coverage")
    evidence = data.get("scenario_evidence")
    _require(isinstance(evidence, list)
             and len(evidence) == len(expected_scenarios)
             and all(isinstance(item, dict) and isinstance(item.get("id"), str)
                     for item in evidence)
             and {item["id"] for item in evidence}
             == set(expected_scenarios),
             f"checks {reference!r} must report evidence for every required scenario")
    for item in evidence:
        expected = expected_scenarios[item["id"]]
        _require(item.get("status") in {"pass", "fail", "unknown", "unavailable", "not_reached"}
                 and item.get("evidence_type") == expected["evidence_type"]
                 and item.get("build_id") == build_id,
                 f"scenario {item['id']!r} has missing, changed or misidentified evidence")
    if data["status"] == "pass":
        _require(data["full_coverage"] is True
                 and all(item["status"] == "pass" for item in evidence),
                 f"checks {reference!r} cannot pass with unknown or unavailable scenarios")
    commands = data.get("commands")
    _require(isinstance(commands, list) and commands
             and all(isinstance(item, dict)
                     and isinstance(item.get("command"), str) and item["command"].strip()
                     and item.get("status") in {"pass", "fail", "unknown"}
                     and (item.get("exit_code") is None
                          or type(item.get("exit_code")) is int)
                     for item in commands),
             f"checks {reference!r} need command, exit status and outcome records")
    if data["status"] == "pass":
        _require(all(item["status"] == "pass" and item["exit_code"] == 0
                     for item in commands),
                 f"checks {reference!r} cannot pass with a failed or unknown command")
    findings = data.get("findings")
    _require(isinstance(findings, list), f"checks {reference!r} needs finding identities")
    found = {}
    for finding in findings:
        _require(isinstance(finding, dict)
                 and isinstance(finding.get("id"), str) and finding["id"].strip()
                 and type(finding.get("severity")) is int and finding["severity"] > 0,
                 f"checks {reference!r} has an invalid finding")
        _require(finding["id"] not in found, f"duplicate finding identity {finding['id']!r}")
        found[finding["id"]] = finding["severity"]
    tasks = data.get("tasks")
    _require(isinstance(tasks, dict) and set(tasks) == set(task_budgets),
             f"checks {reference!r} must report every declared task")
    for task, budget in task_budgets.items():
        result = tasks[task]
        _require(isinstance(result, dict)
                 and result.get("status") in {"pass", "fail", "unknown"}
                 and type(result.get("clicks")) is int and result["clicks"] >= 0
                 and type(result.get("budget")) is int and result["budget"] == budget,
                 f"task {task!r} has invalid result or changed click budget")
    observations = data.get("observations", [])
    _require(isinstance(observations, list), "observations must be a list")
    for item in observations:
        _require(isinstance(item, dict) and isinstance(item.get("profile"), str)
                 and isinstance(item.get("finding_id"), str)
                 and item.get("outcome") in {"pass", "fail", "unknown"}
                 and item.get("evidence_kind") in
                 {"automated_check", "generator_self_assessment",
                  "independent_qualified_review", "human_review",
                  "assistive_technology_evidence"},
                 "finding observation needs profile, identity, outcome and evidence kind")
    return data, found


def verify(path):
    path = Path(path).resolve()
    ledger = _read_json(path, "ledger")
    _require(isinstance(ledger, dict) and type(ledger.get("format_version")) is int
             and ledger.get("format_version") in {1, 2},
             "format_version must be 1 or 2")
    format_version = ledger["format_version"]
    contract = ledger.get("contract")
    _require(isinstance(contract, dict), "contract must be an object")
    scope_id = contract.get("scope_id")
    _require(isinstance(scope_id, str) and scope_id.strip(), "contract needs scope_id")
    points = contract.get("points")
    _require(isinstance(points, list) and points and
             all(isinstance(point, dict) and isinstance(point.get("id"), str)
                 and point["id"].strip()
                 and type(point.get("selected")) is bool for point in points),
             "contract.points must declare unique ids and selected flags")
    point_ids = [point["id"] for point in points]
    _require(len(set(point_ids)) == len(point_ids), "measurement point ids must be unique")
    goal = contract.get("goal")
    if format_version == 1:
        _require(isinstance(goal, dict) and goal.get("score") == 9
                 and type(goal.get("fraction")) in (int, float)
                 and 0.8 <= goal["fraction"] <= 0.9,
                 "format-1 goal must target score 9 across a declared 0.80-0.90 fraction")
    else:
        _require(isinstance(goal, dict) and type(goal.get("score")) is int
                 and 1 <= goal["score"] <= 10
                 and type(goal.get("fraction")) in (int, float)
                 and math.isfinite(goal["fraction"]) and 0 < goal["fraction"] <= 1,
                 "format-2 goal must declare its project-owned score and fraction")
    selected_count = sum(point["selected"] for point in points)
    _require(selected_count > 0, "the selected project-goal denominator cannot be empty")
    if format_version == 1:
        _require(selected_count >= math.ceil(len(points) * goal["fraction"]),
                 "selected points do not meet the declared goal fraction of the full denominator")
    feasibility = contract.get("feasibility")
    _require(isinstance(feasibility, dict)
             and feasibility.get("status") in {"infeasible", "unknown"}
             and isinstance(feasibility.get("assumptions"), list)
             and feasibility["assumptions"]
             and all(isinstance(item, str) and item.strip()
                     for item in feasibility["assumptions"]),
             "feasibility needs a status and explicit assumptions")
    if feasibility["status"] == "infeasible":
        proof = feasibility.get("proof")
        selected_ids = {point["id"] for point in points if point["selected"]}
        _require(isinstance(proof, dict)
                 and proof.get("type") == "immutable_score_ceiling"
                 and isinstance(proof.get("upper_bounds"), dict)
                 and set(proof["upper_bounds"]) == selected_ids
                 and all(type(value) is int and value < goal["score"]
                         for value in proof["upper_bounds"].values()),
                 "infeasible goal needs a bound below target for every selected point")
        _require(isinstance(proof.get("evidence_ref"), str)
                 and proof["evidence_ref"] in ledger.get("artifacts", {}),
                 "infeasible goal needs evidence for its immutable score ceilings")
        bound_evidence = _artifact(path.parent, ledger["artifacts"], proof["evidence_ref"])
        _require(isinstance(bound_evidence, dict)
                 and bound_evidence.get("upper_bounds") == proof["upper_bounds"],
                 "infeasible proof bounds do not match the cited immutable evidence")
    else:
        _require("proof" not in feasibility,
                 "unknown feasibility cannot carry an asserted proof")
    required_scenarios = contract.get("required_scenarios")
    task_budgets = contract.get("task_budgets")
    _require(isinstance(required_scenarios, list) and required_scenarios
             and all(isinstance(item, dict)
                     and all(isinstance(item.get(key), str) and item[key].strip()
                             for key in ("id", "theme", "viewport", "state",
                                         "evidence_type"))
                     for item in required_scenarios)
             and len({item["id"] for item in required_scenarios}) == len(required_scenarios),
             "required_scenarios must uniquely declare state, theme, viewport and evidence type")
    _require(isinstance(task_budgets, dict)
             and all(type(value) is int and value >= 0 for value in task_budgets.values()),
             "task_budgets must map tasks to nonnegative click budgets")
    if format_version == 2:
        for scope in contract["scopes"]:
            task_ids = scope.get("task_ids", [])
            _require(isinstance(task_ids, list)
                     and all(isinstance(item, str) and item in task_budgets
                             for item in task_ids)
                         and len(task_ids) == len(set(task_ids))
                     and (scope["kind"] != "journey" or task_ids),
                     f"scope {scope['id']!r} must map journey tasks to declared task budgets")
    artifacts = ledger.get("artifacts")
    _require(isinstance(artifacts, dict) and artifacts, "artifacts must be a nonempty map")
    brief = None
    version_history = []
    version_mappings = []
    if format_version == 2:
        brief, version_history, version_mappings = _validate_v2_contract(
            path.parent, contract, artifacts, points)
        comparison_point_ids = list(dict.fromkeys(
            point_id for version in version_history for point_id in version["point_ids"]))
        keep_rule_contract = _validate_keep_rule_contract(contract)
        if keep_rule_contract:
            _require(isinstance(brief.get("intake"), dict),
                     "multi_gain_v2 requires a sponsor-confirmed scoped intake")
    else:
        comparison_point_ids = point_ids
        _require("keep_rule" not in contract, "contract.keep_rule is format-2 only")
        keep_rule_contract = None
    for field in ("elapsed_minutes", "review_effort_minutes", "verification_elapsed_seconds"):
        value = contract.get(field)
        _require(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0,
                 f"{field} must be a nonnegative recorded number or null")
    baseline = ledger.get("baseline")
    _require(isinstance(baseline, dict), "baseline must be an object")

    def snapshot(refs, label, *, affected_points=()):
        _require(isinstance(refs, dict), f"{label} must be an object")
        for key in ("source_ref", "scores_ref", "checks_ref"):
            _require(isinstance(refs.get(key), str), f"{label} needs {key}")
        source = _source(path.parent, artifacts, refs["source_ref"], scope_id)
        if format_version == 2:
            _require(refs.get("version_id") in {item["id"] for item in version_history},
                     f"{label} needs a declared version identity")
            snapshot_point_ids = next(item["point_ids"] for item in version_history
                                      if item["id"] == refs["version_id"])
        else:
            snapshot_point_ids = point_ids
        scores = _scores(path.parent, artifacts, refs["scores_ref"], snapshot_point_ids,
                         scope_id, source["build_id"], refs["source_ref"],
                         format_version=format_version,
                         known_sources=set(
                             [baseline.get("source_ref")] +
                             [item.get("source_ref") for attempt in
                              ledger.get("iterations", []) if isinstance(attempt, dict)
                              for item in (attempt.get("before", {}), attempt.get("after", {}))
                              if isinstance(item, dict) and isinstance(item.get("source_ref"), str)]
                         ) if format_version == 2 else None,
                         affected_points=affected_points,
                         known_scenarios=(
                             {item["id"] for item in required_scenarios}
                             if format_version == 2 else ()))
        checks, finding_map = _checks(path.parent, artifacts, refs["checks_ref"],
                                      required_scenarios, task_budgets, source["build_id"])
        return source, scores, checks, finding_map

    _require(baseline.get("scope_id") == scope_id and isinstance(baseline.get("build_id"), str),
             "baseline scope/build identity is missing")
    if format_version == 2:
        _require(baseline.get("version_id") == version_history[0]["id"],
                 "baseline must bind the first immutable contract version")
    before_source, before_scores, before_checks, before_findings = snapshot(
        baseline, "baseline")
    _require(baseline["build_id"] == before_source["build_id"],
             "baseline build identity differs from its source")
    previous_source_ref = baseline["source_ref"]
    retained_scores, retained_checks = before_scores, before_checks
    iterations = ledger.get("iterations")
    _require(isinstance(iterations, list), "iterations must be a list")
    no_gain = 0
    total_effort = 0.0
    final_review_record = None
    previous_version = baseline.get("version_id") if format_version == 2 else None
    attempt_reports = []
    for expected_id, attempt in enumerate(iterations, 1):
        _require(isinstance(attempt, dict) and attempt.get("id") == expected_id,
                 "attempt ids must be unique, positive and sequential")
        _require(isinstance(attempt.get("hypothesis"), str) and attempt["hypothesis"].strip(),
                 f"attempt {expected_id} needs a pre-edit hypothesis")
        if format_version == 2:
            for field in ("expected_outcomes", "actual_outcomes", "affected_points",
                          "dependencies", "guardrails", "regressions"):
                _require(isinstance(attempt.get(field), list)
                         and all(isinstance(item, str) and item.strip()
                                 for item in attempt[field]),
                         f"format-2 attempt {expected_id} needs explicit {field}")
            actor = attempt.get("decision_actor")
            decisions_made = attempt.get("decision_records")
            _require(actor in {"sponsor", "agent"}
                     and isinstance(decisions_made, list),
                     f"format-2 attempt {expected_id} must record its decision authority")
            authority_records = {
                item["id"]: item for item in brief["decision_authority"]["decisions"]
            }
            seen_decisions = set()
            for record in decisions_made:
                _require(isinstance(record, dict)
                         and record.get("id") in authority_records
                         and record.get("id") not in seen_decisions
                         and record.get("actor") == actor
                         and record.get("status") in {"approved", "proposed", "unknown"}
                         and isinstance(record.get("decision"), str)
                         and record["decision"].strip(),
                         f"format-2 attempt {expected_id} has an invalid decision record")
                authority_record = authority_records[record["id"]]
                _require(authority_record["owner"] == actor
                         or actor == "agent"
                         and authority_record["owner"] == "sponsor"
                         and record["status"] != "approved",
                         f"attempt {expected_id} exceeds delegated authority for {record['id']!r}")
                seen_decisions.add(record["id"])
            effort = attempt.get("effort_minutes")
            _require(type(effort) in (int, float) and math.isfinite(effort) and effort >= 0,
                     f"format-2 attempt {expected_id} needs nonnegative elapsed effort")
            _require(len(set(attempt["affected_points"])) == len(attempt["affected_points"])
                     and set(attempt["affected_points"]) <= set(comparison_point_ids),
                     f"format-2 attempt {expected_id} has invalid affected measurement points")
            total_effort += effort
            current_version = attempt.get("version_id")
            _require(current_version in {item["id"] for item in version_history}
                     and (current_version == previous_version
                          or any(item["id"] == current_version
                                 and item["parent"] == previous_version
                                 for item in version_history)),
                     f"attempt {expected_id} must use the current or next appended version")
            previous_version = current_version
            _require(isinstance(attempt.get("actual_evidence"), list)
                     and all(item in artifacts for item in attempt["actual_evidence"]),
                     f"format-2 attempt {expected_id} needs actual evidence references")
            for evidence_ref in attempt["actual_evidence"]:
                _bytes(path.parent, artifacts, evidence_ref)
        dimensions = attempt.get("dimensions")
        _require(isinstance(dimensions, list) and dimensions and
                 set(dimensions) <= set(point_ids),
                 f"attempt {expected_id} needs declared dimensions from the frozen denominator")
        expected_gain = attempt.get("expected_gain")
        _require(isinstance(expected_gain, dict) and set(expected_gain) == set(dimensions)
                 and all(type(value) is int and value > 0
                         for value in expected_gain.values()),
                 f"attempt {expected_id} needs a positive bounded gain for every target dimension")
        proposal_ref = attempt.get("proposal_ref")
        proposal = _artifact(path.parent, artifacts, proposal_ref)
        _require(isinstance(proposal, dict) and proposal.get("recorded_before_edit") is True
                 and proposal.get("hypothesis") == attempt["hypothesis"]
                 and proposal.get("dimensions") == dimensions
                 and proposal.get("expected_gain") == expected_gain,
                 f"attempt {expected_id} proposal must bind the pre-edit hypothesis, dimensions and gain")
        if format_version == 2:
            _require(proposal.get("expected_outcomes") == attempt["expected_outcomes"]
                     and proposal.get("affected_points") == attempt["affected_points"]
                     and proposal.get("dependencies") == attempt["dependencies"]
                     and proposal.get("guardrails") == attempt["guardrails"],
                     f"attempt {expected_id} proposal must bind expected outcomes, impact, dependencies and guardrails before editing")
        if keep_rule_contract:
            _require(proposal.get("keep_rule") == keep_rule_contract,
                     f"attempt {expected_id} proposal must freeze the keep rule and panel before editing")
        _require(attempt.get("before", {}).get("source_ref") == previous_source_ref,
                 f"attempt {expected_id} does not start from the preceding retained source")
        if format_version == 2:
            _require(attempt["before"].get("version_id") == (
                baseline.get("version_id") if expected_id == 1
                else iterations[expected_id - 2].get("version_id")),
                f"attempt {expected_id} before snapshot has the wrong version")
            _require(attempt.get("after", {}).get("version_id") == current_version,
                     f"attempt {expected_id} after snapshot has the wrong version")
        _, old_scores, old_checks, old_findings = snapshot(
            attempt["before"], f"attempt {expected_id} before")
        _, new_scores, new_checks, new_findings = snapshot(
            attempt.get("after"), f"attempt {expected_id} after",
            affected_points=attempt.get("affected_points", ()))
        paired = None
        paired_stats = {}
        if keep_rule_contract:
            paired_ref = attempt.get("paired_scores_ref")
            _require(paired_ref in attempt["actual_evidence"],
                     f"attempt {expected_id} paired scores must appear in actual_evidence")
            paired, parsed = _paired_scores(
                path.parent, artifacts, paired_ref, expected_id, keep_rule_contract,
                attempt["before"]["source_ref"], attempt["after"]["source_ref"],
                set(old_scores["points"]) | set(new_scores["points"]))
            paired_stats = _pair_statistics(parsed)
            for point_id, statistics in paired_stats.items():
                historical = old_scores["points"].get(point_id, {}).get("score")
                statistics["baseline_drift"] = (
                    statistics["baseline_mean"] - historical
                    if statistics["baseline_mean"] is not None and historical is not None else None)
        attempt_comparison_status = (
            "reviewer_changed"
            if old_scores["reviewer"] != new_scores["reviewer"]
            else "legacy_unspecified"
        )
        if format_version == 2:
            before_version = attempt["before"]["version_id"]
            after_version = attempt["after"]["version_id"]
            mapping = next((item for item in version_mappings
                            if item["from"] == before_version
                            and item["to"] == after_version), None)
            if old_scores["reviewer"] != new_scores["reviewer"]:
                attempt_comparison_status = "reviewer_changed"
            elif before_version == after_version or mapping and mapping["compatible"]:
                attempt_comparison_status = "compatible"
            else:
                attempt_comparison_status = "incompatible"
        visual_ref = attempt.get("visual_ref")
        visual_data = None
        if visual_ref is not None:
            _require(isinstance(visual_ref, str) and visual_ref.strip(),
                     f"attempt {expected_id} visual_ref must name a bound artifact")
            visual_data = _visual_evidence(
                path.parent, artifacts, visual_ref, expected_id,
                attempt["before"]["source_ref"], attempt["after"]["source_ref"])
            if format_version == 2:
                visual_refs = {
                    visual_ref, visual_data["before_capture_ref"],
                    visual_data["after_capture_ref"],
                }
                _require(visual_refs <= set(attempt["actual_evidence"]),
                         f"attempt {expected_id} visual evidence and captures must be in actual_evidence")
        score_changes = {}
        points_by_id = {point["id"]: point for point in points}
        targeted_points = dimensions
        targeted_point_ids = set(targeted_points)
        expected_gains = attempt.get("expected_gain", {})
        for point_id in comparison_point_ids:
            before_point = old_scores["points"].get(point_id)
            after_point = new_scores["points"].get(point_id)
            if before_point is None and after_point is None:
                continue
            before_score = before_point.get("score") if before_point else None
            after_score = after_point.get("score") if after_point else None
            if paired:
                before_score = paired_stats[point_id]["baseline_mean"]
                after_score = paired_stats[point_id]["candidate_mean"]
            comparable = (
                old_scores["reviewer"] == new_scores["reviewer"]
                and (format_version == 1 or attempt_comparison_status == "compatible")
            )
            delta = (
                after_score - before_score
                if comparable and before_score is not None and after_score is not None
                else None
            )
            point_expected_gain = expected_gains.get(point_id)
            if keep_rule_contract and point_id in dimensions:
                point_expected_gain = max(point_expected_gain, keep_rule_contract["min_gain"])
            score_changes[point_id] = {
                "selected": points_by_id.get(point_id, {}).get("selected", False),
                "targeted": point_id in targeted_point_ids,
                "expected_gain": point_expected_gain,
                "gain_status": (
                    "not_targeted" if point_id not in targeted_point_ids
                    else "not_comparable" if delta is None or point_expected_gain is None
                    else "met" if delta >= point_expected_gain and (
                        not keep_rule_contract or delta > keep_rule_contract["noise_band"])
                    else "missed"
                ),
                "before_score": before_score,
                "after_score": after_score,
                "delta": delta,
                "before_assessment_state": (
                    before_point.get("assessment_state", "legacy_unspecified")
                    if before_point else "unassessed"
                ),
                "after_assessment_state": (
                    after_point.get("assessment_state", "legacy_unspecified")
                    if after_point else "unassessed"
                ),
                "before_evidence_status": (
                    before_point.get("evidence_status", "not_assessed")
                    if before_point else "not_assessed"
                ),
                "after_evidence_status": (
                    after_point.get("evidence_status", "not_assessed")
                    if after_point else "not_assessed"
                ),
                "before_evidence": before_point.get("evidence", []) if before_point else [],
                "after_evidence": after_point.get("evidence", []) if after_point else [],
            }
        attempt_reports.append({
            "id": expected_id,
            "hypothesis": attempt["hypothesis"],
            "decision": attempt.get("decision"),
            "reason": attempt.get("reason"),
            "reviewer_kind": new_scores["reviewer"]["kind"],
            "reviewer": new_scores["reviewer"],
            "provisional": attempt.get("provisional"),
            "before_source_ref": attempt["before"]["source_ref"],
            "after_source_ref": attempt["after"]["source_ref"],
            "retained_source_ref": attempt.get("retained_source_ref"),
            "expected_outcomes": attempt.get("expected_outcomes", []),
            "actual_outcomes": attempt.get("actual_outcomes", []),
            "actual_evidence": attempt.get("actual_evidence", []),
            "regressions": attempt.get("regressions", []),
            "effort_minutes": attempt.get("effort_minutes"),
            "affected_points": attempt.get("affected_points", []),
            "expected_gain": expected_gains,
            "targeted_points": list(targeted_points),
            "decision_reason": attempt.get("reason"),
            "decision_records": attempt.get("decision_records", []),
            "comparison_status": attempt_comparison_status,
            "score_changes": score_changes,
            "paired_panel": {
                "panel_id": paired["panel_id"], "points": paired_stats,
                "rule": keep_rule_contract,
            } if paired else None,
            "unmet_targets": [
                key for key in dimensions if score_changes.get(key, {}).get("gain_status") != "met"
            ],
            "visual_evidence": (
                {"status": "not_provided"} if visual_data is None
                else {
                    "status": "provided",
                    "reference": visual_ref,
                    "reference_sha256": artifacts[visual_ref]["sha256"],
                    **visual_data,
                }
            ),
            "dimension_changes": {key: value["delta"] for key, value in score_changes.items()},
        })
        _require(attempt.get("reviewer_kind") == new_scores["reviewer"]["kind"],
                 f"attempt {expected_id} reviewer kind does not match score provenance")
        _require(attempt.get("decision") in DECISIONS,
                 f"attempt {expected_id} has invalid decision")
        _require(isinstance(attempt.get("reason"), str) and attempt["reason"].strip(),
                 f"attempt {expected_id} needs a decision reason")
        decision_ref = attempt.get("decision_ref")
        decision_record = _artifact(path.parent, artifacts, decision_ref)
        before_refs = attempt["before"]
        after_refs = attempt["after"]
        _require(isinstance(decision_record, dict)
                 and decision_record.get("attempt_id") == expected_id
                 and decision_record.get("decision") == attempt["decision"]
                 and decision_record.get("reason") == attempt["reason"]
                 and decision_record.get("before_artifacts") == {
                     key: artifacts[before_refs[key]]["sha256"]
                     for key in ("source_ref", "scores_ref", "checks_ref")
                 }
                 and decision_record.get("after_artifacts") == {
                     key: artifacts[after_refs[key]]["sha256"]
                     for key in ("source_ref", "scores_ref", "checks_ref")
                 },
                 f"attempt {expected_id} decision record does not bind its final evidence")
        if format_version == 2:
            expected_summary = {
                key: attempt[key] for key in (
                    "expected_outcomes", "actual_outcomes", "actual_evidence",
                    "affected_points", "dependencies", "guardrails", "regressions",
                    "effort_minutes", "decision_actor", "decision_records",
                )
            }
            if visual_ref is not None:
                expected_summary.update({
                    "visual_ref": visual_ref,
                    "visual_sha256": artifacts[visual_ref]["sha256"],
                })
            if keep_rule_contract:
                expected_summary.update({
                    "keep_rule": keep_rule_contract,
                    "paired_scores_ref": attempt["paired_scores_ref"],
                    "paired_scores_sha256": artifacts[attempt["paired_scores_ref"]]["sha256"],
                })
            _require(decision_record.get("attempt_summary") == expected_summary,
                     f"attempt {expected_id} decision does not freeze outcomes, effort, regressions and authority")
        if visual_ref is not None:
            _require(decision_record.get("visual_ref") == visual_ref,
                     f"attempt {expected_id} decision record does not bind its visual evidence")
            _require(decision_record.get("visual_sha256") == artifacts[visual_ref]["sha256"],
                     f"attempt {expected_id} decision record does not bind its visual evidence digest")
        if attempt["decision"] == "keep":
            _require(attempt.get("provisional") is True,
                     f"attempt {expected_id} keep must be provisional")
            _require(new_checks["status"] == "pass" and new_checks["full_coverage"],
                     f"attempt {expected_id} keep blocked by failed, unknown or incomplete checks")
            if format_version == 2:
                _require(all(
                    new_scores["points"][point_id]["assessment_state"] == "fresh"
                    for point_id in attempt.get("affected_points", [])
                    if point_id in new_scores["points"]),
                    f"attempt {expected_id} keep needs fresh review of every affected point")
            _require(all(result["status"] == "pass" for result in new_checks["tasks"].values()),
                     f"attempt {expected_id} keep blocked by a failed or unknown task")
            _require(old_scores["reviewer"] == new_scores["reviewer"],
                     f"attempt {expected_id} keep uses incomparable reviewer provenance")
            if format_version == 2 and attempt["before"]["version_id"] != attempt["after"]["version_id"]:
                mapping = next(item for item in version_mappings
                               if item["from"] == attempt["before"]["version_id"]
                               and item["to"] == attempt["after"]["version_id"])
                _require(mapping["compatible"],
                         f"attempt {expected_id} cannot claim a measured keep across incompatible versions")
            _require(new_findings.keys() <= old_findings.keys(),
                     f"attempt {expected_id} keep blocked by a new finding identity")
            _require(all(new_findings[key] <= old_findings[key] for key in new_findings),
                     f"attempt {expected_id} keep blocked by a worsened finding severity")
            _require(all(new_checks["tasks"][name]["clicks"] <= old_checks["tasks"][name]["clicks"]
                         for name in task_budgets),
                     f"attempt {expected_id} keep blocked by a task-click regression")
            for point_id in set(old_scores["points"]) & set(new_scores["points"]) if not paired else ():
                old_value = old_scores["points"][point_id]["score"]
                new_value = new_scores["points"][point_id]["score"]
                _require(not (old_value is not None and new_value is None),
                         f"attempt {expected_id} keep blocked by missing score {point_id!r}")
                _require(not (old_value is not None and new_value is not None
                              and new_value < old_value),
                         f"attempt {expected_id} keep blocked by score regression {point_id!r}")
            gained = all(
                point_id in old_scores["points"] and point_id in new_scores["points"]
                and
                (format_version == 1
                 or new_scores["points"][point_id]["assessment_state"] == "fresh")
                and
                new_scores["points"][point_id]["score"] is not None
                and old_scores["points"][point_id]["score"] is not None
                and new_scores["points"][point_id]["score"] - old_scores["points"][point_id]["score"]
                >= expected_gain[point_id]
                for point_id in dimensions)
            if paired:
                _require(all(not value["has_null"] for value in paired_stats.values()),
                         f"attempt {expected_id} keep blocked by unassessed paired scores")
                _require(all(value["delta"] >= 0 for value in paired_stats.values()),
                         f"attempt {expected_id} keep blocked by a paired score regression")
                improved = [key for key in dimensions if score_changes[key]["gain_status"] == "met"]
                gained = len(improved) >= keep_rule_contract["min_improved"]
                _require(gained, f"attempt {expected_id} keep lacks meaningful gains outside the noise band")
            else:
                _require(gained, f"attempt {expected_id} keep did not meet every declared target gain")
            _require(attempt.get("retained_source_ref") == attempt["after"]["source_ref"],
                     f"attempt {expected_id} keep must retain its measured after source")
            previous_source_ref = attempt["after"]["source_ref"]
            retained_scores, retained_checks = new_scores, new_checks
            no_gain = 0
        elif attempt["decision"] == "revert":
            _require(attempt.get("provisional") is False
                     and attempt.get("restore_verification_ref") in artifacts,
                     f"attempt {expected_id} revert needs verified restoration evidence")
            _require(attempt.get("retained_source_ref") == previous_source_ref,
                     f"attempt {expected_id} revert must retain its preceding accepted source")
            restore = _artifact(path.parent, artifacts, attempt["restore_verification_ref"])
            _require(isinstance(restore, dict)
                     and restore.get("verified") is True
                     and restore.get("retained_source_ref") == previous_source_ref,
                     f"attempt {expected_id} restoration evidence does not verify the retained source")
            no_gain += 1
        else:
            _require(attempt.get("provisional") is False
                     and attempt.get("retained_source_ref") is None,
                     f"attempt {expected_id} blocked attempt cannot claim a retained source")
            no_gain += 1
            _require(expected_id == len(iterations),
                     "a blocked attempt must be the final recorded attempt")

    stop = ledger.get("stop")
    _require(isinstance(stop, dict) and stop.get("reason") in STOP_REASONS,
             "stop needs a recognized reason")
    _require(len(iterations) <= contract.get("attempt_limit", 0)
             and type(contract.get("attempt_limit")) is int
             and contract["attempt_limit"] > 0,
             "attempt count exceeds or lacks its positive declared limit")
    _require(type(contract.get("no_gain_limit")) is int and contract["no_gain_limit"] > 0,
             "no_gain_limit must be a positive declared integer")
    if stop["reason"] == "scope_challenge":
        _require(format_version == 2 and isinstance(stop.get("missing_scope"), list)
                 and bool(stop["missing_scope"])
                 and all(isinstance(value, str) and value.strip() for value in stop["missing_scope"]),
                 "scope_challenge needs format-2 missing_scope view ids")
        feedback = _artifact(path.parent, artifacts, stop.get("sponsor_feedback_ref"))
        _require(isinstance(feedback, dict) and INTAKE.text(feedback.get("quote"))
                 and INTAKE.text(feedback.get("actor")) and INTAKE.date(feedback.get("date"))
                 and feedback.get("missing_scope") == stop["missing_scope"],
                 "scope_challenge needs hash-bound sponsor feedback matching missing_scope")
        intake_views = (brief.get("intake") or {}).get("views", [])
        _require(all(value in {view["id"] for view in intake_views}
                     for value in stop["missing_scope"]),
                 "scope_challenge must name inventory views; revise intake to record new scope first")
    elif stop["reason"] == "blocked":
        _require(not iterations or iterations[-1]["decision"] == "blocked",
                 "blocked stop needs a blocked final attempt or explicit baseline blocker")
    elif stop["reason"] == "iteration_cap":
        _require(len(iterations) == contract["attempt_limit"],
                 "iteration_cap stop was not reached")
    elif stop["reason"] == "no_gain":
        _require(no_gain >= contract.get("no_gain_limit", math.inf),
                 "no_gain stop was not reached")
    elif stop["reason"] == "budget":
        budget = brief["budget"].get("limit_minutes") if format_version == 2 else None
        _require(budget is not None and total_effort >= budget
                 and isinstance(stop.get("next_round"), dict),
                 "budget stop needs the declared budget to be reached and a next-round suggestion")
    else:
        _require(stop.get("final_review_status") in {"adoptable", "not_adoptable", "blocked"}
                 and isinstance(stop.get("final_review_ref"), str),
                 "provisional target stop needs a final review status and evidence")
        final_review = _artifact(path.parent, artifacts, stop["final_review_ref"])
        final_review_record = final_review
        _require(isinstance(final_review, dict)
                 and final_review.get("source_ref") == previous_source_ref
                 and final_review.get("scope_id") == scope_id
                 and final_review.get("build_id") ==
                 _source(path.parent, artifacts, previous_source_ref, scope_id).get("build_id")
                 and final_review.get("status") == stop["final_review_status"],
                 "final review does not match the retained source, scope, build or recorded status")
        if stop["final_review_status"] == "adoptable":
            _require(isinstance(final_review.get("reviewer"), dict)
                     and final_review["reviewer"].get("kind") == "independent_qualified_review",
                     "adoptable final review needs independent qualified review provenance")
            if format_version == 2:
                _require(brief["status"] == "complete"
                         and brief["quality_goal"]["status"] == "approved"
                         and all(item["status"] == "approved"
                                 for item in brief["decision_authority"]["decisions"]
                                 if item["owner"] == "sponsor"),
                         "an incomplete brief or unapproved sponsor decisions cannot produce an acceptance claim")
        current_scores = retained_scores
        current_checks = retained_checks
        achieved = sum(
            point["selected"] and current_scores["points"][point["id"]]["score"] is not None
            and current_scores["points"][point["id"]]["score"] >= goal["score"]
            and (format_version == 1
                 or current_scores["points"][point["id"]]["assessment_state"] == "fresh")
            for point in points
        )
        _require(achieved >= math.ceil(
                     (selected_count if format_version == 2 else len(points)) * goal["fraction"])
                 and current_checks["status"] == "pass" and current_checks["full_coverage"],
                 "target_provisionally_met needs current complete scores and passing full checks")
    if iterations and iterations[-1]["decision"] == "blocked":
        _require(stop["reason"] == "blocked",
                 "a blocked final attempt must use the higher-priority blocked stop")
    _require(stop.get("retained_source_ref") == previous_source_ref,
             "stop must identify the retained source")
    _require(isinstance(stop.get("reason_text"), str) and stop["reason_text"].strip(),
             "stop needs an explicit reason")
    if format_version == 2 and stop["reason"] in {"no_gain", "budget"}:
        suggestion = stop.get("next_round")
        _require(isinstance(suggestion, dict)
                 and suggestion.get("trigger") == stop["reason"]
                 and suggestion.get("action") in {
                     "revisit_brief", "test_larger_alternative", "stop_with_reason"}
                 and isinstance(suggestion.get("rationale"), str)
                 and suggestion["rationale"].strip()
                 and isinstance(suggestion.get("hypothesis"), str)
                 and suggestion["hypothesis"].strip(),
                 "plateau or budget stops need an actionable next-round hypothesis and rationale")
        _require(set(suggestion) <= {
            "trigger", "action", "hypothesis", "rationale",
            "budget_remaining_minutes", "proposed_effort_minutes",
        }, "next-round suggestions cannot change scores or lower the declared goal")
        remaining = suggestion.get("budget_remaining_minutes")
        proposed_effort = suggestion.get("proposed_effort_minutes")
        _require(remaining is None or type(remaining) in (int, float)
                 and math.isfinite(remaining) and remaining >= 0,
                 "next-round budget remainder must be nonnegative or null")
        _require(proposed_effort is None or type(proposed_effort) in (int, float)
                 and math.isfinite(proposed_effort) and proposed_effort >= 0,
                 "next-round effort must be nonnegative or null")
        budget_limit = brief["budget"].get("limit_minutes")
        if budget_limit is not None:
            _require(remaining is not None and total_effort + remaining <= budget_limit,
                     "next-round suggestion must state remaining project budget")
        if suggestion["action"] == "test_larger_alternative":
            _require(remaining is not None and proposed_effort is not None
                     and 0 < proposed_effort <= remaining,
                     "a larger alternative must fit within the declared remaining budget")
    if format_version == 2:
        _require(total_effort <= (brief["budget"].get("limit_minutes")
                                  if brief["budget"].get("limit_minutes") is not None
                                  else math.inf)
                 or stop["reason"] == "budget",
                 "recorded effort exceeds the project budget without a budget stop")
    retained_version = None
    if format_version == 2:
        retained_version = baseline.get("version_id")
        if iterations:
            final_attempt = iterations[-1]
            retained_version = (
                final_attempt.get("version_id") if final_attempt.get("decision") == "keep"
                else final_attempt.get("before", {}).get("version_id", retained_version)
            )
    latest_version = version_history[-1]["id"] if format_version == 2 else None
    version_comparison = {"status": "legacy_unspecified", "reason": "format-1 has no version mapping"}
    if format_version == 2:
        if retained_version != latest_version:
            version_path = []
            cursor = baseline["version_id"]
            for mapping in version_mappings:
                if mapping["from"] == cursor:
                    version_path.append(mapping)
                    cursor = mapping["to"]
                    if cursor == latest_version:
                        break
            incompatible = cursor == latest_version and any(
                not item["compatible"] for item in version_path)
            version_comparison = {
                "status": "incompatible" if incompatible else "incomplete",
                "reason": (
                    "The baseline-to-current contract mapping is incompatible; "
                    f"the retained source uses {retained_version}, not {latest_version}."
                    if incompatible else
                    f"Latest contract {latest_version} has no retained measurement; "
                    f"the retained source uses {retained_version}."
                ),
            }
        elif retained_version == baseline["version_id"]:
            version_comparison = {"status": "compatible", "reason": "same contract version"}
        else:
            transitions = []
            cursor = baseline["version_id"]
            for mapping in version_mappings:
                if mapping["from"] == cursor:
                    transitions.append(mapping)
                    cursor = mapping["to"]
                    if cursor == retained_version:
                        break
            transition = transitions if cursor == retained_version else None
            compatible = bool(transition) and all(item["compatible"] for item in transition)
            version_comparison = {
                "status": "compatible" if compatible else "incompatible",
                "reason": "; ".join(item["reason"] for item in transition) if transition else
                "No direct baseline mapping; totals are not comparable.",
            }
    return {
        "path": str(path),
        "contract": contract,
        "current_build_id": _source(
            path.parent, artifacts, previous_source_ref, scope_id).get("build_id"),
        "artifacts": artifacts,
        "baseline": baseline,
        "baseline_scores": before_scores,
        "baseline_checks": before_checks,
        "iterations": iterations,
        "attempt_reports": attempt_reports,
        "stop": stop,
        "retained_source_ref": previous_source_ref,
        "current_scores": retained_scores,
        "current_checks": retained_checks,
        "format_version": format_version,
        "brief": brief,
        "version_history": version_history,
        "version_mappings": version_mappings,
        "version_comparison": version_comparison,
        "total_effort_minutes": total_effort,
        "comparison_point_ids": comparison_point_ids,
        "final_review": final_review_record,
    }


def report(verified):
    contract = verified["contract"]
    points = contract["points"]
    denominator = len(points)
    goal = contract["goal"]
    brief = verified.get("brief")
    scope_report = (
        INTAKE.validate(brief, root=Path(verified["path"]).parent)
        if isinstance(brief, dict) and "intake" in brief else None)
    selected_points = [point for point in points if point["selected"]]
    target_count = math.ceil(
        (len(selected_points) if verified["format_version"] == 2 else denominator)
        * goal["fraction"])
    excluded_points = [point["id"] for point in points if not point["selected"]]
    scores = verified["current_scores"]
    scores_by_point = scores["points"]

    def score_for(point_id):
        return scores_by_point.get(point_id, {
            "score": None, "evidence_status": "not_assessed",
            "assessment_state": "unassessed", "evidence": [],
            "evidence_coverage": {}, "review_required": False,
        })

    baseline_by_point = verified["baseline_scores"]["points"]
    fresh_only = verified["format_version"] == 2
    achieved = sum(
        point["selected"] and score_for(point["id"])["score"] is not None
        and score_for(point["id"])["score"] >= goal["score"]
        and (not fresh_only or score_for(point["id"])["assessment_state"] == "fresh")
        for point in points
    )
    progress_by_kind = {}
    for kind in REVIEWER_KINDS:
        progress_by_kind[kind] = sum(
            point["selected"] and score_for(point["id"])["score"] is not None
            and score_for(point["id"])["score"] >= goal["score"]
            and (not fresh_only or score_for(point["id"])["assessment_state"] == "fresh")
            and scores["reviewer"]["kind"] == kind
            for point in points
        )
    missing_or_below = [
        point["id"] for point in points if point["selected"] and (
            score_for(point["id"])["score"] is None
            or score_for(point["id"])["score"] < goal["score"]
            or fresh_only and score_for(point["id"])["assessment_state"] != "fresh")
    ]
    unassessed = [
        point["id"] for point in selected_points if (
            score_for(point["id"])["score"] is None
            or fresh_only and score_for(point["id"])["assessment_state"] == "unassessed")
    ]
    carried = [
        point["id"] for point in selected_points if fresh_only
        and score_for(point["id"])["assessment_state"] == "carried_forward"
    ]
    stale = [
        point["id"] for point in selected_points if fresh_only
        and score_for(point["id"])["assessment_state"] == "stale"
    ]
    coverage_gaps = [
        {"point_id": point["id"], "evidence_ref": ref}
        for point in points
        for ref, declaration in score_for(point["id"]).get("evidence_coverage", {}).items()
        if point["id"] not in declaration.get("point_ids", [])
    ]
    latest = verified["current_checks"]
    profile_presence = {}
    failed_profile_presence = {}
    outcomes_by_kind = {}
    for observation in latest.get("observations", []):
        profile_presence.setdefault(observation["finding_id"], set()).add(observation["profile"])
        if observation["outcome"] == "fail":
            failed_profile_presence.setdefault(
                observation["finding_id"], set()).add(observation["profile"])
        outcomes_by_kind.setdefault(observation["evidence_kind"], {}).setdefault(
            observation["outcome"], 0)
        outcomes_by_kind[observation["evidence_kind"]][observation["outcome"]] += 1
    observed_evidence_kinds = sorted({
        observation["evidence_kind"] for observation in latest.get("observations", [])
    })
    recurring = sum(len(profiles) > 1 for profiles in profile_presence.values())
    point_reports = []
    for point in points:
        current = score_for(point["id"])
        baseline = baseline_by_point.get(point["id"], {})
        current_value = current["score"]
        baseline_value = baseline.get("score")
        point_reports.append({
            "id": point["id"],
            "selected": point["selected"],
            "before_score": baseline_value,
            "current_score": current_value,
            "change": (
                current_value - baseline_value
                if current_value is not None and baseline_value is not None
            and (not fresh_only or (
                verified["version_comparison"]["status"] == "compatible"
                and verified["baseline_scores"]["reviewer"] == scores["reviewer"]
            ))
                else None
            ),
            "evidence_status": current["evidence_status"],
            "assessment_state": current.get("assessment_state", "legacy_unspecified"),
            "assessed_source_ref": current.get("assessed_source_ref"),
            "review_required": current.get("review_required", False),
            "reviewer_kind": scores["reviewer"]["kind"],
            "rubric_anchor": current.get("anchor"),
            "evidence": current["evidence"],
            "evidence_coverage": current.get("evidence_coverage", {}),
            "scopes": point.get("scopes", []),
        })
    scope_reports = []
    for scope in contract.get("scopes", []):
        members = [
            point for point in points
            if scope["id"] in point.get("scopes", [])
        ]
        selected_members = [point for point in members if point["selected"]]
        scope_reports.append({
            "id": scope["id"],
            "kind": scope["kind"],
            "name": scope["name"],
            "point_ids": [point["id"] for point in members],
            "denominator": len(members),
            "selected_denominator": len(selected_members),
            "achieved_fresh_points": sum(
                score_for(point["id"])["score"] is not None
                and score_for(point["id"])["score"] >= goal["score"]
                and (not fresh_only
                     or score_for(point["id"])["assessment_state"] == "fresh")
                for point in selected_members
            ),
            "unassessed_points": [
                point["id"] for point in selected_members
                if score_for(point["id"])["score"] is None
                or fresh_only and score_for(point["id"])["assessment_state"] == "unassessed"
            ],
            "carried_points": [
                point["id"] for point in selected_members if fresh_only
                and score_for(point["id"])["assessment_state"] == "carried_forward"
            ],
            "stale_points": [
                point["id"] for point in selected_members if fresh_only
                and score_for(point["id"])["assessment_state"] == "stale"
            ],
            "task_outcomes": [
                {"task_id": task_id,
                 **verified["current_checks"]["tasks"][task_id]}
                for task_id in scope.get("task_ids", [])
            ],
            "failed_journey": scope["kind"] == "journey" and (
                any(
                    score_for(point["id"])["score"] is None
                    or score_for(point["id"])["score"] < goal["score"]
                    or fresh_only and score_for(point["id"])["assessment_state"] != "fresh"
                    for point in selected_members
                )
                or any(verified["current_checks"]["tasks"][task_id]["status"] != "pass"
                       for task_id in scope.get("task_ids", []))
            ),
        })
    return {
        "scope_id": contract["scope_id"],
        "scope_header": scope_report["scope_header"] if scope_report else "Scope: undeclared (legacy)",
        "scope_coverage": scope_report["coverage"] if scope_report else None,
        "scope_claim": (
            "partial-scope" if scope_report and scope_report["coverage"]["total"] > 0 and (
                scope_report["coverage"]["assessment"] == "not_assessed"
                or scope_report["coverage"]["covered"] < scope_report["coverage"]["total"])
            else "legacy_unspecified" if scope_report is None else "declared-scope"),
        "build_id": verified["current_build_id"],
        "goal": {
            "scope_denominator": scope_report["coverage"]["total"] if scope_report else None,
            "score": goal["score"],
            "fraction": goal["fraction"],
            "claim_scope": (
                "all_declared_points" if len(selected_points) == denominator
                else "selected_subset"
            ),
            "selected_point_count": len(selected_points),
            "selected_denominator": len(selected_points),
            "excluded_points": excluded_points,
            "achieved_selected_points": achieved,
            "required_selected_points": target_count,
            "denominator": denominator,
            "missing_or_below_goal": missing_or_below,
            "unassessed_selected_points": unassessed,
            "carried_selected_points": carried,
            "stale_selected_points": stale,
            "missing_evidence": [
                point["id"] for point in points if (
                    score_for(point["id"])["score"] is None
                    or fresh_only and score_for(point["id"])["assessment_state"] != "fresh")
            ],
        },
        "points": point_reports,
        "reviewer": scores["reviewer"],
        "baseline_reviewer": verified["baseline_scores"]["reviewer"],
        "reviewer_provenance_comparison": {
            "same_declared_reviewer": (
                verified["baseline_scores"]["reviewer"] == scores["reviewer"]),
            "baseline_kind": verified["baseline_scores"]["reviewer"]["kind"],
            "current_kind": scores["reviewer"]["kind"],
            "limitation": "Declared identity and kind are provenance labels, not proof of independence or qualification.",
        },
        "progress_by_reviewer_kind": progress_by_kind,
        "check_evidence_kinds": observed_evidence_kinds,
        "attempts": len(verified["iterations"]),
        "attempt_reports": verified["attempt_reports"],
        "elapsed_minutes": contract.get("elapsed_minutes"),
        "review_effort_minutes": contract.get("review_effort_minutes"),
        "verification_elapsed_seconds": contract.get("verification_elapsed_seconds"),
        "unknown_costs": [
            field for field in ("elapsed_minutes", "review_effort_minutes",
                                "verification_elapsed_seconds")
            if contract.get(field) is None
        ],
        "findings": {
            "distinct_observation_identities": len(profile_presence),
            "distinct_finding_identities": len(failed_profile_presence),
            "recurring_observation_identities": recurring,
            "recurring_finding_identities": sum(
                len(profiles) > 1 for profiles in failed_profile_presence.values()),
            "profile_occurrences": sum(map(len, profile_presence.values())),
            "outcomes_by_evidence_kind": outcomes_by_kind,
        },
        "scenario_coverage": [
            {**scenario, **next(item for item in latest["scenario_evidence"]
                                if item["id"] == scenario["id"])}
            for scenario in contract["required_scenarios"]
        ],
        "feasibility": contract["feasibility"],
        "stop": verified["stop"],
        "final_review": verified["final_review"],
        "version_comparison": verified["version_comparison"],
        "versions": [
            {"id": item["id"], "parent": item["parent"],
             "goal": item["goal"], "point_ids": item["point_ids"],
             "selected_point_ids": item["selected_point_ids"],
             "scope_ids": item["scope_ids"]}
            for item in verified["version_history"]
        ],
        "version_mappings": verified["version_mappings"],
        "next_round": verified["stop"].get("next_round"),
        "brief": ({
            "status": verified["brief"]["status"],
            "brief_version": verified["brief"]["brief_version"],
            "unresolved_questions": verified["brief"]["unresolved_questions"],
            "decision_authority": verified["brief"]["decision_authority"],
        } if verified["brief"] else {"status": "legacy_unspecified"}),
        "scopes": scope_reports,
        "total_effort_minutes": verified["total_effort_minutes"],
        "evidence_coverage_gaps": coverage_gaps,
        "limitations": [
            "Reviewer labels are declared provenance, not proof of independence or qualification.",
            "Artifact hashes identify bytes; they do not prove truth, capture time, or historical authenticity.",
        ],
    }


def _html_text(value):
    return html.escape(str(value), quote=True)


def _score_label(value):
    return "Not assessed" if value is None else str(value)


def _render_arrow_overlay(evidence, side, attempt_id):
    dimensions = evidence[f"{side}_capture_dimensions"]
    width = dimensions["width"]
    height = dimensions["height"]
    lines = []
    markers = []
    for index, change in enumerate(evidence["changes"], 1):
        arrow = change[side]
        start = arrow["start"]
        end = arrow["end"]
        marker_id = f"arrow-{attempt_id}-{side}-{index}"
        start_x = start["x"] * width
        start_y = start["y"] * height
        end_x = end["x"] * width
        end_y = end["y"] * height
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.hypot(dx, dy)
        radius = min(28.0, width / 4, height / 4, length / 4)
        stroke_width = max(1.0, radius * 0.28)
        badge_stroke_width = min(3.0, radius * 0.1)
        marker_size = min(24.0, radius * 0.9)
        font_size = max(1.0, min(32.0, radius * 1.1))
        badge_x = start_x - (dx / length * radius * 1.8 if length else 0)
        badge_y = start_y - (dy / length * radius * 1.8 if length else 0)
        badge_x = min(max(badge_x, radius), width - radius)
        badge_y = min(max(badge_y, radius), height - radius)
        lines.append(
            f'<line x1="{start_x:.3f}" y1="{start_y:.3f}" '
            f'x2="{end_x:.3f}" y2="{end_y:.3f}" '
            f'class="change-arrow" stroke-width="{stroke_width:.3f}" '
            f'marker-end="url(#{marker_id})"></line>'
            f'<circle cx="{badge_x:.3f}" cy="{badge_y:.3f}" '
            f'r="{radius:.3f}" class="arrow-number" '
            f'stroke-width="{badge_stroke_width:.3f}"></circle>'
            f'<text x="{badge_x:.3f}" y="{badge_y:.3f}" '
            f'class="arrow-number-text" font-size="{font_size:.3f}">{index}</text>'
        )
        markers.append(
            f'<marker id="{marker_id}" markerWidth="{marker_size:.3f}" '
            f'markerHeight="{marker_size:.3f}" refX="{marker_size:.3f}" '
            f'refY="{marker_size / 2:.3f}" orient="auto" '
            f'markerUnits="userSpaceOnUse"><path d="M0 0 '
            f'L{marker_size:.3f} {marker_size / 2:.3f} L0 {marker_size:.3f} z" '
            f'class="arrow-head"></path></marker>'
        )
    return (
        f'<svg class="arrow-overlay" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false">'
        f"<defs>{''.join(markers)}</defs>{''.join(lines)}</svg>"
    )


def _render_capture(verified, evidence, side, attempt_id):
    reference = evidence[f"{side}_capture_ref"]
    data = _bytes(Path(verified["path"]).parent, verified["artifacts"], reference)
    encoded = base64.b64encode(data).decode("ascii")
    title = "Before" if side == "before" else "After"
    overlay = _render_arrow_overlay(evidence, side, attempt_id)
    alt_text = (
        f"{title} capture with numbered red arrows marking the reported changes"
        if evidence["changes"] else
        f"{title} capture; no visual annotations were supplied"
    )
    return (
        f'<figure class="capture-figure"><figcaption>{title} capture '
        f'<span class="artifact-ref">{_html_text(reference)}</span></figcaption>'
        f'<div class="capture-frame"><img src="data:image/png;base64,{encoded}" '
        f'alt="{_html_text(alt_text)}" '
        f'aria-describedby="changes-{attempt_id}">'
        f"{overlay}</div></figure>"
    )


def _render_change_notes(evidence):
    if not evidence["changes"]:
        return (
            f'<p class="empty-evidence" id="changes-{_html_text(evidence["attempt_id"])}">'
            'No changes were annotated in this attempt; arrows were not inferred.</p>'
        )
    cards = []
    for index, change in enumerate(evidence["changes"], 1):
        cards.append(
            f'<li class="change-note"><span class="change-number" aria-hidden="true">'
            f'{index}</span><div><h4>{_html_text(change["label"])}</h4>'
            f'<p>{_html_text(change["description"])}</p></div></li>'
        )
    return f'<ol class="change-notes" id="changes-{_html_text(evidence["attempt_id"])}">{"".join(cards)}</ol>'


def _render_score_table(attempt):
    rows = []
    for point_id, change in attempt["score_changes"].items():
        delta = change["delta"]
        delta_text = "Not comparable" if delta is None else f"{delta:+g}"
        selected = "Selected" if change["selected"] else "Excluded"
        evidence = []
        if change["before_evidence"]:
            evidence.append("before: " + ", ".join(change["before_evidence"]))
        if change["after_evidence"]:
            evidence.append("after: " + ", ".join(change["after_evidence"]))
        if not evidence:
            evidence.append("No evidence references")
        target_label = "Not targeted"
        if change["targeted"]:
            if change["expected_gain"] is None:
                target_label = "Target · gain not declared"
            else:
                result = {
                    "met": "met",
                    "missed": "missed",
                    "not_comparable": "not comparable",
                }[change["gain_status"]]
                target_label = f'Target +{change["expected_gain"]} ({result})'
        rows.append(
            '<tr>'
            f'<th scope="row">{_html_text(point_id)}'
            f'<span class="selection-status">{selected}</span>'
            f'<span class="target-status">{_html_text(target_label)}</span></th>'
            f'<td><span class="mobile-cell-label">Before</span>'
            f'{_score_label(change["before_score"])}'
            f'<small>{_html_text(change["before_assessment_state"])} · '
            f'{_html_text(change["before_evidence_status"])}</small></td>'
            f'<td><span class="mobile-cell-label">After</span>'
            f'{_score_label(change["after_score"])}'
            f'<small>{_html_text(change["after_assessment_state"])} · '
            f'{_html_text(change["after_evidence_status"])}</small></td>'
            f'<td><span class="mobile-cell-label">Delta</span>'
            f'<strong>{delta_text}</strong></td>'
            f'<td><span class="mobile-cell-label">Evidence</span>'
            f'<small>{_html_text(" · ".join(evidence))}</small></td>'
            '</tr>'
        )
    if not rows:
        return '<p class="empty-evidence">No score changes were recorded.</p>'
    return (
        '<div class="score-table-wrap"><table class="score-table">'
        '<caption>Per-point scores for this attempt</caption>'
        '<thead><tr><th scope="col">Point</th><th scope="col">Before</th>'
        '<th scope="col">After</th><th scope="col">Delta</th>'
        '<th scope="col">Evidence</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _render_attempt(verified, attempt):
    attempt_id = attempt["id"]
    evidence = attempt["visual_evidence"]
    decision = attempt.get("decision") or "unrecorded"
    evidence_html = ""
    if evidence["status"] == "provided":
        evidence_html = (
            '<section class="section visual-section" aria-labelledby="visual-'
            f'{attempt_id}"><div class="section-heading"><div><p class="eyebrow">'
            'Visual evidence</p><h3 id="visual-'
            f'{attempt_id}">Before and after</h3></div>'
            f'<span class="artifact-ref">Bound: {_html_text(evidence["reference"])}</span>'
            '</div><div class="capture-grid">'
            f'{_render_capture(verified, evidence, "before", attempt_id)}'
            f'{_render_capture(verified, evidence, "after", attempt_id)}'
            f'</div>{_render_change_notes(evidence)}</section>'
        )
    else:
        evidence_html = (
            '<section class="section visual-section" aria-labelledby="visual-'
            f'{attempt_id}"><p class="eyebrow">Visual evidence</p>'
            f'<h3 id="visual-{attempt_id}">No captures supplied</h3>'
            '<p class="empty-evidence">'
            'No captures or annotations were supplied for this attempt. '
            'No arrows were inferred.</p></section>'
        )

    outcome_items = []
    for label, key in (("Expected outcomes", "expected_outcomes"),
                       ("Observed outcomes", "actual_outcomes"),
                       ("Regressions", "regressions")):
        values = attempt.get(key, [])
        if values:
            content = "".join(f"<li>{_html_text(item)}</li>" for item in values)
        else:
            content = "<li>None recorded</li>"
        outcome_items.append(
            f'<div class="outcome-block"><h4>{label}</h4><ul>{content}</ul></div>'
        )
    refs = attempt.get("actual_evidence", [])
    evidence_refs = (
        ", ".join(_html_text(reference) for reference in refs)
        if refs else "No additional evidence references"
    )
    comparison = attempt.get("comparison_status", "legacy_unspecified")
    decision_label = (
        f'{decision.title()} (provisional)'
        if attempt.get("provisional") is True else decision.title()
    )
    effort = (
        f'{attempt["effort_minutes"]} minutes'
        if attempt.get("effort_minutes") is not None else "Not recorded"
    )
    panel = attempt.get("paired_panel")
    panel_html = ""
    if panel:
        drift = "; ".join(
            f'{key}: {value["baseline_drift"] if value["baseline_drift"] is not None else "not assessed"}'
            for key, value in panel["points"].items())
        panel_html = (
            f'<p><strong>Paired panel:</strong> {_html_text(panel["panel_id"])}. '
            f'Scores below are paired means; noise band {_html_text(panel["rule"]["noise_band"])}. '
            f'<strong>Baseline drift:</strong> {_html_text(drift)}. '
            f'<strong>Unmet targets:</strong> {_html_text(", ".join(attempt["unmet_targets"]) or "none")}.</p>'
        )
    return (
        f'<article class="attempt-card" id="attempt-{attempt_id}">'
        '<header class="attempt-header"><div><p class="eyebrow">'
        f'Attempt {attempt_id} · {_html_text(attempt.get("reviewer_kind", "unknown"))}'
        f'</p><h2>{_html_text(attempt.get("hypothesis", "Attempt"))}</h2></div>'
        f'<span class="decision decision-{_html_text(decision)}">'
        f'{_html_text(decision_label)}</span></header>'
        f'<div class="attempt-summary"><p>{_html_text(attempt.get("decision_reason") or "No decision rationale recorded.")}</p>'
        f'<dl><div><dt>Score comparison</dt><dd>{_html_text(comparison)}</dd></div>'
        f'<div><dt>Effort</dt><dd>{_html_text(effort)}</dd></div>'
        f'<div><dt>Retained source</dt><dd>{_html_text(attempt.get("retained_source_ref") or "Not specified")}</dd></div></dl></div>'
        f'<div class="source-comparison"><span><strong>Before source:</strong> '
        f'{_html_text(attempt.get("before_source_ref") or "Not specified")}</span>'
        f'<span><strong>After source:</strong> '
        f'{_html_text(attempt.get("after_source_ref") or "Not specified")}</span></div>'
        '<section class="section"><p class="eyebrow">Scorecard</p>'
        '<h3>What changed in the scores</h3>'
        f'{panel_html}{_render_score_table(attempt)}</section>'
        f'{evidence_html}'
        '<section class="section"><p class="eyebrow">Change record</p>'
        '<h3>What was expected and observed</h3>'
        f'<div class="outcome-grid">{"".join(outcome_items)}</div>'
        f'<p class="evidence-refs"><strong>Evidence refs:</strong> {evidence_refs}</p>'
        '</section></article>'
    )


def html_report(verified, attempt_id=None):
    """Render a fully self-contained, escaped HTML report from a verified ledger."""
    data = report(verified)
    attempts = data["attempt_reports"]
    if attempt_id is not None:
        _require(type(attempt_id) is int and attempt_id > 0,
                 "--attempt must be a positive integer")
        attempts = [attempt for attempt in attempts if attempt["id"] == attempt_id]
        _require(attempts, f"attempt {attempt_id} does not exist in this ledger")
    embedded_bytes = 0
    embedded_pixels = 0
    root = Path(verified["path"]).parent
    for attempt in attempts:
        evidence = attempt["visual_evidence"]
        if evidence["status"] != "provided":
            continue
        for side in ("before", "after"):
            image = _bytes(
                root, verified["artifacts"], evidence[f"{side}_capture_ref"])
            embedded_bytes += 4 * ((len(image) + 2) // 3)
            dimensions = evidence[f"{side}_capture_dimensions"]
            embedded_pixels += dimensions["width"] * dimensions["height"]
    _require(embedded_pixels <= MAX_HTML_REPORT_PIXELS,
             f"embedded captures exceed the {MAX_HTML_REPORT_PIXELS:,}-pixel HTML report limit")
    _require(embedded_bytes <= MAX_HTML_REPORT_BYTES,
             f"embedded captures exceed the {MAX_HTML_REPORT_BYTES}-byte HTML report limit")
    rendered_attempts = "".join(
        _render_attempt(verified, attempt) for attempt in attempts
    )
    if not attempts:
        rendered_attempts = (
            '<section class="empty-report"><h2>No attempts recorded</h2>'
            '<p>This ledger contains no refinement attempts to report.</p></section>'
        )
    stop = data["stop"]
    stop_text = stop.get("reason_text") or stop.get("reason") or "Not recorded"
    final_review = data.get("final_review")
    if isinstance(final_review, dict):
        reviewer = final_review.get("reviewer")
        reviewer_label = (
            f'{reviewer.get("kind", "unknown")} · {reviewer.get("id", "unnamed")}'
            if isinstance(reviewer, dict) else "Reviewer not recorded"
        )
        final_review_text = (
            f'{final_review.get("status", "unspecified")} · {reviewer_label} · '
            f'source {final_review.get("source_ref", "unspecified")}'
        )
        final_review_text = _html_text(final_review_text)
    else:
        final_review_text = (
            "Not recorded. A kept attempt is provisional progress, not an "
            "independent acceptance or adoption decision."
        )
    limitation_items = "".join(
        f"<li>{_html_text(limitation)}</li>" for limitation in data["limitations"]
    )
    limitation_items += (
        "<li>Design scores are expert judgments, not usability outcomes or "
        "compliance percentages.</li>"
    )
    summary = (
        f'<p class="report-stop">{_html_text(data["scope_header"])}</p>'
        f'<p class="report-meta">Scope <strong>{_html_text(data["scope_id"])}</strong>'
        f'<span>Build {_html_text(data["build_id"])}</span>'
        f'<span>{data["attempts"]} attempt(s)</span></p>'
        f'<p class="report-stop"><strong>Run stop:</strong> {_html_text(stop_text)}</p>'
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Refinement report · {_html_text(data["scope_id"])}</title>
<style>
:root {{
  color-scheme: light;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --ink: #17212b; --page: #f3f5f7; --surface: #fff; --muted: #46596c;
  --text-secondary: #34495c; --subtle: #526579; --line: #d5dce3;
  --line-soft: #e1e6eb; --line-strong: #cbd4dd; --empty-line: #9aa8b5;
  --panel: #edf2f6; --capture-bg: #edf1f4; --empty-bg: #f7f9fa;
  --decision-bg: #e8edf2; --decision-ink: #283b4d;
  --keep-bg: #e5f4eb; --keep-ink: #175c35;
  --revert-bg: #fff2df; --revert-ink: #744700;
  --blocked-bg: #fce8e8; --blocked-ink: #7d1717;
  --focus: #0b5cab; --arrow: #c62836;
  --shadow: 0 8px 24px rgb(23 33 43 / 5%);
  color: var(--ink); background: var(--page); font-synthesis: none;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; line-height: 1.5; }}
main {{ width: min(1120px, 100% - 32px); margin: 0 auto; padding: 32px 0 64px; }}
h1, h2, h3, h4, p {{ margin-top: 0; }}
h1 {{ margin-bottom: 8px; font-size: clamp(1.8rem, 5vw, 2.8rem); line-height: 1.1; letter-spacing: -.03em; }}
h2 {{ font-size: clamp(1.15rem, 3vw, 1.55rem); line-height: 1.25; overflow-wrap: anywhere; }}
h3 {{ margin-bottom: 16px; font-size: 1.25rem; }}
h4 {{ margin-bottom: 4px; font-size: 1rem; }}
.eyebrow {{ margin-bottom: 6px; color: var(--muted); font-size: .75rem; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }}
.report-header {{ padding: 24px; border: 1px solid var(--line); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }}
.report-meta {{ display: flex; flex-wrap: wrap; gap: 8px 20px; margin-bottom: 8px; color: var(--muted); font-size: .9rem; }}
.report-stop {{ margin: 0; padding: 12px 14px; border-left: 4px solid var(--subtle); border-radius: 4px; background: var(--panel); overflow-wrap: anywhere; }}
.attempt-list {{ display: grid; gap: 24px; margin-top: 24px; }}
.attempt-card {{ min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }}
.attempt-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 24px 24px 16px; }}
.attempt-header h2 {{ max-width: 760px; margin-bottom: 0; }}
.attempt-summary {{ padding: 0 24px 20px; }}
.attempt-summary > p {{ max-width: 80ch; color: var(--text-secondary); }}
.attempt-summary dl {{ display: flex; flex-wrap: wrap; gap: 12px 28px; margin: 0; }}
.attempt-summary dl div {{ min-width: 140px; max-width: 100%; }}
dt {{ color: var(--subtle); font-size: .78rem; font-weight: 700; }}
dd {{ margin: 2px 0 0; overflow-wrap: anywhere; font-weight: 600; }}
.decision {{ flex: none; padding: 6px 12px; border-radius: 999px; background: var(--decision-bg); color: var(--decision-ink); font-size: .85rem; font-weight: 750; }}
.decision-keep {{ background: var(--keep-bg); color: var(--keep-ink); }}
.decision-revert {{ background: var(--revert-bg); color: var(--revert-ink); }}
.decision-blocked {{ background: var(--blocked-bg); color: var(--blocked-ink); }}
.section {{ padding: 22px 24px; border-top: 1px solid var(--line-soft); }}
.section-heading {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }}
.section-heading h3 {{ margin-bottom: 0; }}
.artifact-ref {{ max-width: 100%; color: var(--subtle); font-size: .78rem; overflow-wrap: anywhere; }}
.score-table-wrap {{ width: 100%; }}
.score-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
.score-table caption {{ padding-bottom: 8px; color: var(--subtle); font-size: .85rem; text-align: left; }}
.score-table th, .score-table td {{ padding: 11px 10px; border-top: 1px solid var(--line-soft); text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
.score-table thead th {{ color: var(--muted); font-size: .78rem; }}
.score-table tbody th {{ width: 20%; font-weight: 700; }}
.score-table small {{ display: block; margin-top: 3px; color: var(--subtle); font-size: .75rem; }}
.selection-status {{ display: inline-block; margin-left: 6px; color: var(--subtle); font-size: .7rem; font-weight: 600; }}
.mobile-cell-label {{ display: none; }}
.source-comparison {{ display: flex; flex-wrap: wrap; gap: 6px 20px; margin-top: 14px; color: var(--subtle); font-size: .8rem; overflow-wrap: anywhere; }}
.capture-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.capture-figure {{ min-width: 0; margin: 0; }}
.capture-figure figcaption {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; margin-bottom: 8px; font-weight: 750; }}
.capture-frame {{ position: relative; width: 100%; overflow: hidden; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--capture-bg); }}
.capture-frame img {{ display: block; width: 100%; height: auto; }}
.arrow-overlay {{ position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; }}
.change-arrow {{ stroke: var(--arrow); stroke-linecap: round; }}
.arrow-head {{ fill: var(--arrow); }}
.arrow-number {{ fill: var(--arrow); stroke: var(--surface); }}
.arrow-number-text {{ fill: var(--surface); font-weight: 800; text-anchor: middle; dominant-baseline: central; }}
.change-notes {{ display: grid; gap: 10px; margin: 16px 0 0; padding: 0; list-style: none; }}
.change-note {{ display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: start; gap: 10px; padding: 12px; border: 1px solid var(--line-soft); border-radius: 10px; }}
.change-number {{ display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: var(--arrow); color: var(--surface); font-size: .85rem; font-weight: 800; }}
.change-note p {{ margin: 0; color: var(--text-secondary); overflow-wrap: anywhere; }}
.outcome-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
.outcome-block {{ min-width: 0; padding: 12px; border: 1px solid var(--line-soft); border-radius: 10px; }}
.outcome-block ul {{ margin: 6px 0 0; padding-left: 20px; }}
.outcome-block li {{ margin-top: 4px; overflow-wrap: anywhere; }}
.evidence-refs {{ margin: 16px 0 0; color: var(--subtle); font-size: .82rem; overflow-wrap: anywhere; }}
.target-status {{ display: block; margin-top: 3px; color: var(--subtle); font-size: .7rem; font-weight: 600; }}
.empty-evidence {{ margin: 0; padding: 14px; border: 1px dashed var(--empty-line); border-radius: 8px; background: var(--empty-bg); color: var(--text-secondary); }}
.empty-report {{ margin-top: 24px; padding: 24px; border: 1px dashed var(--empty-line); border-radius: 14px; background: var(--surface); }}
.report-footer {{ margin-top: 24px; padding: 20px 24px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }}
.report-footer p {{ overflow-wrap: anywhere; }}
.report-footer ul {{ margin-bottom: 0; padding-left: 20px; }}
:focus-visible {{ outline: 3px solid var(--focus); outline-offset: 3px; }}
@media (max-width: 700px) {{
  main {{ width: min(100% - 20px, 1120px); padding-top: 10px; }}
  .report-header, .attempt-card {{ border-radius: 12px; }}
  .report-header {{ padding: 18px; }}
  .attempt-header {{ padding: 18px 16px 14px; }}
  .attempt-summary {{ padding: 0 16px 16px; }}
  .section {{ padding: 18px 16px; }}
  .capture-grid {{ grid-template-columns: minmax(0, 1fr); gap: 14px; }}
  .outcome-grid {{ grid-template-columns: minmax(0, 1fr); }}
  .section-heading {{ align-items: flex-start; flex-direction: column; }}
}}
@media (max-width: 480px) {{
  .attempt-header {{ flex-direction: column; gap: 10px; }}
  .attempt-summary dl {{ display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }}
  .score-table thead {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
  .score-table, .score-table tbody {{ display: block; width: 100%; }}
  .score-table tr {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; padding: 12px 0; border-top: 1px solid var(--line); }}
  .score-table th, .score-table td {{ display: block; min-width: 0; width: auto; padding: 0; border: 0; }}
  .score-table tbody th {{ grid-column: 1 / -1; }}
  .mobile-cell-label {{ display: block; margin-bottom: 2px; color: var(--subtle); font-size: .7rem; font-weight: 700; text-transform: uppercase; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; animation-duration: .01ms !important; transition-duration: .01ms !important; }} }}
@media (forced-colors: active) {{
  .report-header, .attempt-card, .outcome-block, .change-note, .capture-frame {{ border: 1px solid CanvasText; }}
  .decision, .report-stop, .empty-evidence {{ border: 1px solid CanvasText; background: Canvas; color: CanvasText; }}
  .change-arrow {{ stroke: LinkText; }}
  .arrow-head, .arrow-number, .change-number {{ fill: LinkText; background: LinkText; }}
  .arrow-number-text {{ fill: Canvas; }}
}}
</style>
</head>
<body>
<main>
<header class="report-header">
<p class="eyebrow">UI Workbench · Iterative refinement</p>
<h1>Attempt report</h1>
{summary}
</header>
<div class="attempt-list">{rendered_attempts}</div>
<footer class="report-footer">
<p class="eyebrow">Review status and limits</p>
<h2>Independent review</h2>
<p>{final_review_text}</p>
<ul>{limitation_items}</ul>
</footer>
</main>
</body>
</html>
"""
    _require(len(document.encode("utf-8")) <= MAX_HTML_REPORT_BYTES,
             f"HTML report exceeds the {MAX_HTML_REPORT_BYTES}-byte output limit")
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("verify", "report", "html"))
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--attempt", type=int,
                        help="render only this attempt (HTML command only)")
    parser.add_argument("--output", type=Path,
                        help="write HTML report to this path (HTML command only)")
    args = parser.parse_args(argv)
    try:
        _require(args.command == "html" or (
            args.attempt is None and args.output is None),
            "--attempt and --output are valid only for the HTML command")
        result = verify(args.ledger)
        if args.command == "verify":
            print(f"ledger: valid; {len(result['iterations'])} attempt(s); "
                  f"retained {result['retained_source_ref']}")
        elif args.command == "report":
            print(json.dumps(report(result), indent=2, sort_keys=True))
        else:
            rendered = html_report(result, args.attempt)
            if args.output:
                output_path = args.output.resolve()
                protected_paths = {args.ledger.resolve()}
                for artifact in result["artifacts"].values():
                    artifact_path = Path(artifact["path"])
                    if not artifact_path.is_absolute():
                        artifact_path = args.ledger.resolve().parent / artifact_path
                    protected_paths.add(artifact_path.resolve())
                _require(output_path not in protected_paths,
                         "HTML output must not overwrite the ledger or one of its artifacts")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding="utf-8")
                print(f"HTML report written to {args.output}")
            else:
                sys.stdout.write(rendered)
    except (LedgerError, OSError, TypeError, KeyError) as error:
        print(f"iterations: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
