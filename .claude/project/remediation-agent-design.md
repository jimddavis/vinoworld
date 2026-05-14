# Remediation Agent — Workflow Design

**Status:** design, not yet implemented. Consumed by `/sc:implement`.
**Source spec:** `prompts/debug-agnet.md`.
**Audience:** senior engineer revisiting in 3–12 months. Rationale is preserved
deliberately; if a paragraph reads as obvious to you, it isn't padding — it's
"why this and not the alternative."

---

## 1. Workflow overview

The workflow runs a project codebase through two phases:

- **Phase 0 — Review.** A review agent reads the project standards, scopes a
  set of source files, produces a structured findings document on disk, and
  proposes how findings should be grouped into remediation buckets.
- **Phase 1+ — Remediation.** A fix agent works one bucket at a time on a
  dedicated branch. After each bucket, three gates run in order: Layer 1
  internal self-verification, deploy-and-run testing on Databricks, and Layer 2
  critical review by an isolated fresh-thread reviewer agent. Buckets only
  close when all three pass. The user commits when satisfied; the agent never
  commits.

The workflow is **dependent on no testing framework** — verification is
runtime testing (deploy + run pipeline jobs + confirm success) plus
prose-driven critical review against project standards.

### 1.1 Why this shape

| Risk | Mitigation |
|---|---|
| LLM drift across a long remediation session | Bucket-gated execution: state resets between buckets; each bucket is small enough to hold in working memory. |
| Confirmation bias inside the fix agent | Layer 2 critical reviewer runs in an isolated context with **only the diff + standards + siblings + the original finding** — the fix agent's reasoning is not in the reviewer's prompt. |
| Half-migrated states | Branch-per-bucket isolates each change set; failed buckets abandon cleanly without touching siblings. |
| Drive-by edits ("while I'm in here…") | Layer 1 explicitly diff-attributes every changed line to a planned finding. Unattributed changes fail the gate. |
| Silent normalization to a wrong majority pattern | Critical reviewer's "pattern deviations" lens treats silent deviation as a defect, not a stylistic choice. |
| Re-fixing what's already fixed | Files-on-disk truth: each phase re-reads disk before deciding. If a finding no longer reproduces, it's skipped. |
| Stuck loops between fix and reviewer | 3-attempt cap per bucket, then escalate to user. |
| Test framework absent | Real deploy + real job run against the `user` target catalog `dev_vinoworld`. Empirical, not stubbed. |

### 1.2 Source-of-truth hierarchy (load-bearing)

Resolved top-down — when in conflict, higher wins.

1. **Files on disk** (parsed directly — `.ipynb` JSON, not prose, not memory).
2. **Project standards** — `.claude/CLAUDE.md` and the chain it references
   (`.claude/project/*.md`, `docs/BACKLOG.md`).
3. **Phase 0 review document** — a *guide to where to look*, not authority.
4. **Prior memory / prior conversations** — context only, never authority.

If a finding no longer reproduces on disk by the time remediation starts, it
is **resolved-on-disk** and skipped with a one-line note in the bucket report.

### 1.3 Hands-off vs. user gates

The user explicitly requested a hands-off design where the workflow flows
through buckets without per-bucket approval, BUT also requires that **every
proposed change set receive a secondary review** and that the agent **always
ask on any ambiguity**. The two combine as:

| Decision | Owner | Why |
|---|---|---|
| Phase 0 scope | Agent (default to standard scope) | Standard scope is stable across runs; deviation prompts a question. |
| Bucket plan | Agent proposes, no user gate | Auto-advance trusted. |
| Branch creation | Agent | Authorized in this session. |
| Code edits | Agent | Authorized. |
| Bundle validate / deploy / sync-snapshot reset / job run | Agent | Authorized in this session. |
| Critical review | Agent (mandatory, every bucket) | Hard requirement. |
| Auto-advance to next bucket | Agent (on all gates green) | Liberal trust. |
| `git commit` | **User only** | Hard requirement. |
| `git push`, merge, branch delete | **User only** | Hard requirement. |
| Resolving any ambiguity | **User** | Hard requirement. The agent halts and asks. |
| Resolving parked findings | **User** | Honored, not lobbied. |
| Escalation when retry cap hit | **User** | Hard requirement. |

---

## 2. State machine

```
                 ┌──────────────────────────┐
START ──────────▶│ scope confirmation       │
                 │ (silent if default scope) │
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ PHASE 0: Review          │
                 │   produces claudedocs/   │
                 │   code_review_DATE.md    │
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ bucket plan published    │
                 │ overlaps detected        │
                 └────────────┬─────────────┘
                              │
                              ▼
        ┌───────────────────────────────────────────────────┐
        │  FOR EACH BUCKET (sequential, no parallel)        │
        │                                                   │
        │   ┌──────────────────────────────────┐            │
        │   │ create branch fix/<n>-<slug>     │            │
        │   └──────────────┬───────────────────┘            │
        │                  ▼                                │
        │   ┌──────────────────────────────────┐            │
        │   │ fix agent: apply changes, stage  │            │
        │   └──────────────┬───────────────────┘            │
        │                  ▼                                │
        │   ┌──────────────────────────────────┐            │
        │   │ LAYER 1: self-verification       │            │
        │   │   - rubric checks                │            │
        │   │   - diff attribution             │            │
        │   └──────────────┬───────────────────┘            │
        │              fail│           pass                 │
        │           ┌──────┴─────┐                          │
        │           ▼            ▼                          │
        │   [retry or escalate]  │                          │
        │                        ▼                          │
        │   ┌──────────────────────────────────┐            │
        │   │ DEPLOY + TEST                    │            │
        │   │   bundle validate                │            │
        │   │   rm -rf sync-snapshots          │            │
        │   │   bundle deploy --target user    │            │
        │   │   run seed_volumes               │            │
        │   │   run 001-Truncate_All_Tables    │            │
        │   │   run pipeline orchestrator      │            │
        │   │   verify all tasks SUCCEEDED     │            │
        │   └──────────────┬───────────────────┘            │
        │              fail│           pass                 │
        │           ┌──────┴─────┐                          │
        │           ▼            ▼                          │
        │   [retry or escalate]  │                          │
        │                        ▼                          │
        │   ┌──────────────────────────────────┐            │
        │   │ LAYER 2: critical review         │            │
        │   │   isolated sub-agent             │            │
        │   │   produces critical_review.md    │            │
        │   └──────────────┬───────────────────┘            │
        │              fail│           pass                 │
        │           ┌──────┴─────┐                          │
        │           ▼            ▼                          │
        │   [retry or escalate]  │                          │
        │                        ▼                          │
        │   ┌──────────────────────────────────┐            │
        │   │ bucket closed, all changes       │            │
        │   │ staged on its branch, awaiting   │            │
        │   │ user commit                      │            │
        │   └──────────────┬───────────────────┘            │
        │                  │                                │
        │           more buckets? ─yes─► next bucket        │
        │                  │                                │
        │                  no                               │
        └──────────────────┼────────────────────────────────┘
                           ▼
                 ┌──────────────────────────┐
                 │ run summary written      │
                 │ user picks up commits    │
                 └──────────────────────────┘
```

