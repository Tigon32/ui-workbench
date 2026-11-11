# Refinement example

This is an owned synthetic fixture, not a measured product design.
The baseline and redesign are materially different page layouts. They use the
same expected text, desktop profile, themes, 320 CSS-pixel reflow check and
held-out error-state task. The example records one multi-dimension hypothesis
and a provisional keep. Its 8/9 scores are illustrative generator self-scores.
They are not independent review, human task results, accessibility evidence or
proof that a redesign is faster.

`iterations.json` is intentionally format 1: it is a compatibility example, not
the default for new ledgers. It retains its declared 9/10 and 80% target
without silently migrating the claim. New-project examples are
[`project-intake-v2.json`](project-intake-v2.json),
[`scope-map-v2.json`](scope-map-v2.json) and
[`attempt-v2-report.example.json`](attempt-v2-report.example.json). These are
synthetic excerpts; the tests create fully hash-bound local format-2 ledgers
and exercise incomplete briefs, overlapping scopes, task journeys, freshness,
decision authority, incompatible mappings and budget stops. No upload or model
call is required.

On 2026-11-11, these maintained synthetic fixtures were re-tokenised with sibling
`tokens.css` files. Computed styles, element geometry and text were unchanged in
96 before/after checks covering the existing themes, widths, forced colours and
error state. Source and dependent artifact hashes were regenerated bottom-up;
the old hashes are superseded. The format-1 scores, decisions and report meaning
are unchanged. These fixtures are not historical evidence.

Run the same deterministic checks on both pages from the repository root:

```sh
python3 .github/skills/ui-prototype-council/render_check.py \
  --rubric docs/examples/refinement/rubric.json \
  --expect docs/examples/refinement/expected.json \
  --tasks docs/examples/refinement/tasks.json \
  docs/examples/refinement/alternatives/baseline/index.html \
  docs/examples/refinement/alternatives/redesign/index.html
```

The recorded run used Chrome 157.0.8103.39. Both pages passed with zero
deterministic findings. The held-out task reached its error state in one click
against a one-click budget. Those are synthetic browser-check results, not
human outcomes.

Validate and report the bound ledger:

```sh
python3 .github/skills/ui-prototype-council/iterations.py verify \
  docs/examples/refinement/iterations.json
python3 .github/skills/ui-prototype-council/iterations.py report \
  docs/examples/refinement/iterations.json
python3 .github/skills/ui-prototype-council/iterations.py html \
  docs/examples/refinement/iterations.json --attempt 1 \
  --output refinement-attempt-1.html
```

The report selects all five declared points, including unassessed
accessibility. It records two of five points at the illustrative 9/10 goal;
four are required for 80%. The unassessed point stays in the denominator and
does not count as a 9. The report identifies this as an all-points claim, shows
two scored points below 9 and one unassessed selected point, the generator
reviewer kind, and an iteration-cap stop. Design elapsed time and review effort
are unknown. The recorded 1.68 seconds is renderer execution time only. No
adoption or independent review is claimed.

The HTML command produces a self-contained per-attempt report. Because this
synthetic compatibility ledger has no captures or visual annotations, the
report explicitly says so rather than drawing speculative arrows. Format-2
attempts can bind before/after PNG captures and their authored arrow
coordinates through `visual_ref`; see the
[refinement contract](../../design-quality-contract.md#machine-validated-iteration-ledger).

To declare real desktop browser zoom, add for example:

```json
"desktop_zoom": {"percentages": [100, 125, 150, 200]}
```

The profile validator records those as `real_browser_zoom` and `unavailable`;
the bundled renderer does not execute them. The independent 320 CSS-pixel
reflow check remains `css_viewport` evidence. A project that requires real zoom
must obtain that evidence separately. It must not relabel a CSS width or device
scale as browser zoom.
