# Findings & Design — `transform_detail_log` integration

**Date:** 2026-05-09
**Audit table:** `audit.transform_detail_log` — currently 0 rows
**Reason for writing:** the table and `transform_detail_log_insert()` exist (in `pipeline_logging.py`), but no caller writes to it. The `load_dim_from_csv()` refactor in `pipeline_utils.py` documented the intent in its return-dict shape but never wired the actual log call.

---

## 1. Current logging hierarchy and what each tier captures

```
pipeline_log              — 1 row per pipeline execution (run-level)
  └── pipeline_step_log   — 1 row per notebook (notebook-level)
        └── transform_detail_log  — 1 row per (source, target) transform (table-level)
              └── ingestion_log    — 1 row per source FILE (Bronze ingestion only)
```

`transform_detail_log` is the **table-level** tier. It adds value when a single notebook touches more than one (source, target) pair, or when a single transform has substructure worth recording (rows inserted vs updated vs expired vs rejected).

What `transform_detail_log` records that `pipeline_step_log` can't:

- `source_table` and `target_table` as a **pair** (step_log only has one `target_table`).
- Decomposed counts: `rows_inserted`, `rows_updated`, `rows_expired`, `rows_rejected`, `rows_deduplicated` — vs step_log's single `rows_written`.
- `validation_rules_applied`, `schema_drift_detected`, `schema_drift_detail` — data-quality observability per transform, not per notebook.

---

## 2. Per-notebook analysis

| Notebook | Sources | Targets | Multi-table? | Useful detail to capture | Recommendation |
|---|---|---|---|---|---|
| `slvr_01_load_dim_fromcsv` | 5 CSVs | 5 dims (currency, date, exchange_rate, store, territory) | **Yes (1→1 × 5)** | Per-dim rows_written, status, duration | **High priority** — biggest current gap |
| `slvr_02_load_dim_product` | bronze.products | silver.dim_product | No (1→1) | SCD2 metrics: rows_inserted, rows_expired (different from rows_written) | **Medium priority** — captures SCD2-specific decomposition |
| `slvr_03_load_dim_region` | bronze.products | silver.dim_region | No (1→1) | rows_inserted from DESCRIBE HISTORY | **Low priority** — adds little over step_log |
| `slvr_04_load_sales` | 3 bronze tables → 1 silver | silver.sales | **Yes (3→1)** | Unmatched-FK count, per-source row counts | **High priority** — unmatched-FK is real DQ signal |
| `gold_01_load_sales_fact` | silver.sales + N dims | gold.sales_fact | Yes (multi→1) | Unmatched-FK warnings per dim, rows_inserted from DESCRIBE HISTORY | **High priority** — same pattern as slvr_04 |

**Recommendation 1 — Should you incorporate this logging?**

