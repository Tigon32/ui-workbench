#!/usr/bin/env python3
"""Validate a local what-council handoff and its concept comparison inputs."""

import argparse
import json
import sys
from pathlib import Path


CONFIDENCE = {"low", "medium", "high", "unknown"}
ROLES = {"advisor", "adversary", "judge"}
INPUTS = {"brief", "fixture", "tasks", "constraints", "platforms", "rubric"}
REVIEW_KINDS = {"generator_self_score", "model_review", "human_evidence"}


class HandoffError(ValueError):
    """A handoff is unreadable or has invalid structure."""


def _read_json(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HandoffError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise HandoffError(f"{label} must be a JSON object")
    return value


def _finding(code, severity, message, **details):
    return {"code": code, "severity": severity, "message": message, **details}


def validate(brief, exploration):
    """Return a reviewable report; never infer that the handoff is accepted."""
    if not isinstance(brief, dict) or not isinstance(exploration, dict):
        raise HandoffError("brief and exploration must be JSON objects")
    findings = []

    def problem(code, message, **details):
        findings.append(_finding(code, "blocker", message, **details))

    def note(code, message, **details):
        findings.append(_finding(code, "review", message, **details))

    if not isinstance(brief.get("brief_version"), str) or not brief["brief_version"].strip():
        problem("missing_brief_version", "The canonical format-2 project brief must have a version.")
    if exploration.get("format_version") != 1:
        problem("unsupported_exploration_version", "Exploration metadata must use format_version 1.")
    if exploration.get("brief_version") != brief.get("brief_version"):
        problem("brief_version_mismatch", "Exploration and canonical brief versions differ.")
    if brief.get("status") not in {"complete", "incomplete"}:
        problem("invalid_brief_status", "The canonical brief must be explicitly complete or incomplete.")
    if not isinstance(brief.get("critical_unknowns"), list):
        problem("missing_critical_unknowns", "Critical unknowns must remain explicit in the canonical brief.")

    sources = brief.get("sources")
    source_map = {}
    if not isinstance(sources, list):
        sources = []
        problem("missing_sources", "The canonical brief must record source references.")
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("id"), str)
                or not source.get("kind") or not source.get("reference")):
            problem("invalid_source", "Every source needs an id, kind and declared reference.")
            continue
        if source["id"] in source_map:
            problem("duplicate_source", f"Source id {source['id']!r} is duplicated.")
        source_map[source["id"]] = source

    authority = brief.get("decision_authority", {})
    if not isinstance(authority, dict):
        authority = {}
        problem("missing_authority", "The brief must retain its project-owned decision authority.")
    decision_rows = authority.get("decisions", [])
    if not isinstance(decision_rows, list):
        decision_rows = []
        problem("invalid_authority", "Decision authority must contain a decisions list.")
    decisions = {
        row.get("id"): row for row in decision_rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for decision in decision_rows:
        if not isinstance(decision, dict):
            problem("invalid_authority", "Each decision must be an object.")
            continue
        if decision.get("owner") == "sponsor" and decision.get("status") == "approved":
            ref = decision.get("approval_source_ref")
            source = source_map.get(ref)
            if not source or source.get("kind") != "sponsor_approval":
                problem(
                    "unsupported_sponsor_approval",
                    f"Sponsor decision {decision.get('id')!r} is marked approved without a cited sponsor-approval source.",
                    decision_id=decision.get("id"),
                )
    for decision_id in authority.get("sponsor_decisions", []):
        if decision_id not in decisions or decisions[decision_id].get("owner") != "sponsor":
            problem("invalid_sponsor_authority", f"{decision_id!r} is not recorded as sponsor-owned.")
    for decision_id in authority.get("agent_delegated_decisions", []):
        if decision_id not in decisions or decisions[decision_id].get("owner") != "agent":
            problem("invalid_delegated_authority", f"{decision_id!r} is not recorded as agent-delegated.")

    what_items = brief.get("what_items")
    if not isinstance(what_items, list) or not what_items:
        what_items = []
        problem("missing_what_items", "The canonical brief must identify user needs and constraints.")
    for item in what_items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            problem("invalid_what_item", "Each WHAT item needs a stable id.")
            continue
        if not isinstance(item.get("statement"), str) or not item["statement"].strip():
            problem("invalid_what_item", f"WHAT item {item['id']!r} needs a statement.")
        if item.get("confidence") not in CONFIDENCE:
            problem("invalid_confidence", f"WHAT item {item['id']!r} needs an explicit confidence label.")
        refs = item.get("source_refs", [])
        if not isinstance(refs, list):
            problem("unknown_claim_source", f"WHAT item {item['id']!r} source_refs must be a list.")
            refs = []
        elif any(ref not in source_map for ref in refs):
            problem("unknown_claim_source", f"WHAT item {item['id']!r} cites an unknown source.")
        kind = item.get("kind")
        if kind == "layout_prescription" and not refs:
            note(
                "unsourced_layout_prescription",
                f"WHAT item {item['id']!r} prescribes layout without an attributable source; council review is required.",
                item_id=item["id"],
            )
            if item.get("council_disposition") not in {
                "reclassified_as_direction", "authorized_constraint", "withdrawn"
            }:
                problem(
                    "unresolved_layout_prescription",
                    f"Layout prescription {item['id']!r} remains unresolved.",
                    item_id=item["id"],
                )
        if kind == "design_constraint":
            valid_constraint_source = any(
                source_map.get(ref, {}).get("kind") in {"design_system", "platform_standard"}
                for ref in refs
            )
            authority_ref = item.get("authority_ref")
            constraint_authorities = brief.get("constraint_authorities", [])
            if not isinstance(constraint_authorities, list):
                constraint_authorities = []
            authority_entry = next(
                (entry for entry in constraint_authorities
                 if isinstance(entry, dict) and entry.get("id") == authority_ref),
                None,
            )
            authorized = (
                isinstance(authority_entry, dict)
                and authority_entry.get("owner") in {
                    "project_design_system", "platform_owner", "sponsor"
                }
                and authority_entry.get("source_ref") in refs
            )
            if not valid_constraint_source or not authorized:
                problem(
                    "unsupported_design_constraint",
                    f"Constraint {item['id']!r} needs a cited design-system/platform source and recorded authority.",
                    item_id=item["id"],
                )

    assumptions = brief.get("assumptions")
    if not isinstance(assumptions, list):
        assumptions = []
        problem("missing_assumptions", "The brief must explicitly record assumptions, including an empty list.")
    assumption_ids = set()
    for assumption in assumptions:
        if not isinstance(assumption, dict) or not isinstance(assumption.get("id"), str):
            problem("invalid_assumption", "Each assumption needs a stable id.")
            continue
        assumption_ids.add(assumption["id"])
        if assumption.get("confidence") not in CONFIDENCE:
            problem("invalid_assumption_confidence", f"Assumption {assumption['id']!r} needs confidence.")
        if assumption.get("owner") == "agent" and (
            assumption.get("treatment") != "exploratory"
            or assumption.get("promoted_to_fact") is True
        ):
            problem(
                "delegated_assumption_promoted",
                f"Agent-delegated assumption {assumption['id']!r} must remain exploratory.",
                assumption_id=assumption["id"],
            )
        assumption_sources = assumption.get("source_refs", [])
        if not isinstance(assumption_sources, list):
            problem("invalid_assumption_source", f"Assumption {assumption['id']!r} source_refs must be a list.")
        elif any(ref not in source_map for ref in assumption_sources):
            problem("unknown_assumption_source", f"Assumption {assumption['id']!r} cites an unknown source.")
    for item in what_items:
        if (
            isinstance(item, dict)
            and item.get("kind") != "layout_prescription"
            and not item.get("source_refs")
            and item.get("assumption_ref") not in assumption_ids
        ):
            problem(
                "unsupported_what_claim",
                f"WHAT item {item.get('id')!r} needs a source or an explicitly recorded assumption.",
                item_id=item.get("id"),
            )

    council = brief.get("what_council")
    role_map = {}
    if not isinstance(council, dict):
        council = {}
        problem("missing_council", "The brief must record advisor, adversary and judge roles.")
    members = council.get("members", [])
    if not isinstance(members, list):
        members = []
    for member in members:
        if isinstance(member, dict) and member.get("role") in ROLES:
            role_map[member["role"]] = member
    for role in sorted(ROLES - set(role_map)):
        problem("missing_council_role", f"The {role} role is missing.", role=role)
    perspectives = [member.get("perspective") for member in role_map.values()]
    if len(perspectives) != len(set(perspectives)) or any(not item for item in perspectives):
        problem("undifferentiated_roles", "Council roles need distinct, explicit perspectives.")
    model_ids = [
        member.get("model_id") for member in role_map.values()
        if member.get("model_id") not in (None, "", "not-run")
    ]
    same_model = len(model_ids) != len(set(model_ids))
    if same_model and council.get("same_model_limitation_disclosed") is not True:
        problem(
            "same_model_limitation_missing",
            "Same-model role use must disclose that it does not establish independent judgement.",
        )
    if same_model:
        note(
            "same_model_roles",
            "At least two roles used the same model; role separation does not establish independent judgement.",
        )
    if council.get("mode") == "synthetic":
        note(
            "synthetic_council_record",
            "This is a local synthetic example, not a council run or evidence of independent judgement.",
        )

    objections = council.get("objections", [])
    rulings = council.get("rulings", [])
    if not isinstance(objections, list) or not isinstance(rulings, list):
        objections, rulings = [], []
        problem("invalid_council_record", "Council objections and rulings must be lists.")
    ruling_map = {
        ruling.get("objection_id"): ruling for ruling in rulings
        if isinstance(ruling, dict) and isinstance(ruling.get("objection_id"), str)
    }
    for objection in objections:
        if not isinstance(objection, dict) or not isinstance(objection.get("id"), str):
            problem("invalid_objection", "Each objection needs a stable id.")
            continue
        if objection.get("raised_by") not in ROLES:
            problem(
                "invalid_objection_role",
                f"Objection {objection['id']!r} must identify the advisor, adversary or judge who raised it.",
            )
        ruling = ruling_map.get(objection["id"])
        if not ruling or ruling.get("judge_role") != "judge":
            problem("missing_objection_ruling", f"Objection {objection['id']!r} lacks a judge ruling.")
        elif objection.get("severity") == "critical" and ruling.get("status") != "resolved":
            problem(
                "unresolved_critical_objection",
                f"Critical objection {objection['id']!r} remains unresolved.",
                objection_id=objection["id"],
            )
        elif ruling.get("status") not in {"resolved", "deferred_noncritical"}:
            problem("invalid_ruling", f"Objection {objection['id']!r} has no valid disposition.")
        if ruling and ruling.get("decision_status") == "approved":
            decision = decisions.get(ruling.get("decision_id"))
            if ruling.get("judge_role") == "judge" and (
                ruling.get("decision_owner") == "sponsor"
                or (decision and decision.get("owner") == "sponsor")
            ):
                problem(
                    "judge_exceeded_authority",
                    f"The judge cannot approve sponsor-owned decision {ruling.get('decision_id')!r}.",
                    objection_id=objection.get("id"),
                )
            elif ruling.get("decision_owner") == "sponsor":
                approval_ref = ruling.get("approval_source_ref")
                source = source_map.get(approval_ref)
                if not source or source.get("kind") != "sponsor_approval":
                    problem(
                        "unsupported_sponsor_approval",
                        f"Ruling on sponsor decision {ruling.get('decision_id')!r} lacks an approval source.",
                        objection_id=objection.get("id"),
                    )

    revisions = exploration.get("input_revisions")
    if not isinstance(revisions, dict):
        revisions = {}
        problem("missing_input_revisions", "The comparison must declare versioned shared inputs.")
    for name in INPUTS:
        revision = revisions.get(name)
        if not isinstance(revision, dict) or not revision.get("revision"):
            problem("missing_input_revision", f"Input {name!r} needs a visible revision.")
        elif revision.get("change") and not revision.get("parent_revision"):
            problem("untraceable_input_change", f"Changed input {name!r} needs its parent revision.")

    required_states = exploration.get("required_states")
    if not isinstance(required_states, list) or not required_states:
        required_states = []
        problem("missing_required_states", "Required states must be explicit, including the applicable comparison set.")
    directions = exploration.get("directions")
    if not isinstance(directions, list):
        directions = []
        problem("missing_directions", "At least two directions are required.")
    eligible = []
    input_signatures = {}
    state_gaps = {}
    direction_ids = set()
    declared_tasks = exploration.get("shared_tasks")
    if not isinstance(declared_tasks, list) or not declared_tasks:
        declared_tasks = []
        problem("missing_shared_tasks", "The shared task set must be explicit.")
    for direction in directions:
        if not isinstance(direction, dict) or not isinstance(direction.get("id"), str):
            problem("invalid_direction", "Each direction needs a stable id.")
            continue
        direction_id = direction["id"]
        if direction_id in direction_ids:
            problem("duplicate_direction", f"Direction id {direction_id!r} is duplicated.")
        direction_ids.add(direction_id)
        candidate_inputs = direction.get("inputs")
        if not isinstance(candidate_inputs, dict) or set(candidate_inputs) != INPUTS or candidate_inputs != revisions:
            problem(
                "incompatible_comparison_inputs",
                f"Direction {direction_id!r} does not use the same declared input revisions; do not rank it with the others.",
                direction_id=direction_id,
                candidate_inputs=candidate_inputs,
                comparison_inputs=revisions,
            )
        input_signatures[direction_id] = candidate_inputs
        if direction.get("tasks") != declared_tasks:
            problem(
                "incompatible_comparison_tasks",
                f"Direction {direction_id!r} does not use the same declared tasks.",
                direction_id=direction_id,
                candidate_tasks=direction.get("tasks"),
                comparison_tasks=declared_tasks,
            )
        assessed = direction.get("assessed_states", [])
        if not isinstance(assessed, list):
            assessed = []
        if any(not isinstance(state, str) for state in assessed):
            problem("invalid_assessed_state", f"Direction {direction_id!r} has a non-text assessed state.")
            assessed = [state for state in assessed if isinstance(state, str)]
        if not set(assessed) <= set(required_states):
            problem(
                "unknown_assessed_state",
                f"Direction {direction_id!r} assesses a state outside the declared comparison.",
                direction_id=direction_id,
            )
        state_gaps[direction_id] = sorted(set(required_states) - set(assessed))
        if state_gaps[direction_id]:
            note(
                "unassessed_states",
                f"Direction {direction_id!r} has states without evidence; they remain unassessed.",
                direction_id=direction_id,
                states=state_gaps[direction_id],
            )
        review = direction.get("distinctness_review", {})
        if direction.get("eligible") is True:
            eligible.append(direction)
            if not isinstance(review, dict) or not review.get("rationale"):
                problem("missing_distinctness_review", f"Direction {direction_id!r} needs qualitative review.")
            elif review.get("color_only") is True:
                problem(
                    "color_only_direction",
                    f"Direction {direction_id!r} differs only by color/theme and is not materially distinct.",
                    direction_id=direction_id,
                )
            elif not isinstance(review.get("material_differences"), list) or not review["material_differences"]:
                problem(
                    "unsubstantiated_distinctness",
                    f"Direction {direction_id!r} needs qualitative structural/task differences.",
                    direction_id=direction_id,
                )
        elif isinstance(review, dict) and review.get("color_only") is True:
            note(
                "color_only_direction",
                f"Direction {direction_id!r} was flagged and excluded as a color-only variant.",
                direction_id=direction_id,
            )
    if len(eligible) < 2:
        problem("insufficient_directions", "Fewer than two materially distinct eligible directions remain.")
    comparison_review = exploration.get("comparison_review")
    if not isinstance(comparison_review, dict) or not comparison_review.get("rationale"):
        problem("missing_comparison_review", "A qualitative comparison review is required.")
    elif comparison_review.get("claims_mechanical_creativity") is True:
        problem("mechanical_creativity_claim", "A validator cannot prove creativity or novelty.")
    pair_reviews = (comparison_review or {}).get("pairwise_reviews", [])
    eligible_ids = {direction.get("id") for direction in eligible}
    covered_pairs = set()
    if not isinstance(pair_reviews, list):
        pair_reviews = []
    for pair in pair_reviews:
        if not isinstance(pair, dict):
            problem("invalid_pairwise_review", "Each pairwise comparison must be an object.")
            continue
        ids = pair.get("direction_ids")
        if (not isinstance(ids, list) or len(ids) != 2
                or any(not isinstance(item, str) for item in ids)
                or len(set(ids)) != 2 or not set(ids) <= eligible_ids):
            problem("invalid_pairwise_review", "Pairwise review must name two eligible directions.")
            continue
        covered_pairs.add(frozenset(ids))
        if pair.get("color_only") is True:
            problem(
                "color_only_comparison",
                f"Pair {ids!r} is not materially distinct because its review says color-only.",
                direction_ids=ids,
            )
        if not pair.get("rationale") or not pair.get("material_differences"):
            problem(
                "unsubstantiated_pairwise_review",
                f"Pair {ids!r} needs a qualitative rationale and material differences.",
                direction_ids=ids,
            )
    expected_pairs = {
        frozenset((eligible[left].get("id"), eligible[right].get("id")))
        for left in range(len(eligible))
        for right in range(left + 1, len(eligible))
    }
    if expected_pairs - covered_pairs:
        problem(
            "missing_pairwise_review",
            "Every eligible direction pair needs qualitative review.",
            missing_pairs=[sorted(pair) for pair in sorted(expected_pairs - covered_pairs, key=sorted)],
        )
    if exploration.get("selection_policy") == "rank_incompatible":
        problem("incompatible_ranking_claim", "Incompatible input versions cannot be silently ranked.")

    handoff = exploration.get("handoff")
    if not isinstance(handoff, dict):
        handoff = {}
        problem("missing_existing_workflow_handoff", "The report must name the existing selection and refinement paths.")
    selection = handoff.get("prototype_selection", {})
    if not isinstance(selection, dict) or selection.get("skill") != "ui-prototype-council":
        problem("missing_selection_route", "Directions must route to the existing ui-prototype-council.")
    refinement = handoff.get("refinement", {})
    if not isinstance(refinement, dict):
        refinement = {}
    if refinement.get("skill") != "ui-prototype-council":
        problem("missing_refinement_route", "Selected candidates must route to existing ui-prototype-council refinement.")
    elif refinement.get("format_version") != 2 or not refinement.get("canonical_brief_ref"):
        problem("invalid_refinement_route", "Refinement handoff must retain the canonical brief and format-2 compatibility.")
    elif refinement.get("selected_candidate") is not None and (
        refinement.get("selected_candidate") not in direction_ids
        or not next((d for d in directions if d.get("id") == refinement.get("selected_candidate")
                     and d.get("eligible") is True), None)
    ):
        problem("invalid_selected_candidate", "Refinement target must be an eligible selected direction.")

    evidence = exploration.get("review_evidence", [])
    if not isinstance(evidence, list):
        evidence = []
        problem("invalid_review_evidence", "Review evidence must be explicitly classified.")
    evidence_by_kind = {kind: [] for kind in REVIEW_KINDS}
    for record in evidence:
        if not isinstance(record, dict) or record.get("kind") not in REVIEW_KINDS:
            problem("invalid_review_evidence", "Evidence kind must distinguish self-scores, model reviews and human evidence.")
            continue
        evidence_by_kind[record["kind"]].append(record)
    if exploration.get("acceptance_claim") is True:
        problem("unsupported_acceptance_claim", "Concept exploration cannot itself assert project acceptance.")

    brief_complete = brief.get("status") == "complete"
    critical_unknowns = brief.get("critical_unknowns", [])
    if not isinstance(critical_unknowns, list):
        problem("invalid_critical_unknowns", "Critical unknowns must be an explicit list.")
        critical_unknowns = []
    unresolved_critical = any(
        isinstance(item, dict) and item.get("severity") == "critical"
        and ruling_map.get(item.get("id"), {}).get("status") == "unresolved"
        for item in objections
    )
    blockers = [item for item in findings if item["severity"] == "blocker"]
    if blockers or unresolved_critical:
        status = "blocked"
    elif not brief_complete or critical_unknowns:
        status = "exploratory"
        note(
            "incomplete_brief",
            "The brief is incomplete or has critical unknowns; exploration is allowed but acceptance is not.",
        )
    else:
        status = "ready_for_selection"

    return {
        "format_version": 1,
        "brief_version": brief.get("brief_version"),
        "canonical_brief_ref": refinement.get("canonical_brief_ref"),
        "handoff_status": status,
        "acceptance_claim": False,
        "prototype_selection_ready": status != "blocked",
        "refinement_handoff_permitted_after_selection": status != "blocked",
        "complete_what_handoff": status == "ready_for_selection",
        "sources": sources,
        "what_items": what_items,
        "assumptions": assumptions,
        "decision_authority": authority,
        "council": {
            "mode": council.get("mode"),
            "members": members,
            "objections": objections,
            "rulings": rulings,
        },
        "open_questions": brief.get("unresolved_questions", []),
        "critical_unknowns": critical_unknowns,
        "input_revisions": revisions,
        "direction_ids": [item.get("id") for item in eligible if isinstance(item, dict)],
        "direction_input_versions": input_signatures,
        "unassessed_states": state_gaps,
        "review_evidence_by_kind": evidence_by_kind,
        "same_model_roles": same_model,
        "findings": findings,
        "limitations": [
            "Structure and recorded provenance can be checked; source support, authority authenticity and reviewer independence cannot.",
            "Qualitative review flags material differences but does not prove creativity, novelty, usability or acceptance.",
            "A selected prototype is not product approval; human evidence and engineering checks remain separate.",
        ],
    }


def refinement_route(exploration, selected_direction):
    """Describe the existing format-2 refinement handoff after council selection."""
    direction = next(
        (item for item in exploration.get("directions", [])
         if isinstance(item, dict) and item.get("id") == selected_direction
         and item.get("eligible") is True),
        None,
    )
    if direction is None:
        raise HandoffError(f"selected direction {selected_direction!r} is not eligible")
    refinement = exploration.get("handoff", {}).get("refinement", {})
    if not refinement.get("canonical_brief_ref") or refinement.get("format_version") != 2:
        raise HandoffError("existing format-2 refinement route is incomplete")
    return {
        "skill": "ui-prototype-council",
        "format_version": 2,
        "canonical_brief_ref": refinement["canonical_brief_ref"],
        "selected_candidate": selected_direction,
        "selection_authority": "existing prototype-selection result; not inferred by this validator",
    }


def preflight(action, approval_ref=None, data_class="synthetic"):
    """Check declared authorization only; this command never performs the action."""
    if action not in {"provider-call", "data-sharing", "publication"}:
        raise HandoffError(f"unsupported external action {action!r}")
    if not approval_ref:
        return {
            "status": "denied",
            "action": action,
            "data_class": data_class,
            "reason": "No explicit project authorization reference was supplied.",
            "action_executed": False,
        }
    return {
        "status": "preflight-passed",
        "action": action,
        "data_class": data_class,
        "approval_ref": approval_ref,
        "action_executed": False,
        "note": "The reference is an attestation; this local tool does not verify its authority or perform the action.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate", help="validate a local brief and concept comparison")
    check.add_argument("--brief", type=Path, required=True)
    check.add_argument("--exploration", type=Path, required=True)
    check.add_argument("--report", type=Path)
    gate = commands.add_parser("preflight", help="check an external action's explicit authorization")
    gate.add_argument("--action", choices=("provider-call", "data-sharing", "publication"), required=True)
    gate.add_argument("--approval-ref")
    gate.add_argument("--data-class", default="synthetic")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            report = preflight(args.action, args.approval_ref, args.data_class)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["status"] == "preflight-passed" else 2
        report = validate(_read_json(args.brief, "brief"), _read_json(args.exploration, "exploration"))
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 1 if report["handoff_status"] == "blocked" else 0
    except (HandoffError, OSError, TypeError, KeyError) as error:
        print(f"what-council: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
