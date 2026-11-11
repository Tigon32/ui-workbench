# Design quality, evidence and adoption

## What changed

Issues [#1](https://github.com/Tigon32/ui-workbench/issues/1) and
[#2](https://github.com/Tigon32/ui-workbench/issues/2) distinguish relative
prototype selection from absolute design quality.
The bundled `rubric-default.json` supplies a starting catalogue, without adoption
thresholds. Projects must review its platform, applicability, weights and floors
before a run and declare their own adoption gate before adoption.

A default is not a universal design standard. No finite catalogue proves that
every relevant concern has been found.

## Council and coverage decision

On 2026-11-10, two independent council advisors reviewed the proposed coverage.
One reviewed design and evidence validity. The other inspected browser checks
and capture tooling at `e09ac57`.
The integrating reviewer adjudicated their recommendations.
The host selected the advisor models. Exact model versions were not pinned.
This was a bounded engineering/design council, not a calibrated prototype run
or a study with people.

The design advisor recommended ten weighted domains with detailed subcriteria.
The implementation retains 23 explicit dimensions so the owner's requested
categories remain visible. It groups them as visual, UX and hybrid.
Definitions and exclusions prevent the same defect from receiving several scores.
Weights sum to 100 in the default. Projects can change them before review.

| Additional angle | Owning default dimension |
|---|---|
| Click budgets, keyboard effort, progressive disclosure | `job_completion` |
| Platform conventions | `craft` |
| Perceived responsiveness and difficult states | `feedback` |
| Privacy, scope and permission explanations | `truthful_state` |
| Consequential choices, consent, cancellation and reversibility | `error_recovery` |
| Discoverability and contextual help | `wayfinding` |
| Large datasets, long names and supported localization | `text_resilience` |
| Brief-specific identity without novelty for its own sake | `visual_character` |

The browser advisor rejected pixel-identical theme parity, mandatory distinct
hover/active styles and blanket rejection of native controls.
The integrating decision accepts those objections.
Parity concerns equivalent information and tasks.
Native controls can be appropriate.
Different input states need understandable feedback, not artificial visual differences.

Token scales and motion limits require declared project values.
Static captures cannot establish perceived performance.
Synthetic text expansion cannot establish translation quality.
Browser checks cannot qualify a native app, screen-reader use or human outcomes.

## Coverage matrix

The rubric's `scope` fields define ownership and exclusions.
Use the following evidence map with those fields.
Every dimension can apply to web or native interfaces; the project must declare
actual applicability before review. The mechanical column describes browser
coverage only. Human evidence is required for claims about participant outcomes,
assistive use or perceived behavior, not supplied by an expert score.
Mechanical findings are pass/fail evidence, not subjective score bonuses.
Only declared checks run. Unrequested coverage is not implied.

| Dimension | Mechanical evidence where available | Expert evidence and limits |
|---|---|---|
| `typography` | Declared font-size scale and rendered text sizes | Captures establish reading roles, not participant reading performance |
| `hierarchy` | Required rendered text | Review attention order in named captures |
| `spacing_density` | Declared spacing scale | Review grouping and useful density, not layout alignment again |
| `color` | Existing rendered contrast and declared-color checks | Review semantic color roles, not a second contrast score |
| `iconography` | Existing target/focus checks provide partial evidence | Review meaning and optical coherence |
| `consistency` | Token generation checks | Compare equivalent concepts across screens and states |
| `craft` | Existing clipping and token checks provide partial evidence | Review finish and declared platform conventions |
| `clarity` | Required and forbidden text | Review screen purpose and next-step comprehension |
| `interaction_states` | Existing focus/target checks provide partial evidence | Supply enabled, disabled, selected and pending states, not only a default screenshot |
| `theme_parity` | Visible control/name/state parity in ordinary light/dark | Review equivalent content, emphasis and tasks across all declared themes |
| `accessibility` | Existing contrast, keyboard focus, reflow and target checks | Real assistive use still needs separate trials; browser gates are not compliance |
| `responsive_behavior` | Declared widths and independent 320 CSS pixel reflow | Review adaptation quality; native resizing is unsupported |
| `motion` | Declared reduced-motion CSS duration limit | Review purpose and reduced-motion meaning; JavaScript motion needs separate evidence |
| `job_completion` | Scripted visible-label paths and click budgets | Review path quality; automated clicks are not human task success |
| `truthful_state` | Required/forbidden text and owned edge fixtures | Review unknown, stale, proposed, privacy and permission explanations |
| `wayfinding` | Scripted navigation paths provide partial evidence | Review context, return paths, discoverability and help |
| `feedback` | Named state captures provide partial evidence | Real latency and perceived responsiveness remain unmeasured by static captures |
| `error_recovery` | Scripted cancellation/recovery paths where declared | Review consent, consequences and control; no mutation authority is inferred |
| `content` | Required/forbidden text and visible-word budgets | Review precise terminology and actionable explanations |
| `layout` | Existing reflow checks provide partial evidence | Review grid, alignment and proportion, not whitespace rhythm again |
| `data_display` | Owned expected text/data fixtures | Review encodings, comparisons and metrics, not source certainty again |
| `visual_character` | No automatic originality score | Review fit to the brief; novelty or an anti-template label is not evidence |
| `text_resilience` | Opt-in marked text-expansion fixture clipping check | Review long names, full-detail access, large sets and real supported locales |

Motion and localization remain applicable when the brief needs them.
If not applicable, record the exclusion and reason before scoring.
Do not silently remove categories because a particular prototype omits their evidence.
Unsupported native or human evidence remains explicit, not a browser pass.

## Scope and refinement contract

### Scope intake and paired refinement (issue #13)

New exploration format 2 references the canonical brief's version-1
[scope intake](../.github/skills/what-council-exploration/intake.schema.json).
Scope confirmation, KEEP and inventory precede layout. Product work starts
with shells/IA and journeys, then coverage, data display/density and craft.
Sponsor authority cannot be delegated away by a council ruling. Stale brief
reuse requires explicit fresh reconfirmation; undeclared history is not
detectable. Domain artifact paths remain opaque, with explicit data classes.
Confirmation and sponsor source bind an exact `scope_snapshot`: level, stage
and view-disposition map. Changing exclusions or using a shell requires fresh
sponsor evidence; shells are product-only. Explicit decision/objection topics
prevent missing-topic delegation. History needs prior dates/confirmation refs
or an explicit `prior_briefs_none_reason`. Claims still rely on honest recorded
quotes, source contents and severity assignments, not authenticated signatures.

New selection preparation can bind brief/directions files; selection and
refinement reports show scope independently of craft. Content coverage counts
only `covered`, while a labelled shell stub establishes reachability alone.
Refinement without current coverage evidence is `partial-scope` when it has
in-scope views, even if its local quality goal is met. Legacy runs disclose
undeclared scope and do not silently acquire product claims.
New preparation records `scope_contract_version: 1` and requires both files;
only explicit `--legacy-unscoped` can create unscoped compatibility artifacts.
New refinement contracts also use this marker. Format-2 goal-stop verification
now uses its already documented selected-point denominator, matching the report;
the judge rejected retaining the inconsistent full-inventory calculation.

Format-2 refinement may opt into `contract.keep_rule`:

```json
{
  "id": "multi_gain_v2",
  "min_improved": 3,
  "min_gain": 1,
  "noise_band": 0.5,
  "panel": {
    "reviewers": [{"id": "example", "kind": "generator_self_assessment", "model": "project-configured"}],
    "repeats": 2
  }
}
```

These are illustrative project-owned values, not defaults. This rule requires
scoped intake. Each attempt binds `paired_scores_ref` in actual evidence:

```json
{
  "schema_version": 1,
  "attempt_id": 1,
  "rule_id": "multi_gain_v2",
  "panel_id": "unique-review-session",
  "panel": {
    "reviewers": [{"id": "example", "kind": "generator_self_assessment", "model": "project-configured"}],
    "repeats": 2
  },
  "before_source_ref": "retained-source",
  "after_source_ref": "candidate-source",
  "points": {
    "example-point": {"baseline": [6, 6], "candidate": [8, 8]}
  }
}
```

Use the complete before/after point union, including untargeted guards, with
reviewer-major/repeat-minor arrays. Null evidence prevents keeping. Individual
scores remain integer 1-10; means/variance may be fractional. Proposal freezes
the rule/panel before editing; decision summary binds the paired artifact SHA.
Gains must meet declared minimums and strictly exceed the noise band, while
any regression vetoes keeping. Flat co-targets remain explicit unmet targets.
Historical-to-baseline drift is separate from candidate gain. A panel
attestation cannot prove that independent calls occurred, and repeated
same-model scores measure model variance, not human confidence.

`scope_challenge` stops polishing when sponsor feedback names missing scope.
It binds a feedback artifact containing quote, actor, date and matching
`missing_scope` inventory ids. Revisit scope with the sponsor, not the rubric.
This stop never constitutes adoption.

Consumer component-library lessons are conditional HOW context: reuse approved
components and shared type/radius/density/spacing/motion tokens, choose behavioral
foundations or specialists only for an actual need, and keep decoration
subordinate to tasks. Static prototypes still use offline HTML/CSS and system
fonts: no React dependency, registry fetch or external skill installation.
A library is not an accessibility or licensing approval.

### Issue #13 gap-council record

The issue review and subsequent project-wide audit used separately tasked
advisor, adversary and judge roles configured with Opus 5.5. Role separation
does not establish independent models or human evidence. Implementation
workers were configured separately. No new prototype score or user-study
result was produced by this engineering audit; the retained dogfood selection
attempts remain VOID.

The project audit covered scope/WHAT authority and freshness, paired
refinement/reporting, browser checks/captures, token generation, selection
evidence/identity and their test/documentation contracts. The judge accepted
14 findings, four with compatibility limits, and rejected a fifteenth claim
that the corrected format-2 selected denominator should be reverted.

| Area | Adjudicated gap and required correction |
|---|---|
| Scope inventory | Bind exclusions and stage to the sponsor-confirmed snapshot |
| Authority | Require topics and item-specific sponsor authority for deferrals/exceptions |
| Shells | Restrict stub coverage exceptions to confirmed product shells |
| New/legacy boundary | Require scoped new-run markers or explicit legacy preparation |
| Coverage reporting | Label unmeasured coverage, never present it as observed zero |
| Prior briefs | Require declared history/provenance and fresh reconfirmation |
| Browser isolation | Deny network and outside-folder reads before navigation, failing closed |
| Token scales | Match generated type/spacing names and resolve declared units |
| Colour provenance | Reject literal/page palettes while preserving forced-colour semantics |
| Adoption checks | Bind typed passing check reports, not screenshot declarations |
| Source identity | Include local assets and DESIGN.md in new-round source evidence |
| Reviewer order | Store and enforce reviewer-specific randomized assignments |
| Capture extent | Report truncation rather than silently hiding long-page content |
| Readiness | Wait for fonts/layout and support a bounded explicit ready condition |

These are engineering consistency checks, not signatures or a hostile-browser
sandbox. Source authenticity, completeness of declared history, honest
severity/topic labels, reviewer independence, native/assistive behavior and
participant outcomes remain outside the audit's proof.

## Score semantics

Every dimension uses integer scores from 1 to 10.
Anchors at 3, 5, 7 and 9 describe increasingly strong observed quality.
Scores 2, 4, 6 and 8 lie between anchors.
Use 1 for severe failure and 10 only with evidence exceeding the 9 anchor.

The weighted raw mean is:

```text
raw_mean = sum(weight * score) / sum(weight)
design_total = 100 * (raw_mean - 1) / 9
```

Thus raw 1 maps to 0 and raw 10 maps to 100.
This is not a percentage of compliance, likelihood of success or usability result.
Group subtotals use the same formula within their group.
Category means and totals use only calibrated, non-generator council reviewers.
Reports identify reviewer kind, model/version and seed.
Same-model spread measures within-model variation, not human agreement.

The optional `adoption_gate` requires three project-owned values: `total_min`
(0-100), `every_dimension_min` (1-10) and `critical_min` (1-10).
The workbench supplies no default values for these thresholds.
Record their rationale in `adoption_decision` before scoring.
Without them, category scores and totals remain available, but adoption is blocked.
Each dimension must meet both its declared floor and the applicable gate floors.
Required evidence must be assessed, and declared Tier 1 and Tier 2 gates must pass.

These are project design goals, not experimentally validated thresholds.
Floors apply to each kept reviewer.
A high average cannot hide a critical failure or disagreement across a floor.
`WINNER` and `ADOPTABLE` remain separate verdicts.
A weak relative winner can remain `NOT_ADOPTABLE`.
An adoption verdict is not permission to implement, release or change authority.
Use `council.py --verify RUN --require-adoptable` for an executable adoption gate.
It exits nonzero without an evidence-bound adoptable winner.
Ordinary `--verify` verifies report consistency, not design acceptability.

## Evidence and missingness

Rules version 3 requires the rubric digest, each prototype's source digest and
an evidence manifest in `round.json`.
The manifest maps local reference IDs to a path and SHA-256 digest.
Scoring verifies the evidence bytes and rubric digest before producing a report.
It also verifies that recorded target profiles match the rubric's declared conditions.
Paths may be absolute or relative to the round folder.
Moving a run requires updating paths and reviewing its evidence again.

Every dimension entry starts with `why`, then `score`.
It also declares an evidence status and named references:

```json
{
  "why": "The captured error state retains the original selection and offers cancellation.",
  "score": 7,
  "evidence_status": "observed",
  "evidence": ["error-light"]
}
```

Allowed unobserved statuses are `not_assessed`, `blocked` and `unsupported`.
They require a null score, not a zero or an assumed midpoint.
Missing required evidence makes the total unavailable and blocks adoption.
An incomplete candidate comparison is `VOID`, with no elimination.
Unassessed calibration evidence excludes that reviewer.
Generator self-assessment can be recorded but never supplies a council vote.
For rules version 3, each evidence reference must belong to the item being
scored, using the `<blind-id>/<reference>` prefix. Older version-3 runs that
used shared, unprefixed references will not verify under this item-local check.
Keep those artifacts unchanged for historical audit; create and score a fresh
run with item-prefixed references rather than rewriting old score sheets.

Declare genuine not-applicable dimensions before scoring:

```json
{
  "excluded_dimensions": [
    {"id": "data_display", "reason": "The declared interface contains no data comparisons, tables or diagrams."}
  ]
}
```

Each omitted default needs one substantive reason.
The report exposes exclusions.
All candidates in a run use the same applicable dimensions and denominator.
Never remove a weak or unassessed dimension after seeing its scores.
A changed applicability decision needs fresh evidence and review.
Critical exclusions require particular human scrutiny.
The script validates declaration shape, not the truth of the reason.

An earlier example project chose an anchored 9/10 on 80-90% of its selected
measurement points. That is an example, not a workbench-wide goal or adoption
threshold. With its default 23-point catalogue, it would mean 19 points at
80%, or 21 at 90%. New format-2 refinement ledgers record each project's own
score and fraction. Keep the full denominator in reports. An unassessed or
unsupported point remains visible and does not count toward the goal.
Record the goal and selected points before measurement.
The report labels a result `all_declared_points` only when every declared point
is selected. Otherwise, it labels the result `selected_subset` and lists the
excluded points. A subset claim is not an overall claim; exclusions remain in
the full denominator. Never exclude a point because its evidence is unavailable
or unassessed. An unassessed selected point remains counted and below the goal.

## Gate evidence

For version 3, declare gate results per blind item in `round.json`:

```json
{
  "adoption_checks": {
    "ABC": {
      "tier1": {"status": "pass", "evidence": ["markup-report"]},
      "tier2": {"status": "pass", "evidence": ["render-report"]}
    }
  }
}
```

Both references must exist in the evidence manifest.
Missing, failed or unverified gates block adoption.
The project owns Tier 1 and must supply its real report.
Preparation does not turn a missing project check into a pass.
Hash verification binds declared artifacts. It does not attest their truth,
establish tool provenance or certify accessibility.
Human review must verify that the evidence covers the declared source and scope.

Keep actual human task success, errors, time, Single Ease Question responses,
System Usability Scale responses and engineering results separate.
No composite design total may absorb or replace those measures.
Do not upload private fixtures, screenshots, source or user records without authorization.

## What-council concept exploration

The [what-council exploration skill](../.github/skills/what-council-exploration/SKILL.md)
is an optional upstream path. It extends the existing structured format-2
project brief rather than creating a parallel source of truth. The adopting
project records its advisor, adversary and judge roles, sources, assumptions
and confidence, objections and rulings, project authority, and unresolved
questions. Missing roles or unresolved critical objections block completion.
An incomplete handoff may support labelled exploration, never acceptance.
The sponsor retains sponsor-owned decisions; explicitly delegated decisions
do not require approval of every implementation detail. Claimed sponsor
approval needs an attributable approval source.

WHAT describes the user need, intended information and decision/task. HOW
proposes a layout or interaction model. An unsourced layout prescription is
flagged for council review, not rejected by a keyword rule. A separate,
sourced and authorized design-system or platform constraint is permitted.
At least two directions use the same versioned brief, fixture, tasks,
constraints, platforms and rubric. Qualitative review explains material
differences and flags color-only variants; it does not mechanically prove
creativity or novelty. Changed input versions remain visible, incompatible
comparisons are not ranked, and states without evidence stay unassessed.

The result feeds the existing static prototype-selection loop and, after
selection, the existing format-2 refinement loop. Generator self-scores,
declared model reviews and human evidence remain distinct. Same-model role
use does not establish independent judgement. Neither loop proves real-user
usability or product approval. The local validator checks declarations, not
source truth or authority authenticity; its preflight performs no external
action and denies an action without an explicit authorization reference.
There is no universal model, score, style or novelty threshold.

## Frugal review and compatibility

Run cheap deterministic checks before any model review.
For an increment, inspect changed dimensions and their affected neighbors.
Require complete declared coverage at adoption.
Do not convene a new model council for every small edit.

Rules versions 1 and 2 retain their existing selection arithmetic and report format
when no adoption gate is requested.
An optional gate on a legacy rubric reports scores, but cannot claim adoption
without version 3 evidence.
Do not recalculate historical scores as if missing dimensions had been assessed.

## Iterative refinement

Selection compares alternatives. Refinement can measure a bounded coherent redesign
or compare distinct alternatives through declared attempts. Neither process
implements a product interface. Hold the task, state, theme, viewport and check
scope fixed for every candidate. Do not combine unmeasured changes or omit a
required state after editing.

Before editing, freeze the rubric and adoption rationale, fixture, check commands,
tool versions, target profiles, themes, states, tasks and budgets in a run contract.
Declare positive integer attempted-increment and consecutive no-gain limits, and a
positive minimum meaningful gain for each targeted score or deterministic measure.
Name each targeted check and define the scored-gain repeat count and agreement rule.
Fix the sampling and aggregation rule before measurement; do not choose favorable
samples, retry until a score passes or rescore an attempt after its decision.
There are no workbench defaults for these limits or adoption thresholds.
For raw score gains, use the anchored 1-10 scale, not a rounded total.
Use the predeclared repetitions for borderline observations; inconclusive evidence
blocks a keep rather than authorizing further samples until one passes.

Score targets belong in `adoption_gate`, with rationale in `adoption_decision`.
The gate uses inclusive comparisons. A request for ">85/100" is not equivalent to
`total_min: 85`; settle the intended inclusive threshold with the owner before the
run. Do not change weights, exclusions or targets after seeing a candidate's score.
A changed contract needs an explicitly authorized new baseline, not a reset that
hides previous attempts.

### Measurement and keep/revert

Capture a complete baseline before the first edit. Preserve its source and relevant
inputs, actual reports, scores, conditions and captures under immutable identities.
Include uncommitted inputs if the source revision alone does not identify them.
Source snapshots list exact in-scope files and hashes, including pre-existing edits.
Keep each accepted and rejected candidate snapshot; never overwrite baseline evidence.
Store private artifacts only in the target project's authorized local run location.

Each attempt has one named hypothesis, target and bounded change. Record the
hypothesis before editing. Rerun the complete deterministic contract after the change,
including all declared pages, widths, themes, states, tasks and generated-token checks.
Do not narrow the check set to the changed view.
Re-score the target and affected neighboring dimensions against fresh evidence.
Shared token, theme or layout edits affect all dimensions unless a recorded impact
assessment justifies a narrower set. Generated output does not narrow the impact
of its source tokens.
Inspect all new captures for other changes and expand the scored set when needed.
Preserve reviewer kind, identity/model version and scoring conditions for comparisons.
If they change, stop blocked until comparable before/after evidence is available
under the frozen contract, or the owner authorizes a new baseline. Never subtract
incomparable scores. Self-scores are directional progress evidence only.

Compare finding identity and severity, task success and action budgets, coverage and
assessed dimension scores. A lower total finding count cannot hide a new failure.
A check becoming incomplete or unsupported is a regression, not a zero-finding pass.
Any new finding, severity increase or previously observed dimension becoming null
or lower blocks keeping. Targeted and affected dimensions need comparable observed
scores before and after if a score gain is claimed.
An unresolved question about a possible regression blocks keeping the increment.
Do not claim unchanged dimensions were re-verified merely because their old scores
were carried forward.

Keep only a targeted gain meeting its declared minimum with no regression.
The gain can repair a failure only in a check named by the declared target measure;
do not also award subjective points for the same decidable result.
Unchanged known failures may remain while refining, but still block adoption.
A neutral change, insufficient gain or any regression means
revert this attempt, retain its evidence and record why. Restore only the attempt's
edits; do not discard someone else's work. Verify the retained source identity.
Preserve the exact attempt patch. Reverse only its edits, not whole files containing
someone else's changes. Verify in-scope file hashes against the preceding accepted
snapshot and record the result. A conflicting concurrent edit blocks restoration.
If measurement or restoration fails, record `blocked` and stop.
Complete the measurement and decision record before another edit starts.

Every increment `keep` is provisional: it retains a candidate for further work,
not an independently validated quality gain or adoption. Mark it `provisional: true`.
Generator self-scores may guide that decision, but are not acceptance evidence.
An independent reviewer, blind to before/after order, can strengthen subjective
progress evidence where the project requires it. This does not require a full
council for every increment. Final acceptance always needs the fresh review below.

### Machine-validated iteration ledger

New ledgers use `format_version: 2`. The verifier continues to read format-1
ledgers with their original declared 9/10 and 80-90% goal semantics; it does not
silently convert or reinterpret them. The original
[synthetic comparison example](examples/refinement/README.md) remains format 1
as a migration/compatibility fixture. The tests construct version-2 ledgers
from synthetic local artifacts, including scope overlap, stale evidence,
incompatible mappings and incomplete briefs.

#### Brief, goal and decision authority

Format 2 binds `contract.brief_ref` to a versioned local JSON brief. It records
users and jobs, problem, desired outcomes, platforms, scenarios, constraints,
the project-owned score/fraction, available evidence, budget and stop
conditions, non-goals, unresolved questions and decision authority. Empty lists,
nulls and `status: incomplete` are explicit unknowns, not implied answers.
Incomplete briefs permit labelled exploration. An `adoptable` final review is
rejected unless the brief is complete, the goal is sponsor-approved, and every
sponsor-owned decision is approved. A complete brief must state its critical
users/jobs, problem, outcomes, platforms, scenarios and stop conditions, and
have no declared `critical_unknowns`; non-critical unresolved questions may
remain visible.

The project goal is `score` from 1 through 10 and `fraction` in `(0, 1]`.
That fraction applies to the explicitly selected point denominator; `selected`
points remain a subset of the full inventory when declared. For example, a
project may choose 8/10 across 60% of its selected points. This is not a
workbench-wide threshold. Reports show the full inventory, selected
denominator, exclusions and unknowns. Unselected points are not silently
deleted.

`decision_authority` separates sponsor-owned decisions from agent-delegated
decisions. Each attempt names its decision actor and decision records. An agent
may act within delegated decisions, but cannot mark a sponsor-owned decision
approved. A goal decision has a sponsor decision ID; only an approved sponsor
record can support a final acceptance claim. This records declared authority,
not independent proof of who acted.

#### Scopes, freshness and evidence coverage

Declare stable `scopes` of kind `component`, `region`, `page`, `state` or
`journey`; each measurement point lists its scope IDs. A point can contribute
once to each declared scope denominator, including overlapping region, page
and journey views, but never twice to the same scope. The report lists each
scope's inventory and denominator separately from the whole-project goal.
Journey scopes bind named task IDs from the deterministic check contract.
Failed or unknown tasks and unassessed points keep the journey visible even if
its component points score highly. Automated checks and task outcomes remain
separate from design judgments.

Format-2 score records explicitly use `assessment_state`:

| State | Meaning |
|---|---|
| `fresh` | Assessed on the current source; evidence coverage names this point. |
| `carried_forward` | Historical score from an earlier source; not a current observation. |
| `stale` | Historical score requiring re-review; a changed/affected point cannot support a current claim until freshly assessed. |
| `unassessed` | No current score, including unsupported or blocked evidence. |

Each scored point retains `assessed_source_ref`, reviewer kind and identity,
reason, evidence refs, and `evidence_coverage` for every ref. A coverage entry
states the point IDs and scenario IDs supported plus its rationale. A shared
artifact may cover several points when that membership is declared. Missing
coverage is rejected for a fresh score or reported as a coverage gap; it is
never treated as a pass. A carried/stale score remains visible but does not
count toward current goal progress. Affected carried points must be flagged
stale for re-review; a keep requires fresh assessments of affected points and
fresh evidence for the claimed target gains.

#### Version history and comparison labels

`version_history` is a parent-linked, ordered sequence binding each version's
goal, full and selected point IDs, point-to-scope memberships, scope IDs,
rubric/inventory/scope revisions and material decision artifact. Each appended
version has a mapping for every old and new point and scope, using explicit
`same`, `renamed`, `split`, `merged`, `added` or `removed` relationships.
Any goal, selection, rubric, inventory, point-to-scope or scope revision
must mark the comparison incompatible and explain why. The report labels
incompatible or not-yet-measured comparisons; it does not subtract totals,
drop missing points or imply equivalent denominators.

Like all ledger digests, the version sequence identifies current bytes but
cannot prove historical immutability or chronology. Preserve append-only
records in a trusted review system or commit where that guarantee is needed.
Hashing and metadata do not prove truth, reviewer independence or evidence
quality.

#### Attempt outcomes, effort and stops

Format-2 attempts also record expected and actual outcomes, affected points,
dependencies, guardrails, regressions, local evidence references, elapsed
effort, decision actor/authority and keep/revert rationale. The report includes
these alongside prior time fields. `no_gain` and `budget` stops require a
next-round hypothesis and rationale, an action (`revisit_brief`,
`test_larger_alternative` or `stop_with_reason`) and remaining effort when a
budget exists. A proposed larger alternative must fit within that remaining
budget. A plateau suggests revisiting the brief or testing a larger alternative;
it never authorizes lowering the target or changing scores. No fixed speedup or
quality gain is presumed.

Use the bundled `iterations.py` to verify or report either format. The
[synthetic comparison example](examples/refinement/README.md) contains two
materially different layouts, fixed browser checks, a held-out task, a
multi-dimension hypothesis and a provisional keep.

An HTML attempt report can be generated with
`iterations.py html <ledger> --attempt <id> --output <file.html>`. Omit
`--attempt` to include every attempt in one report. The output is a standalone
document: images are embedded, text is escaped, the score table reflows at
narrow widths, and no external fonts, scripts or stylesheets are loaded.
Each attempt puts its decision and rationale before its scorecard and visual
evidence. Scores show before, after, delta, assessment/evidence status,
evidence references, targeted points and whether each declared gain was met;
incompatible comparisons are labelled rather than subtracted. The report
states whether an independent final review exists and retains the limits on
reviewer provenance and usability claims.

Visual annotations are optional and are never inferred. An attempt's optional
`visual_ref` points to a hash-bound JSON artifact with this exact shape:

```json
{
  "schema_version": 1,
  "coordinate_space": "normalized",
  "attempt_id": 1,
  "before_source_ref": "baseline/source.json",
  "after_source_ref": "attempt-1/source.json",
  "before_capture_ref": "attempt-1/before.png",
  "before_capture_sha256": "<artifact SHA-256>",
  "after_capture_ref": "attempt-1/after.png",
  "after_capture_sha256": "<artifact SHA-256>",
  "changes": [{
    "id": "primary-action",
    "label": "Primary action",
    "description": "Moved the action beside the page heading.",
    "before": {
      "start": {"x": 0.1, "y": 0.2},
      "end": {"x": 0.6, "y": 0.3}
    },
    "after": {
      "start": {"x": 0.1, "y": 0.2},
      "end": {"x": 0.7, "y": 0.3}
    }
  }]
}
```

Coordinates are fractions of the corresponding capture's width and height in
the range `[0, 1]`; each change requires separately authored before and after
arrows. The renderer draws numbered red arrows on each capture and places the
matching escaped description immediately below the pair, not over the captured
content. Arrow geometry uses each capture's pixel dimensions, so full-page
captures do not distort the arrows or number badges. Each PNG is size/dimension checked and bound by SHA-256 in the visual
artifact; the attempt's decision record binds the visual artifact digest. In
format 2, the visual JSON and both capture refs must also appear in
`actual_evidence`. With no metadata, the report states that no captures or
annotations were supplied. Empty annotations also get an explicit state. The
validator limits each capture to 8 MiB and 40 million pixels, the aggregate
captures in one HTML report to 40 million pixels, each complete HTML report to
32 MiB, and accepts at most 100 annotations per attempt.
Hashes establish byte identity, not capture truth or chronology.

The format-1 ledger freezes a `scope_id`, the complete point denominator and
its selected 80-90% goal, required scenarios, task budgets, feasibility
statement, limits and recorded time. Every scenario names its theme, viewport,
state and evidence type. A source-manifest artifact binds its build ID and the
hashes of page sources and inputs. Baseline and after score/check artifacts
bind their own source and build identity. A build may change between attempts;
the declared scope and coverage may not.

Each attempt has a sequential ID, a named hypothesis, target dimensions and
positive per-dimension gains. A hash-bound proposal must declare these before
editing. Its after-score record must contain every denominator point. A null
score has an explicit missing-evidence status. A 9 or 10 needs its rubric anchor,
reason and evidence. The report shows numerator, full denominator, every point's
change, missing evidence, reviewer kind, attempt count, recorded elapsed/review
time, findings and scenario coverage. Unknown time remains null.
The goal report states whether its claim covers all declared points or an
explicitly selected subset, lists the selected count and exclusions, and keeps
the full declared denominator. An unassessed selected point is listed as
unassessed and below goal; missing evidence does not remove a point from either
the denominator or the selected scope.

The check record includes actual command strings, exit codes, check status,
scenario outcomes, finding identities/severities and task clicks. A passing
keep needs every required scenario and command to pass, every task to pass
without a click increase, no new or worsened finding identity, no score loss,
and the full expected gain for each target dimension. Unknown or unavailable
evidence, a command failure, changed coverage or a task-budget regression blocks
a keep. Reverts require a source-hash restoration record; the tool never restores
files. A blocked attempt must be last.

`report` separates generator self-assessment, independent qualified review,
human review, assistive-technology evidence and automated check observations.
These are declared labels. Different labels do not establish reviewer
independence or qualification. Automated findings are grouped by identity and
profile; counts alone do not decide whether a change is safe.

The verifier rejects changed or missing artifact bytes, source inputs, stale
scores, post-decision score/check/source changes, missing points, changed
scope/build evidence, new findings, failed commands, unknown check status and
invalid stop reasons. Each decision artifact freezes the before/after hashes.
It does not infer a per-attempt gain model. `infeasible` is accepted only when
a hash-bound immutable score ceiling proves that every selected point is below
the target, with explicit assumptions. Multi-dimension or unbounded-gain cases
remain `unknown` unless a valid proof is supplied.

SHA-256 binds the bytes currently referenced; it does not prove when they were
recorded, that the evidence is true, or that reviewer labels are genuine.
A person who can rewrite a ledger can also rewrite its hashes. Do not claim that
a freely rewritten hash chain proves historical authenticity. Preserve each
decision's ledger and evidence in a trusted, immutable review record or commit,
and record that external trust anchor. The validator does not create that anchor
or establish edit chronology. Its `recorded_before_edit` proposal flag is a
declared assertion, not a trusted timestamp.

### Stops and final adoption

Record one stop reason: `target_provisionally_met`, `no_gain`, `iteration_cap` or
`blocked`. Every attempted increment counts toward the cap, including reverts.
A rejected or neutral attempt increments the consecutive no-gain count.
An interrupted or blocked attempt also counts toward the cap and does not reset
that streak. Only a kept measured improvement resets it.
If several stops apply, choose `blocked` first, then `target_provisionally_met`,
then `no_gain`, then `iteration_cap`. Thus a kept target-reaching gain at the cap
stops for the target, but a blocked last attempt cannot claim it.
Check stop conditions before editing and after every decision.
If the baseline already meets the provisional target,
skip edits and proceed directly to the final review.

`target_provisionally_met` requires current full deterministic gate passes and no
known unresolved regression. The declared progress score set must contain a latest
observed non-null score for every applicable dimension. Its estimated total must meet
`total_min`, and each score must meet its dimension floor, `every_dimension_min`
and, where critical, `critical_min`. Without declared thresholds or complete scores,
this stop cannot apply. Apply the same test to a baseline that might skip edits.
Identify carried inputs explicitly. A mixed-revision vector can supply this progress
estimate only as a review trigger, never a current complete council score.

For the first three stops, run one fresh full council/adoption review on the retained
source. Preserve that review and record `adoptable`, `not_adoptable` or `blocked`
with its report reference. A blocked refinement cannot claim acceptance while its
required evidence is missing. Do not automatically start another cycle after a failed
final review or extend limits without authorization.

Mixed-revision progress scores and generator self-reviews cannot supply the final
council vote. Carried scores do not establish a current complete total.
A provisional target is only a stop signal; caps and no-gain stops are not success.
Final adoption needs fresh complete evidence, calibrated non-generator reviewers,
declared floors and project gates, with `--require-adoptable` where blocking is needed.
No new model call, spend, publication or product change is authorized by the loop.

Repeated tuning can overfit the frozen fixtures. Declare any held-out validation
cases before refinement and reserve them for final review. If none are available,
record that limit; do not claim that success generalizes to untested cases.
Use the immutable baseline to inspect cumulative drift, not only the last increment.

### Refinement council record

On 2026-11-10, two independent-context automated advisors reviewed issue #4 and the
draft: one covered evidence validity, the other execution and ledger rules.
The integrating reviewer adjudicated their findings as follows.
This was a bounded contract review, not a calibrated prototype council, design
improvement result or human study.

| Concern | Adjudication |
|---|---|
| Simultaneous stops, interrupted attempts and cap counting | Add ordered stops, reserved attempt IDs and blocked recovery rules |
| New findings, missing scores and vague mechanical gains | Explicitly block regressions and require a named target check |
| Safe restoration and ledger replacement | Record exact source/patch identities, restoration evidence and immutable ledger revisions |
| Self-awarded subjective gains | Mark all keeps provisional; retain independent final acceptance instead of requiring a new council per edit |
| Shared-token impact and stale progress scores | Require an impact assessment and per-score assessment/source markers |
| Undefined provisional target | Define a complete progress-vector/floor test, separate from a current council score |
| Noise and fixture overfitting | Predeclare repeats/aggregation and held-out cases where available; do not waive regressions as noise |
| Mandatory hash chains or new helper tooling | Defer; this issue documents a protocol, not automated integrity enforcement or regression comparison |

## Browser profile usage

Both `render_check.py` and `round_prep.py prepare` accept `--rubric PATH`.
Use the same rubric bytes for preparation, checks and scoring.
The five `target_platforms` flags explicitly include or exclude mobile, tablet,
laptop, desktop and wide browser viewports.
Record the decision in `target_platform_decision`.
At least one must be enabled.

Default widths are 390, 768, 1280, 1920 and 2560 CSS pixels.
`target_widths` can override enabled profiles with integers from 320 to 7680.
Equal widths share captures while metadata retains both profile names.
The independent 320 CSS pixel reflow check always runs.
It models web zoom/reflow, not a required phone target.
These are CSS viewports, not proof of actual device or touch behavior.
Set `renderer` to `web`. Native renderers fail before preparation creates output.

An optional `desktop_zoom` object declares real browser zoom percentages, for
example `[100, 125, 150, 200]`. It requires the desktop profile and records
`evidence_type: real_browser_zoom`. The bundled renderer does not execute real
browser zoom, so each declared real-zoom scenario is marked `unavailable`.
This is not a pass. A CSS-width change, device scale factor or 320-pixel reflow
must not be relabelled as real browser zoom. If a project requires these steps,
obtain separate real-zoom evidence before keeping or adopting a candidate.
Explicitly disabling the mobile profile does not remove desktop zoom or reflow
from the declared scope.

The optional `quality_checks` object supports:

| Key | Declared value | Scope |
|---|---|---|
| `semantic_control_parity` | Boolean | Compare visible control roles, names and availability in ordinary light/dark |
| `reduced_motion_max_ms` | Integer 0-10000 | Bound computed nonessential CSS durations under the reduced-motion preference |
| `typography_scale_px` | Unique positive integers, maximum 256 | Check declared `--font-size-` tokens and rendered visible text sizes |
| `spacing_scale_px` | Unique nonnegative integers, maximum 512 | Check declared `--space-` tokens and visible computed spacing |
| `text_expansion_factor` | Number greater than 1 and at most 3 | Enlarge text within `[data-text-expansion]` fixtures and inspect clipping |

The default enables semantic parity only.
Other checks require project-specific limits, tokens or fixtures.
They are not universal typography, motion or translation standards.
`data-motion-essential` exclusions require human review.
The motion check does not establish JavaScript, pseudo-element or full animation behavior.
Text enlargement is not pseudotranslation or right-to-left qualification.
Unknown requested coverage is incomplete, not a pass.
Use the CLI help for the existing expected-text, forbidden-text and task contracts.

## Native adoption evidence profile

This is an evidence contract, not an implemented native runner.
The bundled browser commands reject native rendering.
Do not treat their result as native qualification.

Bind a native review to the source revision, app build, operating-system version,
declared window sizes, themes and named states.
Include native light/dark captures of equivalent information and tasks.
Exercise keyboard-only navigation, focus, shortcuts and menu behavior in the
running app. Record task paths and their project-owned action budgets.
Record VoiceOver navigation, accessible names, roles, values and state changes
with the actual app and assistive technology.
Exercise resizing at declared minimum, typical and maximum window sizes.
Verify reduced-motion behavior with the operating-system setting enabled.
Include long identifiers, supported locales and relevant empty, partial, denied,
loading, stale and error states.

Project checks must supply their native pass/fail reports and unresolved gaps.
An unsupported or unassessed required observation blocks native adoption.
Human task outcomes remain separate from the expert-design score.
No native evidence or human study was produced by this tooling implementation.

## Validation on 2026-11-10

`UI_CHECK_REQUIRED=1 python3 -m unittest discover -s tests` passed all 62 tests,
with no skips.
The installed Chrome version was 157.0.8103.39.
The suite also exercised generated Swift token compilation.
`git diff --check` passed.

An owned synthetic integration test exercised actual rendering, preparation,
reveal, capture manifests and the scoring CLIs together.
It verified that a missing project Tier 1 gate blocks adoption despite a winning
expert-score vector. Mutating a captured artifact then blocked verification.
These vectors test the tool, not design quality or human usability.

Focused negative controls cover a weak relative winner, a critical floor failure
inside a high total, missing category evidence, changed rubric/captures, mismatched
target profiles, unsupported native rendering and incomplete requested checks.
