# Vinoworld code review — 2026-05-12

Snapshot of the current state of `databricks_code/` as it sits on the
local file system right now. Source of truth: the files on disk, read
directly via `Read` and `python3 json.load` on every `.ipynb`. Not git.
Every finding cites the exact file path; if it isn't listed here, the
current file content is clean against the rule.

Scope:
- `databricks_code/libs/*` (Python + the `notebook_init` notebook).
- `databricks_code/notebooks/**/*.ipynb` (bronze, silver, gold, root).
- `databricks_code/setup/*.ipynb`.
- `databricks_code/dashboards/*.lvdash.json`.
- `databricks_code/databricks.yml`.

Rules checked against: `.claude/CLAUDE.md`, `.claude/project/*.md`,
`docs/BACKLOG.md`.

---

## Severity legend

- **P0** — will fail at runtime / wrong data.
- **P1** — violates a documented rule (forbidden string, deviation, gotcha).
- **P2** — consistency / hygiene.
- **P3** — documentation drift / cosmetic.

---

## P0 — Runtime / data correctness

### P0-1. Dashboard hardcodes the dev catalog — *user has marked this deferred*

- **File**: `databricks_code/dashboards/sales_overview.lvdash.json`,
  lines 8, 75, 139, 189.
- **Current content**:
  ```
  "source": "dev_vinoworld.reporting.vw_sales_monthly_by_store"
  "source": "dev_vinoworld.reporting.vw_top_products"
  "source": "dev_vinoworld.reporting.vw_sales_by_variety_winery"
  "source": "dev_vinoworld.audit.vw_pipeline_run_summary"
  ```
- **Risk**: `databricks.yml` L41–45 deploys this dashboard to every
  target. On `staging`/`prod`/`azure_prod` the queries either read dev
  data or fail because `dev_vinoworld` doesn't exist (Azure).
- **Status**: deferred per your decision. Listed for visibility; no
  action requested.

---

## P1 — Documented-rule violations

### P1-1. Step-log success close-out missing in `slvr_01` and `slvr_03`

- **Files**:
  - `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb`
  - `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`
- **Current state**: both notebooks write `pipeline_step_log` once at
  start with `STATUS_RUNNING` and only update on failure paths. The
  success path never writes the close-out row, so the row sits as
  `'running'` after a clean run.
- **Already tracked** in `docs/BACKLOG.md` *Next up* §
  "Step-log success close-out — `slvr_01` and `slvr_03`". No new action
  needed.

### P1-2. `slvr_03_load_dim_region.ipynb` has zero `transform_detail_log` coverage

- **File**: `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`.
- **Current state**: no `from pipeline_logging import
  transform_detail_log_insert` and no call. Every other transform-style
  notebook in silver/gold (`slvr_01`, `slvr_02`, `slvr_04`, `gold_01`)
  has one. dim_region transforms are invisible at the table-tier audit.
- **Fix**: mirror `slvr_02` cell 5's Pattern B layout — pre-declare
  variables outside `try`, call `transform_detail_log_insert(..., status=
  STATUS_SUCCEEDED, ...)` on success and `..., status=STATUS_FAILED,
  ...` on the except path.
- **Suggested branch**: same as P1-1 (one notebook, one branch).

### P1-3. `slvr_01_load_dim_fromcsv.ipynb` per-dim cells have no `try/except`

- **File**: same notebook, cells 4–8 (Currency, Date, Exchange Rate,
  Store, Territory).
- **Current shape**: each cell calls `Utils.load_dim_from_csv(...)` and
  then `transform_detail_log_insert(spark, ..., **result)`. The helper
  catches its own exceptions and returns
  `{"status": "failed", ...}` — so the cell never raises, but the
  notebook's `pipeline_step_log` row also never flips to
  `STATUS_FAILED`. A real upstream failure (missing CSV, schema drift)
  records as "running" in the audit views.
- **Fix options**:
  (a) wrap each per-dim block in `try/except`, OR
  (b) check `result["status"] == STATUS_FAILED` and raise after the
  `transform_detail_log_insert` call.
- **Suggested branch**: pair with P1-1 (same notebook).

### P1-4. `001-Truncate_All_Tables.ipynb` bypasses `notebook_init`

- **File**: `databricks_code/notebooks/001-Truncate_All_Tables.ipynb`, cell 0.
- **Current content**:
  ```python
  dbutils.widgets.text("catalog", "dev_vinoworld")
  CATALOG = dbutils.widgets.get("catalog")
  BRONZE  = f"{CATALOG}.bronze"
  SILVER  = f"{CATALOG}.silver"
  GOLD    = f"{CATALOG}.gold"
  AUDIT   = f"{CATALOG}.audit"
  ```
