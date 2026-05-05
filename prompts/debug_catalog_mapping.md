# Debug: Catalog Name Mapping — End-to-End Trace

## Problem Statement

The Vinoworld Databricks bundle has four deployment targets (`dev`, `staging`, `prod`, `azure_prod`)
that are supposed to write to separate catalogs (`dev_vinoworld`, `staging_vinoworld`, `vinoworld`,
`vinoworld` on Azure). Despite the bundle passing the correct `catalog` job parameter, pipeline
runs are writing data to `vinoworld` regardless of target. The multi-environment isolation is broken.

## What to Analyze

Perform a complete end-to-end trace of how the catalog name flows from bundle configuration through
to every table reference in every notebook. Identify every place where the chain is broken, bypassed,
or hardcoded.

## The Expected Chain

The correct flow for every pipeline notebook is:

```
databricks.yml (var.catalog = dev_vinoworld for dev target)
  → job parameter: catalog = ${var.catalog}
    → notebook widget: dbutils.widgets.text("catalog", "vinoworld")
      → CATALOG = dbutils.widgets.get("catalog")        ← should be dev_vinoworld
        → BRONZE/SILVER/GOLD/AUDIT derived from CATALOG
          → all table references use three-part names    ← dev_vinoworld.bronze.sales_arancione
```

The `CATALOG` constant is set in `databricks_code/libs/notebook_init.ipynb` and injected into
every pipeline notebook via `%run`. The key question is whether this chain holds unbroken.

## Files to Analyze

Read every file listed below. For each one, document what you find against the checklist.

### Bundle Configuration
- `databricks_code/databricks.yml`

### Shared Libraries
- `databricks_code/libs/notebook_init.ipynb`
- `databricks_code/libs/catalog_setup.py`
- `databricks_code/libs/pipeline_logging.py`
- `databricks_code/libs/pipeline_utils.py`
- `databricks_code/libs/init_pipeline_run_log.py`

### Setup Notebooks
- `databricks_code/setup/catalog_ddl.ipynb`
- `databricks_code/setup/seed_volumes.ipynb`

### Pipeline Notebooks
- `databricks_code/notebooks/001-Truncate_All_Tables.ipynb`
- `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb`
- `databricks_code/notebooks/bronze/brz_01_arancione_sales.ipynb`
- `databricks_code/notebooks/bronze/brz_02_celeste_sales.ipynb`
- `databricks_code/notebooks/bronze/brz_03_verde_sales.ipynb`
- `databricks_code/notebooks/bronze/brz_04_products.ipynb`
- `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb`
- `databricks_code/notebooks/silver/slvr_02_load_dim_product.ipynb`
- `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`
- `databricks_code/notebooks/silver/slvr_04_load_sales.ipynb`
- `databricks_code/notebooks/gold/gold_01_load_sales_fact.ipynb`

## Checklist — Apply to Every Notebook

For each notebook, answer these questions:

### 1. %run path
- What is the exact string passed to `%run`?
- Does it point to `/Workspace/Shared/notebook_init` (old, hardcoded path)?
- Or does it use the bundle-deployed path via `shared_lib_path` widget?
- **Critical**: Databricks `%run` does not support widget-based paths — the path must be a
  string literal. If the path is hardcoded to `/Workspace/Shared/notebook_init`, determine
  whether that file on the workspace has the correct widget-based catalog logic or has
  hardcoded catalog names.

### 2. Hardcoded catalog references
- Search every cell for the literal strings `vinoworld`, `dev_vinoworld`, `staging_vinoworld`.
- A hardcoded catalog name in any non-`%skip` cell is a bug.
- `%skip` cells are acceptable but should still be noted.
- Hardcoded names in markdown cells (documentation) are acceptable.

### 3. Widget chain
- Does the notebook (or its `%run`'d init) call `dbutils.widgets.text("catalog", ...)` before
  reading `CATALOG`?
- Is `CATALOG` derived from `dbutils.widgets.get("catalog")`, or is it assigned a literal string?

### 4. Table references
- Are all table references three-part (`{CATALOG}.{schema}.{table}` or
  `{BRONZE}.table_name` where BRONZE derives from CATALOG)?
- Are any table references two-part (`schema.table`) or hardcoded?

### 5. shared_lib_path usage
- Does the notebook read a `shared_lib_path` widget and use it for `sys.path.insert()`?
- Is it consistent with how `notebook_init` reads the same widget?

### 6. Volume paths
- Do volume paths use `RAW_FILES` (derived from CATALOG in notebook_init) or hardcoded strings?
- `/Volumes/vinoworld/...` in any non-skip cell is a bug.

## Specific Issues Already Known

These were spotted during a prior review — confirm they exist and check all other notebooks
for the same patterns:

1. `brz_01_arancione_sales.ipynb` cell-1: `%run "/Workspace/Shared/notebook_init"` —
   hardcoded to old workspace path. Determine if all other notebooks have the same issue.

2. `brz_01_arancione_sales.ipynb` cell-8: `%sql SELECT COUNT(*) FROM vinoworld.bronze.sales_arancione`
   — hardcoded catalog in a non-skip active cell.

## Deliverable

Produce a structured report with these sections:

### Section 1: %run Path Audit
A table with one row per notebook: notebook name | %run path used | verdict (correct/broken/missing)

### Section 2: Hardcoded Catalog References
For each occurrence: file | cell id | the exact string | severity (active cell = HIGH, skip cell = LOW)

### Section 3: Widget Chain Verification
For each notebook: does the catalog widget chain work correctly end-to-end? Yes / No / Partial

### Section 4: Volume Path Audit
Any volume paths not derived from CATALOG/RAW_FILES.

### Section 5: Root Cause Summary
What is the primary reason data lands in `vinoworld` instead of `dev_vinoworld`?
Is it one root cause or multiple compounding issues?

### Section 6: Fix List
An ordered list of every change required, grouped by file, with the exact fix for each.
Prioritize by impact: fixes that affect all notebooks first, then per-notebook fixes.
