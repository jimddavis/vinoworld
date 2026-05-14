# Critical review — bucket 02 fix-slvr03-and-slvr01-cleanup (Layer 2 — independent)

- **Verdict:** DEFECTS FOUND — 2 defects. Both P1/P2/P3 findings in scope correctly addressed. Defect 1 is behavioral (incorrect `rows_written` on the failure path in slvr_01 cells 4–8); Defect 2 is a structural Pattern B violation in slvr_03 cell 4 (rows_read not pre-declared outside try), though the canonical sibling itself exhibits the same pattern — flagged for human judgment.

---

## Lens 1 — Assumption audit

### slvr_01 cells 4–8: `result.get("status") == STATUS_FAILED` is a reliable failure signal

`load_dim_from_csv` (`pipeline_utils.py` lines 265–278) catches all exceptions, never re-raises, and returns `{"status": "failed", ...}`. `STATUS_FAILED = "failed"` (`pipeline_logging.py` line 35). String values are identical. The comparison is a sound exit check. **Verified. PASS.**

### slvr_01 cells 4–8: `**result` spread covers all required parameters of `transform_detail_log_insert`

`transform_detail_log_insert` required positional params (no defaults): `spark`, `pipeline_run_id`, `step_log_id`, `source_table`, `target_table`, `status`, `started_timestamp`. The call is `transform_detail_log_insert(spark, pipeline_run_id=PIPELINE_RUN_ID, step_log_id=step_log_id, **result)`. `result` contains `source_table`, `target_table`, `status`, `started_timestamp` as documented in `helpers.md` and verified in `pipeline_utils.py` lines 252–263. All required params covered. **Verified. PASS.**

### slvr_01 cells 4–8: `rows_read` and `rows_written` are safe in the except handler before any accumulation

`rows_read = 0` and `rows_written = 0` are initialized in cell 3. Per-dim cells do `rows_read += ...` only on the success path. If cell N's try raises before executing `+=`, the except handler reads the accumulated values from cells 1..(N-1), never `NameError`. **Verified. PASS.**

### slvr_01 cell 9: reachability invariant

Cell 9 is a normal notebook cell — Databricks executes cells sequentially; if any of cells 4–8 raise, execution stops at that cell and cell 9 is never reached. This means cell 9's `STATUS_SUCCEEDED` write is only reachable when all five per-dim cells completed without raising. The accumulation semantics are sound. **Verified. PASS.**

### slvr_03 cell 4: `rows_inserted` safe on except path

`rows_inserted = 0` is declared before the `try:` block, per the Pattern B gotcha rule. If the try raises before `rows_inserted = post_total_count - pre_total_count`, the except handler passes `rows_inserted=0` to `transform_detail_log_insert`. This is a valid failure row — 0 inserted because the MERGE never committed. **Verified. PASS.**

### slvr_03 cell 4: `rows_read` safe on except path (with caveat)

`rows_read = 0` is initialized in cell 3 (outside cell 4). Inside cell 4's try, `rows_read = spark.sql(...).collect()[0][0]` runs after `pre_total_count = spark.table(transform_target_table).count()`. If the pre-count raises, `rows_read` was never assigned in cell 4 — the except handler uses cell 3's `0`. Runtime-safe. However, `rows_read` is NOT declared before the `try:` line in cell 4's per-transform pre-declaration block. This violates the pattern's intent (see Defect 2).

### slvr_01 except path: `rows_written` accumulation (FAILED assumption)

The handoff packet states: "pass rows_written=0 to match the canonical bronze / slvr_02 sibling pattern." But the actual cells 4–8 except handlers pass `rows_written=0` as the literal `0` to `pipeline_step_log_upsert` — **but also pass the pre-accumulated notebook-level `rows_written` implicitly through the accumulated variable on any subsequent cell's failure path**.

Wait — re-reading the source: every except handler in cells 4–8 calls:
```python
pipeline_step_log_upsert(
    spark, step_log_id, pipeline_run_id, step_sequence,
    notebook_folder, notebook_name, status, started_timestamp,
    layer, target_table, rows_read, 0, ended_timestamp, error_message
)
```
The `0` is a literal — not `rows_written`. So `rows_written=0` on the failure path is correctly hard-coded. **The packet's claim is true. PASS.**

However, `rows_read` in the except call uses the accumulated notebook-level `rows_read` (all prior dim successes), not just the current dim's read count. This means a failure on dim 3 (exchange_rate) logs `rows_read` = rows from currency + dates + exchange_rates. The canonical `slvr_02` cell 5 logs the current transform's `rows_read` only. This is a behavioral divergence (see Defect 1).

---

## Lens 2 — Standards conformance

