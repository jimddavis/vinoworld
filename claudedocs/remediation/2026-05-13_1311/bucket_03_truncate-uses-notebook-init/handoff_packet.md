# Handoff packet — Bucket 03

## Bucket

- **ID:** 03
- **Slug:** fix-truncate-uses-notebook-init
- **Branch:** `fix/03-truncate-uses-notebook-init`
- **Findings addressed:** P1-4

## Output path for your verdict

`/home/dev/work/AI/databricks/vinoworld/claudedocs/remediation/2026-05-13_1311/bucket_03_truncate-uses-notebook-init/critical_review.md`

## Finding being addressed (verbatim from `claudedocs/code_review_2026-05-12.md`)

### P1-4. `001-Truncate_All_Tables.ipynb` bypasses `notebook_init`

- **File**: `databricks_code/notebooks/001-Truncate_All_Tables.ipynb`, cell 0.
- **Original content**:
  ```python
  dbutils.widgets.text("catalog", "dev_vinoworld")
  CATALOG = dbutils.widgets.get("catalog")
  BRONZE  = f"{CATALOG}.bronze"
  SILVER  = f"{CATALOG}.silver"
  GOLD    = f"{CATALOG}.gold"
  AUDIT   = f"{CATALOG}.audit"
  ```
- **Problems**:
  1. Duplicates the catalog-derivation logic instead of `%run "../libs/notebook_init"` — violates CLAUDE.md § 4 *Load-bearing values must be centralized*.
  2. Hardcodes `dev_vinoworld` as the widget default. The reset job in `databricks.yml` does pass `catalog` via job parameters, so the widget IS overridden in the bundled flow — but a standalone manual run defaults to dev_vinoworld and truncates it.
  3. The notebook writes no `pipeline_step_log` row at all — a destructive operation is invisible in the audit hierarchy.
- **Suggested fix**: replace cell 0 with `%run "../libs/notebook_init"` and rely on the constants/widgets it sets. Add a step-log init/close-out pair while you're in there.

## How to inspect the changes

Read the post-edit notebook directly:

- `/home/dev/work/AI/databricks/vinoworld/databricks_code/notebooks/001-Truncate_All_Tables.ipynb`

Unified diff (working tree vs HEAD): `git diff HEAD -- databricks_code/notebooks/001-Truncate_All_Tables.ipynb`.

## Pre-edit cell structure

- Cell 0: hardcoded catalog widget + 6 lines deriving BRONZE/SILVER/GOLD/AUDIT.
- Cell 1: table list + truncate loop.

## Post-edit cell structure (3 cells)

- **Cell 0:** `%run "../libs/notebook_init"`. Single line. Inherits `CATALOG`, `BRONZE`, `SILVER`, `GOLD`, `AUDIT`, `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`, `PIPELINE_RUN_ID`, `Utils`, `pipeline_step_log_upsert`, `datetime`, `timezone`, `uuid` from the central init.

- **Cell 1:** Step-log init mirroring `000-MoveFilesFromArchiveToBronze` cell 1 exactly: get `notebook_folder`/`notebook_name` from `Utils.get_notebook_context`, generate `step_log_id`, set `step_sequence=1`, `layer="all"`, `target_table=None`, `status=STATUS_RUNNING`, then call `pipeline_step_log_upsert(... STATUS_RUNNING ...)`.

- **Cell 2:** The truncate loop wrapped in try/except, mirroring `000-MoveFilesFromArchiveToBronze` cell 2:
  - try: truncate loop → success-path `pipeline_step_log_upsert(... STATUS_SUCCEEDED ...)` with `rows_read=0, rows_written=0`.
  - except: `Utils.capture_exception`, set status = `STATUS_FAILED`, call `pipeline_step_log_upsert(... STATUS_FAILED ...)` with `rows_read=0, rows_written=0`, then `raise`.

## Standards files to read

- `/home/dev/work/AI/databricks/vinoworld/.claude/CLAUDE.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/deviations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/migrations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/helpers.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/gotchas.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/environments.md`
- `/home/dev/work/AI/databricks/.claude/CLAUDE.md`

## Sibling families to read

| Changed object | Sibling to read end-to-end |
|---|---|
| `001-Truncate_All_Tables.ipynb` post-edit (3 cells) | `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` — same folder, same kind of single-operation lifecycle notebook, follows the exact `%run + step-log init + try/except + close-out` pattern. |

## Deliberate choices worth flagging

1. **`target_table = None`** instead of the sibling's prose string ("Move datafiles from archive to re-run"). The sibling's prose value is itself the subject of finding **P1-5** ("target_table is not a real table name") which is scheduled for bucket 4. The original review said "either None or one canonical name is honest"; this notebook truncates 17 tables across 4 schemas so no single canonical name applies — None is honest. I am deliberately NOT propagating the soon-to-be-fixed anti-pattern into the new notebook.

2. **`layer = "all"`** instead of a single-schema value. The truncate spans bronze/silver/gold/audit; `"all"` is an honest descriptor at the notebook level. The sibling uses `"bronze"` because it only moves bronze-source files.

3. **`rows_written = 0` on the failure path** is correct here (different from bucket 02's slvr_01 case): the truncate notebook performs a single logical operation (the loop). If the loop raises, no notion of "partial success rows_written" applies — TRUNCATE deletes, doesn't write. This is a single-operation notebook, like the sibling — the bucket 02 multi-transform exception does not apply here.

## Pre-existing issues you should NOT flag

- `helpers.md` documents `REPORTING` as injected by `notebook_init` but the notebook doesn't define it. Surfaced in bucket 01's Layer 2; doc-side fix outside the workflow's scope.

## Pre-existing changes outside this bucket (ignore)

The working tree contains staged changes from buckets 01 and 02 (in `libs/` and `notebooks/silver/`). Those were reviewed in their own Layer 2 rounds. Bucket 03's diff is scoped to `databricks_code/notebooks/001-Truncate_All_Tables.ipynb` only.

## Test evidence

- Bundle deploy succeeded; deploy-verify ritual confirmed the new 3-cell structure on the remote.
- `vinoworld_reset_pipeline` run 18322292153706: parent TERMINATED/SUCCESS; both child tasks (`truncate_all_tables`, `move_archive_to_bronze`) TERMINATED/SUCCESS. This pipeline IS the bucket's direct test — its first task is the changed notebook.
- ELT pipeline deliberately not re-run: it doesn't reference the truncate notebook, so it wouldn't exercise any code this bucket changed. Both prior buckets already proved the ELT path is green.
