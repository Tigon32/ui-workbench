# UI Workbench

UI Workbench holds reusable GitHub Copilot skills for interface design work.
It separates design decisions from prototype selection. It does not contain a
product interface or project-specific design rules.

## Skills

| Need | Skill | Result |
|---|---|---|
| Resolve a design goal, a blocking choice or a needed deferral | [`interface-design-review`](.github/skills/interface-design-review/SKILL.md) | A bounded decision map with evidence, choices and deferrals |
| Select among interface prototypes | [`ui-prototype-council`](.github/skills/ui-prototype-council/SKILL.md) | Deterministic gate results and a computed selection outcome |

Use the review skill when requirements or constraints are not settled. Use the
prototype council only when the brief, fixture and rubric are ready. Neither
skill builds the product interface.

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
