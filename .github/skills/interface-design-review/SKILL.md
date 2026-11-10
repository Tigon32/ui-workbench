---
name: interface-design-review
description: Clarify and stress-test a bounded interface design decision before implementation or prototype selection.
---

# Interface design review

Use this skill when the user requests a design interview or when an unresolved
interface decision blocks work. Do not use it to implement the interface.

## Set the scope

Name the goal, users, target platform and non-goals. Read the target project's
contributor rules, accepted decisions and relevant implementation. Separate
observed facts, accepted constraints, proposals and unknowns.

Do not reopen an accepted decision without new evidence or a changed
requirement. Keep the review within the requested design scope.

## Resolve facts before preferences

Use authorized read-only inspection to resolve questions about current source,
tools or behavior. Do not ask the user to discover facts that you can inspect.
Do not run a costly experiment or inspect private data to answer a preference.

If a required fact or authorization is missing, name it. Block only the
decision that depends on it. Continue independent work that does not depend on
the missing input.

## Ask bounded questions

Ask only material choices that remain open. Use the host's structured question
tool when available. State the main tradeoff and mark recommendations as
proposals, not accepted defaults.

Ask independent choices in the same round. Do not combine choices that depend
on each other. If an answer does not resolve the question, clarify it rather
than infer consent.

Stop when the scoped choices are settled, deferred or blocked by named input.
Do not interview indefinitely.

## Close the review

Record the goal, evidence, decisions, explicit deferrals and consequences. Use
the target project's existing decision record when one applies. Do not create a
new policy record for interview technique alone.

A review does not authorize implementation, external data sharing, model spend,
publication or other actions. Follow the target project's rules and obtain the
required user authorization before those actions.
