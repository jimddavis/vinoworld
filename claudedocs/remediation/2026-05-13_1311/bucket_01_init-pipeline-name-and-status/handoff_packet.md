# Handoff packet — Bucket 01

## Bucket

- **ID:** 01
- **Slug:** fix-init-pipeline-name-and-status
- **Branch:** `fix/01-init-pipeline-name-and-status`
- **Parent branch:** `feat/remediation-agent-workflow`
- **Findings addressed:** P1-6, P1-7

## Output path for your verdict

Write your verdict to:

`claudedocs/remediation/2026-05-13_1311/bucket_01_init-pipeline-name-and-status/critical_review.md`

## Findings being addressed (verbatim from `claudedocs/code_review_2026-05-12.md`)

### P1-6. `init_pipeline_run_log.py` PIPELINE_NAME is a test value

- **File**: `databricks_code/libs/init_pipeline_run_log.py` L27.
- **Original content**:
  ```python
  PIPELINE_NAME     = "Vinoworld TEST LOAD"
  ```
- The literal pipeline_name written to every `pipeline_log` row in every target — `user`, `dev`, `staging`, `prod`, `azure_prod`. The `vw_pipeline_run_summary` view surfaces this string to anyone reading the audit dashboard.
- **Suggested fix**: rename to a durable name (`"vinoworld_elt_pipeline"` matches the bundle job key) — either as a module constant or via a third `sys.argv` from `databricks.yml`.

### P1-7. `init_pipeline_run_log.py` PIPELINE_STATUS is a string literal

- **File**: `databricks_code/libs/init_pipeline_run_log.py` L28.
- **Original content**:
  ```python
  PIPELINE_STATUS   = "running"
  ```
- Same vocabulary as the notebook `STATUS_RUNNING` constant — but this is a `spark_python_task` that doesn't run `notebook_init`, so the constant isn't in scope.
- **Recommendation**: move the four status strings (`"running"`, `"succeeded"`, `"failed"`, `"no_files"`) into `pipeline_logging.py` as module constants. Both `spark_python_task` scripts can then import from there; `notebook_init` can re-export them. Collapses three of the four current sources of the status vocabulary into one.

## Diff

```diff
diff --git a/databricks_code/libs/init_pipeline_run_log.py b/databricks_code/libs/init_pipeline_run_log.py
index 515c848..4406a9d 100755
--- a/databricks_code/libs/init_pipeline_run_log.py
+++ b/databricks_code/libs/init_pipeline_run_log.py
@@ -18,14 +18,14 @@ if len(sys.argv) < 2:
 sys.path.insert(0, sys.argv[1])
 catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"

-from pipeline_logging import pipeline_log_upsert, configure
+from pipeline_logging import pipeline_log_upsert, configure, STATUS_RUNNING
 configure(f"{catalog}.audit")


 PIPELINE_RUN_ID   = str(uuid.uuid4())
 PIPELINE_START_TS = datetime.now(timezone.utc)
-PIPELINE_NAME     = "Vinoworld TEST LOAD"
-PIPELINE_STATUS   = "running"
+PIPELINE_NAME     = "vinoworld_elt_pipeline"
+PIPELINE_STATUS   = STATUS_RUNNING
 PIPELINE_END_TS   = None
 ERROR_MESSAGE     = None

diff --git a/databricks_code/libs/pipeline_logging.py b/databricks_code/libs/pipeline_logging.py
index 41649a2..a538960 100755
--- a/databricks_code/libs/pipeline_logging.py
+++ b/databricks_code/libs/pipeline_logging.py
@@ -23,6 +23,19 @@ from pyspark.sql.types import (
     StringType, IntegerType, LongType, TimestampType, DoubleType, BooleanType
 )

+# ---------------------------------------------------------------------------
+# Status vocabulary — single source of truth for the audit-row status column.
+# notebook_init re-exports these so notebooks see STATUS_RUNNING etc; the
+# spark_python_task scripts (init_pipeline_run_log, finalize_pipeline_run_log)
+# import them directly since they don't run notebook_init.
+# ---------------------------------------------------------------------------
+
+STATUS_RUNNING   = "running"
+STATUS_SUCCEEDED = "succeeded"
+STATUS_FAILED    = "failed"
+STATUS_NO_FILES  = "no_files"
+
+
 # ---------------------------------------------------------------------------
 # Audit schema is set at runtime by notebook_init via configure().
 # All audit table names derive from this prefix so the module honors the
@@ -172,18 +185,18 @@ def pipeline_log_finalize(spark, pipeline_run_id: str):
             COLLECT_LIST(notebook_name) AS failed_notebooks
         FROM {_audit('pipeline_step_log')}
         WHERE pipeline_run_id = '{pipeline_run_id}'
-          AND status = 'failed'
+          AND status = '{STATUS_FAILED}'
     """).collect()[0]

     if failed["failed_count"] > 0:
-        status        = "failed"
+        status        = STATUS_FAILED
         error_message = (
             f"{failed['failed_count']} step(s) failed: "
             f"{', '.join(failed['failed_notebooks'])}. "
             f"See {_audit('pipeline_step_log')} for details."
         )
     else:
-        status        = "succeeded"
+        status        = STATUS_SUCCEEDED
         error_message = None

     pipeline_log_upsert(

# notebook_init.ipynb cell 0 (only the relevant excerpt — full cell rewrite preserves all other content):
# BEFORE:
#   from pipeline_logging import pipeline_log_upsert, pipeline_step_log_upsert, ingestion_log_insert
#   ...
#   STATUS_RUNNING   = "running"
#   STATUS_SUCCEEDED = "succeeded"
#   STATUS_FAILED    = "failed"
#   STATUS_NO_FILES  = "no_files"
# AFTER:
#   from pipeline_logging import (
#       pipeline_log_upsert, pipeline_step_log_upsert, ingestion_log_insert,
#       STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_NO_FILES,
#   )
#   ...
#   (local STATUS_* assignments removed — now re-exported from pipeline_logging)
```

