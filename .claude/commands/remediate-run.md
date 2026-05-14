# Remediate — Full Workflow

Run the full remediation workflow described in `.claude/project/remediation-agent-design.md`: Phase 0 review → per-bucket fix loop with three gates → all buckets staged on branches awaiting user commits.

This command is the hands-off entry point. The agent self-paces through buckets and only halts on: ambiguity, gate failures past the retry cap, or escalation.

## Step 1: Read the design before doing anything else

Read in order:

1. `.claude/project/remediation-agent-design.md` — the whole document is load-bearing for this command. § 2 is the state machine. § 3 is Phase 0. § 4 is the fix-agent loop. § 5 is the critical reviewer. § 6 is the action log layout. § 7 is the git workflow. § 8 is escalation.
2. `.claude/CLAUDE.md` and every file referenced under `.claude/project/` (`environments.md`, `deviations.md`, `migrations.md`, `helpers.md`, `gotchas.md`).
3. `~/work/AI/databricks/.claude/CLAUDE.md` for the Databricks ETL standards.
4. `docs/BACKLOG.md` if present.

## Step 2: Resume detection

Check whether an open run exists:

```bash
ls claudedocs/remediation/ 2>/dev/null
```

If a `<date>_<slug>/` folder contains an unfinished bucket (no `bucket_report.md`), this is a resume. Read the latest `run_log.md`, identify the open bucket and the last completed gate, and continue from there. Skip Phase 0; the bucket plan in that run's referenced review is still authoritative.

If no open run, this is a fresh start — continue to Step 3.

## Step 3: Verify branch and working tree

```bash
git branch --show-current
git status --short -- databricks_code/
```

