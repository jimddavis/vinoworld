# Catalog Mapping — Sequenced Fix Plan

**Companion document to:** [`catalog_mapping_audit.md`](catalog_mapping_audit.md)
**Status:** Design / not yet implemented
**Goal:** Restore end-to-end catalog isolation so `--target dev` writes exclusively to `dev_vinoworld.*`, `--target staging` to `staging_vinoworld.*`, and `--target prod` (or `--target azure_prod`) to `vinoworld.*`.

---

## Design principles

1. **One concept per phase.** Each phase introduces exactly one change. After each, the bundle deploys cleanly, the partial pipeline runs, and one specific assertion holds. No phase introduces two new mechanisms at once.
2. **Foundation first.** Phase 1 (the `%run` path) is a no-op functionally — but every later phase depends on it because they all modify `notebook_init.ipynb` or `pipeline_logging.py` and need those edits to actually load at run time. Fixing the data-path bugs *before* the load-path bug would mask whether subsequent edits took effect.
3. **Reversibility.** Every phase is a small, self-contained git commit. Rolling back a phase = `git revert` of one commit. No phase deletes data; the only destructive workspace action (deleting `/Workspace/Shared/`) is the very last phase, after multi-target validation has already passed.
4. **Validation gate is binary.** Every phase has a single SQL or CLI check that returns an unambiguous yes/no answer. Don't proceed until the gate passes.
5. **Don't refactor.** Per `CLAUDE.md`: "Preserve the existing pipeline logic. The notebooks work. The goal is packaging, not rewriting." This plan changes only the strings and one function call in `pipeline_logging.py`. It does not restructure the audit module, change write strategies, or touch business logic.

---

## Dependency graph

```
Phase 0 (baseline)
   │
   ▼
Phase 1: fix %run paths   ◄── foundation; all later notebook_init edits depend on this
   │
   ├──────────────────────┬──────────────────────┬──────────────────────┐
   ▼                      ▼                      ▼                      ▼
Phase 2: parameterize    Phase 4: fix         Phase 5: fix slvr_02   Phase 6: fix slvr_03
pipeline_logging         000-MoveFiles        hardcoded SQL          hardcoded SQL
   │                      RAW_FILES
   ▼
Phase 3: pass catalog
to init_pipeline_run_log
   │
   ▼
Phase 7: diagnostic cleanup (optional)
   │
   ▼
Phase 8: multi-target validation
   │
   ▼
Phase 9: delete stale /Workspace/Shared/
```

Phases 4, 5, 6 are mutually independent and could in principle run in parallel — but per design principle 1 (one concept per phase), they run sequentially.

---

## Phase 0 — Baseline & safety net

**Purpose:** Capture current state so we can prove each later phase changed something specific. Build the validation harness once.

**Actions**

1. Confirm current branch is `restructure_folders` and working tree is clean apart from the new `databricks_code/` and `prompts/` (already noted in git status).
2. Inspect the deployed workspace state to know what we're up against:
   ```bash
   databricks workspace list /Workspace/Shared/
   ```
   Record whether `/Workspace/Shared/notebook_init` exists. If it does, **leave it alone** until Phase 9.
3. Drop the local sync snapshot so the next deploy is unambiguous:
   ```bash
   rm -rf databricks_code/.databricks/bundle/dev/sync-snapshots/
   ```
4. Save the exact validation queries you'll run after each phase. Append the file to `docs/`:
   - `docs/catalog_mapping_validation_queries.sql` — five queries that return row counts from `vinoworld.audit.pipeline_log`, `vinoworld.silver.dim_product`, `vinoworld.silver.dim_region`, `dev_vinoworld.audit.pipeline_log`, `dev_vinoworld.silver.dim_product`, `dev_vinoworld.silver.dim_region` filtered by a known recent timestamp window.

**Validation gate**

- `databricks bundle validate --target dev` returns clean.
- The validation-query file runs without syntax errors against the workspace (use `databricks sql` or run it in a notebook).

**Rollback:** none needed — read-only.

---

## Phase 1 — Fix `%run` paths (foundation)

