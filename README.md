# UI Workbench

UI Workbench holds reusable GitHub Copilot skills for interface design work.
It separates design decisions from prototype selection. It does not contain a
product interface or project-specific design rules.

## Skills

| Need | Skill | Result |
|---|---|---|
| Resolve a design goal, a blocking choice or a needed deferral | [`interface-design-review`](.github/skills/interface-design-review/SKILL.md) | A bounded decision map with evidence, choices and deferrals |
| Derive a sourced WHAT and explore different concept directions | [`what-council-exploration`](.github/skills/what-council-exploration/SKILL.md) | A challenged, versioned project handoff for prototype selection |
| Select or incrementally refine interface prototypes | [`ui-prototype-council`](.github/skills/ui-prototype-council/SKILL.md) | Measured increments, deterministic gates and a computed selection/adoption outcome |

Use the review skill when requirements or constraints are not settled. Use the
what-council exploration when user intent is understood but materially
different interface directions should be compared. Use the prototype council
only when the brief, fixture and rubric are ready. Neither skill builds the
product interface.

## Design quality and adoption

Start new runs from
[`rubric-default.json`](.github/skills/ui-prototype-council/rubric-default.json).
It covers 23 explicit dimensions, with anchors, groups, weights and critical
floors. Review its target platforms and thresholds before scoring.
Justify each omitted default dimension.

Version 3 reports category scores, group subtotals and an expert-design total
out of 100. Its adoption verdict is separate from the relative winner.
Missing required evidence and critical failures cannot disappear inside an average.
Generator self-assessment does not count as a council vote.

The [quality contract](docs/design-quality-contract.md) records the bounded
council, coverage map, scoring formula, evidence rules and limitations.
The total is expert judgment, not human usability or accessibility certification.
New refinement ledgers use a versioned project-owned score and fraction; 9/10
across 80-90% is only an example. Keep the complete inventory, selected
denominator, exclusions and unknown evidence visible. Format-1 ledgers remain
readable with their original declared semantics and are not silently migrated.

## Improve an existing prototype

Use the [refinement loop](.github/skills/ui-prototype-council/SKILL.md#iterative-refinement-loop),
not one large edit followed by a before/after score.
First declare the project-owned target, iteration cap, no-gain limit and meaningful
gain. An increment can test a bounded multi-dimension hypothesis or compare distinct
alternatives. Keep conditions fixed and record every attempt in the
[iteration ledger](docs/design-quality-contract.md#iteration-ledger).

Illustration only; these scores are synthetic, not council or usability results:

1. **Baseline:** preserve source, inputs, full Tier 1/2 reports and captures;
   record typography 6/10 and neighboring dimensions with evidence.
2. **Increment:** name the hypothesis "a coherent heading scale improves reading
   roles"; change that scale in `DESIGN.md` and regenerate tokens.
3. **Measure and keep:** rerun all declared checks, widths, themes, states and tasks.
   Re-score typography and affected neighbors. If the declared gain is observed
   (for example 6 to 7) with no regression or missing coverage, provisionally keep
   and log it. Shared-token changes need a documented impact assessment.
4. **Next attempt and revert:** make and measure only the next declared change.
   If it introduces an overflow or another new finding, revert only that attempt,
   preserve its evidence and verify the preceding accepted source. A higher score
   cannot offset it.

Do not start the next increment before measurement and keep/revert are recorded.
Stop at a provisional target, the no-gain limit or the iteration cap; stop blocked
if evidence or restoration cannot be verified. Then obtain one fresh full
council/adoption review when unblocked. Self-scores can guide edits, not acceptance.
The [council record](docs/design-quality-contract.md#refinement-council-record)
explains the evidence and execution safeguards added to this loop.
The bundled [`iterations.py`](.github/skills/ui-prototype-council/iterations.py)
validates and reports a hash-bound ledger. Run its
[synthetic comparison example](docs/examples/refinement/README.md) with two
materially different page layouts and a held-out error task.
The [version-2 intake](docs/examples/refinement/project-intake-v2.json),
[overlapping scope map](docs/examples/refinement/scope-map-v2.json) and
[attempt report excerpt](docs/examples/refinement/attempt-v2-report.example.json)
illustrate local synthetic data, incomplete-brief exploration, project authority,
whole-page/journey coverage and plateau direction. Automated ledger tests build
and verify runnable format-2 fixtures without uploads or model calls.

## Explore from a project WHAT

The [what-council exploration skill](.github/skills/what-council-exploration/SKILL.md)
adds an upstream project advisor/adversary/judge handoff. It distinguishes
user intent from layout HOW, versions comparison inputs and qualitative
direction review, then hands candidates to the existing prototype-selection
and format-2 refinement loops. It does not replace the structured brief or
grant external-call authorization. The local validator and all-synthetic
example are documented in
[`docs/examples/concept-exploration`](docs/examples/concept-exploration/README.md).

## Checks

The prototype tools use Python's standard library. Run their tests with:

```sh
python3 -m unittest discover -s tests
```

Rendered checks require an installed Google Chrome. Token generation writes
CSS and SwiftUI outputs from `DESIGN.md`. Swift output checks require `swiftc`
and SwiftUI. Tests report a skip when an optional tool is not available.

## Boundaries

The prototype council checks static browser prototypes. It does not qualify a
native interface, assistive-technology behavior or outcomes with real people.
Use the target project's own standards and acceptance rules.

The scripts do not authorize external model use, model spend, network access or
publication. Confirm those choices before sending a brief, fixture or capture
to a service. Keep private project data out of public runs.

No license file is included. Public visibility does not grant redistribution
rights.