- Never run on `main`/`master`. If on either, propose a branch like `remediate/<YYYY-MM-DD>_<slug>` and ASK before continuing.
- `databricks_code/` must be clean OR all uncommitted changes under that path belong to this workflow. **Working-tree state outside `databricks_code/` is ignored** — `.claude/`, `claudedocs/`, `prompts/`, root-level files are tooling/notes, not in scope.
- If the branch name's intent doesn't match remediation (e.g. you're on a feature branch from earlier work), prefer to propose a new branch — but if the user has already authorized this branch as the parent, proceed.

Per-bucket branches are children of whatever branch you start from (the "parent branch"). Record the parent branch name in the run log — every bucket branches off it.

## Step 4: Create the run folder

```
<YYYY-MM-DD>_<HHmm>  # the run slug
claudedocs/remediation/<run-slug>/
  ├── run_log.md
  └── (bucket folders appear here)
```

Initialize `run_log.md` with the first line:

```
<UTC timestamp>  START  parent_branch=<branch>  scope=default
```

Every subsequent state transition appends a line (see design § 6.2 for the schema).

## Step 5: Phase 0 — Review

**First-run shortcut:** if this is the very first remediation run on this project (no `claudedocs/remediation/` directory previously existed) AND exactly one `claudedocs/code_review_*.md` file exists AND its date is today or yesterday, you MAY use it as the Phase 0 input. Otherwise — and on every subsequent run — generate a fresh review by following `/remediate-review`'s Step 1–6 (or invoke that command first).

Write the review to `claudedocs/code_review_<YYYY-MM-DD>.md` (suffix the run slug if a same-date file already exists).

Log: `<ts> PHASE0 findings written: <path> (<n> findings, <m> buckets, <p> parked)`.

If Phase 0 emits any `ASK:`, halt — do not proceed to buckets.

## Step 6: Workflow start — deploy + seed (runs ONCE)

Before bucket 1, prepare the test environment per design § 4.5 "Workflow start":

```bash
databricks bundle validate --target user
rm -rf .databricks/bundle/user/sync-snapshots/
databricks bundle deploy --target user
```

Then run `seed_volumes.ipynb` ad-hoc. It is NOT a bundle task — do not add it to `databricks.yml`. Submit a one-off notebook run:

1. Read the deployed notebook path via `databricks bundle summary --target user --output json`. The relevant field is the workspace root path for this target (e.g. `/Workspace/Users/<email>/.bundle/vinoworld/user`). The notebook lands at `<root>/files/setup/seed_volumes.ipynb`.
2. Read the target catalog from `databricks_code/databricks.yml` under `targets.user.variables.catalog` (or inherit from the default).
3. Submit:

   ```bash
   databricks jobs submit --json '{
     "run_name": "remediate-seed-volumes",
     "tasks": [{
       "task_key": "seed_volumes",
       "notebook_task": {
         "notebook_path": "<resolved deployed path>",
         "base_parameters": {
           "catalog": "<target catalog>",
           "shared_lib_path": "<workspace root>/files/libs"
         }
       },
       "environment_key": "Default"
     }],
     "environments": [{
       "environment_key": "Default",
       "spec": {"environment_version": "5"}
     }]
   }'
   ```

   If the `submit` subcommand isn't present, fall back to `databricks api post /api/2.1/jobs/runs/submit --json @body.json`.
4. Poll the run until terminal state. SUCCESS is required. A `dbutils.notebook.exit("skipped: target is production catalog")` is treated as success — that only fires when target is prod, which `--target user` is not.

Log the run id and outcome.

## Step 7: Per-bucket loop

For each bucket in the plan (P0 first, then P1, P2, P3), in order:

### 7a. Create the bucket branch

```bash
git switch <parent-branch>
git switch -c fix/<NN>-<slug>
```

If the bucket plan flagged this bucket as "chain after bucket N-1" (file overlap), branch off `fix/N-1-<slug>` instead — and require N-1 to be committed by the user first (halt and ASK if it isn't).

Log: `<ts> BUCKET_<NN>_START fix/<NN>-<slug>`.

### 7b. Apply fixes

For each finding in the bucket:

1. **Verify the finding still reproduces on disk.** Re-read the file. If resolved, record "skipped: resolved on disk" in `bucket_report.md` and continue.
2. **Read the closest sibling pattern** before writing the fix (CLAUDE.md § 2 prime directive).
3. **Apply via `Edit` / `NotebookEdit` / `Write`**. Re-read immediately to confirm.
4. **Hardcoded values for load-bearing strings → propose a constant** instead of typing the same string twice (CLAUDE.md § 4).
5. **On ANY ambiguity** (signature shape, helper choice, constant location, naming) → halt and emit `ASK: <question>`. Do not guess.

Stage with `git add <files>` — never `git add -A` / `git add .` — to keep the bucket scope-tight.

### 7c. Layer 1 — self-verification

Run every check in design § 4.6 against the bucket's staged diff. Write the verdict to `claudedocs/remediation/<run-slug>/bucket_<NN>_<slug>/self_verify.md` with explicit PASS/FAIL per check.

Any FAIL → fix it, re-stage, re-run § 7b/c. Counts toward the bucket's 3-attempt retry cap.

Log: `<ts> BUCKET_<NN> LAYER1 PASS|FAIL`.

### 7d. Deploy + test

Per design § 4.5 "Per-bucket":

```bash
databricks bundle validate --target user
rm -rf .databricks/bundle/user/sync-snapshots/
databricks bundle deploy --target user
databricks bundle run vinoworld_reset_pipeline --target user
databricks bundle run vinoworld_elt_pipeline --target user
```

For each `bundle run`, poll the parent run to terminal state, then call `databricks jobs get-run --run-id <id>` and verify every child task is `SUCCESS`. Any `FAILED` / `INTERNAL_ERROR` / `TIMEDOUT` is a test failure.

Capture every run id and per-task status into `bucket_<NN>_<slug>/test_run.md`.

Test-failure handling (design § 4.5):
- Caused by this bucket → fix, restart from § 7c. Counts toward retry cap.
- Pre-existing failure unrelated to this bucket → halt and ASK.
- Databricks transient (cluster start, workspace unavailable) → retry the affected job ONCE without consuming a bucket attempt. Second consecutive transient → halt and ASK.

Log: `<ts> BUCKET_<NN> bundle deploy SUCCESS deployment_id=...`, one line per job run with run id and outcome.

### 7e. Layer 2 — critical review (MANDATORY, every bucket)

1. Build the handoff packet per design § 5.6 and write it to `bucket_<NN>_<slug>/handoff_packet.md`. The packet must contain: bucket metadata, output path, verbatim Phase 0 finding entries, full `git diff <parent>..HEAD`, list of standards file paths, sibling family pointers, and explicit justifications for any intentional deviations.

2. Invoke the critical reviewer as an **isolated sub-agent** via the `Agent` tool. Prompt = design § 5.5 (the self-contained reviewer prompt) followed by the handoff packet contents. Important: do NOT include any fix-agent reasoning, prior verdicts, commit messages, or bucket-report prose. The sub-agent forms an independent judgment from primary sources.

   If the `Agent` tool is unavailable in the host, fall back to printing the prompt + packet to chat and asking the user to paste it into a fresh Claude Code thread.

3. Read the reviewer's output at `bucket_<NN>_<slug>/critical_review.md`. The first-line `Verdict:` is `PASS` or `DEFECTS FOUND`.

4. **DEFECTS FOUND** → fix every defect, re-run § 7c (Layer 1), § 7d (deploy + test), then re-invoke Layer 2 with a refreshed packet. The prior verdict is NOT included in the new packet — every Layer 2 invocation sees a clean slate. Counts toward retry cap.

Log: `<ts> BUCKET_<NN> LAYER2 PASS|DEFECTS_FOUND`.

### 7f. Bucket close

When all three gates are green:

1. Write `bucket_<NN>_<slug>/bucket_report.md` per design § 4.7.
2. Log: `<ts> BUCKET_<NN>_CLOSED retries=<n>`.
3. Leave the branch as-is with all changes staged. **Do not commit. Do not push. Do not delete the branch.** The user owns commits.
4. Switch back to the parent branch (`git switch <parent>`) for the next bucket.

Auto-advance to the next bucket.

## Step 8: Escalation

If any bucket hits the 3-attempt retry cap on any gate, halt and emit the escalation block from design § 8 with the four options (try again / park bucket / park bucket + dependents / hand off). Do not consume further attempts without user input.

If at any point an `ASK:` is raised that requires a user decision, halt and wait. Do not silently absorb ambiguity.

## Step 9: Run close

When every bucket is either closed or parked-via-escalation:

1. Write `claudedocs/remediation/<run-slug>/summary.md` per design § 6.3.
2. Log a final line: `<ts> RUN_CLOSED buckets_closed=<n> buckets_escalated=<m>`.
3. Print to chat: the path of the summary, a list of branches awaiting user commit, and any open `ASK:` questions still unanswered.

## Hard rules (do not violate)

- **Never commit, push, force-push, or delete branches.** The user owns all git history mutations.
- **Never modify files outside the current bucket's "files touched" list.** Drive-by edits are forbidden and fail Layer 1.
- **Never `git add -A` / `git add .` / `git stash`-pop without permission.** Named files only.
- **Never touch the prod catalog `vinoworld`** or any non-`user` bundle target. All testing is `--target user`.
- **`rm -rf` is authorized only against `.databricks/bundle/user/sync-snapshots/`.** Any other destructive shell action requires explicit per-action confirmation.
- **Never silently normalize a minority pattern to the majority** (CLAUDE.md § 3). Inconsistencies → halt and ASK.
- **On any ambiguity → halt and emit `ASK:`.** Guessing is forbidden and fails Layer 1.
