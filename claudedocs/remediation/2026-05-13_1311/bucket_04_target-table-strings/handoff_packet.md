# Handoff packet — Bucket 04

## Bucket

- **ID:** 04
- **Slug:** fix-target-table-strings
- **Branch:** `fix/04-target-table-strings`
- **Findings addressed:** P1-5

## Output path for your verdict

`/home/dev/work/AI/databricks/vinoworld/claudedocs/remediation/2026-05-13_1311/bucket_04_target-table-strings/critical_review.md`

## Finding being addressed (verbatim)

### P1-5. `target_table` is not a real table name

- **Files**:
  - `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 1 → `target_table = "Move datafiles from archive to re-run"`
  - `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` cell 3 → `target_table = f"{SILVER} dim_currency, dim_date, dim_exchange_rate, dim_store, dim_territory"` (missing dot after `{SILVER}`; commas inside the identifier slot)
- **Problem**: `pipeline_step_log.target_table` is a fully-qualified table name everywhere else. The column is nullable; either `None` or one canonical name is honest.

## How to inspect the changes

Read the post-edit notebooks:

- `/home/dev/work/AI/databricks/vinoworld/databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` (cell 1)
- `/home/dev/work/AI/databricks/vinoworld/databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` (cell 3)

Both edits change exactly one line each: `target_table = <bad string>` → `target_table = None`. The rest of each cell is byte-identical.

## Deliberate choice

Both notebooks now use `target_table = None`. The review explicitly said `"either None or one canonical name is honest"`; neither notebook has a single canonical target table (000-MoveFiles moves files across 4 store volumes; slvr_01 loads 5 different dim tables), so None is the honest choice. This matches the bucket 03 truncate notebook's identical `target_table = None` convention for multi-target lifecycle notebooks.

## Standards files to read

- `/home/dev/work/AI/databricks/vinoworld/.claude/CLAUDE.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/deviations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/migrations.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/helpers.md`
- `/home/dev/work/AI/databricks/vinoworld/.claude/project/gotchas.md`

## Pre-existing changes outside this bucket (ignore)

Prior buckets' changes to `libs/`, `notebooks/silver/slvr_03_load_dim_region.ipynb`, the bucket-2 try/except wrappers in slvr_01 cells 4–8, the bucket-2 cell 9 close-out, and the bucket-3 truncate rewrite are all staged from prior buckets. They were reviewed in their own Layer 2 rounds. Bucket 04's diff is just two one-line changes.

## Test evidence

- Reset pipeline SUCCESS (000-MoveFiles ran with new None value).
- ELT pipeline run 193450700430434 SUCCESS 11/11 (slvr_01 ran with new None value via `load_dims_from_csv` task).

## What this bucket does NOT touch

- The `helpers.md` `REPORTING` doc-drift item (out of scope).
- Pre-existing patterns in cell 0 / cell 2 of either notebook.
- The bucket 02 multi-transform `rows_read/rows_written` cumulative pattern in slvr_01 cells 4–8.