- **Problems**:
  1. Duplicates the catalog-derivation logic instead of `%run
     "../libs/notebook_init"` — violates CLAUDE.md § 4 *Load-bearing
     values must be centralized*.
  2. Hardcodes `dev_vinoworld` as the widget default. The reset job
     in `databricks.yml` does pass `catalog` via job parameters, so the
     widget IS overridden in the bundled flow — but a standalone
     manual run defaults to dev_vinoworld and truncates it.
  3. The notebook writes no `pipeline_step_log` row at all — a
     destructive operation is invisible in the audit hierarchy.
- **Fix**: replace cell 0 with `%run "../libs/notebook_init"` and rely
  on the constants/widgets it sets. Add a step-log init/close-out pair
  while you're in there.

### P1-5. `target_table` is not a real table name

- **Files**:
  - `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb`
    cell 1 → `target_table = "Move datafiles from archive to re-run"`
  - `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb`
    cell 3 → `target_table = f"{SILVER} dim_currency, dim_date,
    dim_exchange_rate, dim_store, dim_territory"`
    (missing dot after `{SILVER}`; commas inside the identifier slot).
- **Problem**: `pipeline_step_log.target_table` is a fully-qualified
  table name everywhere else. The column is nullable; either `None`
  or one canonical name is honest. The two values above flow through
  to `vw_pipeline_step_drilldown.step_target_table`, breaking any BI
  user who parses it.

### P1-6. `init_pipeline_run_log.py` PIPELINE_NAME is a test value

- **File**: `databricks_code/libs/init_pipeline_run_log.py` L27.
- **Current content**:
  ```python
  PIPELINE_NAME     = "Vinoworld TEST LOAD"
  ```
- The literal pipeline_name written to every `pipeline_log` row in
  every target — `user`, `dev`, `staging`, `prod`, `azure_prod`. The
  `vw_pipeline_run_summary` view surfaces this string to anyone
  reading the audit dashboard.
- **Fix**: rename to a durable name (`"vinoworld_elt_pipeline"` matches
  the bundle job key) — either as a module constant or via a third
  `sys.argv` from `databricks.yml`.

### P1-7. `init_pipeline_run_log.py` PIPELINE_STATUS is a string literal

- **File**: `databricks_code/libs/init_pipeline_run_log.py` L28.
- **Current content**:
  ```python
  PIPELINE_STATUS   = "running"
  ```
- Same vocabulary as the notebook `STATUS_RUNNING` constant — but this
  is a `spark_python_task` that doesn't run `notebook_init`, so the
  constant isn't in scope.
- **Recommendation**: move the four status strings (`"running"`,
  `"succeeded"`, `"failed"`, `"no_files"`) into `pipeline_logging.py`
  as module constants. Both `spark_python_task` scripts can then
  import from there; `notebook_init` can re-export them. Collapses
  three of the four current sources of the status vocabulary into one.

---

## P2 — Consistency / hygiene

### P2-1. Every notebook uses `step_sequence = 1`

- **Files**: every step-log init cell across bronze, silver, gold and
  the two root lifecycle notebooks (`000-`, `001-`).
- The column is meant to record ordinal position (`pipeline_step_log_upsert`
  docstring: "ordinal position of this step (1, 2, 3...)"). With every
  step at sequence 1, it's dead data.
- Decision needed: drop the column, populate from a bundle parameter,
  or document the deviation in `deviations.md`.

### P2-2. `STORE_NAME = "Arancione, Celeste, Verde"` in `brz_04_products`

- **File**: `databricks_code/notebooks/bronze/brz_04_products.ipynb` cell 2.
- Passed to `ingestion_log_insert` as `source_system`, which the
  helper's docstring and helpers.md describe as a single store value
  (`'arancione' | 'celeste' | 'verde'`). DDL accepts it (just `NOT NULL
  STRING`) but the documented contract is broken.
- **Fix options**: split into one ingest call per derived store_name,
  OR update the helper's contract to allow multi-source values and
  reflect in helpers.md.

### P2-3. `brz_03_verde_sales` uses string literal `"Verde"`

- **File**: `databricks_code/notebooks/bronze/brz_03_verde_sales.ipynb`
  cell 6 (ingestion_log call).
- brz_01 / brz_02 / brz_04 define `STORE_NAME` in cell 2 and pass it.
  brz_03 inlines `"Verde"`.
- **Fix**: add `STORE_NAME = "Verde"` in cell 2 and reference it.

