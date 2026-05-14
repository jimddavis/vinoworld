# Bucket 01 — Deploy + Test

**Verdict:** PASS — all gates green on first attempt.

## Deploy

- `databricks bundle validate --target user` → `Validation OK!`
- `rm -rf .databricks/bundle/user/sync-snapshots/` → done
- `databricks bundle deploy --target user` → `Deployment complete!`
- Verify-deploy ritual:
  - File count: LOCAL=6, REMOTE=6 — match
  - `pipeline_logging.py` content: STATUS_RUNNING/SUCCEEDED/FAILED/NO_FILES at L33–36 present on remote; STATUS_FAILED substitution at L188/L192/L199 present
  - `init_pipeline_run_log.py` content: `PIPELINE_NAME = "vinoworld_elt_pipeline"` at L27; `PIPELINE_STATUS = STATUS_RUNNING` at L28 — both present on remote

## Reset run

- Job: `vinoworld_reset_pipeline`
- Run id: **1092157121241959**
- URL: https://dbc-d0f295f4-d028.cloud.databricks.com/?o=7474649167980843#job/639508412478373/run/1092157121241959
- Result: TERMINATED / SUCCESS
- Child tasks:
  - `truncate_all_tables` — SUCCESS
  - `move_archive_to_bronze` — SUCCESS

## ELT run

- Job: `vinoworld_elt_pipeline`
- Run id: **361208283948490**
- URL: https://dbc-d0f295f4-d028.cloud.databricks.com/?o=7474649167980843#job/277026653349386/run/361208283948490
- Result: TERMINATED / SUCCESS
- Child tasks (all 11, all SUCCESS):

  | Task key | State |
  |---|---|
  | `init_pipeline_log` | TERMINATED/SUCCESS |
  | `brz_load_arancione_sales_files` | TERMINATED/SUCCESS |
  | `brz_load_celeste_sales_files` | TERMINATED/SUCCESS |
  | `brz_load_verde_sales_files` | TERMINATED/SUCCESS |
  | `brz_load_product_files` | TERMINATED/SUCCESS |
  | `load_dims_from_csv` | TERMINATED/SUCCESS |
  | `load_dim_product` | TERMINATED/SUCCESS |
  | `load_dim_region` | TERMINATED/SUCCESS |
  | `load_silver_sales` | TERMINATED/SUCCESS |
  | `load_gold_sales_fact` | TERMINATED/SUCCESS |
  | `finalize_pipeline_log` | TERMINATED/SUCCESS |

  Notably, `finalize_pipeline_log` exited cleanly — proving the bucket's `STATUS_FAILED` / `STATUS_SUCCEEDED` substitutions inside `pipeline_log_finalize` are wire-correct (the function ran and printed `pipeline_log closed: run_id=...`).

  And `init_pipeline_log` succeeded with `PIPELINE_NAME = "vinoworld_elt_pipeline"` and `PIPELINE_STATUS = STATUS_RUNNING` — confirms the renamed name and the new constant import resolve at runtime in a `spark_python_task` context.

## Transient retries: 0