**Retry path:** any gate failure → fix agent inspects the failure report, makes
a corrective pass, re-runs the failed gate **only**. Capped at 3 fix-agent
attempts per bucket (initial + 2 retries). 4th would-be-attempt → halt and
escalate.

**Ambiguity path:** at any state, if the current agent encounters real
ambiguity (multiple plausible patterns, finding scope unclear, standards
conflict), it halts and emits an `ASK:` block to the user. No silent
guessing — this is enforced in every persona's prompt.

---

## 3. Phase 0 — Review agent

### 3.1 Persona

**Role.** Senior reviewer doing static analysis against documented project
standards. Produces a findings document; does not edit code.

**Mindset.** Files on disk are truth. The reviewer reads `.ipynb` JSON,
`.py` source, `databricks.yml`, and `*.lvdash.json` directly. It does not infer
content from filenames, prior reviews, prose summaries, or memory. When it
quotes content, it has just read that content in this session.

**Discipline reminders embedded in the prompt:**
- A finding's "current content" field must be a verbatim quote from disk.
- A finding's location (file path + cell # / line # / function name) must be
  verifiable by re-reading the same file.
- If a finding only reproduces under a specific catalog/runtime/condition,
  state that condition explicitly.

### 3.2 Tools

- `Read` (notebooks, Python, YAML).
- `Bash` for `python3 -c "import json; ..."` to parse `.ipynb` cells.
- `Grep` for cross-file pattern detection.
- `Glob` for scope enumeration.
- `WebFetch` allowed for Databricks docs verification when a finding hinges on
  platform behavior (e.g., a runtime semantic the reviewer needs to confirm).

No `Edit`, `Write` against source files — only writes the findings document.

### 3.3 Scope

**Default scope** (applied silently — no confirmation handshake needed):

```
databricks_code/libs/*.py
databricks_code/libs/*.ipynb
databricks_code/notebooks/**/*.ipynb
databricks_code/setup/*.ipynb
databricks_code/dashboards/*.lvdash.json
databricks_code/databricks.yml
```

**Out of scope by default:**

```
claudedocs/
docs/
.claude/
prompts/
data/samples/
review_reports/
*.md anywhere in the repo
```

**Scope override:** if the user invokes the workflow with an explicit scope
argument, use it. If files outside scope are referenced by an in-scope file
(e.g., a notebook imports a lib), they are read for context but not reviewed.

### 3.4 Standards intake

Before producing any finding, the reviewer reads:

1. `.claude/CLAUDE.md` (project-level).
2. Every file referenced by `.claude/CLAUDE.md` via `@.claude/project/*.md`:
   `environments.md`, `deviations.md`, `migrations.md`, `helpers.md`,
   `gotchas.md`.
3. The workspace-level `CLAUDE.md` at `~/work/AI/databricks/.claude/CLAUDE.md`
   (loaded via `claudeMd` context).
4. `docs/BACKLOG.md` if present.

If a standards file references another file or external rule, follow the
chain. Track which standards were read; cite by file path + section in
findings.

### 3.5 Severity tiers

```
P0  — Defect that will fail at runtime or produce incorrect data.
      MUST be fixed.
P1  — Documented-rule violation (forbidden string, deviation, gotcha
      explicitly called out in standards). SHOULD be fixed in this pass.
P2  — Consistency / hygiene: sibling objects diverge without reason, dead
      code, copy-paste rot, inert debug scaffolding. Fix unless cost > value.
P3  — Documentation drift: stale comments, wrong cell numbers, scratch
      notes left in. Fix when adjacent code is touched anyway.
```

Tiers map to bucket priority — P0 buckets are first, P3 buckets are last.

### 3.6 Finding shape

Every finding is a section with:

```markdown
### F-<NN>. <one-line summary>

- **Severity:** P0 | P1 | P2 | P3
- **Location:** `path/to/file.ipynb` cell 3, `function_name`, lines 12–18
- **Current content:**
  ```python
  <verbatim quote from disk>
  ```
- **Rule violated:** `<standard file>:<section>` — quote the rule.
- **Risk:** what breaks or degrades if unfixed.
- **Suggested fix:** prose, optional code sketch. Not authoritative — fix
  agent decides the actual edit.
- **Status:** actionable | parked.
- **Park reason** (if parked): the open question or design decision required.
```

### 3.7 Bucket grouping

After enumerating findings, the reviewer proposes buckets:

