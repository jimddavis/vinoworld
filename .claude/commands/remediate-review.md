# Remediate — Phase 0 Review Only

Run the Phase 0 review described in `.claude/project/remediation-agent-design.md` and stop. Produces a findings document and a bucket plan; makes no code changes.

Use this when you want to eyeball the findings before authorizing any remediation. Otherwise see `/remediate-run`.

## Step 1: Read the design

Before doing anything else, read in order:

1. `.claude/project/remediation-agent-design.md` — § 3 is the review-phase spec; § 3.9 is the canonical self-contained prompt this command executes.
2. `.claude/CLAUDE.md` and every file it references under `.claude/project/`.
3. The workspace-level `CLAUDE.md` (`~/work/AI/databricks/.claude/CLAUDE.md`) — already in your context as `claudeMd`, but re-confirm the sections that bear on the review (audit columns, write strategies, anti-patterns, hard constraints).
4. `docs/BACKLOG.md` if present.

Track which standards files you read and cite findings by file path + section.

## Step 2: Verify branch

Run `git branch --show-current` and `git status --short`. The review produces a markdown file under `claudedocs/` — fine to write from any branch since `claudedocs/` is outside `databricks_code/`. But if you're on `main`/`master`, propose a branch first.

## Step 3: Scope

Default scope (apply silently — no handshake needed):

```
databricks_code/libs/*.py
databricks_code/libs/*.ipynb
databricks_code/notebooks/**/*.ipynb
databricks_code/setup/*.ipynb
databricks_code/dashboards/*.lvdash.json
databricks_code/databricks.yml
```

Out of scope: markdown, `claudedocs/`, `.claude/`, `prompts/`, `data/`.

If `$ARGUMENTS` supplies an explicit scope override, use it instead.

## Step 4: Read files on disk (source-of-truth discipline)

- For every `.ipynb` file in scope, parse the JSON and read cell sources directly. Do not infer content from filenames or prior reviews.
- Every "current content" block in a finding must be a verbatim quote you just read in this session.
- Locations must be verifiable (file path + cell # / line # / function name).
- Never trust git history, prior reviews, or memory as authority — they are context only.

## Step 5: Execute the review

Follow § 3.9 of the design document — the self-contained Phase 0 prompt block. It specifies the finding shape, severity tiers (P0/P1/P2/P3), categories, bucket-plan structure, parked-vs-actionable handling, and ambiguity protocol.

**Hard rule:** on any ambiguity (which standard applies, scope edge case, conflicting patterns), halt and emit `ASK: <question>`. Do not guess.

## Step 6: Write the findings document

Path: `claudedocs/code_review_<YYYY-MM-DD>.md` (today's date in the user's timezone).

If a file with that name already exists, suffix with a short run slug: `code_review_<YYYY-MM-DD>_<run-slug>.md`. Never overwrite.

Structure (per design § 3.6 and § 3.7):

- Front matter: standards files consulted, scope, file count reviewed.
- `## Findings` — `F-NN` entries grouped by severity (P0 first).
- `## Bucket plan` — coherent buckets, file overlap notes, severity priority.
- `## Parked — needs user decision` — findings requiring design decisions.

## Step 7: Report

Print a short summary to the user:

- Path of the findings document.
- Counts: findings by severity, buckets proposed, parked items.
- Any `ASK:` questions that came up during the review (these block remediation).

Stop. Do not start remediation — that's `/remediate-run`'s job.
