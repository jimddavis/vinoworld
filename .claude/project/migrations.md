# In-flight migrations and forbidden strings

## In-flight migrations

A LIVING list. New code MUST use the new pattern. Do not "fix" new-pattern
code back to the old. Do not propagate the old pattern to new files.

Protocol for completing one: see § 5 of `CLAUDE.md`. When complete, remove
from this section and add the old-pattern tripwire to *Forbidden strings*
below.

### Step-log success close-out

- **Old**: `pipeline_step_log_upsert` called only at start (`status="running"`)
  and on failure. The success path never writes the close-out row, so the row
  sits as `'running'` forever even when the pipeline succeeds.
- **New canonical**: every notebook closes out its `pipeline_step_log` row
  with `STATUS_SUCCEEDED` and `ended_timestamp` on the success path,
  mirroring the `STATUS_FAILED` path.
- **Status**: bronze (4/4), `slvr_02`, `slvr_04`, `gold_01` migrated.
  `slvr_01_load_dim_fromcsv` and `slvr_03_load_dim_region` not yet migrated.
- **Rule for new notebooks**: MUST close out.
- **Old-pattern fixes**: in a dedicated branch, not opportunistically.

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
