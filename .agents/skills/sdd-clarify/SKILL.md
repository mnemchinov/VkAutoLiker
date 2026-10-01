---
name: sdd-clarify
description: Reduce ambiguity in the active feature spec by asking up to 5 targeted questions and recording answers inline. Use after /skill:sdd-specify, before /skill:sdd-plan.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Resolve feature dir**. Require `spec.md`.

2. Load: `spec.md`, `CONSTITUTION.md` (if present).

3. **Scan spec against taxonomy** — Clear / Partial / Missing:
   - Functional scope & success criteria
   - Domain & data model
   - Interaction / UX flow
   - Non-functional (perf, security, observability)
   - Integration & external dependencies
   - Edge cases & failure handling
   - Constraints & tradeoffs
   - Terminology consistency
   - Completion signals

4. **Generate up to 5 questions** — highest `impact × uncertainty` first.

   For each:
   - Line 1: `**Question:** <interrogative ending with ?>?  (FR-XXX)`
   - Line 2: `**Why it matters:** <one plain-language sentence>`
   - If multiple choice: `**Recommended:** Option X — <rationale>` + table A-E
   - If short-answer: `**Suggested:** <answer> — <rationale>` + hint `Answer in ≤5 words.`

5. **Ask one question at a time.** Accept `"yes"`, `"recommended"`, `"suggested"`.
   Stop early on `"done"` / `"stop"` / `"proceed"`, or after 5 questions.

6. **After each accepted answer**, immediately:
   - Ensure `## Clarifications` exists with `### Session YYYY-MM-DD` subheading.
   - Append: `- Q: <question> → A: <answer>`
   - Update most relevant spec section:
     - FR ambiguity → edit/add FR bullet
     - Actor/role → User Scenarios
     - Data shape → Key Entities
     - Non-functional → add measurable SC
     - Edge case → Error/Edge Flows
     - Terminology → normalize across spec
   - If answer invalidates earlier text — replace it.
   - Write file immediately.

7. **Final validation**:
   - One bullet per accepted answer, no duplicates
   - Total asked ≤ 5
   - No leftover contradictions
   - Only permitted new headings: `## Clarifications`, `### Session YYYY-MM-DD`

8. **Report**: questions asked, sections touched, coverage summary, next step.
