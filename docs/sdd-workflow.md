# Specification-Driven Development Workflow

Status: Draft  
Last reviewed: 2026-04-30  
Scope: How this project will use specifications before and during implementation.

## Purpose

This project will use Specification-Driven Development (SDD), also called Specification-Driven Code in our project conversation, to keep product intent, constraints, code, and tests aligned.

The practical rule is simple: meaningful behavior changes start with an explicit specification. Code is implemented against that specification, and the specification stays current when the behavior, constraints, or design change.

## Source Material Reviewed

- Martin Fowler / Thoughtworks, "Understanding Spec-Driven-Development: Kiro, spec-kit, and Tessl", 2025-10-15: https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html
- GitHub Spec Kit documentation and repository, checked 2026-04-30: https://github.github.com/spec-kit/index.html and https://github.com/github/spec-kit
- Kiro Specs documentation, page updated 2026-02-18: https://kiro.dev/docs/specs/
- Tessl Spec-Driven Development documentation, checked 2026-04-30: https://docs.tessl.io/use/spec-driven-development-with-tessl

These tools are evolving quickly, so this project adopts the stable workflow ideas rather than binding itself to one tool.

## Working Definition

A spec is a structured, behavior-oriented Markdown artifact that describes what the software must do, why it matters, what constraints apply, and how success will be verified.

Specs are different from general project memory:

- Project memory describes durable context that applies to most work: product vision, architecture, conventions, deployment environment, safety rules, and technology choices.
- Feature specs describe a bounded capability or change: behavior, acceptance criteria, interfaces, edge cases, constraints, and tests.

## SDD Level For This Project

We will use a spec-anchored workflow.

- Spec-first: every meaningful feature or behavior change starts with a spec.
- Spec-anchored: the spec remains after implementation and is updated as the feature evolves.
- Not spec-as-source by default: humans and agents may edit code directly, but code changes must stay traceable to specs.

Spec-as-source may be reconsidered later for narrow generated components, but it is too restrictive for the initial project.

## Repository Structure

Recommended structure:

```text
docs/
  sdd-workflow.md          # This workflow
  project-context.md       # Durable project memory, created after project discussion
  architecture.md          # Durable architecture notes, created when architecture stabilizes
specs/
  project.spec.md          # Living product-level specification
  features/
    <feature-name>/
      requirements.md      # Functional behavior and acceptance criteria
      design.md            # Technical approach and constraints
      tasks.md             # Implementation checklist linked to requirements
```

For small changes, a single spec file is acceptable if it contains the same essential information. For larger features, split into requirements, design, and tasks.

## Standard Workflow

1. Intake

Capture the requested outcome, target users or systems, current assumptions, known constraints, and what must not change.

2. Clarification

If requirements are ambiguous, ask focused questions before writing code. Prefer one important question at a time when the answer affects behavior, safety, data, or architecture.

3. Specification

Create or update the relevant spec before implementation. The spec should describe observable behavior first. Technical design belongs in a design section or file after the required behavior is clear.

4. Review Gate

Implementation starts only after the spec is accepted for the current scope. Approval can be lightweight in conversation, but the accepted behavior must be reflected in the spec.

5. Planning

Break implementation into small tasks. Each task should link back to one or more requirements or acceptance criteria.

6. Implementation

Implement against the approved spec. If implementation reveals a wrong assumption, update the spec before continuing or record the question for review.

7. Verification

Verify that code, tests, and docs satisfy the accepted spec. Tests should trace to acceptance criteria where practical.

8. Closeout

Before a change is considered complete, update spec status, note any decisions made during implementation, and record remaining gaps or follow-up work.

## Spec Template

Use this structure for `specs/project.spec.md` and feature specs:

```markdown
# <Spec Name>

Status: Draft | Approved | Implemented | Superseded
Last reviewed: YYYY-MM-DD
Owner: <person or team>
Related code: <paths or TBD>
Related tests: <paths or TBD>

## Summary

What this system or feature is responsible for.

## Goals

- User-visible or system-visible outcomes.

## Non-Goals

- Explicitly excluded behavior.

## Users And Actors

- Human users, agents, services, hardware devices, or external systems.

## Functional Requirements

- Requirement IDs, e.g. `FR-001`.
- Observable behavior.
- Acceptance criteria, preferably in Given/When/Then form when it improves clarity.

## Constraints

- Hardware, runtime, network, safety, security, privacy, latency, reliability, cost, operational, and compatibility constraints.

## Interfaces

- APIs, commands, protocols, events, files, environment variables, or external services.

## Error Handling And Edge Cases

- Expected failures and required responses.

## Verification

- Tests, manual checks, smoke tests, hardware checks, or monitoring signals that prove the requirements are met.

## Open Questions

- Decisions needed before implementation or release.

## Change Log

- YYYY-MM-DD: What changed and why.
```

## Freshness Rules

The specification must be fresh enough to trust.

- Every spec has `Status` and `Last reviewed`.
- Any behavior-changing code change updates the relevant spec in the same work cycle.
- External facts that can change, such as dependency APIs, hardware support, security guidance, cloud limits, legal requirements, pricing, or release status, must be checked against current primary sources before being added.
- If a spec describes obsolete behavior, mark it `Superseded` or update it before implementing against it.
- If code and spec disagree, treat that as a defect until resolved.

## Proportionality Rules

Use the smallest workflow that preserves control.

- Trivial refactor or formatting: no new spec required if behavior is unchanged.
- Small bug fix: update the affected requirement or add a short bugfix note with current behavior, expected behavior, regression risk, and verification.
- Small feature: one focused spec file with requirements, constraints, and verification is enough.
- Medium or risky feature: use requirements, design, and tasks.
- Large or unclear feature: do discovery first, keep open questions explicit, and avoid implementation until the behavioral scope is accepted.

## Quality Gates

A spec is ready for implementation when:

- The requested behavior is observable and testable.
- Constraints and non-goals are explicit.
- Open questions do not block the planned implementation.
- Acceptance criteria cover common success paths and important failure paths.
- The verification approach is known.

A change is done when:

- Implementation matches the approved spec.
- Tests or documented checks verify the critical acceptance criteria.
- New constraints, edge cases, or decisions discovered during implementation are reflected in the spec.
- Remaining gaps are documented rather than hidden.

## Practical Guardrails

- Do not treat the spec as a long prompt dump. Keep it structured, reviewable, and current.
- Avoid excessive upfront design for small changes.
- Keep functional requirements separate from technical implementation choices.
- Prefer small iterative changes over large speculative plans.
- Do not rely on AI context alone for durable project knowledge. Put durable facts in specs or project memory.
- For hardware or home automation behavior, include safety constraints and manual verification steps.

## Next Project Step

Before implementation starts, create `specs/project.spec.md` through a requirements discussion. The first version should capture:

- Project purpose and target environment.
- Core functionality.
- Hardware and network constraints.
- Safety and security boundaries.
- Required interfaces and automations.
- Initial verification strategy.
