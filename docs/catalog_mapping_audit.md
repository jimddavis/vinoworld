# Catalog Mapping Audit — End-to-End Trace

**Date:** 2026-05-05
**Branch:** `restructure_folders`
**Scope:** All files under `databricks_code/`. Source-only — does not inspect deployed workspace state.
**Symptom:** Running `databricks bundle deploy --target dev && databricks bundle run` writes data to catalog `vinoworld` instead of the expected `dev_vinoworld`.

---

## TL;DR

The bundle config and `libs/notebook_init.ipynb` are correct: `var.catalog → ${var.catalog}` job parameter → notebook widget → `CATALOG` constant works as designed. The chain breaks **after** `notebook_init` because multiple notebooks and one shared module bypass the `CATALOG` constant entirely with literal `vinoworld.…` strings. There is **no single root cause** — five independent bypass points compound. Three of them write data; two corrupt audit/file-staging.

| # | Location | Effect | Severity |
|---|---|---|---|
| 1 | `libs/pipeline_logging.py` lines 18, 85, 183, 328 | All audit log writes go to `vinoworld.audit.*`, always | **CRITICAL — every run** |
| 2 | `silver/slvr_02_load_dim_product.ipynb` cells 5, 6, 7 | `dim_product` MERGE/INSERT always writes to `vinoworld.silver.dim_product` | **CRITICAL — every run** |
| 3 | `silver/slvr_03_load_dim_region.ipynb` cell 6 | `dim_region` MERGE always writes to `vinoworld.silver.dim_region` | **CRITICAL — every run** |
| 4 | `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 2 | `RAW_FILES = "/Volumes/vinoworld/datafiles/"` hardcoded — file move always operates on `vinoworld` volumes | **CRITICAL — every run** |
| 5 | `libs/init_pipeline_run_log.py` + `databricks.yml` lines 85–92 | `catalog` parameter is never passed to the Python script task | HIGH — compounds #1 |
| 6 | All pipeline notebooks: `%run "/Workspace/Shared/notebook_init"` | Old absolute path; bundle deploys notebook_init to `${workspace.root_path}/files/libs/`, not `/Workspace/Shared/` | HIGH — see §6 |

A successful `--target dev` run produces tables in **two different catalogs**: ETL data in `dev_vinoworld.bronze` / `dev_vinoworld.gold` / `dev_vinoworld.silver` (for *most* silver tables), but `dim_product`, `dim_region`, all four audit tables, and any output of the file-move step end up in `vinoworld.*`. That is consistent with the user's observation that "data lands in `vinoworld`."

---

## Section 1 — `%run` Path Audit

| Notebook | `%run` cell content | Verdict |
|---|---|---|
| `setup/catalog_ddl.ipynb` | (no `%run` — declares widgets inline) | ✓ correct |
| `setup/seed_volumes.ipynb` | (no `%run` — declares widgets inline) | ✓ correct |
| `notebooks/001-Truncate_All_Tables.ipynb` | (no `%run` — declares widgets inline) | ✓ correct |
| `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/bronze/brz_01_arancione_sales.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/bronze/brz_02_celeste_sales.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/bronze/brz_03_verde_sales.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/bronze/brz_04_products.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/silver/slvr_02_load_dim_product.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/silver/slvr_03_load_dim_region.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/silver/slvr_04_load_sales.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |
| `notebooks/gold/gold_01_load_sales_fact.ipynb` | `%run "/Workspace/Shared/notebook_init"` | ✗ broken path |

**The bundle deploys `libs/notebook_init.ipynb` under `${workspace.root_path}/files/libs/notebook_init` — not under `/Workspace/Shared/`.** Every `%run "/Workspace/Shared/notebook_init"` in the table above will either (a) fail outright if the path does not exist, or (b) silently load a stale copy of the file that pre-dates the bundle restructure. Databricks `%run` does **not** support widget-based or variable-based paths — the string is literal — so the only fixes are to hardcode a different absolute path or use a relative path like `../../libs/notebook_init`.

**No orchestrator notebook was found anywhere under `databricks_code/`.** `find databricks_code -name '*orchestrator*' -o -name '01-*'` returned zero results. The bundle's `vinoworld_elt_pipeline` job in `databricks.yml` lines 80–162 invokes each notebook directly as a separate task, so an orchestrator is not architecturally required, but the job-parameter → notebook-widget chain depends on the bundle YAML (working) rather than any orchestrator code.

---

