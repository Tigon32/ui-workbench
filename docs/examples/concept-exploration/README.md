# What-council concept exploration example

This is a fully synthetic, local-only example. It does not run an agent,
provider, model review, or user study and contains no confidential fixture.
The canonical WHAT is the format-2 project intake; `exploration.json`
references its version and carries only comparison-specific directions and
input revisions.

The exploration is format 2; its canonical brief contains version-1 scope
intake. This fictional page example includes a sponsor quote/decision, current
capture references, KEEP evidence and per-direction coverage/dispositions.
Capture references are declarations, not actual screenshots or usability proof.
The component path omits views/journeys/domain artifacts and uses
`keep: {"none_reason": "No existing behavior is being replaced."}` when applicable;
it still requires sponsor confirmation and a component quality target.
Product scope requires all inventory captures, two cross-view journeys,
artifact paths/data classes or a none reason, and all three quality targets.
The shared validator never opens domain artifact paths.

For selection, extract eligible direction records to a JSON list, name them
exactly as the `round_prep.py prepare NAME=FOLDER` candidates, then pass
`--brief project-intake-v2.json --directions directions.json`. These files
become hash-bound scope evidence. Existing unscoped runs remain explicitly
legacy. A below-product result is never a new product interface.

The advisor, adversary and judge are represented as separate illustrative
roles. The example flags an unsourced layout prescription and reclassifies
it as an optional direction; it separately permits a sourced, authorized
semantic-token constraint. Its assumption remains exploratory. The
sponsor-owned goal is still open, so the resulting status must remain
`exploratory`, not accepted.

Two eligible directions share one brief, fixture, task list, constraints,
platform declaration and rubric. The qualitative comparison describes
different information architectures. A third, color-only variant is
explicitly excluded. `chronological-stream` does not assess the empty state,
which remains visible as unassessed. These declarations are examples, not
proof that the designs are creative or useful.

Validate without external services:

```sh
python3 .github/skills/what-council-exploration/what_council.py validate \
  --brief docs/examples/concept-exploration/project-intake-v2.json \
  --exploration docs/examples/concept-exploration/exploration.json
```

Use eligible directions as the shared inputs to the existing
[`ui-prototype-council`](../../../.github/skills/ui-prototype-council/SKILL.md)
selection loop. After that loop selects a candidate, start its existing
format-2 refinement ledger from the same canonical brief; do not infer a
selection or acceptance from this example. The example has no adoption
threshold beyond the illustrative values already present in its brief.

The validator reports versions, source references, unassessed states,
findings and evidence kinds. It cannot verify source truth or authority
authenticity. A `preflight` result records an authorization attestation only;
it never performs the external action.