### P2-4. `%load_ext autoreload` / `%autoreload 2` in all four silver notebooks

- **Files**: `slvr_01_load_dim_fromcsv.ipynb`, `slvr_02_load_dim_product.ipynb`,
  `slvr_03_load_dim_region.ipynb`, `slvr_04_load_sales.ipynb` —
  all four have the two magic lines in their constants cell.
- Iteration aid; inert in deployed jobs. Bronze/gold/root don't have
  them.
- **Fix**: remove.

### P2-5. `transform_detail_log_insert` not exported by `notebook_init`

- **File**: `databricks_code/libs/notebook_init.ipynb` cell 0 import line.
- Every silver/gold notebook carries the same boilerplate:
  ```python
  # transform_detail_log_insert isn't in notebook_init's central import yet —
  # pull it in here so this notebook can log per-transform audit rows.
  from pipeline_logging import transform_detail_log_insert
  ```
  in `slvr_01` cell 2, `slvr_02` cell 2, `slvr_04` cell 2, `gold_01`
  cell 2.
- **Fix**: add to `notebook_init`'s import, delete the scattered
  per-notebook imports, update helpers.md.

### P2-6. `REPORTING` constant documented but not exported

- `.claude/project/helpers.md` claims `REPORTING` is one of the
  constants injected by `notebook_init`. `databricks_code/libs/notebook_init.ipynb`
  does not define it. Only `setup/catalog_ddl.ipynb` defines `REPORTING`
  locally (`REPORTING = f"{CATALOG}.reporting"`).
- **Fix**: add `REPORTING = f"{CATALOG}.reporting"` to `notebook_init`
  (cheap; aligns code to docs), OR remove the claim from helpers.md.

### P2-7. Inconsistent task-key naming in `databricks.yml`

- **File**: `databricks_code/databricks.yml`, `vinoworld_elt_pipeline.tasks`.
- Bronze tasks use `brz_*` prefix
  (`brz_load_arancione_sales_files`, etc.).
- Silver/gold tasks use no layer prefix
  (`load_dim_product`, `load_dim_region`, `load_dims_from_csv`,
  `load_silver_sales`, `load_gold_sales_fact`).
- CLAUDE.md § 3 warns: don't normalize without checking. **Question
  for user**: which is canonical?

### P2-8. `seed_volumes.ipynb` not wired into the setup job

- `databricks_code/setup/seed_volumes.ipynb` exists, but
  `vinoworld_environment_setup` in `databricks.yml` only runs
  `provision_catalog` (`catalog_ddl.ipynb`).
- A brand-new target catalog gets schema/tables but no source data,
  surprising for anyone trying to spin up `staging` for the first time.
- Decide: wire as a second setup task, or delete and document
  manual seeding.

### P2-9. Hardcoded `vinoworld.*` table refs in `%skip` debug cells

- All inside `%skip` guards, so they never run in deployed jobs. But
  un-skipping in dev queries prod.
- Files: `brz_01` cells 8/9, `brz_02` cell 8, `brz_04` cells 8/9,
  `slvr_01` cell 9, `slvr_02` cells 7/8, `slvr_04` cells 6/7,
  `gold_01` cells 6/7/8.
- **Fix**: replace `vinoworld.<schema>.<table>` with
  `{CATALOG}.<schema>.<table>` (the cells are inside notebooks where
  `CATALOG` is in scope).

### P2-10. Stale backup file in repo

- `databricks_code/databricks.yml-WithStartCleanTasks` (201 lines).
  Delete and rely on git history.

### P2-11. `slvr_03_load_dim_region.ipynb` cell 2 `%skip` block hardcodes the catalog

- **File**: `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`, cell 2.
- **Current content**:
  ```
  %skip
  CATALOG = "dev_vinoworld"
  print(CATALOG)
  BRONZE = "dev_vinoworld.bronze"
  SILVER = "dev_vinoworld.silver"
  ```
- Inert because of `%skip`; signals a dev-time override never cleaned up.

### P2-12. `slvr_03` cell 5 banner names the wrong target

- **File**: same notebook, cell 5 header comment.
- **Current text**: `# Pipeline: vinoworld.bronze.products →
  vinoworld.silver.dim_product` — copy-pasted from `slvr_02`. Should
  say `→ vinoworld.silver.dim_region`.

### P2-13. `slvr_03` cell 6 `%skip` references the wrong table

- **File**: same notebook, cell 6.
- **Current code**:
  ```python
  metrics = spark.sql(f"DESCRIBE HISTORY dev_vinoworld.silver.dim_product LIMIT 1")
  ```
  in a notebook that loads `dim_region`. Also subject to P2-9 (catalog
  hardcoded).