## Section 2 — Hardcoded Catalog References (verified by direct cell scan)

A literal `vinoworld` string in a non-`%skip` code cell is the bug. Documentation cells (markdown) and `%skip` cells are noted but not severity-counted. Widget *defaults* (e.g., `dbutils.widgets.text("catalog", "vinoworld")`) are correct: they get overridden by the job parameter at run time and are required for standalone notebook runs.

### 2.1 — `libs/pipeline_logging.py` (CRITICAL — affects every run, every target)

| Line | Code | Notes |
|---|---|---|
| 18 | `PIPELINE_LOG_TABLE = "vinoworld.audit.pipeline_log"` | Module-level constant; no parameter override |
| 85 | `_STEP_LOG_TABLE = "vinoworld.audit.pipeline_step_log"` | Module-level constant |
| 183 | `_TRANSFORM_DETAIL_TABLE = "vinoworld.audit.transform_detail_log"` | Module-level constant |
| 328 | `_INGESTION_LOG_TABLE = "vinoworld.audit.ingestion_log"` | Module-level constant |

None of the four audit-log functions (`pipeline_log_upsert`, `pipeline_step_log_upsert`, `transform_detail_log_insert`, `ingestion_log_insert`) accept a `catalog` parameter. Every audit log row produced by every notebook in every target writes to `vinoworld.audit.*`. This alone guarantees the symptom.

### 2.2 — `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` (CRITICAL — affects every run)

| Cell | Skip? | Code | Severity |
|---|---|---|---|
| 2 | active | `RAW_FILES = "/Volumes/vinoworld/datafiles/"` | **CRITICAL** — literal overrides the value `notebook_init` would have set |
| 2 | active | `sys.path.append("/Workspace/Shared")` | MEDIUM — bypasses `shared_lib_path` widget |

The notebook `%run`s `notebook_init` (which would set `RAW_FILES = f"/Volumes/{CATALOG}/datafiles/"`), then immediately overwrites it with the literal. The result: regardless of target, file-archive moves operate on `/Volumes/vinoworld/datafiles/...`.

### 2.3 — `notebooks/silver/slvr_02_load_dim_product.ipynb` (CRITICAL — writes to wrong catalog)

| Cell | Skip? | Hits | Notes |
|---|---|---|---|
| 4 | %skip | `TRUNCATE TABLE vinoworld.silver.dim_product;` | LOW |
| 5 | active | `FROM vinoworld.bronze.products` and a doc-comment line | **HIGH** |
| 6 | active | `MERGE INTO vinoworld.silver.dim_product AS tgt` + `JOIN vinoworld.silver.dim_product d` + `INSERT INTO vinoworld.silver.dim_product` + `FROM vinoworld.silver.dim_product d` | **HIGH** — 4 occurrences |
| 7 | active | `FROM vinoworld.silver.dim_product` + `INSERT INTO vinoworld.silver.dim_product` | **HIGH** |
| 8–10 | %skip | diagnostic queries | LOW |

Cell 2 defines `TARGET_TABLE = f"{SILVER}.dim_product"` correctly — but cells 5–7 ignore that constant and use literal three-part names. **The dim_product load always writes to `vinoworld.silver.dim_product`, regardless of target.**

### 2.4 — `notebooks/silver/slvr_03_load_dim_region.ipynb` (CRITICAL — writes to wrong catalog)

| Cell | Skip? | Hits | Notes |
|---|---|---|---|
| 2 | %skip | `CATALOG = "Vinoworld"` and `RAW_FILES = "/Volumes/vinoworld/datafiles/"` | LOW (skip cell — but a hazard if ever un-skipped) |
| 5 | %skip | `TRUNCATE TABLE vinoworld.silver.dim_region;` | LOW |
| 6 | **active** | `MERGE INTO vinoworld.silver.dim_region a … FROM vinoworld.bronze.products p` | **HIGH** |
| 7 | %skip | `DESCRIBE HISTORY vinoworld.silver.dim_product LIMIT 1` | LOW |
| 8, 9 | %skip | diagnostic queries | LOW |

Same pattern as slvr_02: parameterized `TARGET_TABLE` defined but ignored by the active SQL. **dim_region always writes to `vinoworld.silver.dim_region`.**

### 2.5 — Bronze notebooks (LOW–MEDIUM — diagnostic/read-only, but cosmetically wrong)

The actual production write path in every bronze notebook uses `f"{BRONZE}.<table>"` — those are correct. The hardcoded references that remain are diagnostic SELECTs, but several are **active** (no `%skip`):