```markdown
## Bucket plan

### Bucket 1 — <short slug, e.g. "logging-helper-signatures">
- **Findings:** F-03, F-07, F-11
- **Rationale:** all three are signature drift in `pipeline_logging.py`
  helpers; fixing them touches the same file and same helper family.
- **Files touched:** `databricks_code/libs/pipeline_logging.py` (callers
  unaffected — additive change).
- **Severity:** highest = P0 (F-03).
- **Estimated diff size:** small (~30 lines).
- **Overlap risk:** none — no other bucket touches this file.

### Bucket 2 — ...
```

**Grouping rules:**

1. One coherent concern per bucket. A bucket is "fix logging helper signature
   drift," not "improve libs."
2. Bucket size target: small enough that the diff fits in one review pass
   without paging — rough budget < 300 changed lines, < 8 files.
3. **File overlap:** if two buckets touch the same file, either (a) merge
   them, or (b) chain bucket B off bucket A's branch (sequential, not
   sibling). The reviewer flags overlap explicitly; the fix-agent honors it.
4. Bucket priority order: all P0 buckets, then P1, then P2, then P3.
5. Parked findings do not appear in buckets; they appear in a separate
   "Parked — needs user decision" section.

### 3.8 Output

Write to `claudedocs/code_review_<YYYY-MM-DD>.md` (today's date in user's
timezone). If a file with that name already exists, append a short suffix:
`code_review_<YYYY-MM-DD>_<run-slug>.md`. Never overwrite.

### 3.9 Phase 0 self-contained prompt (deliverable)

This block is the actual prompt the workflow embeds when invoking Phase 0.
It must run cold against any compliant project.

```
You are the Phase 0 review agent in a code-remediation workflow.

GOAL
Review the project codebase against its documented standards and produce
claudedocs/code_review_<TODAY>.md with structured findings and a bucket plan
for the remediation phase. Do not edit any source file.

SOURCE-OF-TRUTH DISCIPLINE
- Files on disk are truth. Read .ipynb files by parsing their JSON, not by
  guessing content from filenames or prose.
- Quote verbatim. Every "current content" block must be a real excerpt you
  just read in this session.
- Locations must be verifiable: file path + cell # (for .ipynb) or line #s
  (for .py/.yml/.json) + function/identifier name when applicable.
- Never trust git history, prior reviews, memory, or training data as
  authority — they are context only.

SCOPE
Default scope:
  databricks_code/libs/*.py
  databricks_code/libs/*.ipynb
  databricks_code/notebooks/**/*.ipynb
  databricks_code/setup/*.ipynb
  databricks_code/dashboards/*.lvdash.json
  databricks_code/databricks.yml
If a user-supplied scope override is provided as input, use it instead.
Out of scope: markdown, claudedocs/, .claude/, prompts/, data/.

STANDARDS TO CHECK AGAINST
Read in order:
  1. .claude/CLAUDE.md (project)
  2. Every file referenced by it under .claude/project/*.md
  3. The workspace-level CLAUDE.md if present in claudeMd context
  4. docs/BACKLOG.md if present
Follow any further references the standards make. Track which files you
read; cite findings by file path + section.

FINDING CATEGORIES (at minimum)
- Runtime / data-correctness defects.
- Documented-rule violations (forbidden strings, deviations, gotchas).
- Consistency and hygiene (divergent siblings, dead code, copy-paste rot,
  inert debug scaffolding).
- Documentation drift (stale comments, wrong cell numbers, scratch notes).

SEVERITY TIERS
P0 must-fix runtime/data defect.
P1 documented-rule violation.
P2 consistency/hygiene.
P3 documentation drift / cosmetic.

FINDING SHAPE
For each finding, produce a section:
  ### F-<NN>. <one-line summary>
  - Severity: P0|P1|P2|P3
  - Location: <path> cell <n> / lines <a-b> / <fn name>
  - Current content: ```<lang>
    <verbatim quote>
    ```
  - Rule violated: <standards file>:<section> — "<quote of the rule>"
  - Risk: <what breaks if unfixed>
  - Suggested fix: <prose, code sketch optional>
  - Status: actionable | parked
  - Park reason (if parked): <the open question>

BUCKET PLAN
After findings, produce a "## Bucket plan" section. Group actionable findings
into buckets of one coherent concern each. For each bucket:
  - Findings list (F-NN ids)
  - Rationale
  - Files touched
  - Highest severity in bucket
  - Estimated diff size (small / medium / large)
  - Overlap risk vs other buckets (note any shared files; propose merge or
    chain)
Order buckets P0 → P1 → P2 → P3.

PARKED SECTION
Findings that require a design decision rather than a mechanical fix go in
"## Parked — needs user decision". Surface the open question; do not decide.

AMBIGUITY PROTOCOL
If anything is unclear (which standard applies, scope edge case, conflicting
patterns) — halt and emit:
  ASK: <question>
Do not guess. The user resolves before you proceed.

OUTPUT
Write findings to claudedocs/code_review_<TODAY>.md. If that filename exists,
suffix with the run slug. Do not overwrite. Do not write anywhere else.

TONE
Senior engineer audience. Prose where prose is clearer, structure where
structure is clearer. No padding, no restatement of the obvious.
```

---

## 4. Phase 1+ — Fix agent

### 4.1 Persona

**Role.** Implementor. Takes a bucket and produces a staged diff on a
dedicated branch that resolves its findings without touching anything else.

**Mindset.** Match existing patterns exactly. Read the closest sibling
before writing the new code. On any ambiguity, halt and ASK — do not guess.
The fix agent's success metric is "diff that closes the bucket's findings,
attribution-complete, passes Layer 1 + deploy/test + Layer 2."

### 4.2 Tools

- `Read`, `Edit`, `Write`, `Bash`, `Grep`, `Glob`, `NotebookEdit` for source
  changes.
- `Bash` permissions used in this session:
  - `git checkout`, `git switch -c`, `git add`, `git status`, `git diff`,
    `git log`, `git stash` (creating staging boundaries).
  - **Authorized non-default**: `rm -rf .databricks/bundle/user/sync-snapshots/`.
  - **Authorized non-default**: `databricks bundle validate --target user`,
    `databricks bundle deploy --target user`,
    `databricks bundle run <task_key> --target user`.
  - `databricks jobs runs get`, `databricks jobs runs list` for verifying
    test outcomes.
