# Skillset baseline

* Status: Initial migration
* Scope: Reusable interface design review and prototype selection for GitHub
  Copilot projects

## Source and coverage

The initial source is the `ui-prototype-council` skill in
`Tigon32/diskterrier` at revision `3aca484743836ca533b79d5133ca1dfcacbb73bd`.
This repository carries its entrypoint, four standard-library tools and focused
tests. The tools support a static browser prototype workflow with local Chrome.

`interface-design-review` is a portable adaptation of the source project's
bounded decision-review method, not a verbatim migration. It removes
product-specific paths, policies and cleanup authority. It prepares decisions
and deferrals. It does not implement a product.

| Need | Coverage | Limit |
|---|---|---|
| Resolve interface decisions before prototyping | `interface-design-review` | The target project's own rules remain authoritative |
| Reject deterministic prototype defects | Tier 1 and Tier 2 gates in `ui-prototype-council` | The rendered checks cover browser prototypes only |
| Compare surviving designs | Blind, calibrated reviewer scoring and a computed stop rule | A score does not establish user preference or usability |
| Generate matching CSS and SwiftUI tokens | `design_tokens.py` | The accepted `DESIGN.md` subset is limited and marked alpha |
| Prepare blind captures | `round_prep.py` | Requires installed Chrome; refuses non-empty blind directories and existing round metadata |

## Exclusions

Do not migrate DiskTerrier product decisions, UI requirements, prototypes,
fixtures, screenshots, reviewer records or project-specific authority rules.
The general build, writing and evidence-research skills are not UI-specific and
remain in their source project.

The skills do not authorize external model calls, data sharing, spend,
publication or implementation. The user and target project must authorize each
applicable action.

## Validation

The initial migration passed `python3 -m unittest discover -s tests` with 23 tests.
`test_ui_council.py` checks the bundled script digests. Local Markdown links were
checked. Browser and Swift checks depend on local tool availability. Those checks
do not qualify accessibility with assistive technology or real user outcomes.

## Design-quality extension

The [quality contract](design-quality-contract.md) records the subsequent council
and implementation for issues `Tigon32/ui-workbench#1` and `Tigon32/ui-workbench#2`.
The extension adds a default catalogue, absolute adoption gates, evidence rules,
target profiles and declared rendered checks. The initial four-tool description
above remains historical. The current skill also includes `profiles.py`.
