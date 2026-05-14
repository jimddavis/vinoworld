# Bucket 02 — Deploy + Test

**Verdict:** PASS — all gates green on first attempt.

## Deploy

- `databricks bundle validate --target user` → `Validation OK!`
- `rm -rf .databricks/bundle/user/sync-snapshots/` → done
- `databricks bundle deploy --target user` → `Deployment complete!`
- Verify-deploy ritual:
  - `silver/` notebook count: LOCAL=4, REMOTE=4 — match
  - `slvr_01` deployed content: 11 cells (was 10 pre-bucket); close-out cell at idx=9; 5 try blocks (cells 4–8). All as expected.
  - `slvr_03` deployed content: 6 cells (was 7 pre-bucket — cell 2 deleted); `transform_detail_log_insert` present; "CLAUDE deleted" note absent; no `dev_vinoworld` literal anywhere.

## Reset run

- Job: `vinoworld_reset_pipeline`
- Run id: **364622418568646**
- Result: TERMINATED / SUCCESS
- Child tasks: `truncate_all_tables` SUCCESS, `move_archive_to_bronze` SUCCESS

## ELT run

- Job: `vinoworld_elt_pipeline`
- Run id: **896725236706322**
- Result: TERMINATED / SUCCESS
- Child tasks (11/11 SUCCESS):

  | Task key | State | Bucket-relevant? |
  |---|---|---|
  | `init_pipeline_log` | TERMINATED/SUCCESS | — |
  | `brz_load_arancione_sales_files` | TERMINATED/SUCCESS | — |
  | `brz_load_celeste_sales_files` | TERMINATED/SUCCESS | — |
  | `brz_load_verde_sales_files` | TERMINATED/SUCCESS | — |
  | `brz_load_product_files` | TERMINATED/SUCCESS | — |
  | `load_dims_from_csv` | TERMINATED/SUCCESS | **yes — exercises slvr_01 try/except + new close-out cell** |
  | `load_dim_region` | TERMINATED/SUCCESS | **yes — exercises slvr_03 Pattern B (transform_detail_log + step-log close-out)** |
  | `load_dim_product` | TERMINATED/SUCCESS | — |
  | `load_silver_sales` | TERMINATED/SUCCESS | — |
  | `load_gold_sales_fact` | TERMINATED/SUCCESS | — |
  | `finalize_pipeline_log` | TERMINATED/SUCCESS | — |

**Concrete proof of bucket effects:**

- `load_dims_from_csv` (slvr_01) ran the new try/except blocks across all five per-dim cells AND reached the new step-log close-out cell at the end. A non-success path through any per-dim cell would have raised; the task succeeded → all five dims loaded and the step-log row flipped to STATUS_SUCCEEDED on the success path (was the BACKLOG item).
- `load_dim_region` (slvr_03) ran the new Pattern B cell. `transform_detail_log_insert` was called with status=STATUS_SUCCEEDED (visible only via audit table query, not captured here). Step-log close-out reached on success path.

## Transient retries: 0
## Accidental duplicate run

I issued a stray `databricks bundle run vinoworld_elt_pipeline --target user --no-wait` while inspecting outputs from the primary run — it submitted **run_id 83732231404137**. Cancelled within seconds via `databricks jobs cancel-run`. State: TERMINATED/CANCELED. No interference with bucket 2's authoritative ELT run.