- **Forbidden** without explicit per-action user approval:
  - `git commit`, `git push`, `git reset --hard`, `git rebase`, force operations.
  - `databricks bundle deploy --target prod` or any non-`user` target.
  - `rm -rf` against anything outside `.databricks/bundle/user/sync-snapshots/`.
  - Any operation against the prod catalog `vinoworld`.

### 4.3 Branch model

- One branch per bucket: `fix/<bucket-NN>-<slug>` (e.g.
  `fix/01-logging-helper-signatures`).
- All bucket branches branch from the parent branch the run started on
  (typically `main`, sometimes a feature branch).
- Buckets are siblings, NOT chained — unless the Phase 0 bucket plan
  explicitly flagged file overlap requiring chaining. In a chain, bucket N
  branches off bucket N-1's branch.
- The agent creates and switches to the branch. The agent never commits,
  never pushes, never deletes branches.

### 4.4 Per-bucket execution loop

```
1. read bucket plan from Phase 0 review
2. read the closest sibling pattern for the change (CLAUDE.md prime directive)
3. for each finding in the bucket:
     a. verify the finding still reproduces on disk (re-read the file)
     b. if resolved-on-disk → record "skipped: resolved on disk" in bucket
        report, continue
     c. apply the fix using Edit / Write / NotebookEdit
     d. immediately re-read the file to confirm the edit is correct
4. run git status and git diff to confirm changes are coherent and scoped
5. stage all bucket changes (git add)
6. produce the Layer 1 self-verification report (§ 4.6)
7. if Layer 1 fails → halt, fix, re-verify (counts toward retry cap)
8. run deploy + test pipeline (§ 4.5)
9. if deploy or test fails → halt, fix, re-verify (counts toward retry cap)
10. invoke Layer 2 critical reviewer (§ 5)
11. if Layer 2 returns defects → halt, fix, re-verify (counts toward retry cap)
12. write bucket report; advance to next bucket
```

### 4.5 Test protocol (deploy + run)

The bundle exposes these jobs (read from `databricks_code/databricks.yml`):

- `vinoworld_environment_setup` — provisions the catalog DDL.
- `vinoworld_elt_pipeline` — the end-to-end ELT pipeline (bronze → silver → gold + audit logging).
- `vinoworld_reset_pipeline` — dev-only reset: `truncate_all_tables` then `move_archive_to_bronze` (moves archived source files back into active Bronze volumes for re-ingestion).

`seed_volumes.ipynb` is **not** wired as a bundle task and the fix agent must
not modify the bundle to wire it. It is invoked ad-hoc only when needed (see
"workflow start" below).

**Workflow start — runs ONCE before bucket 1:**

```bash
# 1. validate
databricks bundle validate --target user

# 2. clean sync state
rm -rf .databricks/bundle/user/sync-snapshots/

# 3. deploy
databricks bundle deploy --target user

# 4. ensure user-catalog data volumes are seeded (idempotent).
#    seed_volumes is not a bundle task, so submit ad-hoc against the
#    deployed notebook path. Resolve the deployed path from `databricks
#    bundle summary --target user --output json` (workspace.file_path +
#    /setup/seed_volumes.ipynb).
databricks jobs submit --json '{
  "run_name": "remediate-seed-volumes",
  "tasks": [{
    "task_key": "seed_volumes",
    "notebook_task": {
      "notebook_path": "<resolved deployed path>",
      "base_parameters": {
        "catalog": "<catalog for target user>",
        "shared_lib_path": "<workspace.file_path>/libs"
      }
    },
    "environment_key": "Default"
  }],
  "environments": [{
    "environment_key": "Default",
    "spec": {"environment_version": "5"}
  }]
}'
#    wait for terminal state; verify SUCCESS. Notebook exits cleanly with
#    "skipped: target is production catalog" when CATALOG == vinoworld —
#    treat that as success, not failure.
#    Confidence: "submit" subcommand shape — verify against `databricks
#    jobs --help` at runtime; the underlying REST endpoint
#    POST /api/2.1/jobs/runs/submit is stable. Fall back to
#    `databricks api post /api/2.1/jobs/runs/submit --json @body.json` if
#    the high-level subcommand isn't present.
```

**Per-bucket — runs after Layer 1, before Layer 2:**

```bash
# 1. validate
databricks bundle validate --target user

# 2. clean sync state (required after refactors that rename or move files;
#    cheap to do every time)
rm -rf .databricks/bundle/user/sync-snapshots/

# 3. deploy
databricks bundle deploy --target user

# 4. reset data state via the bundle's reset job
databricks bundle run vinoworld_reset_pipeline --target user
#    verify: parent run SUCCESS and both child tasks SUCCESS
#    (truncate_all_tables, move_archive_to_bronze). All tables empty;
#    archived files moved back to the active Bronze volume paths.

# 5. run the full pipeline
databricks bundle run vinoworld_elt_pipeline --target user
#    verify: parent run SUCCESS and every child task SUCCESS.
#    Use `databricks jobs get-run --run-id <id>` to read each task state.
#    Any task in FAILED / INTERNAL_ERROR / TIMEDOUT state is a test failure.

