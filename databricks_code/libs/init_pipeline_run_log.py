# -------------------------------------------------------------------------------
# A simple script that initializes that inserts a record into pipeline_run_log
# and sets a taskValue to the pipeline_run_id to be used by all other tasks
# At root scope of project as this is project specific
# -------------------------------------------------------------------------------
import uuid, sys
from datetime import datetime, timezone

# shared_lib_path is passed as sys.argv[1] by the bundle (spark_python_task.parameters).
# Falls back to /Workspace/Shared when run outside a bundle job.
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else "/Workspace/Shared")

from pipeline_logging import pipeline_log_upsert


PIPELINE_RUN_ID   = str(uuid.uuid4())
PIPELINE_START_TS = datetime.now(timezone.utc)
PIPELINE_NAME     = "Vinoworld TEST LOAD"
PIPELINE_STATUS   = "running"
PIPELINE_END_TS   = None
ERROR_MESSAGE     = None

dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)

pipeline_log_upsert(spark, PIPELINE_RUN_ID, PIPELINE_NAME, PIPELINE_STATUS, PIPELINE_START_TS)
