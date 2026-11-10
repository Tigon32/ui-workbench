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