# 6. capture all run ids and per-task statuses into the bucket's test_run.md
```

**Test failure handling:** if a task FAILED, the fix agent reads the failure
detail (stderr / exception trace) and decides:

- **Failure caused by this bucket's change** → fix, re-run from step 1.
  Counts toward retry cap.
- **Pre-existing failure unrelated to this bucket** (verifiable by checking
  git diff against parent branch) → halt and ASK. Do not silently absorb a
  pre-existing breakage into this bucket.
- **Infrastructure / Databricks transient** (e.g. cluster failed to start,
  workspace temporarily unavailable) → retry the affected job ONCE without
  counting toward bucket retry cap. Second consecutive transient → halt and
  ASK.

**Why this shape:**

- The user catalog is seeded once per workflow run; subsequent buckets re-use
  the seeded volumes. `seed_volumes` is itself idempotent (only copies files
  missing from the target's active root), so re-running it is safe but
  unnecessary.
- `vinoworld_reset_pipeline` is the canonical reset path defined by the
  bundle and handles both halves of "clean state": truncate the managed
  tables, then move archived source files back into the active Bronze volume
  paths so the pipeline has files to ingest.
- This avoids modifying `databricks.yml` to wire `seed_volumes` as a task —
  the fix agent's scope is bug remediation, not bundle authoring.

### 4.6 Layer 1 self-verification rubric

The fix agent writes `claudedocs/remediation/<run-id>/bucket_<NN>_<slug>/self_verify.md`
with each of the following as an explicit "PASS" or "FAIL: <reason>".

**A. Diff attribution.**
For every changed line in the bucket's `git diff`, name which finding (F-NN)
authorizes it. Any unattributed change → FAIL.

**B. Standards conformance (mechanical checks).**
Run these against changed files only:

- Three-part table names everywhere referenced. `grep -E '\bspark\.table\("[^.]+\."` against changed files should find no two-part names.
- No `inferSchema=True` in any changed cell.
- No `monotonically_increasing_id()` used as a surrogate key.
- No `datetime.now()` used as a DataFrame column value (only as Python audit
  values).
- No `df.collect()` / `df.toPandas()` against any DataFrame that isn't
  visibly bounded (a `.limit(N)` upstream).
- No path-based Delta read/write (`spark.read.load("/...")`, `df.write.save("/...")`).
- No `/dbfs/` paths.
- No hardcoded catalog/schema/table strings repeated in more than one cell of
  a notebook (must be a constant).
- `except dbutils.NotebookExit: raise` appears before `except Exception:` in
  every notebook try/except chain that calls `dbutils.notebook.exit`.
- Audit columns present in every Bronze/Silver/Gold write (`inserted_ts`,
  `updated_ts` where applicable, `run_id`, `source_file_path`).
- Row-count assertion present after every write.
- For DDL touched: `NOT NULL` columns are populated by the writing function;
  `GENERATED ALWAYS AS IDENTITY` columns are NOT in the `StructType`.

**C. Forbidden strings.**
`grep` changed files for every entry in `.claude/project/migrations.md`
"forbidden strings". Any hit → FAIL.

**D. Helper usage.**
For each new function or block of inline logic, check
`.claude/project/helpers.md` for a canonical helper that covers the same
ground. If one exists and was not used → FAIL.

**E. Deviations honored.**
For each pattern in `.claude/project/deviations.md`, check that the changed
code follows the project deviation (not the upstream best practice). FAIL on
any silent "fix" of a deliberate deviation.

**F. Scope.**
No file modified outside the bucket's "files touched" list from Phase 0. No
file modified outside the standard scope from § 3.3.

**G. Notebook hygiene (when notebooks are touched).**
- No table name or path string appears in more than one cell.
- No import appears more than once across cells.
- `%skip` cells used for debug code; no commented-out inline blocks.
- Step log updated to `STATUS_SUCCEEDED` exactly once per success path.
- Source files archived after a successful write.

**H. Ambiguity log.**
Did the fix agent encounter any ambiguity during this bucket? List them. If
any were resolved by guessing (not by asking the user), the bucket FAILS
Layer 1 — guessing is forbidden.

If any check is FAIL, the fix agent corrects and re-runs Layer 1 (counts
toward retry cap).

### 4.7 Bucket report (at bucket close)

After all three gates pass, the fix agent writes
`claudedocs/remediation/<run-id>/bucket_<NN>_<slug>/bucket_report.md`:

```markdown
# Bucket <NN> — <slug>

- **Branch:** fix/<NN>-<slug>
- **Parent branch:** <branch the run started from>
- **Findings addressed:** F-03, F-07, F-11
- **Findings skipped (resolved-on-disk):** F-09 (note: file already at
  canonical pattern when verified at <timestamp>)
- **Files touched:**
  - databricks_code/libs/pipeline_logging.py (+18 -12)
  - databricks_code/libs/pipeline_utils.py (+4 -0)
- **Layer 1:** PASS (see self_verify.md)
- **Test runs:**
  - seed_volumes: run <id> SUCCESS
  - truncate_all_tables: run <id> SUCCESS
  - pipeline_orchestrator: run <id> SUCCESS (12/12 tasks SUCCEEDED)
- **Layer 2:** PASS (see critical_review.md)
- **Retry count:** 0 (clean first pass)
- **Diff summary:** <2–3 sentences on what changed and why.>
- **Next:** awaiting user commit on branch fix/<NN>-<slug>.
```

---

## 5. Layer 2 — Critical review

### 5.1 Why isolated

The fix agent's reasoning, intuitions, and self-justifications are
unreliable witnesses to its own correctness. The critical reviewer must
form an independent judgment from primary sources:

- the diff,
- the standards,
- relevant siblings,
- the original Phase 0 finding(s).

That's it. No fix-agent prose, no commit messages, no bucket report. The
reviewer asks "is this diff correct, conforming, and consistent?" without
being primed with the fix agent's answer.

### 5.2 Mechanism

The fix agent invokes the critical reviewer via the `Agent` tool with a
self-contained prompt (§ 5.5) and a handoff packet (§ 5.6). The sub-agent
inherits **none** of the fix agent's conversation context.

**Fallback if the Agent tool is unavailable in some host:** the fix agent
prints the prompt + packet to chat, halts, and asks the user to paste it
into a fresh Claude Code thread, then paste the verdict back. Slower but
preserves isolation.

### 5.3 Critical reviewer persona

