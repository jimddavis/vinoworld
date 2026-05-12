# Deliberate deviations from best practice

Each item here differs from a sensible default and IS INTENTIONAL. Do not
"normalize" these. The reason is recorded next to each so future edits can
make informed judgment calls.

## Silver `dim_*` columns are PascalCase

- **Best practice**: snake_case columns throughout.
- **This project**: silver `dim_*` tables use PascalCase
  (`ProductNo`, `CurrencyCode`, `InsertedDate`, `UpdatedDate`, `IsRowCurrent`,
  `EffectiveDate`, `EndDate`, `RowHash`).
- **Why**: The silver dimensions were ported from a SQL Server warehouse where
  these columns already existed in PascalCase. Renaming across silver, gold
  views, fact joins, and reporting views was judged not worth the churn for
  a learning project.
- **Apply where**: silver `dim_*` tables only. Bronze, silver `sales`, gold,
  audit, and reporting all use snake_case.
- **Do not**: introduce PascalCase anywhere else; do not rename existing
  silver dim columns.

## Silver `sales` and Gold `sales_fact` use INSERT OVERWRITE, not MERGE

- **Best practice**: MERGE for idempotent writes.
- **This project**: `silver.sales` and `gold.sales_fact` use
  `INSERT OVERWRITE` — full atomic replace each run.
- **Why**: Upstream silver is itself a full rebuild. MERGE on the downstream
  fact would require a second DELETE pass to retire rows that no longer
  exist upstream. INSERT OVERWRITE replaces atomically — readers see either
  the previous complete dataset or the new one, never empty.
- **Apply where**: silver-to-silver and silver-to-gold full-rebuild flows.
  Use MERGE for incremental/idempotent ingest (bronze) and SCD2 (silver dims).

## Bronze MERGE uses `WHEN NOT MATCHED` only

- **Best practice**: MERGE with both MATCH-UPDATE and NOT-MATCHED-INSERT.
- **This project**: bronze MERGE is `WHEN NOT MATCHED THEN INSERT *` only.
- **Why**: Bronze rows are immutable. Changed source data produces a new
  `row_hash` and appears as a new versioned row alongside the original.
  Bronze is a versioned raw store, not a current-state mirror.
- **Apply where**: every bronze MERGE.

## Gold `dim_*` are views, not tables

- **Best practice**: gold has its own dim tables.
- **This project**: `gold.dim_*` are `CREATE OR REPLACE VIEW` over the
  corresponding `silver.dim_*` table. Only `gold.sales_fact` is a managed
  table.
- **Why**: SCD2 history lives in silver. The gold view exposes a clean
  current-rows projection to BI tools (filtering `IsRowCurrent = TRUE` for
  SCD2 dims) without duplicating storage.
- **Apply where**: all gold dim_* objects. Adding a new gold dim creates a
  view, not a table.

## SCD2 uses `BEGIN ATOMIC` for expire + insert

- **Best practice**: a single MERGE statement with both branches.
- **This project**: `dim_product` (the canonical SCD2) uses
  `BEGIN ATOMIC ... END;` wrapping a `MERGE` (expire) followed by an
  `INSERT INTO ... SELECT ... WHERE NOT EXISTS` (new rows).
- **Why**: Cleaner separation of expire vs insert logic and atomic commit.
- **Cost**: `DESCRIBE HISTORY` returns zeros for `operationMetrics` inside a
  `BEGIN ATOMIC` block. Derive `rows_inserted` and `rows_expired` from
  pre/post `COUNT(*)` differentials, not `DESCRIBE HISTORY`.
- **Apply where**: any SCD2 dimension load that follows the `dim_product`
  pattern.

## `inserted_ts` in bronze uses `F.lit(started_timestamp)`, not `F.current_timestamp()`

- **Best practice**: `F.current_timestamp()` in DataFrame columns for
  consistency across executors.
- **This project**: bronze rows use
  `F.lit(started_timestamp).cast("timestamp")` where `started_timestamp` is
  the step's Python `datetime` from cell 3.
- **Why**: Every row from a single bronze run gets the exact same
  `inserted_ts`, matching the `started_timestamp` written to
  `pipeline_step_log`. With `F.current_timestamp()`, rows would get slightly
  different timestamps across executors.
- **`.cast("timestamp")` is load-bearing** — without it Spark may infer
  `timestamp_ntz`.
- **Apply where**: bronze `inserted_ts` only. Silver `inserted_ts`/`updated_ts`
  use `CURRENT_TIMESTAMP()` in SQL (set at write time, not at notebook start).

## `_target_catalog_map` lives in two places and must be hand-mirrored

- **Best practice**: single source of truth for environment → catalog mapping.
- **This project**: the map is in `libs/notebook_init.ipynb` AND must mirror
  `targets.<target>.variables.catalog` in `databricks.yml`. Both files must
  be edited in the same commit when targets change.
- **Why**: `notebook_init` needs to resolve a catalog when run standalone
  (no job parameter present). The bundle CANNOT inject its var values into
  notebooks at parse time — only at runtime via parameters.
- **Mitigation**: a header comment in `notebook_init` flags this. Keep that
  comment.
- **Apply where**: whenever you add/rename/remove a target in `databricks.yml`,
  update the map in `notebook_init.ipynb` in the same commit.
- **Future**: centralizing this is a candidate improvement — out of scope
  for the current state.

## `silver.sales`-style notebooks log "rows_rejected" for unresolved FKs

- **Best practice**: `rows_rejected` = rows that failed validation and were
  written to a quarantine table.
- **This project**: `slvr_04_load_sales` and `gold_01_load_sales_fact` use
  the `rows_rejected` column of `transform_detail_log` to record rows that
  landed with a `-1` surrogate key (no dim match) — they are NOT quarantined.
- **Why**: Closest-fit existing column. Adding a dedicated `rows_unmatched`
  column wasn't worth a schema change for a learning project.
- **Apply where**: any join-to-dim flow that uses COALESCE → -1 fallback.

---

## How to add a new deviation

When a future task introduces another intentional deviation, append a section
here with the same shape:
- **Best practice**
- **This project**
- **Why** (the constraint or incident that drove the choice)
- **Apply where** (scope of the rule)
- Anything else load-bearing
