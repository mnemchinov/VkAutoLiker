---
name: sdd-tasks
description: Generate an ordered, dependency-aware tasks.md for the active feature. Use after /skill:sdd-plan.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Resolve feature dir**. Require `spec.md` and `plan.md`.

2. Load: spec (FRs, SCs, user stories), plan (structure, files, phases),
   data-model (if exists), contracts (if exists), research (if exists),
   `CONSTITUTION.md` (if present).

3. **Generate tasks organized by user story.**

   Strict format — every task line:
   ```
   - [ ] T### [P?] [US#?] <imperative> in <exact file path>
   ```
   - `T###` — sequential, zero-padded, global
   - `[P]` — only if parallelizable (different file, no deps)
   - `[US#]` — only in user-story phases
   - File path required (except install/setup tasks)

4. **Phases**:
   - Phase 1: Setup (deps, scaffolding)
   - Phase 2: Foundational (blocking prerequisites for all stories)
   - Phase 3+: One phase per user story, in priority order (P1 first)
   - Final: Polish & cross-cutting

5. **Dependencies** — story completion order.

6. **Write** `specs/NNN-slug/tasks.md`.

7. **Report**: task count, per-story breakdown, parallel opportunities,
   MVP scope, format validation.

## Tasks Template

```markdown
# Tasks: <feature title>

**Feature**: NNN | **Spec**: spec.md | **Plan**: plan.md

## Phase 1: Setup

- [ ] T001 <task> in <path>
- [ ] T002 [P] <task> in <path>

## Phase 2: Foundational

- [ ] T003 <task> in <path>

## Phase 3: User Story 1 (P1) — <title>

**Independent test**: <criterion>

- [ ] T004 [US1] <task> in <path>
- [ ] T005 [P] [US1] <task> in <path>

## Phase 4: User Story 2 (P2) — <title>

...

## Phase N: Polish

- [ ] TXXX <task>

## Dependencies

- US1 → US2
- US3 independent

## MVP

Phase 1 + Phase 2 + US1 → shippable increment.
```