**Role.** Adversarial reader. Trusts nothing it wasn't given as primary
source. Produces a markdown verdict at
`claudedocs/remediation/<run-id>/bucket_<NN>_<slug>/critical_review.md`.

**Mindset.** Short and declarative if clean; detailed and specific if not.
The reviewer documents defects; it does **not** propose fixes — a later
fix-agent pass handles remediation.

### 5.4 The four lenses

**Lens 1 — Assumption audit.**
For each non-trivial change in the diff, name what the fix took for granted.
Examples of bad assumptions:
- "the table already has this column" without verifying the DDL,
- "the caller always passes a non-null value" without checking call sites,
- "Spark coerces this implicitly" without verifying the runtime semantic.
Any unverifiable assumption → defect.

**Lens 2 — Standards conformance.**
Walk through the changed code citing specific standards by file path +
section. Quote the rule. Quote the code. Show the match (or mismatch). This
is the most mechanical lens.

**Lens 3 — Cross-object consistency.**

Procedure (concrete, not vague):
1. For each function or block touched, identify its **sibling family**:
   other functions in the same file that share its role (e.g.
   `pipeline_step_log_upsert` siblings are the other `*_upsert` and `*_insert`
   functions in `pipeline_logging.py`), or other notebooks in the same layer
   (`brz_*.ipynb` siblings are the other `brz_*.ipynb` files).
2. Read at least one sibling end to end.
3. Compare on these axes:
   - Function signature shape (positional vs keyword, parameter order,
     defaults).
   - Error handling (try/except shape, what gets logged, what gets re-raised).
   - Audit column composition.
   - Status string choice (constants vs literal).
   - Helper usage (`Utils.*`, `pipeline_logging.*`).
   - Naming (case, separators, suffixes).
4. Any divergence from siblings without an explicit justification in the
   handoff packet → defect ("silent deviation").

**Lens 4 — Pattern deviations.**

Read `.claude/project/deviations.md`. For each deviation listed there, check
whether the diff respects it or "fixes" it. Silent deviation fixing is the
classic failure mode — flag as a defect even if the new code matches
upstream best practice.

Then, for any pattern in the diff that doesn't match `.claude/project/deviations.md`
**or** the standard from `~/work/AI/databricks/.claude/CLAUDE.md`: name the
pattern, name the source it does or doesn't match, and decide:
- **defect** if it's an unjustified deviation, or
- **justified** if the handoff packet contains explicit reasoning that
  satisfies the reviewer.

### 5.5 Critical reviewer self-contained prompt (deliverable)

```
You are the Layer 2 critical reviewer in a code-remediation workflow.

YOU HAVE NO PRIOR CONTEXT. The fix agent's reasoning is deliberately not in
your conversation. You see only this prompt and the handoff packet appended
below. Form an independent judgment from primary sources.

YOUR JOB
Read the diff in the handoff packet. Read the relevant project standards.
Read at least one sibling object per changed function/notebook. Produce a
markdown verdict at the path specified in the packet. Document defects;
do NOT propose fixes — a later step handles remediation.

THE FOUR LENSES
Apply each in order. Be specific. Cite primary sources verbatim.

LENS 1 — ASSUMPTION AUDIT
For each non-trivial change, name what it took for granted (DDL state,
caller behavior, runtime semantics, library invariants). Verify or mark
"unverifiable from packet — defect".

LENS 2 — STANDARDS CONFORMANCE
For each standards file in the packet, walk through the changed code and
cite specific rules (file:section). Quote the rule. Quote the code. Note
PASS or FAIL with one line of evidence.

LENS 3 — CROSS-OBJECT CONSISTENCY
For each changed function/notebook:
  1. Identify its sibling family.
  2. Read at least one sibling end to end.
  3. Compare: signature shape, error handling, audit columns, status
     constants, helper usage, naming.
  4. Note any divergence. Silent divergence = defect.

LENS 4 — PATTERN DEVIATIONS
Read .claude/project/deviations.md. Check that the diff respects each
listed deviation (does not "fix" it to upstream best practice). Then check
the diff for unjustified deviations from standards. Each must be either
defect or justified-by-packet.

OUTPUT FORMAT
Write a single markdown file to the path in the packet:

  # Critical review — bucket <NN> <slug>
  - **Verdict:** PASS | DEFECTS FOUND
  - **Lens 1 — Assumption audit:** <findings>
  - **Lens 2 — Standards conformance:** <findings>
  - **Lens 3 — Cross-object consistency:** <findings>
  - **Lens 4 — Pattern deviations:** <findings>
  - **Defects (if any):** numbered list, each with file path, line(s),
    rule violated (cite source), and one sentence on why it's wrong.
  - **Notes for the next reviewer pass:** anything you couldn't verify and
    deferred to the human reader.

TONE
Senior engineer audience. Short and declarative if clean. Detailed and
specific if defects exist. No padding.

AMBIGUITY
If the packet is missing something you need to render judgment (a sibling
file, a standards reference, the DDL of a touched table), emit:
  ASK: <what's missing>
and stop. Do not guess.

--- HANDOFF PACKET FOLLOWS ---
```

### 5.6 Handoff packet schema

The fix agent assembles and appends below the prompt above:

```markdown
## Bucket
- ID: <NN>
- Slug: <slug>
- Branch: fix/<NN>-<slug>
- Parent branch: <parent>

## Output path
claudedocs/remediation/<run-id>/bucket_<NN>_<slug>/critical_review.md

## Findings being addressed
(verbatim copies of F-<NN> sections from the Phase 0 review,
including suggested fix prose)

## Diff
```diff
<output of `git diff <parent>..HEAD` against changed files>
```

## Standards files in scope
List of absolute paths. Reviewer reads these directly:
- .claude/CLAUDE.md
- .claude/project/deviations.md
- .claude/project/migrations.md
- .claude/project/helpers.md
- .claude/project/gotchas.md
- ~/work/AI/databricks/.claude/CLAUDE.md

## Sibling families
For each changed function/notebook, list at least one sibling absolute path
the reviewer should read for consistency comparison:
- changed: databricks_code/libs/pipeline_logging.py::pipeline_step_log_upsert
  sibling: databricks_code/libs/pipeline_logging.py::ingestion_log_insert

## Justifications for any intentional deviations
(if the fix deliberately diverges from a sibling or from a documented
pattern, explain here — silent deviation otherwise becomes a defect)
None / <list>
```