| File | Active hardcoded cells | Skip-cell hardcoded |
|---|---|---|
| `brz_01_arancione_sales.ipynb` | cell 8 — `SELECT COUNT(*) FROM vinoworld.bronze.sales_arancione` | cells 9, 10 |
| `brz_02_celeste_sales.ipynb` | (none) | cells 8, 9, 10 |
| `brz_03_verde_sales.ipynb` | cell 9 — `SELECT … FROM vinoworld.audit.pipeline_step_log`; cell 11 — `select count(*) from vinoworld.bronze.sales_verde` | cells 8, 10 |
| `brz_04_products.ipynb` | cell 12 — `select count(*) from vinoworld.bronze.products`; cell 13 — `select * from vinoworld.bronze.products …` | cells 2, 9, 10, 11 |

These are read-only diagnostic queries — they do not corrupt write paths but will return misleading counts (or 0/missing-table errors) when the run target is anything other than `vinoworld`.

### 2.6 — `slvr_01_load_dim_fromcsv.ipynb`, `slvr_04_load_sales.ipynb`, `gold_01_load_sales_fact.ipynb`

The actual write paths use parameterized `{SILVER}` / `{GOLD}` constants and are correct. Remaining hardcodes:

| File | Active hardcoded cells |
|---|---|
| `slvr_01` cell 3 | `target_table = "vinoworld.silver dim_currency, dim_date, dim_region, dim_store, dim_territory"` — this is a *log message label*, not a SQL identifier (and it's malformed as SQL anyway). Cosmetic — fix when convenient |
| `slvr_04` cell 8 | `select * from vinoworld.silver.sales` — diagnostic SELECT, active |
| `gold_01` | (no active hardcoded refs) ✓ |

### 2.7 — Widget defaults (informational, not bugs)

| File | Cell | Code |
|---|---|---|
| `001-Truncate_All_Tables.ipynb` | cell 0 | `dbutils.widgets.text("catalog", "vinoworld")` |
| `setup/catalog_ddl.ipynb` | cell 0 | `dbutils.widgets.text("catalog", "vinoworld")` |
| `setup/seed_volumes.ipynb` | cell 0 | `dbutils.widgets.text("catalog", "vinoworld")` |
| `setup/seed_volumes.ipynb` | cell 1 | `SOURCE_CATALOG = "vinoworld"   # always seed from the reference/prod catalog` (intentional — by design) |
| `libs/notebook_init.ipynb` | cell 0 | `dbutils.widgets.text("catalog", "vinoworld")` |

Each widget default is overridden by the job parameter `catalog: ${var.catalog}` at deploy time. They are required for manual standalone notebook runs and are not the source of the bug.

---

## Section 3 — Widget Chain Verification (per file)

| File | Has its own `dbutils.widgets.get("catalog")`? | Reads CATALOG via `%run`? | Verdict |
|---|---|---|---|
| `setup/catalog_ddl.ipynb` | yes (cell 0) | n/a | **Yes** — chain works |
| `setup/seed_volumes.ipynb` | yes (cell 0) | n/a | **Yes** — chain works |
| `001-Truncate_All_Tables.ipynb` | yes (cell 0) | n/a | **Yes** — chain works |
| `000-MoveFilesFromArchiveToBronze.ipynb` | no | yes — but then overrides `RAW_FILES` | **Partial** — CATALOG is correct, but RAW_FILES is bypassed |
| `brz_01` … `brz_04` | no | yes (via `%run`) | **Yes for production write path** — CATALOG flows; but the `%run` path itself targets the old workspace location (§1) |
| `slvr_01_load_dim_fromcsv.ipynb` | no | yes | **Yes** — production path uses `{SILVER}` |
| `slvr_02_load_dim_product.ipynb` | no | yes | **No** — CATALOG is loaded but not used in the active MERGE/INSERT cells |
| `slvr_03_load_dim_region.ipynb` | no | yes | **No** — same as slvr_02 |
| `slvr_04_load_sales.ipynb` | no | yes | **Yes** — production path uses `{SILVER}` and `{BRONZE}` |
| `gold_01_load_sales_fact.ipynb` | no | yes | **Yes** — production path uses `{GOLD}` |

`libs/init_pipeline_run_log.py` is a `spark_python_task`, not a notebook — it has no widgets. It receives only `sys.argv[1]` (= `${var.shared_lib_path}`) per `databricks.yml` line 91. **The catalog is never passed to it.** It then calls `pipeline_log_upsert(...)`, which writes to the hardcoded `vinoworld.audit.pipeline_log` from §2.1.

---

## Section 4 — Volume Path Audit

| File | Volume path source | Verdict |
|---|---|---|
| `libs/notebook_init.ipynb` cell 0 | `RAW_FILES = f"/Volumes/{CATALOG}/datafiles/"` | ✓ derived |
| `setup/seed_volumes.ipynb` cell 2 | `f"/Volumes/{CATALOG}/datafiles/{vol}/"` (target), `f"/Volumes/{SOURCE_CATALOG}/datafiles/{vol}/"` (source — intentional, seeds from prod) | ✓ correct (mixed by design) |
| `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 2 | `RAW_FILES = "/Volumes/vinoworld/datafiles/"` (literal) | ✗ **bug** — overwrites `notebook_init`'s value |
| All bronze notebooks | `SOURCE_PATH = f"{RAW_FILES}{SOURCE_SUBPATH}"` — uses RAW_FILES from notebook_init | ✓ correct (assuming `%run` is fixed) |
| Silver / gold notebooks | (no volume paths) | n/a |

---

## Section 5 — Root Cause Summary

The user reported "data writes to `vinoworld` regardless of target." That observation conflates several distinct bypass paths. After end-to-end trace:

**The bundle config (`databricks.yml`) is correct.** `var.catalog = dev_vinoworld` is properly defined for the `dev` target (line 174–177). Both jobs declare `parameters: - name: catalog, default: ${var.catalog}` (lines 41–42 and 76–77). Job-level parameters automatically inject into notebook-task widgets in Databricks.

**`libs/notebook_init.ipynb` is correct.** Cell 0 line 24 reads the widget; lines 26–30 derive `BRONZE`/`SILVER`/`GOLD`/`AUDIT`/`RAW_FILES` from `CATALOG`. Given a `dev` run, `notebook_init` produces the right values.

**The chain breaks in five independent places downstream of `notebook_init`:**

1. **`pipeline_logging.py` is catalog-blind.** The four audit table names are module-level string literals. Every audit log write — from every notebook, every target — writes to `vinoworld.audit.*`. **This alone fully explains the symptom for the audit tables.**
2. **`slvr_02_load_dim_product.ipynb` and `slvr_03_load_dim_region.ipynb` ignore their own `TARGET_TABLE` constant.** Cells 5–7 of slvr_02 and cell 6 of slvr_03 contain literal three-part names (`vinoworld.silver.dim_product`, `vinoworld.silver.dim_region`, `vinoworld.bronze.products`). These two silver dimensions always write to `vinoworld`.
3. **`000-MoveFilesFromArchiveToBronze.ipynb` cell 2 reassigns `RAW_FILES`** to a literal `/Volumes/vinoworld/datafiles/` *after* the `%run`, so file movement always operates on `vinoworld` volumes.
4. **`init_pipeline_run_log.py` does not receive `catalog`.** `databricks.yml` line 91 passes only `${var.shared_lib_path}` to the Spark Python task. Even if `pipeline_logging.py` were fixed, this script would still need to forward the catalog.
5. **All pipeline notebooks `%run "/Workspace/Shared/notebook_init"`** — an absolute path that is not the bundle's deployment target (`${workspace.root_path}/files/libs/notebook_init`). This either fails the `%run` outright or loads a stale copy. Source-only audit cannot say which; the user can verify by listing `/Workspace/Shared/` in the workspace.

**Is it one root cause or multiple compounding issues?** Multiple. The audit-log issue (#1) and the silver-dimension issues (#2) are completely independent of each other and of the bundle config. Even a perfect `databricks.yml` cannot save the run from these — they are runtime literals in the application code itself. The `%run` path issue (#5) is also independent: even after fixing #1–#4, every pipeline notebook will continue to load `notebook_init` from `/Workspace/Shared/` rather than from the bundle artifact, which means future edits to the in-repo `libs/notebook_init.ipynb` will not take effect at deploy time.

---

## Section 6 — Fix List (ordered by impact)

### TIER 1 — Highest impact: fixes that affect every notebook in every run

#### Fix 1.1 — Re-deploy `notebook_init` via the bundle and update every `%run` to the bundle artifact path

`databricks.yml` line 22 already defines `var.shared_lib_path = ${workspace.root_path}/files/libs`, and the bundle copies `libs/notebook_init.ipynb` there. The notebooks need to call that copy.

Two viable patterns:

**Option A (recommended): relative path.** `%run` accepts relative paths. From a notebook at `notebooks/bronze/brz_01_arancione_sales.ipynb`, the bundle deploys `libs/notebook_init.ipynb` at `../../libs/notebook_init`:

```python
%run "../../libs/notebook_init"
```

For `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` (one level shallower):

```python
%run "../libs/notebook_init"
```

**Option B: absolute deployment path.** Less robust — depends on `${workspace.root_path}` resolving the same way at edit time.

Apply to all of:
- `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 1 → `%run "../libs/notebook_init"`
- `notebooks/bronze/brz_01_arancione_sales.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/bronze/brz_02_celeste_sales.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/bronze/brz_03_verde_sales.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/bronze/brz_04_products.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/silver/slvr_02_load_dim_product.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/silver/slvr_03_load_dim_region.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/silver/slvr_04_load_sales.ipynb` cell 1 → `%run "../../libs/notebook_init"`
- `notebooks/gold/gold_01_load_sales_fact.ipynb` cell 1 → `%run "../../libs/notebook_init"`

After applying, also delete the workspace folder `/Workspace/Shared/` (or rename it) so a stale copy can never be loaded again.

#### Fix 1.2 — Parameterize audit table names in `libs/pipeline_logging.py`

Remove the four module-level constants. Make every audit-log function accept a `catalog` (or a fully qualified `audit_schema`) parameter and build the table name from it. The cleanest minimal change:

- **Add a one-time setter at module top:**
  ```python
  _AUDIT_SCHEMA = None

  def configure(audit_schema: str) -> None:
      global _AUDIT_SCHEMA
      _AUDIT_SCHEMA = audit_schema
  ```
- **Replace each constant with a property/lookup:**
  ```python
  def _table(name: str) -> str:
      if _AUDIT_SCHEMA is None:
          raise RuntimeError("pipeline_logging.configure(audit_schema) was not called")
      return f"{_AUDIT_SCHEMA}.{name}"
  ```
- **Inside each function, replace the constant:**
  - line 72 area: `f"... INTO {_table('pipeline_log')} ..."`
  - line 167 area: `f"... INTO {_table('pipeline_step_log')} ..."`
  - line 317 area: `f"... INTO {_table('transform_detail_log')} ..."`
  - line 378 area: `f"... INTO {_table('ingestion_log')} ..."`
- **Wire it up in `libs/notebook_init.ipynb`** right after `AUDIT` is computed:
  ```python
  import pipeline_logging
  pipeline_logging.configure(AUDIT)
  ```

(An equally valid alternative is a per-call `audit_schema=` parameter — but every caller would need to be updated. The setter approach keeps the call sites intact.)

#### Fix 1.3 — Pass `catalog` to `init_pipeline_run_log.py` and have it call `pipeline_logging.configure`

`databricks.yml` lines 85–92 currently:
```yaml
- task_key: init_pipeline_log
  spark_python_task:
    python_file: ./libs/init_pipeline_run_log.py
    parameters:
      - "${var.shared_lib_path}"
```
Add a second positional argument:
```yaml
    parameters:
      - "${var.shared_lib_path}"
      - "${var.catalog}"
```

Update `libs/init_pipeline_run_log.py` line 11 area to read it:
```python
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else "/Workspace/Shared")
catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"

from pipeline_logging import pipeline_log_upsert, configure
configure(f"{catalog}.audit")
```

### TIER 2 — Per-notebook fixes (write-path bugs)

#### Fix 2.1 — `notebooks/silver/slvr_02_load_dim_product.ipynb` (active cells 5, 6, 7)

Replace every `vinoworld.silver.dim_product` with `{TARGET_TABLE}` and every `vinoworld.bronze.products` with `{SOURCE_TABLE}` (define `SOURCE_TABLE = f"{BRONZE}.products"` in the constants cell if not already present). Use f-string SQL or `spark.sql(f"...")`.

#### Fix 2.2 — `notebooks/silver/slvr_03_load_dim_region.ipynb` (active cell 6)

Same pattern as 2.1. Replace `vinoworld.silver.dim_region` with `{TARGET_TABLE}` and `vinoworld.bronze.products` with `{SOURCE_TABLE}` (define `SOURCE_TABLE = f"{BRONZE}.products"`).

The `%skip` cell 2 that reassigns `CATALOG = "Vinoworld"` should be **deleted entirely** rather than left dormant — leaving it is a foot-gun.

#### Fix 2.3 — `notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 2

```python
# BEFORE (literal):
RAW_FILES = "/Volumes/vinoworld/datafiles/"
import sys
sys.path.append("/Workspace/Shared")

# AFTER (rely on notebook_init):
# RAW_FILES is already set by `%run` above. No re-assignment.
# sys.path is already configured by notebook_init. Remove the append.
```

If the notebook needs to keep working before Fix 1.1 is deployed, leave the `sys.path.append` but change `RAW_FILES` to `f"/Volumes/{CATALOG}/datafiles/"`.

### TIER 3 — Diagnostic and cosmetic cleanup (no functional impact on writes)

#### Fix 3.1 — Bronze notebook diagnostic cells

Add `%skip` to currently active diagnostic cells, OR rewrite them to use parameterized refs:

- `brz_01` cell 8 → `SELECT COUNT(*) FROM {TARGET_TABLE}` (using f-string `spark.sql(f"...")`) **or** add `%skip`
- `brz_03` cell 9, 11 → same pattern or `%skip`
- `brz_04` cell 12, 13 → same pattern or `%skip`

#### Fix 3.2 — `slvr_01_load_dim_fromcsv.ipynb` cell 3

The `target_table` argument passed to logging is a label, not SQL. Change:
```python
target_table = "vinoworld.silver dim_currency, dim_date, dim_region, dim_store, dim_territory"
```
to a layer-correct label like:
```python
target_table = f"{SILVER}.dim_csv_load (multi-table)"
```

#### Fix 3.3 — `slvr_04` cell 8

Add `%skip` or convert to `spark.sql(f"select * from {TARGET_TABLE}")`.

### TIER 4 — Verification after fixes

1. Delete the local sync snapshot and the deployed `/Workspace/Shared/` folder:
   ```bash
   rm -rf databricks_code/.databricks/bundle/dev/sync-snapshots/
   databricks workspace delete -r /Workspace/Shared/  # confirm path first
   ```
2. `databricks bundle validate --target dev` → expect clean.
3. `databricks bundle deploy --target dev`
4. `databricks bundle run vinoworld_environment_setup --target dev`
5. `databricks bundle run vinoworld_elt_pipeline --target dev`
6. After the run, confirm with three queries — **all three should return rows**, and the equivalent queries against `vinoworld.*` should return empty / not-found:
   ```sql
   SELECT COUNT(*) FROM dev_vinoworld.silver.dim_product;
   SELECT COUNT(*) FROM dev_vinoworld.silver.dim_region;
   SELECT COUNT(*) FROM dev_vinoworld.audit.pipeline_log
     WHERE pipeline_run_id = '<the run id>';
   ```
7. Repeat steps 3–6 for `--target staging`. The same three queries against `staging_vinoworld.*` should now return rows.

---

## Appendix A — Files Not Audited

The audit was scoped to source files under `databricks_code/`. Out of scope:

- `databricks_code/.databricks/` — local CLI state, not deployed
- `Shared/` at the project root (the canonical source per CLAUDE.md, but `databricks_code/libs/` is the bundle's source of truth as configured in `databricks.yml`)
- The deployed workspace state itself (per the user's instruction). In particular, the contents of `/Workspace/Shared/notebook_init` cannot be inferred from this repo. If that file exists in the workspace and predates the restructure, it almost certainly contains its own version of the `dbutils.widgets.text("catalog", ...)` call — which may or may not match `databricks_code/libs/notebook_init.ipynb`. This is one reason Fix 1.1 (relative `%run` path) is critical: it eliminates the dependency on workspace state entirely.

## Appendix B — How to reproduce the scan

```bash
cd /home/dev/work/AI/databricks/vinoworld_bundle
python3 -c "
import json, re, os, glob
for nb in sorted(glob.glob('databricks_code/**/*.ipynb', recursive=True)):
    with open(nb) as f:
        d = json.load(f)
    for i, c in enumerate(d.get('cells', [])):
        if c.get('cell_type') != 'code': continue
        src = ''.join(c.get('source', []))
        is_skip = '%skip' in src[:30]
        for line in src.splitlines():
            if re.search(r'(?i)vinoworld', line) and 'widgets.text' not in line:
                marker = 'SKIP' if is_skip else 'ACTIVE'
                print(f'{nb}:cell{i}:{marker}: {line.strip()[:140]}')
"
```