**Purpose:** Make every pipeline notebook load `notebook_init` from the *bundle-deployed* copy under `${workspace.root_path}/files/libs/`, not from `/Workspace/Shared/`. Until this is done, all subsequent edits to `libs/notebook_init.ipynb` are invisible at run time.

**Actions** — replace the `%run` line in cell 1 of each notebook:

| File | New `%run` line |
|---|---|
| `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` | `%run "../libs/notebook_init"` |
| `databricks_code/notebooks/bronze/brz_01_arancione_sales.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/bronze/brz_02_celeste_sales.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/bronze/brz_03_verde_sales.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/bronze/brz_04_products.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/silver/slvr_02_load_dim_product.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/silver/slvr_04_load_sales.ipynb` | `%run "../../libs/notebook_init"` |
| `databricks_code/notebooks/gold/gold_01_load_sales_fact.ipynb` | `%run "../../libs/notebook_init"` |

**Why relative paths.** Databricks `%run` resolves paths relative to the calling notebook's location. After `databricks bundle deploy --target dev`, the workspace tree is:
```
${workspace.root_path}/files/
    libs/notebook_init           (deployed from databricks_code/libs/)
    notebooks/000-MoveFilesFromArchiveToBronze
    notebooks/bronze/brz_01_arancione_sales
    notebooks/silver/slvr_02_load_dim_product
    ...
```
From `notebooks/bronze/brz_01_…`, two levels up gets to `files/`, then down into `libs/notebook_init`. Relative paths survive a future change of `workspace.root_path` (e.g., when porting to Azure) without further edits. `${var.shared_lib_path}` cannot be used inside `%run` — `%run` is a string literal, not a templated expression.

**Validation gate**

1. `databricks bundle deploy --target dev`
2. Open the deployed `notebooks/bronze/brz_01_arancione_sales` notebook in the workspace UI and **run only cells 1 and 2**. After cell 2 prints, the notebook's widgets panel should show `catalog = dev_vinoworld` (because the bundle injects the job parameter as a widget default). Add a temporary cell that runs `print(CATALOG, BRONZE, RAW_FILES)` — expect:
   ```
   dev_vinoworld dev_vinoworld.bronze /Volumes/dev_vinoworld/datafiles/
   ```
3. Remove the temporary print cell before committing.

If the gate fails: `%run` returns a "not found" error → confirm the relative path against the deployed tree (`databricks workspace list ${workspace.root_path}/files/libs/`).

**Rollback:** revert the commit. The notebooks return to using `/Workspace/Shared/notebook_init`.

---

## Phase 2 — Parameterize `pipeline_logging.py` audit table names

**Purpose:** Stop hardcoding `vinoworld.audit.*` in the module. After this phase, audit log writes go to `{CATALOG}.audit.*` for whichever target is running.

**Design choice — setter vs per-call parameter.** Two viable shapes:

| Approach | Change footprint | Risk |
|---|---|---|
| **A. Module-level `configure(audit_schema)` setter** (proposed) | 1 new function + replace 4 constants with 1 helper. Call sites unchanged. | Module is no longer stateless — second `configure()` call from a separate notebook in the same JVM could surprise. Acceptable here because every notebook's first cell is `%run notebook_init`, which calls `configure(AUDIT)` consistently. |
| **B. Add `audit_schema=` keyword to every public function** | All four function signatures change; every caller in every notebook updates. | Larger blast radius; touches notebooks this plan otherwise leaves alone. |

