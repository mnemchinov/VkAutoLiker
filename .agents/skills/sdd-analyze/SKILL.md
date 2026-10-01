---
name: sdd-analyze
description: Read-only cross-artifact consistency analysis of spec.md, plan.md, tasks.md. Use after /skill:sdd-tasks, before implementation.
---

## User Input

```text
$ARGUMENTS
```

## Constraints

**STRICTLY READ-ONLY**. Do NOT modify any file. Output a report. Remediation
edits are offered but never applied automatically.

## Outline

1. **Resolve feature dir**. Require `spec.md`, `plan.md`, `tasks.md`.

2. Load all three + `CONSTITUTION.md` (if present).

3. **Build internal models**:
   - Requirements inventory (FR-### / SC-### keys)
   - User story → task mapping
   - Constitution rule set (MUST statements)

4. **Detection passes**:
   - **Duplication** — near-duplicate requirements
   - **Ambiguity** — vague adjectives, TODO markers
   - **Underspecification** — FRs without measurable outcomes
   - **Constitution alignment** — violations → CRITICAL
   - **Coverage** — FR/SC without tasks; tasks without source
   - **Inconsistency** — terminology drift, entity mismatch, conflicting tech

5. **Severity**:
   - **CRITICAL** — constitution violation, no-coverage FR blocking baseline
   - **HIGH** — duplicate/conflicting FR, ambiguous security/perf
   - **MEDIUM** — terminology drift, missing edge-case task
   - **LOW** — style, non-blocking redundancy

6. **Report** (max 50 rows, aggregate the rest):

   ```markdown
   ## Specification Analysis Report

   | ID | Category | Sev | Location | Summary | Recommendation |
   |----|----------|-----|----------|---------|----------------|

   ### Coverage Summary

   | Requirement | Has Task? | Task IDs | Notes |
   |-------------|-----------|----------|-------|

   ### Constitution Alignment Issues
   <list or "none">

   ### Metrics
   - Total FR / SC:
   - Total tasks:
   - Coverage %:
   - Ambiguity count:
   - Duplication count:
   - Critical issues:
   ```

7. **Recommend next step**:
   - CRITICAL exists → resolve before implementation.
   - Else → may proceed with improvement suggestions.

8. **Ask**: "Suggest concrete remediation edits for the top N issues?"
   — wait for explicit approval. Do NOT apply.