**Rule: `except dbutils.NotebookExit: raise` must appear before `except Exception` when the cell calls `dbutils.notebook.exit()`.**
— Source: Databricks `CLAUDE.md` Error Handling section; `gotchas.md`.

None of the changed cells (slvr_01 cells 4–8, slvr_03 cell 4, slvr_01 cell 9) call `dbutils.notebook.exit()`. Guard not required. PASS.

**Rule: `status` variable must use constants `STATUS_RUNNING/SUCCEEDED/FAILED`, not bare string literals.**
— Source: `migrations.md` Forbidden strings section: `status = "running"`, `status = "succeeded"`, `status = "failed"`.

All changed cells use `STATUS_RUNNING` (cell 3, unchanged), `STATUS_SUCCEEDED`, `STATUS_FAILED`. No bare string literals introduced or retained in modified code. PASS.

**Rule: No `/Workspace/Shared/` or `sys.path.append("/Workspace/Shared")` in changed code.**
— Source: `migrations.md` Forbidden strings.

Neither string appears in any changed cell. PASS.

**Rule: Audit-logging variables must be declared OUTSIDE the `try` block for Pattern B.**
— Source: `gotchas.md`: "If they live inside `try:` and the first SQL statement raises, the `except` handler hits `NameError` instead of logging the actual failure. See `slvr_02_load_dim_product` cell 5 for the canonical layout."

`slvr_03` cell 4: `transform_source_table`, `transform_target_table`, `transform_started`, `rows_inserted` declared before `try:`. `rows_read` declared only inside `try:`. The canonical example (`slvr_02` cell 5, verified by reading the file) also declares `rows_read` only inside the try block. This is a deviation from the strict rule text but is consistent with the canonical sibling. See Defect 2 (flagged for human judgment).

**Rule: Step-log success close-out required on all notebooks.**
— Source: `migrations.md` in-flight migration "Step-log success close-out".

`slvr_01`: new cell 9 writes `pipeline_step_log_upsert(... STATUS_SUCCEEDED ...)`. Migration complete. PASS.
`slvr_03`: cell 4 success path writes `pipeline_step_log_upsert(... STATUS_SUCCEEDED ...)`. Migration complete. PASS.

**Rule: `transform_detail_log_insert` called on both success and failure paths.**
— Source: `gotchas.md` Pattern B; `CLAUDE.md` error handling section.

`slvr_03` cell 4: called on success with `STATUS_SUCCEEDED`, called in except with `STATUS_FAILED`. PASS.
`slvr_01` cells 4–8: called once via `**result` before the status check. When `load_dim_from_csv` returns a failed result, `transform_detail_log_insert` records the failure, then `RuntimeError` is raised, then the except handler calls only `pipeline_step_log_upsert` (no second `transform_detail_log_insert`). This is correct — no double-logging, and the failure is captured in the transform audit row. PASS.

**Rule: Hardcoded table/path strings must not appear in more than one cell.**
— Source: Databricks `CLAUDE.md`.

`slvr_03` cell 4 uses `f"{SILVER}.dim_region"` in two places: `transform_target_table` and the MERGE SQL `{SILVER}.dim_region`. However, both references are inside cell 4 only and the MERGE SQL uses the constant `{SILVER}` (not a hardcoded catalog), so this is consistent with standards. PASS.

**Rule: P2-11 (`%skip` hardcoded catalog), P2-12 (wrong banner), P2-13 (wrong table in debug cell), P3-2 (Claude note), P3-4 (wrong docstring).**

From diff inspection:
- P2-11: `%skip` block with `CATALOG = "dev_vinoworld"` deleted. PASS.
- P2-12: Banner now reads `Pipeline: {BRONZE}.products → {SILVER}.dim_region`. PASS.
- P2-13: Debug cell now uses `{CATALOG}.silver.dim_region`. PASS.
- P3-2: Claude scratch note removed from cell 0 markdown. PASS.
- P3-4: `slvr_01` cell 2 docstring updated to "dim load from CSV"; `slvr_03` cell 2 docstring updated to "dim_region Silver load". PASS.

---

## Lens 3 — Cross-object consistency

### slvr_03 cell 4 (Pattern B) vs slvr_02 cell 5

Read `slvr_02` cell 5 end-to-end. Comparison:

| Element | slvr_02 cell 5 | slvr_03 cell 4 | Match? |
|---|---|---|---|
| Pre-transform vars outside try | `transform_source_table`, `transform_target_table`, `transform_started`, `rows_inserted`, `rows_expired` | `transform_source_table`, `transform_target_table`, `transform_started`, `rows_inserted` | MATCH (no SCD2 expired rows in slvr_03) |
| `rows_read` placement | Inside try | Inside try | MATCH |
| Pre-count SQL before MERGE | YES (`pre_total_count`, `pre_current_count`) | YES (`pre_total_count`) | MATCH |
| Post-count differential | YES | YES | MATCH |
| `transform_detail_log_insert` success kwargs | explicit, includes `rows_expired` | explicit, no `rows_expired` | MATCH (correct for Type-1 dim) |
| `transform_detail_log_insert` failure kwargs | `rows_inserted`, `rows_expired`, `error_message` — omits `rows_read`, `rows_written` | `rows_inserted`, `error_message` — omits `rows_read`, `rows_written` | MATCH |
| `pipeline_step_log_upsert` success | explicit with `error_message` | explicit with `error_message` | MATCH |
| `pipeline_step_log_upsert` failure | `rows_read, 0, ended_timestamp, error_message` | `rows_read, 0, ended_timestamp, error_message` | MATCH |
| `raise` at end of except | YES | YES | MATCH |
| Status constants | `STATUS_SUCCEEDED`, `STATUS_FAILED` | `STATUS_SUCCEEDED`, `STATUS_FAILED` | MATCH |

**slvr_03 cell 4 faithfully mirrors slvr_02 cell 5.** PASS.

### slvr_01 cells 4–8 (try/except wrap) vs brz_01 cells 5–6

Confirmed by reading `brz_01_arancione_sales.ipynb` cells 5–6. Comparison on the failure path:

| Element | brz_01 cell 6 except | slvr_01 cells 4–8 except | Match? |
|---|---|---|---|
| `Utils.capture_exception(e)` | YES | YES | MATCH |
| `error_message = f"..."` format | YES | YES | MATCH |
| `ended_timestamp = datetime.now(timezone.utc)` | YES | YES | MATCH |
| `status = STATUS_FAILED` | YES | YES | MATCH |
| `pipeline_step_log_upsert` args on failure | `rows_read, 0` | `rows_read, 0` | MATCH (literal `0` is correct) |
| `raise` | YES | YES | MATCH |
| `except dbutils.NotebookExit: raise` guard | YES (cell 4 calls exit) | NO — correct; cells 4–8 do not call exit | N/A |

**Shape matches bronze canonical pattern. PASS.**

**Divergence on `rows_read` semantics:** `brz_01` and `slvr_02` pass the *current transform's* `rows_read` to the failure-path step log (the value computed within the same try block). `slvr_01` cells 4–8 pass the *accumulated notebook-level* `rows_read` (sum of all prior successful dims, initialized to 0 in cell 3, incremented by each prior dim). This means a failure on dim 3 logs `rows_read` = rows from dim 1 + dim 2 + dim 3 combined. The canonical siblings never accumulate across transforms into a single failure-path log row. See **Defect 1**.

### slvr_01 cell 9 (close-out) vs slvr_02 cell 5 success path

`slvr_02` cell 5 success-path `pipeline_step_log_upsert` call includes `error_message` as the final argument (value `None` on the success path):
```python
pipeline_step_log_upsert(
    spark, step_log_id, pipeline_run_id, step_sequence,
    notebook_folder, notebook_name, status, started_timestamp,
    layer, target_table, rows_read, rows_written, ended_timestamp, error_message
)
```

`slvr_01` cell 9 omits `error_message`:
```python
pipeline_step_log_upsert(
    spark, step_log_id, pipeline_run_id, step_sequence,
    notebook_folder, notebook_name, status, started_timestamp,
    layer, target_table, rows_read, rows_written, ended_timestamp
)
```

`pipeline_step_log_upsert` signature: `error_message=None` is the last keyword argument with a default. Omitting it results in `None` — functionally identical to the sibling. Runtime impact: zero. Cosmetic inconsistency vs canonical sibling, not a defect.

---

## Lens 4 — Pattern deviations

`deviations.md` entries checked:

- **Silver `dim_*` columns are PascalCase.** `slvr_03` cell 4 MERGE SQL uses `Province`, `RegionName`, `SubRegionName`, `InsertedDate`, `UpdatedDate` — all PascalCase. Intentional deviation preserved. PASS.
- **Bronze MERGE `WHEN NOT MATCHED` only.** Not applicable to changed cells. PASS.
- **Bronze `inserted_ts` uses `F.lit(started_timestamp)`.** Not applicable to silver notebooks. `slvr_03` uses `current_timestamp()` in SQL (correct for silver). PASS.
- **SCD2 uses `BEGIN ATOMIC`.** `slvr_03` is Type-1, no BEGIN ATOMIC needed or used. PASS.
- **Silver `sales` and Gold `sales_fact` use INSERT OVERWRITE.** Not applicable. PASS.
- **`_target_catalog_map` lives in two places.** Not touched. PASS.