Approach **A** is cheaper and matches design principle 5 (don't refactor). If at any point the module gains stateless-purity requirements (e.g., used from multiple jobs in the same cluster), revisit.

**Actions**

1. **`databricks_code/libs/pipeline_logging.py`** — at module top (after imports), add:
   ```python
   _AUDIT_SCHEMA: str | None = None

   def configure(audit_schema: str) -> None:
       global _AUDIT_SCHEMA
       _AUDIT_SCHEMA = audit_schema

   def _audit(table: str) -> str:
       if _AUDIT_SCHEMA is None:
           raise RuntimeError(
               "pipeline_logging.configure(audit_schema) must be called "
               "before any logging function (typically from notebook_init)."
           )
       return f"{_AUDIT_SCHEMA}.{table}"
   ```
2. **`pipeline_logging.py`** — remove the four module-level constants:
   - line 18: `PIPELINE_LOG_TABLE = "vinoworld.audit.pipeline_log"` → delete
   - line 85: `_STEP_LOG_TABLE = "vinoworld.audit.pipeline_step_log"` → delete
   - line 183: `_TRANSFORM_DETAIL_TABLE = "vinoworld.audit.transform_detail_log"` → delete
   - line 328: `_INGESTION_LOG_TABLE = "vinoworld.audit.ingestion_log"` → delete
3. **`pipeline_logging.py`** — at each call site (around lines 72, 167, 317, 378), replace the constant reference with the helper:
   - `PIPELINE_LOG_TABLE` → `_audit('pipeline_log')`
   - `_STEP_LOG_TABLE` → `_audit('pipeline_step_log')`
   - `_TRANSFORM_DETAIL_TABLE` → `_audit('transform_detail_log')`
   - `_INGESTION_LOG_TABLE` → `_audit('ingestion_log')`
4. **`databricks_code/libs/notebook_init.ipynb`** cell 0 — right after the line `AUDIT = f"{CATALOG}.audit"`, add:
   ```python
   import pipeline_logging
   pipeline_logging.configure(AUDIT)
   ```
   (`pipeline_logging` is already on `sys.path` from earlier in the cell.)

**Validation gate**

1. `databricks bundle deploy --target dev`
2. Run `vinoworld_elt_pipeline` for `--target dev` (full job is fine; if you want a smaller blast radius, run only `init_pipeline_log` + `truncate_all_tables` + `brz_load_arancione_sales_files`).
3. Query both catalogs:
   ```sql
   SELECT 'dev'  AS where, COUNT(*) FROM dev_vinoworld.audit.pipeline_step_log
     WHERE started_timestamp > current_timestamp() - INTERVAL 30 MINUTES
   UNION ALL
   SELECT 'prod' AS where, COUNT(*) FROM vinoworld.audit.pipeline_step_log
     WHERE started_timestamp > current_timestamp() - INTERVAL 30 MINUTES;
   ```
   Expected: `dev` row > 0; `prod` row = 0 (no new rows during the test window).

**Rollback:** revert the commit. Constants return; `configure()` and helper are removed; notebook_init's call disappears.

---

## Phase 3 — Forward `catalog` to `init_pipeline_run_log.py`

**Purpose:** Close the one remaining audit-log leak. The `init_pipeline_log` task is a `spark_python_task`, not a notebook, so it has no widgets and currently receives only `shared_lib_path`.

**Actions**

1. **`databricks_code/databricks.yml`** lines 85–92 — add a second positional parameter:
   ```yaml
   - task_key: init_pipeline_log
     depends_on:
       - task_key: truncate_all_tables
     spark_python_task:
       python_file: ./libs/init_pipeline_run_log.py
       parameters:
         - "${var.shared_lib_path}"
         - "${var.catalog}"             # NEW
     environment_key: Default
   ```
2. **`databricks_code/libs/init_pipeline_run_log.py`** — read the new arg and configure logging:
   ```python
   import sys
   sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else "/Workspace/Shared")
   catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"

   from pipeline_logging import pipeline_log_upsert, configure
   configure(f"{catalog}.audit")
   # … rest of script unchanged
   ```

**Validation gate**

1. `databricks bundle deploy --target dev`
2. `databricks bundle run vinoworld_elt_pipeline --target dev`
3. After the `init_pipeline_log` task completes:
   ```sql
   SELECT pipeline_run_id, pipeline_name, status, started_timestamp
   FROM dev_vinoworld.audit.pipeline_log
   ORDER BY started_timestamp DESC LIMIT 1;
   ```
   Expected: one new row, status `running`, started in the last few minutes.
4. Same query against `vinoworld.audit.pipeline_log` — expected: no new rows in the same window.

**Rollback:** revert the commit. The task returns to passing only `shared_lib_path`; the script falls back to `"vinoworld"`.

---

## Phase 4 — Remove the `RAW_FILES` literal in `000-MoveFilesFromArchiveToBronze.ipynb`

**Purpose:** Restore the parameterized `RAW_FILES` value that `notebook_init` already provides.

**Actions** — `databricks_code/notebooks/000-MoveFilesFromArchiveToBronze.ipynb` cell 2:

- Delete the line `RAW_FILES = "/Volumes/vinoworld/datafiles/"`.
- Delete the lines `import sys` and `sys.path.append("/Workspace/Shared")` — `notebook_init` (loaded via the now-correct relative `%run`) already configures `sys.path` from the `shared_lib_path` widget.
- Leave `SOURCE_PATH = f"{RAW_FILES}{SOURCE_SUBPATH}"` and downstream code untouched. `RAW_FILES` is now inherited from `notebook_init` as `f"/Volumes/{CATALOG}/datafiles/"`.

**Validation gate**

1. `databricks bundle deploy --target dev`
2. Run only the `move_datafiles_from_archive` task. It should report files moved within `/Volumes/dev_vinoworld/datafiles/<subpath>/archive/` (or report "no files to move" — whichever applies).
3. `databricks fs ls dbfs:/Volumes/vinoworld/datafiles/arancione/` (the wrong location) — expected: no recent file movement timestamps for this run.

**Rollback:** revert the commit. The literal returns.

---

## Phase 5 — Convert `slvr_02_load_dim_product.ipynb` hardcoded SQL to f-strings

**Purpose:** Make the active MERGE/INSERT statements honor `{TARGET_TABLE}` and a new `{SOURCE_TABLE}` constant.

**Actions** — `databricks_code/notebooks/silver/slvr_02_load_dim_product.ipynb`:

1. Cell 2 (constants) — add:
   ```python
   SOURCE_TABLE = f"{BRONZE}.products"
   ```
   Confirm `TARGET_TABLE = f"{SILVER}.dim_product"` is already there (it is per the audit).
2. Cell 5 — convert the SQL to an f-string and substitute:
   - `vinoworld.bronze.products` → `{SOURCE_TABLE}`
   - Wrap the SQL with `spark.sql(f""" … """)` if not already wrapped.
3. Cell 6 — same pattern. Replace every literal `vinoworld.silver.dim_product` with `{TARGET_TABLE}`. The cell already runs the SQL via `spark.sql` based on the audit; check the wrapping is f-string-aware.
4. Cell 7 — same pattern. Replace every literal `vinoworld.silver.dim_product` with `{TARGET_TABLE}`.

**Critical check before committing:** the audit confirmed cells 5–7 are *not* `%skip`. Don't accidentally skip them.

**Validation gate**

1. `databricks bundle deploy --target dev`
2. Run `vinoworld_elt_pipeline --target dev` through at least the `slvr_load_dim_product` task. Earlier silver and bronze tasks must run too (they're upstream dependencies).
3. ```sql
   SELECT 'dev' AS where, COUNT(*) FROM dev_vinoworld.silver.dim_product
   UNION ALL
   SELECT 'prod', COUNT(*) FROM vinoworld.silver.dim_product
     WHERE updated_ts > current_timestamp() - INTERVAL 30 MINUTES;
   ```
   Expected: `dev` count > 0; `prod` recent count = 0.

**Rollback:** revert the commit.

---

## Phase 6 — Convert `slvr_03_load_dim_region.ipynb` hardcoded SQL + remove the dormant override cell

**Purpose:** Same as Phase 5 for `dim_region`. Also remove the `%skip` cell 2 that re-defines `CATALOG = "Vinoworld"` — leaving it is a foot-gun (any future hand re-run of "all cells" would silently corrupt the catalog).

**Actions** — `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`:

1. Cell 3 (constants) — add:
   ```python
   SOURCE_TABLE = f"{BRONZE}.products"
   ```
   Confirm `TARGET_TABLE = f"{SILVER}.dim_region"` is already there.
2. Cell 6 — convert active SQL to f-string. Replace `vinoworld.silver.dim_region` → `{TARGET_TABLE}` and `vinoworld.bronze.products` → `{SOURCE_TABLE}`.
3. **Delete cell 2 entirely** (the `%skip` cell containing `CATALOG = "Vinoworld"` and `RAW_FILES = "/Volumes/vinoworld/datafiles/"`). Don't just blank it — delete the cell so it can never be un-skipped accidentally.

**Validation gate**

1. `databricks bundle deploy --target dev`
2. Run the `slvr_load_dim_region` task and its upstreams.
3. Same shape as Phase 5:
   ```sql
   SELECT 'dev' AS where, COUNT(*) FROM dev_vinoworld.silver.dim_region
   UNION ALL
   SELECT 'prod', COUNT(*) FROM vinoworld.silver.dim_region
     WHERE updated_ts > current_timestamp() - INTERVAL 30 MINUTES;
   ```
   Expected: `dev` count > 0; `prod` recent count = 0.

**Rollback:** revert the commit. Cell 2 reappears with `%skip` intact.

---

## Phase 7 — Diagnostic-cell cleanup (cosmetic, optional)

**Purpose:** Eliminate the remaining active hardcoded `vinoworld.*` references in diagnostic SELECT cells. None of these write data, but they will return misleading counts (or table-not-found errors) when the active target is anything other than `vinoworld`.

**Actions** — for each cell listed below, either prepend `%skip` or convert the SQL to `spark.sql(f"…")` with `{TARGET_TABLE}` / `{BRONZE}.<table>` substitution:

| File | Cell | Current | Recommended |
|---|---|---|---|
| `bronze/brz_01_arancione_sales.ipynb` | 8 | `SELECT COUNT(*) FROM vinoworld.bronze.sales_arancione` | f-string with `{TARGET_TABLE}` |
| `bronze/brz_03_verde_sales.ipynb` | 9 | `SELECT * FROM vinoworld.audit.pipeline_step_log …` | `%skip` (it's a dev-only inspection) |
| `bronze/brz_03_verde_sales.ipynb` | 11 | `select count(*) from vinoworld.bronze.sales_verde` | f-string with `{TARGET_TABLE}` |
| `bronze/brz_04_products.ipynb` | 12 | `select count(*) from vinoworld.bronze.products` | f-string with `{TARGET_TABLE}` |
| `bronze/brz_04_products.ipynb` | 13 | `select * from vinoworld.bronze.products …` | `%skip` |
| `silver/slvr_01_load_dim_fromcsv.ipynb` | 3 | `target_table = "vinoworld.silver dim_currency, …"` (a log label, not SQL) | `target_table = f"{SILVER}.dim_csv_load (multi-table)"` |
| `silver/slvr_04_load_sales.ipynb` | 8 | `select * from vinoworld.silver.sales` | `%skip` |

**Validation gate**

1. Re-run the scan from `catalog_mapping_audit.md` Appendix B. Expected output: every remaining `vinoworld` line is either marked `[SKIP]` or appears inside a widget-default `dbutils.widgets.text("catalog", "vinoworld")` (informational, by design), or inside `seed_volumes.ipynb` `SOURCE_CATALOG = "vinoworld"` (intentional).

**Rollback:** revert the commit.

---

## Phase 8 — Multi-target validation

**Purpose:** Confirm the same fix works for `staging` (and prove the user's earlier assumption was correct that all targets were broken).

**Actions**

1. `databricks bundle deploy --target staging`
2. `databricks bundle run vinoworld_environment_setup --target staging` (creates `staging_vinoworld` catalog + schemas if not yet present)
3. `databricks bundle run vinoworld_elt_pipeline --target staging`
4. Run the full validation matrix:
   ```sql
   SELECT 'pipeline_log'   AS check, COUNT(*) FROM staging_vinoworld.audit.pipeline_log
     WHERE started_timestamp > current_timestamp() - INTERVAL 30 MINUTES
   UNION ALL
   SELECT 'dim_product',     COUNT(*) FROM staging_vinoworld.silver.dim_product
   UNION ALL
   SELECT 'dim_region',      COUNT(*) FROM staging_vinoworld.silver.dim_region
   UNION ALL
   SELECT 'sales_fact',      COUNT(*) FROM staging_vinoworld.gold.sales_fact;
   ```
   Expected: all four > 0.

5. Same shape against `vinoworld.*` for the same time window — expected: zero new rows.

**Rollback:** none — read-only verification phase.

---

## Phase 9 — Delete stale `/Workspace/Shared/` (final cleanup)

**Purpose:** Eliminate the workspace fallback that nobody should ever resolve to. After Phase 1 nothing references `/Workspace/Shared/notebook_init` from this project — but if any hand-run or unrelated notebook still calls that path, this phase catches the mistake immediately rather than silently loading stale code.

**Actions**

1. `databricks workspace list /Workspace/Shared/` — confirm what's there. If anything other than the project's old `notebook_init`, `pipeline_logging.py`, `pipeline_utils.py`, `catalog_setup.py` is present, stop and ask.
2. ```bash
   databricks workspace delete -r /Workspace/Shared/
   ```
   (Confirm with the user before running — this is destructive on a shared workspace path.)

**Validation gate**

- Re-run `vinoworld_elt_pipeline --target dev` once more. Expected: still passes. (If it fails with "notebook not found" pointing at `/Workspace/Shared/`, a `%run` was missed in Phase 1.)

**Rollback:** restore the four files from local `databricks_code/libs/` by uploading via `databricks workspace import`.

---

## Decision log

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| `pipeline_logging` parameterization shape | module-level `configure()` setter | per-call `audit_schema=` kwarg on every function | Smaller change footprint, no notebook edits required, matches the "don't refactor" principle. Trade-off: introduces module state. |
| `%run` path style | relative (`../../libs/notebook_init`) | absolute (`/Workspace/Users/<email>/.bundle/.../files/libs/notebook_init`) | Survives target / workspace changes without further edits; the absolute path differs across `dev` / `prod` / `azure_prod`. |
| Order of audit-log fix vs silver-table fix | audit first (Phase 2) before slvr_02 (Phase 5) | other order | The audit-log gate is the cleanest single-task validation: it produces a row on *every* notebook task, so we can prove the parameterization works without running the full ELT. |
| Delete `/Workspace/Shared/` | last (Phase 9) | first or in Phase 1 | If we delete it before all `%run` paths are fixed and we missed one, the partial run fails. By Phase 9, every `%run` has been demonstrated to load from the bundle path. |
| Phase 7 (diagnostic cleanup) | optional, deferable | mandatory | These are read-only and don't affect data correctness. Defer if Jim wants to ship the catalog isolation fix sooner and revisit cosmetic cleanup later. |

---

## Out of scope (intentional)

- **Refactoring `pipeline_logging.py` into a class** — would solve the module-state concern but is a bigger change than the audit-driven scope.
- **Adding a Bundle pre-commit / CI test** that runs the Appendix B scan and fails on any new active `vinoworld` literal — strong recommendation for future work, but per `CLAUDE.md`: "GitHub Actions CI/CD is out of scope for now."
- **Switching from `%run` shared notebooks to a Python wheel** — architecturally cleaner (proper imports, packaging, pythonpath in environments), but a larger restructuring than this fix plan should attempt.
- **Updating `notebooks/notebook_init.ipynb`** (the stale copy referenced in `CLAUDE.md`'s project structure note) — `databricks_code/libs/notebook_init.ipynb` is the bundle's source of truth; the stale one in the old `notebooks/` tree should be deleted, but that belongs in a separate housekeeping task.

---

## When you're ready to execute

Run `/sc:implement` referencing this document, or step through phases manually with `databricks bundle deploy` + the validation gate after each one. Don't compress phases. The whole point of the sequencing is that if Phase 4 breaks something, you know the bug is in Phase 4's three lines of changes and not buried in twelve mixed edits.