**Yes, but selectively.** The table exists because someone (you, earlier) saw a real audit gap. The gap is biggest where step_log compresses multiple transforms into a single status row — `slvr_01` (5 dims hidden under 1 step), `slvr_04` and `gold` (multi-source unions where you currently can't see how many rows came from which source, or how many failed FK resolution).

**Skip `slvr_03_load_dim_region`** — single source, single target, single MERGE, no multi-statement substructure, no DQ flags worth recording. `pipeline_step_log` already captures everything meaningful. Adding a transform_detail row would be ceremony, not signal.

**Add to all the others** in priority order: `slvr_01` first (highest ROI), then `slvr_04` and `gold` (DQ-signal value), then `slvr_02` (SCD2 decomposition).

---

## 3. Three implementation patterns

### Pattern A — Helper returns a log-ready dict; notebook calls the logger

The helper stays pure: it reads, transforms, writes to the target, and **returns** all the audit data the caller needs. It does **not** write to audit itself. The caller (notebook) unpacks the returned dict into `transform_detail_log_insert` via `**result`.

The contract: `load_dim_from_csv` returns a dict whose keys exactly match `transform_detail_log_insert`'s parameter names. The call site becomes one extra line:

```python
result = Utils.load_dim_from_csv(
    spark=spark,
    source_path=f"{SOURCE_PATH}/Currency.csv",
    target_table=f"{SILVER}.dim_currency",
    merge_sql_fn=currency_merge_sql,
    add_timestamps=True,
)

transform_detail_log_insert(
    spark,
    pipeline_run_id=PIPELINE_RUN_ID,
    step_log_id=step_log_id,
    **result,
)
```

`**result` spreads the dict into named keyword arguments — Python's idiomatic equivalent to method overloading. No second function signature needed.

**Pros:**
- **No side effects in the helper.** The helper does one thing: load a dim and report what happened. It can be unit-tested without a Spark session writing to audit; reused outside the audit context; called during local debugging without polluting the audit table.
- Logging happens at the call site — readers can see exactly what gets logged.
- The notebook controls whether and where to log. Could send to a different destination, batch the calls, skip them in dry-run mode.
- Future helpers (`load_dim_scd2`, `load_fact`) follow the same convention.

**Cons:**
- Helper's return-dict keys must match the logger's parameter names exactly. Today they don't — renaming/extending the dict is part of the change.
- One extra line per call site (5 calls × 1 line in `slvr_01`).

**Best for:** `slvr_01_load_dim_fromcsv` (uses the helper for all 5 dims).

### Pattern B — Notebook-side wrapping

Notebook performs its own SQL, then explicitly calls `transform_detail_log_insert` after the success path and from each `except` block.

**Pros:**
- Logging is visible at the call site.
- No helper modifications.
- Each notebook controls exactly what gets logged (e.g., custom DQ counters like `unmatched_count`).

**Cons:**
- Per-notebook boilerplate (~15 lines per success/except pair).
- Risk of drift if the notebook's logic changes but the log call doesn't.

**Best for:** `slvr_02`, `slvr_04`, `gold_01` — they each do bespoke SQL, no helper to hook into.

### Pattern C — Context manager / decorator

A `@logged_transform` decorator or a `with transform_logger(...) as t:` context manager that auto-captures start/end/exception and writes the audit row. Caller updates `t.rows_written` etc. inside the block.

**Pros:**
- Cleanest call-site syntax.
- Centralized error-path handling.

**Cons:**
- Most engineering effort. Requires a new helper, testing, and a mental model the project doesn't currently use.
- Overkill for five notebooks. Justifiable only if you'll reach 20+.

**Best for:** **don't do this in this project.** Reconsider when the codebase is 5× larger.

---

## 4. Recommended approach per notebook

### `slvr_01_load_dim_fromcsv` — Pattern A

Modify `Utils.load_dim_from_csv()` in `pipeline_utils.py`:

- **Remove the unused `step_log_id` parameter** (currently a placeholder; not used anywhere). Caller doesn't need to pass it to the helper — it passes it directly to the logger.
- **Rename / extend the return dict** so its keys match `transform_detail_log_insert`'s parameter names exactly. Concretely:
  | Current key | Become |
  |---|---|
  | `source_path` | `source_table` |
  | `started` | `started_timestamp` |
  | `ended` | `ended_timestamp` |
  | `file_row_count` | `rows_read` |
  | `rows_written` | (keep) |
  | `status` | (keep) |
  | `error_message` | (keep) |
  | `target_table` | (keep) |
  | (new) | `rows_inserted` |
  | (new) | `rows_updated` |

- **Compute `rows_inserted` / `rows_updated` from `DESCRIBE HISTORY <target> LIMIT 1`** `operationMetrics`. The MERGE here is plain (not BEGIN ATOMIC), so `numTargetRowsInserted` / `numTargetRowsUpdated` are populated. Read them after the MERGE returns.
- **No `transform_detail_log_insert` call inside the helper.** Helper stays pure.
- **Drop `source_path` and `file_row_count` from the return** (renamed above). Drop the duplicated `rows_written` key in the current return (currently appears twice).
- **Failure path returns the same shape** with `status="failed"`, `error_message=...`, and `rows_inserted`/`rows_updated` set to `0` or `None` (dealer's choice; `None` is more honest about "didn't get that far").

In `slvr_01_load_dim_fromcsv.ipynb`:

- After each `result = Utils.load_dim_from_csv(...)`, add:
  ```python
  transform_detail_log_insert(
      spark,
      pipeline_run_id=PIPELINE_RUN_ID,
      step_log_id=step_log_id,
      **result,
  )
  ```
- 5 calls × 6 added lines = 30 lines of new notebook code. Trivial; each call site is identical except for the preceding `result =` block.
- Replace the existing `print(f"Results = {result}")` lines (debug-only) with the logger call.
- Optional: raise on `result["status"] == "failed"` so the notebook's `pipeline_step_log` flips to failed and dependent tasks stop. Today the helper swallows failures silently, which is its own bug — flag for follow-up (already in §8 of this doc).

**Result:** 5 `transform_detail_log` rows per run with full per-dim audit data. Helper stays pure (no side effects). Notebook explicitly logs each call.

### `slvr_02_load_dim_product` — Pattern B (with atomic-block workaround)

Single transform: `bronze.products → silver.dim_product`. SCD2 atomic block.

**Atomic-block caveat (already documented in the function docstring):** DESCRIBE HISTORY returns zeros for BEGIN ATOMIC blocks. Use pre/post count differential instead:

```python
# Before the atomic block
pre_current_count  = spark.sql(
    f"SELECT COUNT(*) FROM {SILVER}.dim_product WHERE IsRowCurrent = TRUE"
).collect()[0][0]
pre_total_count    = spark.table(f"{SILVER}.dim_product").count()
started = datetime.now(timezone.utc)

# ... atomic block runs ...

# After the atomic block
post_current_count = spark.sql(
    f"SELECT COUNT(*) FROM {SILVER}.dim_product WHERE IsRowCurrent = TRUE"
).collect()[0][0]
post_total_count   = spark.table(f"{SILVER}.dim_product").count()

rows_inserted = post_total_count   - pre_total_count            # net new physical rows
rows_expired  = pre_current_count  - (post_current_count - rows_inserted)  # current rows that became non-current
rows_written  = rows_inserted + rows_expired
```

Call `transform_detail_log_insert(... source_table="bronze.products", target_table="silver.dim_product", rows_inserted=..., rows_expired=..., rows_written=...)` in the success block (cell 5) and in each except block.

**Skip the unknown-row insert (cell 6).** It's a one-time bootstrap; logging it adds noise.

### `slvr_03_load_dim_region` — **skip**

Already covered by `pipeline_step_log`. Adding transform_detail here is ceremony.

### `slvr_04_load_sales` — Pattern B

Three sources, one target, INSERT OVERWRITE. The notebook already computes `rows_written` and `unmatched_count`. Map to schema:

- `source_table`: `"bronze.sales_arancione + sales_celeste + sales_verde"` (string concat — the schema is a string, not a foreign key, so a multi-source label is acceptable)
- `target_table`: `"silver.sales"`
- `rows_written`: existing variable (post-write count)
- `rows_rejected`: `unmatched_count` (rows where `product_no = '-1'`) — these *aren't* rejected, they're flagged. Two options:
  - **Option 1:** Use `rows_rejected` for unmatched-FK count, document it in the notebook header. Pragmatic, slightly off-spec.
  - **Option 2:** Use `validation_rules_applied = '["product_no resolved via dim_product"]'` and put the unmatched count in a separate log statement. Strictly correct, more boilerplate.

  **Recommendation:** Option 1 for now — `rows_rejected` is the closest match in the existing schema and a comment explains the convention. If you ever add a real reject path (rows actually quarantined), introduce a new column `rows_unmatched` then.

- `rows_read`: sum of pre-counts on the three bronze tables. Two extra `count()` calls in the staging block — acceptable cost.

Call once after the INSERT OVERWRITE, success path. Mirror call in except.

### `gold_01_load_sales_fact` — Pattern B

Same shape as slvr_04. The notebook has `warn_counts` for unresolved FKs across multiple dims. Map to:

- `source_table`: `"silver.sales + dims"` (or list each — acceptable as a label)
- `target_table`: `"gold.sales_fact"`
- `rows_read`: pre-INSERT row count of the staging view (already computed: `rows_read = spark.sql("SELECT COUNT(*) FROM vw_gold_sales_staging").collect()[0][0]`)
- `rows_written`: post-INSERT count (already computed)
- `rows_rejected`: sum of all `warn_counts` for unresolved FKs (analogous to slvr_04's unmatched_count)
- `validation_rules_applied`: `'["FK resolution: dim_product, dim_region, dim_date, dim_store, dim_territory"]'`

---

## 5. Cross-cutting decisions

### D1 — Where to map MERGE metrics from

| Operation | Use |
|---|---|
| Plain MERGE (slvr_01 helpers, slvr_03) | `DESCRIBE HISTORY <target> LIMIT 1` → `operationMetrics.numTargetRowsInserted` / `numTargetRowsUpdated` |
| BEGIN ATOMIC blocks (slvr_02) | Pre/post count differential. Atomic blocks return zeros from DESCRIBE HISTORY. |
| INSERT OVERWRITE (slvr_04, gold) | `rows_written` = post-write count. `rows_inserted` = same as rows_written (overwrite has no "update" concept). Don't try to distinguish updated vs inserted. |

### D2 — Log on failure too?

Yes. The schema has a `status` column with values `'succeeded' | 'failed' | 'skipped'`. Each `except` block must call `transform_detail_log_insert(... status="failed", error_message=..., ended_timestamp=...)` *before* re-raising — same pattern as the existing `pipeline_step_log_upsert` calls. Otherwise failed transforms leave no audit trail at the table level.

### D3 — `step_log_id` resolution for `slvr_01`

The notebook generates one `step_log_id` at the start of the run. The notebook passes that same `step_log_id` directly to each `transform_detail_log_insert` call (the helper itself doesn't see or need it under Pattern A's pure-helper design). Each `transform_detail_log` row carries the parent step_log_id — correct hierarchy.

The notebook does *not* need a separate step_log_id per dim. The notebook is the "step"; the dims are "transforms" within the step.

### D4 — `validation_rules_applied` and schema drift

Out of scope for this round. The schema fields exist for future work. Leave them `None` for now. Document this decision in code so a future contributor doesn't think they're forgotten.

---

## 6. Estimated change footprint

| File | Changes |
|---|---|
| `databricks_code/libs/pipeline_utils.py` | Modify `load_dim_from_csv` — rename return-dict keys to match logger params, drop unused `step_log_id` param, add `rows_inserted`/`rows_updated` from DESCRIBE HISTORY. **No** logger call from inside the helper. ~15 changed lines. |
| `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` | After each helper call, add a `transform_detail_log_insert(spark, pipeline_run_id=..., step_log_id=..., **result)` block. Replace `print(result)` debug lines. ~30 added lines (5 calls × 6 lines each). |
| `databricks_code/notebooks/silver/slvr_02_load_dim_product.ipynb` | Add pre/post counts (cell 4–5 boundary), `transform_detail_log_insert` calls in cell 5 success and except paths. ~30 added lines. |
| `databricks_code/notebooks/silver/slvr_04_load_sales.ipynb` | Add 3 pre-counts (cell 4), `transform_detail_log_insert` in cell 5 success and except paths. ~25 added lines. |
| `databricks_code/notebooks/gold/gold_01_load_sales_fact.ipynb` | `transform_detail_log_insert` calls in success and except paths (rows_read/written already computed). ~20 added lines. |
| `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb` | **No changes.** |

Total: ~5 files, ~100 new lines. No schema changes (audit table already exists).

---

## 7. Acceptance criteria

After implementation and one full pipeline run on the `user` target:

- `audit.transform_detail_log` contains exactly **8 rows** for one successful run:
  - 5 rows from `slvr_01` (one per dim: currency, date, exchange_rate, store, territory).
  - 1 row from `slvr_02` (dim_product).
  - 1 row from `slvr_04` (silver.sales).
  - 1 row from `gold_01` (gold.sales_fact).
- Each row has the same `pipeline_run_id` and the correct `step_log_id` matching its parent `pipeline_step_log` row.
- `rows_inserted + rows_updated` for plain MERGE rows equals `rows_written`.
- For `slvr_02`, `rows_inserted + rows_expired` equals `rows_written`.
- A deliberate failure (e.g., bad source path) produces a row with `status='failed'` and a populated `error_message`.

---

## 8. What this does *not* address

- **`pipeline_utils.py:152` `load_dim_from_csv` returns a dict that is currently inspected only via `print(f"Results = {result}")`** in the notebook. Beyond logging, the notebook should probably also raise on `result["status"] == "failed"` so the `pipeline_step_log` for the notebook flips to `failed` and the orchestrator stops dependent tasks. That's a separate concern from transform logging — flag for a follow-up.
- **Schema drift detection.** The columns exist in `transform_detail_log` (`schema_drift_detected`, `schema_drift_detail`) but no transform currently checks for it. Real implementation would compare current source schema to a stored "last-good" schema. Out of scope.
- **`audit.transform_detail_log` DDL.** I'm assuming it already exists from `setup/catalog_ddl.ipynb`. Verify before implementation; if missing, the catalog DDL needs adding too.

---

## 9. Recommendation summary

1. **Yes, incorporate `transform_detail_log_insert`** — it fills a real audit gap, especially for multi-dim and multi-source notebooks.
2. **Wire it into 4 of the 5 silver/gold notebooks**: skip `slvr_03_load_dim_region` (no incremental value); modify `slvr_01`, `slvr_02`, `slvr_04`, `gold_01`.
3. **Use Pattern A** for `slvr_01`: keep `load_dim_from_csv` pure (no side effects), reshape its return dict so keys match the logger's parameter names, and have the notebook call `transform_detail_log_insert(spark, pipeline_run_id=..., step_log_id=..., **result)` after each helper call. **Pattern B (notebook-side)** for the other three notebooks. Pattern A separates concerns cleanly: the helper transforms; the notebook decides what to log.
4. **Verify `audit.transform_detail_log` table exists** in `setup/catalog_ddl.ipynb` before any notebook changes.

After your review of this design, hand it to `/sc:implement` for execution.
