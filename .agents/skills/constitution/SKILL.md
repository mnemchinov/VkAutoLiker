---
name: constitution
description: Create or amend CONSTITUTION.md — project-wide invariants and governance. Use when formalizing rules or amending principles. Never for feature implementation.
---

## User Input

```text
$ARGUMENTS
```

Consider the input before proceeding.

## Scope Guard

Only write `CONSTITUTION.md`. Do NOT touch source code, tests, or feature artifacts.
If the input mixes constitution content with feature work — extract feature work into a
`## Next Actions` section and suggest `/skill:sdd-specify`, but do NOT execute it.

## Outline

1. Read `CONSTITUTION.md` if it exists. Read `AGENTS.md` for project invariants.

2. Extract governance principles. Classify:
   - Non-negotiable invariants → MUST / MUST NOT
   - Operational rules → SHOULD / SHOULD NOT
   - Recommendations → MAY

3. Assign version:
   - No file exists → `1.0.0`
   - Else SemVer bump: MAJOR (removed MUST) / MINOR (new MUST) / PATCH (wording).

4. Draft using the template below.

5. Validate:
   - No `[PLACEHOLDER]` tokens remain
   - Every article has a name + MUST/SHOULD statements
   - Dates are ISO YYYY-MM-DD

6. Write `CONSTITUTION.md`.

7. Report: version, bump rationale, TODO items, suggested commit message.

## Template

```markdown
# Project Constitution — VkAutoLiker

**Version**: X.Y.Z | **Ratified**: YYYY-MM-DD | **Last Amended**: YYYY-MM-DD

## Preamble

<1-2 sentences: what this governs, why it exists>

## Article I: Account Safety (MUST)

All automated actions MUST imitate human behavior.

- All delays MUST use `random.uniform(min, max)`. Fixed `time.sleep(...)` forbidden,
  except two documented exceptions (retry code 6, post-click pause).
- Daily and per-session limits MUST be enforced at two levels.
- Captcha MUST abort the session (`max_captcha_streak`), never bypassed.

**Rationale**: Violations risk permanent account ban.

## Article II: API Boundary (MUST)

All VK API calls MUST go through `VKApiClient.call()`.

- Direct `requests.*` in feature code forbidden.
- Rate limit (~3 req/sec) and error handling (codes 6, 14) non-negotiable.

**Rationale**: Centralizes throttling, retries, error classification.

## Article III: Data Integrity (MUST)

Every post MUST be deduplicated by `(owner_id, item_id)`.

- Successful, failed, errored attempts MUST be marked processed.
- `owner_id` for groups MUST be negative.

**Rationale**: Prevents repeated processing.

## Article IV: Testing (SHOULD)

Tests MUST NOT hit real network or real browser unless explicitly marked.

- `@pytest.mark.browser` for Chrome-dependent tests.
- `@pytest.mark.live` for real VK API.

**Rationale**: Unit tests must run without side effects.

## Article V: Configuration & Secrets (MUST)

- `config.yaml` MUST NOT be logged, echoed, or committed with real tokens.
- Test code MUST use placeholder values (`"test_token"`).

**Rationale**: Token leak compromises the account.

## Amendment Procedure

- Amendments require an explicit `/skill:constitution` run.
- Version bumps follow SemVer.
- Compliance verified by `/skill:sdd-analyze` and `@python-oop-reviewer`.
```

Adapt article set to actual invariants from AGENTS.md.
