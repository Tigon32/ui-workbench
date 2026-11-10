---
name: what-council-exploration
description: Derive a sourced, challenged project WHAT handoff and compare materially different interface concepts before prototype selection.
---

# What-council concept exploration

Use this upstream of `ui-prototype-council` when a project needs to clarify
what its interface must communicate and enable before choosing how it should
look or work. The adopting project owns domain truth, constraints and
decision authority. This skill does not define project requirements or
approve a product design.

## Authority and safety

Use the target project's contributor rules, accepted decisions, existing
structured brief and implementation. Treat missing evidence as unknown.
Retain the format-2 structured brief as the canonical source of truth; extend
it with source, confidence, assumption and council records rather than
creating a second brief. Existing format-1 and format-2 refinement ledgers
remain unchanged and readable.

The project sponsor retains sponsor-owned decisions. Respect decisions
explicitly delegated to agents; agents can make bounded proposals without
asking approval for every detail. Do not invent sponsor approval. Require a
cited sponsor-approval source for any sponsor decision labelled approved.
Agent-delegated assumptions stay explicitly exploratory and are not project
facts.

No skill, council or script authorizes external model calls, data sharing,
spend, publication or provider actions. Check the project's data policy and
explicit authorization before any such action. The bundled local preflight
denies actions without an approval reference; even a passed preflight only
records an attestation and performs no action. Use synthetic fixtures in
examples and tests, never secrets or confidential project data.

The WHAT-council (advisor, adversary, judge) is not the prototype reviewer
council. Distinct role perspectives are required. Disclose same-model use:
separate prompts do not establish independent judgement. A validator can
check declared structure and provenance, not source truth or reviewer
independence.

## Workflow

1. **Start from the existing brief.** Preserve its version, users/jobs,
   outcomes, scenarios, constraints, platforms, evidence, unknowns, budget and
   decision authority. Add source references and confidence to material
   claims; record assumptions with owner and treatment. Keep user needs,
   project constraints, proposals and unresolved sponsor questions distinct.
2. **Run the project what-council.**
   - The advisor proposes what users need to understand, decide and do, and
     why, citing available sources and confidence.
   - The adversary challenges unsupported domain assumptions, omitted tasks
     and states, hidden layout prescriptions, decision conflicts and
     invented approvals.
   - The judge records a reasoned resolution, revision or blocker for each
     objection. The judge cannot approve sponsor-owned decisions.

   Record who or what filled each role, how it was run, distinct
   perspectives, objections, rulings and open questions. Missing roles or
   unresolved critical objections block completion. An incomplete brief may
   still support clearly labelled exploration, never an acceptance claim.
3. **Separate WHAT from HOW.** “Show the source and uncertainty of each
   finding so an analyst can decide what to investigate” describes WHAT.
   “Use a three-column table with a filter rail” prescribes HOW. Flag a
   layout prescription lacking source and authority for council review; do
   not use a keyword ban. A separately recorded and sourced/authorized
   design-system or platform constraint is allowed. Resolve or reclassify
   prescriptions without losing their history.
4. **Freeze comparable inputs.** Version the brief, fixture, tasks,
   constraints, platforms and rubric. State required states and tasks. A
   material change creates a visible new revision. Do not silently rank
   candidates with incompatible inputs; rerun them under a common version or
   report separate, incomparable groups. Show every state without evidence
   as unassessed.
5. **Explore at least two HOW directions.** Derive materially different
   information architectures or interaction models from exactly the same
   WHAT, fixture, tasks, constraints, platforms and rubric. Describe each
   direction's organizing principle and task/state coverage. A qualitative
   project review should explain meaningful differences and flag
   color/theme-only variants as insufficient, including a pairwise review of
   eligible directions. This review is not a
   mechanical creativity or novelty test; no universal style or novelty
   threshold applies.
6. **Hand off, do not replace downstream workflows.** Give the directions
   to `ui-prototype-council` for its existing static prototype generation,
   gates, captures, review and selection process. Once that process selects a
   candidate, hand it and the same canonical brief to the existing format-2
   refinement loop. A selected concept is not product approval.
7. **Keep evidence kinds separate.** Label generator self-scores, declared
   model reviews and human evidence separately. A self-score is not a vote;
   a model review does not become human evidence. Static browser evidence
   does not establish native, assistive-technology or usability outcomes.

## Local validator and example

The standard-library validator checks recorded roles, rulings, authorities,
input revisions, candidate compatibility, state coverage, qualitative
distinctness declarations and downstream handoff fields. It flags
unsupported sponsor approvals, promoted delegated assumptions, unattributed
layout prescriptions and color-only concepts. It does not decide whether a
source is true or a concept is genuinely creative. The
[`exploration.schema.json`](exploration.schema.json) describes the comparison
artifact shape; the validator adds cross-record and authority checks.

Run the all-synthetic example locally:

```sh
python3 .github/skills/what-council-exploration/what_council.py validate \
  --brief docs/examples/concept-exploration/project-intake-v2.json \
  --exploration docs/examples/concept-exploration/exploration.json
```

Its expected status is `exploratory`: the brief intentionally retains a
sponsor-owned unknown. It shows the two concept directions and their exact
shared input revisions, flags a color-only variant and an unassessed state,
and does not claim acceptance.

Test authorization before an external action:

```sh
python3 .github/skills/what-council-exploration/what_council.py preflight \
  --action provider-call --data-class private
python3 .github/skills/what-council-exploration/what_council.py preflight \
  --action data-sharing --data-class confidential
```

Both are denied without an explicit project approval reference. The
preflight never invokes a provider, transfers data or publishes anything.

## Boundaries

There is no universal model, score, platform, style, novelty threshold or
human-approval requirement for every delegated detail. A declared status is
not proof that its source supports the claim. A validator pass is not
independent judgement, creative diversity, human usability, accessibility
qualification or sponsor acceptance. An incomplete or blocked handoff cannot
claim acceptance.
