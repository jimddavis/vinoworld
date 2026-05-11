# -------------------------------------------------------------------------------
# Finalize the pipeline_log row written by init_pipeline_run_log.py.
# All logic lives in pipeline_logging.pipeline_log_finalize — this script just
# bootstraps the import path, recovers the run_id from the init task's
# taskValue, and hands off.
#
# Wired into the bundle as the last task of vinoworld_elt_pipeline with
# run_if: ALL_DONE so it executes whether upstream succeeded, failed, or
# was skipped.
# -------------------------------------------------------------------------------
import sys

# shared_lib_path comes from sys.argv[1] (bundle spark_python_task.parameters
# → ${var.shared_lib_path}). catalog comes from sys.argv[2] (${var.catalog}).
# __file__ is NOT defined in a spark_python_task because Databricks invokes
# the script via exec(compile(...)); rely on the bundle to pass the path.
if len(sys.argv) < 2:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path. Set in databricks.yml under "
        "spark_python_task.parameters when wiring this script into a job."
    )
sys.path.insert(0, sys.argv[1])
catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"

from pipeline_logging import pipeline_log_finalize, configure
configure(f"{catalog}.audit")

PIPELINE_RUN_ID = dbutils.jobs.taskValues.get(
    taskKey="init_pipeline_log",
    key="pipeline_run_id",
)

pipeline_log_finalize(spark, PIPELINE_RUN_ID)
print(f"pipeline_log closed: run_id={PIPELINE_RUN_ID}")
