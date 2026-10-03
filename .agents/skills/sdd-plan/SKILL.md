---
name: sdd-plan
description: Generate technical design artifacts (plan, research, data model, contracts, quickstart) for the active feature. Use after /skill:sdd-clarify.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Resolve feature dir**. Require `spec.md`.

2. Load: `spec.md`, `CONSTITUTION.md` (if present), `AGENTS.md`.

3. **Fill Technical Context** — anything unknown → `NEEDS CLARIFICATION`.

4. **Constitution Check** — for each MUST article, verify plan complies.
   Violations → ERROR.

5. Generate artifacts:

   **`research.md`** — for each NEEDS CLARIFICATION:
   ```
   ## <topic>
   - Decision: <what>
   - Rationale: <why>
   - Alternatives considered: <what else>
   ```

   **`data-model.md`** (if data involved) — entities, fields, relationships,
   validation rules, state transitions.

   **`contracts/`** (if external interface exposed):
   - For VkAutoLiker: CLI commands, YAML config schema, SQLite schema.
   - Skip for pure internal changes.

   **`quickstart.md`** — prerequisites, setup, run commands, expected outcomes.
   No full code, no class bodies.

6. **Re-run Constitution Check** post-design.

7. **Write** all artifacts. Report paths.

## Plan Template

```markdown
# Plan: <feature title>

**Feature**: NNN | **Spec**: specs/NNN-slug/spec.md

## Summary

<1-2 sentences: approach, primary requirement>

## Technical Context

- **Language / Version**: Python 3.14
- **Dependencies**: <new deps or "existing requirements.txt">
- **Storage**: SQLite (`vk_autoliker.db`) / N/A
- **Testing**: pytest, markers `browser` / `live`
- **Target**: CLI / service / etc.
- **Constraints**: <from AGENTS.md>
- **Scale / Scope**: single-user personal automation

## Constitution Check

| Article | Compliant? | Notes |
|---|---|---|
| I. Account Safety | ✅ | All delays via random.uniform |
| II. API Boundary | ✅ | New calls via VKApiClient.call() |
| III. Data Integrity | ✅ | Dedup preserved |
| IV. Testing | ✅ | Mocks, no real network |
| V. Config & Secrets | ✅ | New fields in Settings |

## Project Structure

### New files
- `src/<new_service>.py` — <responsibility>
- `tests/test_<new_service>.py` — <what it tests>

### Modified files
- `src/settings.py` — new fields in Settings
- `src/liker.py` — wire new service into AutoLiker

## Phases

### Phase 0: Research
See `research.md`.

### Phase 1: Design
See `data-model.md`, `contracts/`, `quickstart.md`.

## Risks

- <risk> → <mitigation>
```