The packet is plain-text markdown, written into the bucket folder as
`handoff_packet.md`, then passed to the sub-agent invocation as the prompt
suffix.

### 5.7 Retry on defects

If Layer 2 returns DEFECTS FOUND, the fix agent reads the verdict, corrects
each defect, re-runs Layer 1, re-runs deploy + test, and re-invokes Layer 2
with an updated packet (the diff is fresher; the prior verdict is **not**
included — every Layer 2 invocation sees a clean slate to avoid anchoring).

The retry counts toward the bucket's 3-attempt cap.

---

## 6. Action log

### 6.1 Location

```
claudedocs/
├── code_review_<YYYY-MM-DD>.md            ← Phase 0 output (spec-required)
└── remediation/
    └── <YYYY-MM-DD>_<run-slug>/           ← one folder per workflow run
        ├── run_log.md                     ← append-only chronological log
        ├── bucket_01_<slug>/
        │   ├── plan.md
        │   ├── self_verify.md             ← Layer 1
        │   ├── test_run.md                ← deploy + run results
        │   ├── handoff_packet.md          ← what went to Layer 2
        │   ├── critical_review.md         ← Layer 2 output
        │   └── bucket_report.md           ← bucket close
        ├── bucket_02_<slug>/
        │   └── ...
        └── summary.md                     ← final run summary
```

`<run-slug>` is a short token, e.g. derived from the first bucket's slug or
a 4-char random suffix. Multiple runs in one day get distinct slugs.

### 6.2 What goes in `run_log.md`

Append-only, timestamped lines. Captures the operator-visible state
transitions so a reader six months later can reconstruct what happened
without scrolling through the conversation transcript.

```
2026-05-12 14:03:12  START  scope=default  parent_branch=main
2026-05-12 14:03:12  PHASE0  reading standards (5 files)
2026-05-12 14:08:44  PHASE0  findings written: claudedocs/code_review_2026-05-12.md (23 findings, 6 buckets, 2 parked)
2026-05-12 14:08:51  BUCKET_01_START  fix/01-logging-helper-signatures
2026-05-12 14:08:52  BUCKET_01  branch created from main
2026-05-12 14:11:30  BUCKET_01  3 files edited, 18 lines changed
2026-05-12 14:11:45  BUCKET_01  LAYER1 PASS
2026-05-12 14:11:50  BUCKET_01  bundle validate PASS
2026-05-12 14:11:55  BUCKET_01  sync-snapshots reset
2026-05-12 14:12:30  BUCKET_01  bundle deploy SUCCESS deployment_id=abc123
2026-05-12 14:13:15  BUCKET_01  run seed_volumes SUCCESS run_id=778822
2026-05-12 14:14:02  BUCKET_01  run truncate_all_tables SUCCESS run_id=778830
2026-05-12 14:21:48  BUCKET_01  run pipeline_orchestrator SUCCESS run_id=778850 (12/12 tasks)
2026-05-12 14:22:00  BUCKET_01  LAYER2 invoked (sub-agent)
2026-05-12 14:25:14  BUCKET_01  LAYER2 PASS
2026-05-12 14:25:15  BUCKET_01_CLOSED  retries=0
2026-05-12 14:25:15  BUCKET_02_START  ...
```

Every gate result and every job run id appears here. Failure paths log
the failure reason as a one-line summary plus a pointer to the relevant
artifact in the bucket folder.

### 6.3 `summary.md`

Written when all buckets close (or on early termination). Contents:
- Total buckets attempted / closed / escalated.
- Findings addressed vs parked vs skipped-resolved-on-disk.
- Branches left awaiting user commit.
- Any open ASK questions still unanswered.
- Total elapsed time and total retry count across buckets.

---

## 7. Git workflow

| Action | Who | Notes |
|---|---|---|
| Create branch | Agent | `git switch -c fix/<NN>-<slug>` from parent. |
| Edit files | Agent | Confined to the bucket's "files touched" list. |
| Stage files | Agent | `git add` named files only — never `git add -A` or `git add .`. |
| Commit | **User** | Agent never commits. Branch sits with staged-or-working changes. |
| Push | **User** | |
| Merge / fast-forward | **User** | |
| Delete branch | **User** | |
| Switch back to parent for next bucket | Agent | `git switch <parent>` before creating the next sibling branch. Working tree must be clean — if not, halt and ask. |

**Staging strategy at bucket close:** the agent runs `git add <files>` for
each file in the bucket so the user sees a coherent staged set, then runs
`git status` and `git diff --staged` and embeds the output in
`bucket_report.md` so the user can review before committing.

**Branches that overlap files** (per Phase 0 detection):
- Either the buckets are merged before execution (preferred), or
- Bucket N is chained: `git switch -c fix/N-<slug> fix/N-1-<slug>` — N
  branches off N-1, not parent. This requires N-1 to be committed (or at
  least `git stash`-saved) before N starts. The agent halts and asks the
  user to commit N-1 before starting N in the chained case.

---

## 8. Escalation rules and retry cap

**Cap:** 3 total fix-agent attempts per bucket (initial + 2 retries).