### P2-14. `pipeline_utils.py` has `import traceback` mid-file

- **File**: `databricks_code/libs/pipeline_utils.py` L55.
- Module-level but not at the top of the file. Same `import
  traceback` appears in `slvr_01`, `slvr_02`, `slvr_03` cell 2 — where
  it's never used (those notebooks call `Utils.capture_exception`,
  which internally uses traceback).
- **Fix**: move to top of `pipeline_utils.py`; delete unused imports
  from silver constants cells.

### P2-15. `move_all_files` re-raises as bare `Exception(...)`

- **File**: `databricks_code/libs/pipeline_utils.py` L131.
- **Current code**:
  ```python
  raise Exception(f"Fatal move_all_files error: {str(e)}\n{traceback.format_exc()}")
  ```
- Loses original exception class and chain. Prefer `raise
  RuntimeError(...) from e` or bare `raise`.

### P2-16. `capture_exception` uses a Python 3.13+ API

- **File**: `databricks_code/libs/pipeline_utils.py` L60.
- **Current code**: `te.exc_type.__name__   # Python 3.13+`.
- Free Edition's serverless `environment_version: "5"` Python version
  isn't pinned in this repo. If it's <3.13, this raises
  `AttributeError` the first time `capture_exception` runs.
- **Fix**: one-line probe in a notebook (`import sys;
  print(sys.version_info)`). If 3.13+ is guaranteed, drop the comment;
  if not, fall back to `type(exc).__name__`.

---

## P3 — Documentation / cosmetic

### P3-1. `JDD TEST EDIT` markers

- `databricks_code/libs/init_pipeline_run_log.py` L4 comment.
- `databricks_code/notebooks/silver/slvr_02_load_dim_product.ipynb`
  cell 0 markdown body.

### P3-2. `slvr_03` cell 0 markdown mentions Claude

- **File**: `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`, cell 0.
- **Text**: "CLAUDE deleted the cell that populated dim_region when it
  deleted the %skip cells. Had to add it back in"
- Scratch note; safe to delete.

### P3-3. `brz_01` cell 3 init comment lacks `(STATUS_RUNNING)` suffix

- `brz_02`, `brz_03`, `brz_04` cell 3 banners end with
  `(STATUS_RUNNING)`; `brz_01` does not. Trivial.

### P3-4. `slvr_01` cell 2 docstring says "Arancione Bronze load"

- **File**: `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb`
  cell 2 docstring.
- Copy-pasted from a bronze notebook. `slvr_03` cell 3 has the same
  mis-labelling.

### P3-5. `000-MoveFilesFromArchiveToBronze` cell 1 banner says "Cell 3"

- **File**: `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 1.
- Banner comment reads `# Cell 3 — Step log init (STATUS_RUNNING)` —
  but it's cell 1. Drop the cell-number annotation entirely; notebooks
  re-index when cells move.

### P3-6. `init_pipeline_run_log.py` comment grammar

- L1–4: "A simple script that initializes that inserts a record into
  pipeline_run_log" — duplicated "that".

---

## Suggested branch grouping

1. **`fix-init-pipeline-name-and-status`** — P1-6 + P1-7.
   Touches `init_pipeline_run_log.py` (and ideally
   `finalize_pipeline_run_log.py` + `pipeline_logging.py` to centralize
   the status constants).
2. **`fix-slvr03-and-slvr01-cleanup`** — P1-1 (already in BACKLOG) +
   P1-2 + P1-3 + P2-11 + P2-12 + P2-13 + P3-2 + P3-4. One silver
   directory; safe to bundle.
3. **`fix-truncate-uses-notebook-init`** — P1-4. Discrete, small.
4. **`fix-target-table-strings`** — P1-5. Two files, one-line edits.
5. **`chore-hygiene`** — P2-4 (autoreload), P2-9 (`%skip` catalog
   literals), P2-10 (stale yml backup), P2-14 (move `import traceback`,
   drop unused imports), P3-1 (`JDD TEST EDIT`), P3-3, P3-5, P3-6.
   No risk; one cleanup commit.

Parked, decision required (no action this round):
P0-1 (dashboard — deferred per user), P2-1 (step_sequence design),
P2-2 (multi-source `source_system` contract), P2-5 / P2-6
(`notebook_init` exports), P2-7 (task-key naming), P2-8 (seed_volumes
wiring), P2-15 (`move_all_files` exception shape), P2-16 (Python 3.13
dependency).