**No unjustified new deviations introduced.** The only divergences from canonical siblings are Defect 1 (`rows_read` accumulation semantics) and the cosmetic `error_message` omission in cell 9. Neither is listed in `deviations.md`. Defect 1 is a real, unlisted, unjustified deviation; the cell 9 omission is too minor to constitute a deviation.

---

## Defects

**Defect 1** — `slvr_01_load_dim_fromcsv.ipynb`, cells 4–8, except handler: `rows_read` passed to `pipeline_step_log_upsert` is the accumulated notebook-level count, not the current transform's count.

- **File:** `databricks_code/notebooks/silver/slvr_01_load_dim_fromcsv.ipynb`, cells 4, 5, 6, 7, 8
- **Rule violated:** Cross-object consistency (`CLAUDE.md` §2 — mirror the closest existing analog exactly). `slvr_02` cell 5 and `brz_01` cell 6 both pass the current transform's own `rows_read` to the failure-path `pipeline_step_log_upsert` call. In slvr_01, `rows_read` on the except path is the running total from all prior successful dims (accumulated via `rows_read += ...` in each successful cell). A failure at dim 3 logs `rows_read` = rows from dims 1 + 2 + 3, which does not represent what that step's failure row should record.
- **Why it's wrong:** It silently misrepresents the audit semantics. The failure row for `dim_exchange_rate` should log how many rows were read for that specific dim's operation, not the running sum of all dims processed before it. A reader of the step log seeing `rows_read=N` on a `STATUS_FAILED` row for this notebook cannot tell which dim's count N reflects. This is an unjustified, undocumented deviation from the canonical sibling pattern.
- **Severity:** Audit data quality. No pipeline functionality is broken; the deviation only affects the accuracy of `pipeline_step_log.rows_read` on failure paths.

---

**Defect 2** — `slvr_03_load_dim_region.ipynb`, cell 4: `rows_read` is not declared outside the `try` block alongside the other Pattern B pre-declarations.

- **File:** `databricks_code/notebooks/silver/slvr_03_load_dim_region.ipynb`, cell 4
- **Rule violated:** `gotchas.md` — "Audit-logging variables must be declared OUTSIDE the `try` block (Pattern B)... If they live inside `try:` and the first SQL statement raises, the `except` handler hits `NameError` instead of logging the actual failure."
- **Why it's wrong:** `rows_read` is used in `pipeline_step_log_upsert` in both the success and except paths. It is assigned only inside `try:` (`rows_read = spark.sql(...).collect()[0][0]`), after `pre_total_count = spark.table(...).count()`. If the pre-count raises, `rows_read` was never assigned in cell 4 — the except path relies on cell 3's notebook-level `rows_read = 0`. This is safe at runtime today, but violates the structural intent of Pattern B: all variables used on both paths of a try/except should be declared before the `try:` in the same cell, to make the invariant self-documenting and robust against future refactors.
- **Caveat:** The canonical sibling `slvr_02` cell 5 also places `rows_read` inside the try block. This means either (a) `slvr_02` itself is a latent Pattern B violation for `rows_read` that was accepted when the pattern was designed (because `rows_read` always has an outer fallback), or (b) the gotcha rule intends "declare outside" only for variables with no outer fallback — in which case `rows_read`'s initialization in cell 3 satisfies the spirit of the rule. **Human judgment required:** if the rule is strict, both `slvr_03` cell 4 and `slvr_02` cell 5 have this issue; if the rule is interpreted as "must not produce NameError on except," slvr_03 cell 4 is fine.
- **Severity:** Low runtime risk; structural/documentation concern.

---

## Notes for the next reviewer pass

1. **`migrations.md` step-log close-out entry needs update.** It still lists `slvr_01` and `slvr_03` as "not yet migrated." Both are now complete. This is a `.claude/` file outside the bucket's `databricks_code/` scope — not a defect for this bucket, but needs a follow-on doc commit.

2. **`slvr_01` cell 3 `target_table` string:** `f"{SILVER} dim_currency, ..."` has a space instead of a dot after `{SILVER}`. Pre-existing in the original code, not touched by this diff. Parked — not a bucket-02 defect.

3. **`slvr_01` cell 10 debug SQL:** Uses hardcoded `vinoworld.silver.*` table names instead of `{CATALOG}.silver.*`. Pre-existing `%skip` cell, not introduced by this bucket. Log for a hygiene bucket.

4. **Defect 1 remediation note:** The clean fix for Defect 1 requires understanding what `rows_read` should mean in `pipeline_step_log` for a multi-dim notebook. Option A: log the current dim's `rows_read` (matches sibling pattern; requires each except handler to use `result.get("rows_read", 0)` rather than the accumulated `rows_read`). Option B: log the accumulated total (documents how much work was done before the failure; requires a documented justification in `deviations.md`).
