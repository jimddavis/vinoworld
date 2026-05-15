# In-flight migrations and forbidden strings

## In-flight migrations

A LIVING list. New code MUST use the new pattern. Do not "fix" new-pattern
code back to the old. Do not propagate the old pattern to new files.

Protocol for completing one: see § 5 of `CLAUDE.md`. When complete, remove
from this section and add the old-pattern tripwire to *Forbidden strings*
below.

_(none currently in flight)_

---

## Forbidden strings

Regression tripwires for COMPLETED migrations. Before declaring any task
complete, grep changed files for these strings. If found in NEW or MODIFIED
code, stop and fix.

This list grows as migrations finish; it never shrinks except by deliberate
decision.

### `/Workspace/Shared/`

- Old shared-helper path. Migration completed on the same branch as
  `CLAUDE.md`.
- **Replacement**: `%run "../../libs/notebook_init"` (or `"../libs/notebook_init"`
  from root-level notebooks). `notebook_init` self-discovers the libs folder
  from its own path. No full `/Workspace/...` path is hardcoded anywhere.
- **Where to check**: notebook markdown cells, Python comments, all `.py`
  and `.ipynb` files in `databricks_code/`.

### `sys.path.append("/Workspace/Shared")`

- Same migration. `notebook_init` and the two `spark_python_task` scripts
  (`init_pipeline_run_log.py`, `finalize_pipeline_run_log.py`) handle
  `sys.path` setup. Notebook code does not.

### `status = "running"`, `status = "succeeded"`, `status = "failed"` (string literals at assignment)

- Old: bare string literals. Migration completed on the same branch as
  `CLAUDE.md`.
- **Replacement**: the constants `STATUS_RUNNING`, `STATUS_SUCCEEDED`,
  `STATUS_FAILED`, `STATUS_NO_FILES` from `notebook_init`.
- **Where to check**: every notebook cell that assigns the `status` variable
  before calling `pipeline_step_log_upsert` or `transform_detail_log_insert`.

### Step-log close-out missing on success path

- Old: notebooks called `pipeline_step_log_upsert(... STATUS_RUNNING ...)` at
  start and only re-upserted on the failure path. The row stayed `'running'`
  forever on success. Migration completed 2026-05-13 (PR #13). Last two
  holdouts (`slvr_01`, `slvr_03`) closed during the remediation run.
- **Replacement**: every notebook that opens its step-log row with
  `STATUS_RUNNING` MUST also close it with a second `pipeline_step_log_upsert`
  call passing `STATUS_SUCCEEDED` and `ended_timestamp` on the success path.
  Multi-transform notebooks accumulate `rows_read` / `rows_written` across
  per-transform cells and pass the totals at close-out (see deviations.md).
- **Where to check**: every `databricks_code/notebooks/**/*.ipynb`. Tripwire:
  if a notebook contains `STATUS_RUNNING` it must also contain
  `STATUS_SUCCEEDED` (outside `%skip` cells).

---

## How to add a new forbidden string

When a global replacement completes, append here:

```
### `<forbidden string>`

- Old <what it was>. Migration completed on <date / branch>.
- **Replacement**: <the new pattern>.
- **Where to check**: <files / directories>.
```

Add it ONLY after the grep-then-replace-then-grep-again protocol from § 5
of `CLAUDE.md` has been completed and verified.
