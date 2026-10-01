---
name: sdd-specify
description: Create a new feature spec at specs/NNN-slug/spec.md from a natural language description. Use to start a new feature in the SDD workflow.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Generate slug** from input: 2-4 words, kebab-case, action-noun.
   - "add multi-account support" → `multi-account-support`
   - "fix captcha handling" → `fix-captcha-handling`

2. **Allocate feature number**:
   - Glob `specs/[0-9][0-9][0-9]-*` → take max NNN, next = max + 1
   - If none, start at `001`
   - Create `specs/NNN-slug/`

3. **Load context**: `CONSTITUTION.md` (if present), `AGENTS.md`.

4. **Fill spec** using the template below.

   Rules:
   - Max 3 `[NEEDS CLARIFICATION: ...]` markers, prioritized: scope > security > UX > tech.
   - Every FR must be testable.
   - Success criteria: measurable, technology-agnostic.
   - No implementation details (no classes, files, libraries).
   - User scenarios with explicit acceptance criteria.

5. **Write** `specs/NNN-slug/spec.md`.

6. **Validate inline**:
   - No implementation details leak
   - All mandatory sections filled
   - ≤3 `[NEEDS CLARIFICATION]` markers
   - Requirements testable and unambiguous
   - Success criteria measurable
   - Edge cases identified

7. **Report**: feature dir, spec path, remaining clarifications, next step.

## Spec Template

```markdown
# Feature: <title>

**Feature ID**: NNN | **Created**: YYYY-MM-DD | **Status**: Draft

## Overview

<2-3 sentences: what and why>

## User Scenarios

### Primary Flow
<actor> <does X> → <outcome>

### Alternative Flows
- ...

### Error / Edge Flows
- ...

## Functional Requirements

- **FR-001**: The system MUST ...
- **FR-002**: ...

## Non-Functional Requirements

- **NFR-001** (Performance): ...
- **NFR-002** (Security): ...

## Success Criteria

- **SC-001**: <measurable outcome>
- **SC-002**: ...

## Key Entities

<if applicable>

## Out of Scope

- ...

## Assumptions

- ...

## Open Questions

- [NEEDS CLARIFICATION: ...] (max 3)
```
