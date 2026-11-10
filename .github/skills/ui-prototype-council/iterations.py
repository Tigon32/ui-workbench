#!/usr/bin/env python3
"""Verify and report a hash-bound, project-local refinement ledger."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


class LedgerError(ValueError):
    """A ledger or one of its referenced artifacts is invalid."""


REVIEWER_KINDS = {
    "generator_self_assessment",
    "independent_qualified_review",
    "human_review",
    "assistive_technology_evidence",
}
DECISIONS = {"keep", "revert", "blocked"}
STOP_REASONS = {"target_provisionally_met", "no_gain", "iteration_cap", "blocked"}


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


def _scores(root, artifacts, reference, points, scope_id, build_id, source_ref):
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
        else:
            _require(score["evidence_status"] == "observed" and bool(refs),
                     f"scored point {point_id!r} needs observed evidence")
            _require(isinstance(score.get("reason"), str) and score["reason"].strip(),
                     f"scored point {point_id!r} needs a reason")
            _require(isinstance(score.get("assessed_source_ref"), str),
                     f"scored point {point_id!r} needs assessed_source_ref")
            _require(score["assessed_source_ref"] == source_ref,
                     f"score {point_id!r} is stale for the current source; reassess it")
            if value >= 9:
                _require(isinstance(score.get("anchor"), str) and score["anchor"].strip(),
                         f"score {point_id!r} at 9 or above needs its rubric anchor")
    return data


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
    _require(isinstance(ledger, dict) and ledger.get("format_version") == 1,
             "format_version must be 1")
    contract = ledger.get("contract")
    _require(isinstance(contract, dict), "contract must be an object")
    scope_id = contract.get("scope_id")
    _require(isinstance(scope_id, str) and scope_id.strip(), "contract needs scope_id")
    points = contract.get("points")
    _require(isinstance(points, list) and points and
             all(isinstance(point, dict) and isinstance(point.get("id"), str)
                 and type(point.get("selected")) is bool for point in points),
             "contract.points must declare unique ids and selected flags")
    point_ids = [point["id"] for point in points]
    _require(len(set(point_ids)) == len(point_ids), "measurement point ids must be unique")
    goal = contract.get("goal")
    _require(isinstance(goal, dict) and goal.get("score") == 9
             and type(goal.get("fraction")) in (int, float)
             and 0.8 <= goal["fraction"] <= 0.9,
             "goal must target score 9 across a declared 0.80-0.90 fraction")
    selected_count = sum(point["selected"] for point in points)
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
    artifacts = ledger.get("artifacts")
    _require(isinstance(artifacts, dict) and artifacts, "artifacts must be a nonempty map")
    for field in ("elapsed_minutes", "review_effort_minutes", "verification_elapsed_seconds"):
        value = contract.get(field)
        _require(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0,
                 f"{field} must be a nonnegative recorded number or null")
    baseline = ledger.get("baseline")
    _require(isinstance(baseline, dict), "baseline must be an object")

    def snapshot(refs, label):
        _require(isinstance(refs, dict), f"{label} must be an object")
        for key in ("source_ref", "scores_ref", "checks_ref"):
            _require(isinstance(refs.get(key), str), f"{label} needs {key}")
        source = _source(path.parent, artifacts, refs["source_ref"], scope_id)
        scores = _scores(path.parent, artifacts, refs["scores_ref"], point_ids,
                         scope_id, source["build_id"], refs["source_ref"])
        checks, finding_map = _checks(path.parent, artifacts, refs["checks_ref"],
                                      required_scenarios, task_budgets, source["build_id"])
        return source, scores, checks, finding_map

    _require(baseline.get("scope_id") == scope_id and isinstance(baseline.get("build_id"), str),
             "baseline scope/build identity is missing")
    before_source, before_scores, before_checks, before_findings = snapshot(baseline, "baseline")
    _require(baseline["build_id"] == before_source["build_id"],
             "baseline build identity differs from its source")
    previous_source_ref = baseline["source_ref"]
    retained_scores, retained_checks = before_scores, before_checks
    iterations = ledger.get("iterations")
    _require(isinstance(iterations, list), "iterations must be a list")
    no_gain = 0
    attempt_reports = []
    for expected_id, attempt in enumerate(iterations, 1):
        _require(isinstance(attempt, dict) and attempt.get("id") == expected_id,
                 "attempt ids must be unique, positive and sequential")
        _require(isinstance(attempt.get("hypothesis"), str) and attempt["hypothesis"].strip(),
                 f"attempt {expected_id} needs a pre-edit hypothesis")
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
        _require(attempt.get("before", {}).get("source_ref") == previous_source_ref,
                 f"attempt {expected_id} does not start from the preceding retained source")
        _, old_scores, old_checks, old_findings = snapshot(attempt["before"], f"attempt {expected_id} before")
        _, new_scores, new_checks, new_findings = snapshot(attempt.get("after"), f"attempt {expected_id} after")
        attempt_reports.append({
            "id": expected_id,
            "hypothesis": attempt["hypothesis"],
            "decision": attempt.get("decision"),
            "reason": attempt.get("reason"),
            "reviewer_kind": new_scores["reviewer"]["kind"],
            "dimension_changes": {
                point_id: (
                    new_scores["points"][point_id]["score"]
                    - old_scores["points"][point_id]["score"]
                    if new_scores["points"][point_id]["score"] is not None
                    and old_scores["points"][point_id]["score"] is not None else None
                )
                for point_id in point_ids
            },
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
        if attempt["decision"] == "keep":
            _require(attempt.get("provisional") is True,
                     f"attempt {expected_id} keep must be provisional")
            _require(new_checks["status"] == "pass" and new_checks["full_coverage"],
                     f"attempt {expected_id} keep blocked by failed, unknown or incomplete checks")
            _require(all(result["status"] == "pass" for result in new_checks["tasks"].values()),
                     f"attempt {expected_id} keep blocked by a failed or unknown task")
            _require(old_scores["reviewer"] == new_scores["reviewer"],
                     f"attempt {expected_id} keep uses incomparable reviewer provenance")
            _require(new_findings.keys() <= old_findings.keys(),
                     f"attempt {expected_id} keep blocked by a new finding identity")
            _require(all(new_findings[key] <= old_findings[key] for key in new_findings),
                     f"attempt {expected_id} keep blocked by a worsened finding severity")
            _require(all(new_checks["tasks"][name]["clicks"] <= old_checks["tasks"][name]["clicks"]
                         for name in task_budgets),
                     f"attempt {expected_id} keep blocked by a task-click regression")
            for point_id in point_ids:
                old_value = old_scores["points"][point_id]["score"]
                new_value = new_scores["points"][point_id]["score"]
                _require(not (old_value is not None and new_value is None),
                         f"attempt {expected_id} keep blocked by missing score {point_id!r}")
                _require(not (old_value is not None and new_value is not None
                              and new_value < old_value),
                         f"attempt {expected_id} keep blocked by score regression {point_id!r}")
            gained = all(
                new_scores["points"][point_id]["score"] is not None
                and old_scores["points"][point_id]["score"] is not None
                and new_scores["points"][point_id]["score"] - old_scores["points"][point_id]["score"]
                >= expected_gain[point_id]
                for point_id in dimensions)
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
    if stop["reason"] == "blocked":
        _require(not iterations or iterations[-1]["decision"] == "blocked",
                 "blocked stop needs a blocked final attempt or explicit baseline blocker")
    elif stop["reason"] == "iteration_cap":
        _require(len(iterations) == contract["attempt_limit"],
                 "iteration_cap stop was not reached")
    elif stop["reason"] == "no_gain":
        _require(no_gain >= contract.get("no_gain_limit", math.inf),
                 "no_gain stop was not reached")
    else:
        _require(stop.get("final_review_status") in {"adoptable", "not_adoptable", "blocked"}
                 and isinstance(stop.get("final_review_ref"), str),
                 "provisional target stop needs a final review status and evidence")
        final_review = _artifact(path.parent, artifacts, stop["final_review_ref"])
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
        current_scores = retained_scores
        current_checks = retained_checks
        achieved = sum(
            point["selected"] and current_scores["points"][point["id"]]["score"] is not None
            and current_scores["points"][point["id"]]["score"] >= goal["score"]
            for point in points
        )
        _require(achieved >= math.ceil(len(points) * goal["fraction"])
                 and current_checks["status"] == "pass" and current_checks["full_coverage"],
                 "target_provisionally_met needs current complete scores and passing full checks")
    if iterations and iterations[-1]["decision"] == "blocked":
        _require(stop["reason"] == "blocked",
                 "a blocked final attempt must use the higher-priority blocked stop")
    _require(stop.get("retained_source_ref") == previous_source_ref,
             "stop must identify the retained source")
    _require(isinstance(stop.get("reason_text"), str) and stop["reason_text"].strip(),
             "stop needs an explicit reason")
    return {
        "path": str(path),
        "contract": contract,
        "current_build_id": _source(
            path.parent, artifacts, previous_source_ref, scope_id).get("build_id"),
        "artifacts": artifacts,
        "baseline": baseline,
        "baseline_scores": before_scores,
        "baseline_scores": before_scores,
        "baseline_checks": before_checks,
        "iterations": iterations,
        "attempt_reports": attempt_reports,
        "stop": stop,
        "retained_source_ref": previous_source_ref,
        "current_scores": retained_scores,
        "current_checks": retained_checks,
    }


def report(verified):
    contract = verified["contract"]
    points = contract["points"]
    denominator = len(points)
    goal = contract["goal"]
    target_count = math.ceil(denominator * goal["fraction"])
    selected_points = [point for point in points if point["selected"]]
    excluded_points = [point["id"] for point in points if not point["selected"]]
    scores = verified["current_scores"]
    scores_by_point = scores["points"]
    achieved = sum(
        point["selected"] and scores_by_point[point["id"]]["score"] is not None
        and scores_by_point[point["id"]]["score"] >= goal["score"]
        for point in points
    )
    progress_by_kind = {}
    for kind in REVIEWER_KINDS:
        progress_by_kind[kind] = sum(
            point["selected"] and scores_by_point[point["id"]]["score"] is not None
            and scores_by_point[point["id"]]["score"] >= goal["score"]
            and scores["reviewer"]["kind"] == kind
            for point in points
        )
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
    recurring = sum(len(profiles) > 1 for profiles in profile_presence.values())
    return {
        "scope_id": contract["scope_id"],
        "build_id": verified["current_build_id"],
        "goal": {
            "score": goal["score"],
            "fraction": goal["fraction"],
            "claim_scope": (
                "all_declared_points" if len(selected_points) == denominator
                else "selected_subset"
            ),
            "selected_point_count": len(selected_points),
            "excluded_points": excluded_points,
            "achieved_selected_points": achieved,
            "required_selected_points": target_count,
            "denominator": denominator,
            "missing_or_below_goal": [
                point["id"] for point in points
                if point["selected"] and (
                    scores_by_point[point["id"]]["score"] is None
                    or scores_by_point[point["id"]]["score"] < goal["score"])
            ],
            "unassessed_selected_points": [
                point["id"] for point in selected_points
                if scores_by_point[point["id"]]["score"] is None
            ],
            "missing_evidence": [
                point["id"] for point in points
                if scores_by_point[point["id"]]["score"] is None
            ],
        },
        "points": [
            {
                "id": point["id"],
                "selected": point["selected"],
                "before_score": verified["baseline_scores"]["points"][point["id"]]["score"],
                "current_score": scores_by_point[point["id"]]["score"],
                "change": (
                    scores_by_point[point["id"]]["score"]
                    - verified["baseline_scores"]["points"][point["id"]]["score"]
                    if scores_by_point[point["id"]]["score"] is not None
                    and verified["baseline_scores"]["points"][point["id"]]["score"] is not None
                    else None
                ),
                "evidence_status": scores_by_point[point["id"]]["evidence_status"],
                "reviewer_kind": scores["reviewer"]["kind"],
                "rubric_anchor": scores_by_point[point["id"]].get("anchor"),
                "evidence": scores_by_point[point["id"]]["evidence"],
            }
            for point in points
        ],
        "reviewer": scores["reviewer"],
        "progress_by_reviewer_kind": progress_by_kind,
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
        "limitations": [
            "Reviewer labels are declared provenance, not proof of independence or qualification.",
            "Artifact hashes identify bytes; they do not prove truth, capture time, or historical authenticity.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("verify", "report"))
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.ledger)
        if args.command == "verify":
            print(f"ledger: valid; {len(result['iterations'])} attempt(s); "
                  f"retained {result['retained_source_ref']}")
        else:
            print(json.dumps(report(result), indent=2, sort_keys=True))
    except (LedgerError, OSError, TypeError, KeyError) as error:
        print(f"iterations: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
