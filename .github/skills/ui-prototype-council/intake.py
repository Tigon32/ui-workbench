#!/usr/bin/env python3
"""Shared, local scope-intake checks. Domain artifact contents are never read."""

import datetime
import hashlib
import json
from pathlib import Path

LEVELS = {"component", "page", "flow", "product"}
DATA_CLASSES = {"synthetic", "public", "private", "confidential"}


def text(value):
    return isinstance(value, str) and bool(value.strip())


def member(value, choices):
    return isinstance(value, str) and value in choices


def digest(value):
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value)


def date(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def sponsor_approved(brief, decision_id, *, subject_id=None):
    authority = brief.get("decision_authority", {})
    decisions = authority.get("decisions", []) if isinstance(authority, dict) else []
    sources = brief.get("sources", [])
    sources = sources if isinstance(sources, list) else []
    for decision in decisions if isinstance(decisions, list) else []:
        if not isinstance(decision, dict) or decision.get("id") != decision_id:
            continue
        if decision.get("owner") != "sponsor" or decision.get("status") != "approved":
            return False
        if subject_id is not None and (
                not isinstance(decision.get("subject_ids"), list)
                or subject_id not in decision["subject_ids"]):
            return False
        return any(
            isinstance(source, dict)
            and source.get("id") == decision.get("approval_source_ref")
            and source.get("kind") == "sponsor_approval"
            and text(source.get("reference")) and text(source.get("quote"))
            and text(source.get("actor")) and date(source.get("date"))
            for source in sources
        )
    return False


def _signature(brief):
    # Provenance/version edits do not change the job being commissioned.
    fields = ("users_and_jobs", "problem", "desired_outcomes", "platforms",
              "scenarios", "constraints", "non_goals")
    return {key: brief.get(key) for key in fields}


def validate(brief, *, root=None, directions=None, current_brief_path=None):
    findings = []

    def problem(code, message):
        findings.append({"code": code, "severity": "blocker", "message": message})

    def note(code, message):
        findings.append({"code": code, "severity": "review", "message": message})

    brief = brief if isinstance(brief, dict) else {}
    intake = brief.get("intake")
    if not isinstance(intake, dict):
        intake = {}
    scope = intake.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    level = scope.get("level")
    confirmation = scope.get("sponsor_confirmation")
    confirmation = confirmation if isinstance(confirmation, dict) else {}
    source_rows = brief.get("sources", [])
    sources = {
        row["id"]: row for row in source_rows
        if isinstance(row, dict) and text(row.get("id"))
    } if isinstance(source_rows, list) else {}
    if not isinstance(source_rows, list) or len(sources) != len(source_rows):
        problem("invalid_scope_sources", "Scope sources need unique nonempty string ids.")
    confirmation_ref = confirmation.get("source_ref")
    approval = sources.get(confirmation_ref, {}) if text(confirmation_ref) else {}
    authority = brief.get("decision_authority")
    authority = authority if isinstance(authority, dict) else {}
    decisions = authority.get("decisions")
    decisions = decisions if isinstance(decisions, list) else []
    if (type(intake.get("version")) is not int or intake["version"] != 1
            or not member(level, LEVELS)
            or not text(scope.get("decision_id"))
            or not text(confirmation.get("quote"))
            or not text(confirmation.get("actor"))
            or not date(confirmation.get("date"))
            or confirmation.get("quote") != approval.get("quote")
            or confirmation.get("date") != approval.get("date")
            or confirmation.get("actor") != approval.get("actor")
            or not sponsor_approved(brief, scope.get("decision_id"))
            or not any(isinstance(row, dict)
                       and row.get("id") == scope.get("decision_id")
                       and row.get("topic") == "scope"
                       and row.get("approval_source_ref") == confirmation.get("source_ref")
                       for row in decisions)):
        problem("scope_unconfirmed", "Scope level or sponsor confirmation missing. Generation blocked.")
    if "stage" in scope and not member(scope["stage"], {"shell", "content"}):
        problem("invalid_scope_stage", "Scope stage must be shell or content.")
    claim = intake.get("claim_level", level)
    if not member(claim, LEVELS) or claim != level:
        problem("invalid_scope_claim", "Claim level must match the sponsor-confirmed scope level.")

    questions = brief.get("unresolved_questions", [])
    if not isinstance(questions, list):
        questions = []
        problem("invalid_scope_question", "Unresolved questions must be a list.")
    for question in questions:
        if (not isinstance(question, dict) or not text(question.get("id"))
                or not member(question.get("topic"), {"scope", "primary_job", "quality", "other"})
                or not member(question.get("blocks"), {"generation", "selection", "acceptance", "nothing"})):
            problem("invalid_scope_question", "New intake questions need an id, topic and blocking stage.")
        elif question["topic"] in {"scope", "primary_job"} and question["blocks"] == "nothing":
            problem("scope_question_parked",
                    f"Question {question['id']} concerns scope or primary job and cannot be marked 'blocks nothing'.")

    views = intake.get("views", [])
    if not isinstance(views, list):
        views = []
        problem("invalid_view_inventory", "View inventory must be a list.")
    view_map = {}
    for view in views:
        if not isinstance(view, dict) or not text(view.get("id")):
            problem("invalid_view_inventory", "Every view needs a stable id.")
            continue
        ident = view["id"]
        if ident in view_map or not member(view.get("disposition"), {"in", "context", "out"}):
            problem("invalid_view_inventory", f"View {ident} needs a unique id and in/context/out disposition.")
        view_map[ident] = view
        if view.get("disposition") != "in" and not text(view.get("reason")):
            problem("invalid_view_inventory", f"View {ident} needs an exclusion/context reason.")
        refs = view.get("capture_refs")
        needs_capture = level == "product" or (
            member(level, {"page", "flow"}) and view.get("disposition") == "in")
        if needs_capture and (not isinstance(refs, list) or not refs
                              or any(not text(ref) or ref not in sources for ref in refs)):
            problem("view_capture_missing", f"View {ident} needs current-UI capture source references.")
    in_ids = [ident for ident, view in view_map.items() if view.get("disposition") == "in"]
    if member(level, {"page", "flow", "product"}) and not in_ids:
        problem("invalid_view_inventory", "Page, flow and product scope need in-scope views.")
    snapshot = {"level": level, "stage": scope.get("stage", "content"),
                "view_dispositions": {ident: view.get("disposition")
                                      for ident, view in view_map.items()}}
    if (confirmation.get("scope_snapshot") != snapshot
            or approval.get("scope_snapshot") != snapshot):
        problem("scope_unconfirmed", "Scope level or sponsor confirmation missing. Generation blocked.")
    if scope.get("stage") == "shell" and level != "product":
        problem("invalid_scope_stage", "Only sponsor-confirmed product scope can use a shell stage.")
    journeys = intake.get("journeys", [])
    if not isinstance(journeys, list):
        journeys = []
        problem("invalid_journeys", "Journeys must be an explicit list.")
    cross_view_journeys = 0
    journey_ids = set()
    for journey in journeys:
        ids = journey.get("view_ids") if isinstance(journey, dict) else None
        if (not isinstance(journey, dict) or not text(journey.get("id"))
                or not isinstance(ids, list) or not ids
                or any(not isinstance(ident, str) or ident not in view_map for ident in ids)
                or len(set(ids)) != len(ids) or journey["id"] in journey_ids):
            problem("invalid_journeys", "Journeys need an id and unique inventory view ids.")
            continue
        journey_ids.add(journey["id"])
        cross_view_journeys += len(ids) >= 2
    if member(level, {"flow", "product"}):
        required = 2 if level == "product" else 1
        if cross_view_journeys < required:
            problem("journeys_missing", f"{level} scope needs {required} cross-view journey(s).")
    if member(level, {"page", "flow", "product"}) and not brief.get("users_and_jobs"):
        problem("jobs_missing", "Page/flow/product scope needs personas and jobs.")
    targets = intake.get("quality_targets")
    needed = {"component"} if level == "component" else {"component", "page"}
    if level == "product":
        needed.add("product")
    if not isinstance(targets, dict) or any(not text(targets.get(key)) for key in needed):
        problem("quality_targets_missing", "Declare quality targets at the applicable scope levels.")
    artifacts = intake.get("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
        problem("invalid_domain_artifacts", "Domain artifact references must be a list.")
    if level == "product" and not artifacts and not text(intake.get("no_artifacts_reason")):
        problem("domain_artifacts_missing", "Product scope needs artifact references or an explicit none reason.")
    for artifact in artifacts:
        if (not isinstance(artifact, dict) or not text(artifact.get("path"))
                or not member(artifact.get("data_class"), DATA_CLASSES)):
            problem("invalid_domain_artifacts", "Every domain artifact needs a path and known data_class.")

    keep = intake.get("keep", {})
    keep = keep if isinstance(keep, dict) else {}
    items = keep.get("items")
    no_items = text(keep.get("none_reason"))
    if (not isinstance(items, list) or not items) and not no_items:
        problem("keep_list_missing",
                "No KEEP/CHANGE/DROP list (or explicit 'none' with reason). Directions must state a disposition per keep item.")
    items = items if isinstance(items, list) else []
    if items and no_items:
        problem("invalid_keep_list", "Choose a KEEP list or an explicit none reason, not both.")
    keep_map = {}
    for item in items:
        if (not isinstance(item, dict) or not text(item.get("id"))
                or not member(item.get("kind"), {"keep", "change", "drop"})
                or not text(item.get("what")) or not text(item.get("reason"))
                or not member(item.get("evidence_ref"), sources) or item.get("id") in keep_map):
            problem("invalid_keep_list", "KEEP entries need unique ids, kind, WHAT, reason and a known evidence source.")
            continue
        keep_map[item["id"]] = item
    if len(items) > 10:
        note("large_keep_list", "Review the KEEP list for focus; prefer about ten or fewer items.")

    priors = intake.get("prior_briefs", [])
    if not isinstance(priors, list):
        priors = []
        problem("invalid_prior_briefs", "Prior briefs must be an explicit list.")
    if not priors and not text(intake.get("prior_briefs_none_reason")):
        problem("prior_brief_history_missing", "Declare prior briefs or an explicit no-prior-brief reason.")
    for prior in priors:
        if (not isinstance(prior, dict) or not text(prior.get("id"))
                or not digest(prior.get("sha256")) or not text(prior.get("purpose"))
                or not (type(prior.get("round")) is int or text(prior.get("round")))
                or not text(prior.get("confirmation_ref")) or not date(prior.get("date"))
                or ("path" in prior and not text(prior["path"]))):
            problem("invalid_prior_briefs", "Prior briefs need id, raw SHA-256, round, purpose, date and confirmation_ref.")
            continue
        if not prior.get("path"):
            problem("prior_brief_unavailable", f"Prior brief {prior['id']} needs a checkable local path.")
        same = False
        if prior.get("path"):
            path = Path(prior["path"])
            if not path.is_absolute():
                path = Path(root or ".") / path
            try:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != prior["sha256"]:
                    problem("prior_brief_hash_mismatch", f"Prior brief {prior['id']} digest differs.")
                old = json.loads(data)
                same = isinstance(old, dict) and _signature(old) == _signature(brief)
                old_intake = old.get("intake") if isinstance(old, dict) else None
                old_scope = old_intake.get("scope") if isinstance(old_intake, dict) else None
                old_confirmation = old_scope.get("sponsor_confirmation") if isinstance(old_scope, dict) else None
                if isinstance(old_confirmation, dict) and (
                        prior["confirmation_ref"] != old_confirmation.get("source_ref")
                        or prior["date"] != old_confirmation.get("date")):
                    problem("prior_brief_provenance_mismatch",
                            f"Prior brief {prior['id']} confirmation reference/date differs from its recorded intake.")
            except (OSError, ValueError, UnicodeDecodeError) as error:
                problem("prior_brief_unavailable", f"Prior brief {prior['id']} cannot be checked: {error}")
        if current_brief_path is not None:
            try:
                same |= hashlib.sha256(Path(current_brief_path).read_bytes()).hexdigest() == prior["sha256"]
            except OSError as error:
                problem("brief_unavailable", str(error))
        reconfirmed = (
            isinstance(confirmation.get("reconfirms"), list)
            and prior["sha256"] in confirmation["reconfirms"]
            and confirmation.get("source_ref") != prior.get("confirmation_ref")
            and date(prior.get("date")) and date(confirmation.get("date"))
            and confirmation["date"] >= prior["date"]
        )
        if same and not reconfirmed:
            problem("brief_stale",
                    f"Brief {prior['id']} is identical to round {prior['round']}'s brief written for {prior['purpose']}. Sponsor must reconfirm scope before reuse.")

    excluded = [{"id": ident, "reason": view.get("reason")}
                for ident, view in view_map.items() if view.get("disposition") != "in"]
    base = {"scope_level": level, "view_ids": in_ids, "covered": 0,
            "total": len(in_ids), "reachable": 0, "excluded": excluded,
            "assessment": "not_assessed"}
    direction_reports = {}
    if directions is not None:
        if not isinstance(directions, list):
            problem("invalid_scope_direction", "Scope directions must be a list.")
            directions = []
        for direction in directions:
            if (not isinstance(direction, dict) or not text(direction.get("id"))
                    or direction["id"] in direction_reports):
                problem("invalid_scope_direction", "Scope directions need a unique id.")
                continue
            ident = direction["id"]
            rows = direction.get("view_coverage", [])
            rows = rows if isinstance(rows, list) else []
            by_view = {}
            for row in rows:
                if (not isinstance(row, dict) or not member(row.get("view_id"), view_map)
                        or row.get("view_id") in by_view
                        or not member(row.get("status"), {"covered", "labelled_stub", "placeholder", "absent", "deferred"})):
                    problem("invalid_view_coverage", f"Direction {ident} has invalid view coverage.")
                    continue
                by_view[row["view_id"]] = row
                if row["status"] in {"covered", "labelled_stub"} and (
                        not isinstance(row.get("evidence_refs"), list) or not row["evidence_refs"]
                        or any(not member(ref, sources) for ref in row["evidence_refs"])):
                    problem("scope_evidence_missing", f"View {row['view_id']} needs coverage evidence sources.")
            for view_id in in_ids:
                row = by_view.get(view_id, {})
                is_shell_stub = scope.get("stage") == "shell" and row.get("status") == "labelled_stub"
                if row.get("status") != "covered" and not is_shell_stub and not sponsor_approved(
                        brief, row.get("deferral_decision_ref"), subject_id=view_id):
                    problem("scope_coverage",
                            f"In-scope view {view_id} is not covered and has no sponsor-signed deferral.")
            dispositions = direction.get("keep_dispositions", [])
            dispositions = dispositions if isinstance(dispositions, list) else []
            dmap = {row.get("id"): row for row in dispositions if isinstance(row, dict) and text(row.get("id"))}
            if set(dmap) != set(keep_map) or len(dmap) != len(dispositions):
                problem("keep_list_missing",
                        "No KEEP/CHANGE/DROP list (or explicit 'none' with reason). Directions must state a disposition per keep item.")
            for key, row in dmap.items():
                expected = keep_map.get(key, {}).get("kind")
                if (not member(row.get("disposition"), {"keep", "change", "drop", "exception"})
                        or not isinstance(row.get("evidence_refs"), list) or not row["evidence_refs"]
                        or any(not member(ref, sources) for ref in row["evidence_refs"])
                        or row.get("disposition") != expected
                        and not sponsor_approved(brief, row.get("exception_decision_ref"), subject_id=key)):
                    problem("invalid_keep_disposition", f"Direction {ident} has an unsupported disposition for {key}.")
            direction_reports[ident] = {
                **base, "assessment": "declared",
                "covered": sum(by_view.get(key, {}).get("status") == "covered" for key in in_ids),
                "reachable": sum(by_view.get(key, {}).get("status") in {"covered", "labelled_stub"} for key in in_ids),
            }
    coverage = dict(base)
    if direction_reports:
        coverage["covered"] = min(row["covered"] for row in direction_reports.values())
        coverage["reachable"] = min(row["reachable"] for row in direction_reports.values())
        coverage["assessment"] = "declared"
    counts = (f"covered {coverage['covered']}/{coverage['total']} · "
              f"reachable {coverage['reachable']}/{coverage['total']}"
              if coverage["assessment"] == "declared"
              else f"coverage not assessed ({coverage['total']} in-scope views)")
    label = (
        f"Scope: {level if member(level, LEVELS) else 'unconfirmed'} · {', '.join(in_ids) or 'component'} · "
        f"{counts} · excluded: "
        + ("; ".join(f"{row['id']} ({row['reason']})" for row in excluded) or "none")
    )
    if level != "product":
        label += " · not a new product interface"
    return {"findings": findings, "scope_header": label, "coverage": coverage,
            "directions": direction_reports}