**Retry triggers:**
- Layer 1 FAIL.
- Deploy or any test job FAIL (where root cause is attributable to the
  bucket's changes).
- Layer 2 DEFECTS FOUND.

**Out-of-cap events** (do NOT count toward the 3 attempts):
- Databricks transient failures (one free retry, see § 4.5).
- User-resolved ambiguity (the agent halted and asked; user answered; agent
  proceeds — no retry consumed).

**Escalation form** (when cap is hit):

```
ESCALATE: bucket <NN> failed gate <which> on attempt 3.

Last failure summary:
  <one-paragraph summary>

Artifacts:
  - claudedocs/remediation/<run-id>/bucket_<NN>_<slug>/...

Options:
  (a) I attempt a different approach (one more pass) — requires your go.
  (b) Park this bucket; I move to bucket <NN+1>.
  (c) Park this bucket AND its dependents; I close the run.
  (d) You take over.

Awaiting decision.
```

The agent halts at this point — no further state changes until the user
chooses.

---

## 9. Open questions

These are surfaced explicitly because they're judgment calls I made on the
user's behalf and may want to revisit:

1. **Full-pipeline test scope.** Every bucket triggers a full end-to-end
   pipeline run, even buckets that only touch (say) `gold/` notebooks.
   Justification: confidence > speed for a learning project; the orchestrator
   run is on serverless and bounded in cost. Revisit if elapsed time per
   bucket exceeds ~20 minutes consistently.

2. **First-run review reuse.** The user explicitly authorized using the
   existing `claudedocs/code_review_2026-05-12.md` as the Phase 0 input for
   the **very first** invocation. The implementation should detect "is this
   the first invocation?" cheaply — proposed heuristic: no
   `claudedocs/remediation/` directory exists yet AND only one
   `code_review_*.md` exists AND its date is today or yesterday. If
   ambiguous, ask.

3. **Seed scope and reset path (resolved).** `seed_volumes.ipynb` is not a
   bundle task and is invoked ad-hoc once at workflow start (§ 4.5) to
   ensure user-catalog volumes are populated. Per-bucket reset uses the
   wired `vinoworld_reset_pipeline` job (truncate + move_archive_to_bronze).
   The fix agent does not modify the bundle to wire seed_volumes — its
   scope is bug remediation, not bundle authoring.

4. **Branch chaining vs bucket merging on file overlap.** Default behavior:
   propose merging two overlapping buckets into one larger bucket if their
   combined diff still fits the size budget (~300 lines / 8 files). Only
   chain when merge would exceed the budget. Implementation should prompt
   the user with both options when overlap is detected, since this is a
   judgment call.

5. **Concurrent ambiguity vs auto-advance.** If a bucket completes cleanly
   but the agent surfaced an ASK during execution that the user has not yet
   answered, does it advance to the next bucket or wait? Proposed: advance,
   because the ASK is parked, not blocking. Unanswered ASKs are listed in
   `summary.md` for end-of-run resolution.

6. **Critical reviewer access to memory.** The sub-agent spawned via the
   `Agent` tool may still receive the same auto-memory context as any agent.
   For pure isolation, we'd want it without memory. Decision: accept the
   memory because it's general project context, not fix-agent reasoning;
   the isolation requirement is "no fix-agent prose", not "zero context".
   Revisit if the reviewer starts anchoring on memory entries.

---

## 10. Alternatives considered and rejected

**A. Single mega-agent does review + fix + self-review.**
Rejected. Self-review is unreliable. The whole point of Layer 2 is an
independent reading, and that requires context isolation. A single agent
cannot un-know what it just decided.

**B. Auto-commit per bucket on green gates.**
Rejected per user instruction ("no git commits until approved"). Also makes
recovery from "ship it, but I changed my mind" expensive — uncommitted
staged changes are trivially `git reset`-able; committed ones are not.

**C. Critical review only on user request (the original spec).**
Rejected per user override ("MUST have secondary review"). User overrode
the spec deliberately to enforce hands-off-but-thorough; mandatory Layer 2
is the resulting design.

**D. Per-finding (not per-bucket) execution.**
Rejected. Buckets are the natural unit of coherent change. Per-finding
execution multiplies branch churn and dilutes Layer 2's signal — a single
finding's diff is too small to assess consistency against siblings.

**E. Narrow per-bucket test scope (only run affected jobs).**
Rejected for now. Hard to determine "affected" correctly when changes touch
shared libs. Full-pipeline runs give the strongest signal and are not
prohibitively slow on serverless. Open Question 1 captures the revisit
trigger.

**F. Reviewer proposes fixes.**
Rejected. The reviewer's job is independent verdict; mixing proposal back
in re-creates the very feedback loop Layer 2 is meant to break. A later
fix-agent attempt handles remediation given the reviewer's verdict.

**G. Cumulative chained branches (every bucket off the previous bucket).**
Rejected as default. Siblings off the parent branch make per-branch review
clean and let the user merge in any order. Chained branches are an
escape hatch for the overlap case only.

**H. Allow `git commit` with a `commit_message_prefix` agreed up front.**
Rejected. The user explicitly retained commit authority; a "well, we agreed
in advance" workaround would undermine that. Asking each commit takes
seconds; getting it wrong takes minutes to undo.

**I. Skip the Phase 0 review and consume an existing markdown file every
run.**
Rejected. Phase 0 enforces files-on-disk truth as of the start of this run.
A stored review goes stale the moment any code changes. The first-run
shortcut (Open Question 2) is the narrow exception.

---

## 11. Implementation map

This design produces these artifacts when `/sc:implement` runs against it:

| Artifact | Purpose | Path |
|---|---|---|
| Review agent skill / slash command | Phase 0 trigger | `.claude/commands/remediate-review.md` (or skill equivalent) |
| Fix agent skill / slash command | Phase 1+ trigger | `.claude/commands/remediate-bucket.md` |
| Critical reviewer prompt | embedded in fix agent code path; also kept here in § 5.5 as the canonical version | (in code) |
| Phase 0 prompt | embedded in review agent code path; canonical version in § 3.9 | (in code) |
| Action log writer | helper used by both agents | (in code) |

`/sc:implement` chooses skill files vs slash commands vs agent personas as
fits the host. The design above is implementation-agnostic; the only hard
contracts are the file paths, the gate ordering, and the prompts.