## Standards files to read

Absolute paths. Read these directly:

- `/home/dev/work/AI/databricks/vinoworld/.claude/CLAUDE.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/deviations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/migrations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/helpers.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/gotchas.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/environments.md`
- `/home/dev/work/AI/databricks/.claude/CLAUDE.md` (workspace-level Databricks ETL standards)
- `/home/dev/work/AI/databricks/vinoworld/docs/BACKLOG.md`

## Sibling families

For each changed object, here is the sibling file to read for cross-object consistency comparison.

| Changed object | Sibling to read |
|---|---|
| `databricks_code/libs/init_pipeline_run_log.py` (spark_python_task script) | `databricks_code/libs/finalize_pipeline_run_log.py` |
| `databricks_code/libs/pipeline_logging.py` (module-level constants) | The other module-level state in the same file: `_AUDIT_SCHEMA_NAME`, `configure()`, `_audit()` |
| `databricks_code/libs/notebook_init.ipynb` (re-export pattern) | This is the central init notebook — no sibling. The pattern under review is "consolidate four local literal assignments into a single grouped import from `pipeline_logging`." |

## Pre-existing changes you should ignore (out of scope)

The working tree contains uncommitted changes outside `databricks_code/` — `.claude/commands/remediate-*.md`, `.claude/project/remediation-agent-design.md`, `CLI_Commands.txt`, `prompts/debug-agnet.md`, and `claudedocs/remediation/`. These are workflow tooling and notes, NOT part of this bucket. Your review is scoped to the three files under `databricks_code/libs/` in the diff above.

## Explicit justifications for intentional deviations

**None.** This bucket does not introduce any deviation from the project's documented standards or from the patterns visible in sibling files. The changes are purely consolidative — they replace string literals with named constants that already follow the project's existing `STATUS_*` naming convention (previously defined locally in `notebook_init.ipynb`; now moved to `pipeline_logging.py` and re-exported).

## Notes for context

- The fix agent verified each finding still reproduces on disk before fixing (P1-6: line 27 confirmed `"Vinoworld TEST LOAD"`; P1-7: line 28 confirmed `"running"` literal).
- The fix agent also replaced two additional in-module status literals at `pipeline_logging.py` L188 (SQL filter inside `pipeline_log_finalize`'s f-string) and L192/L199 (Python assignments in the same function). These were attributed to P1-7's "centralize the status vocabulary" intent; they are within the same module that received the new constants. Treat this as in-scope of P1-7, not as a drive-by edit.
- The bundle deploy + reset_pipeline + elt_pipeline test cycle passed: 11/11 ELT child tasks SUCCEEDED. `finalize_pipeline_log` and `init_pipeline_log` both ran clean, exercising the new STATUS_* substitutions in their actual `spark_python_task` execution context.
