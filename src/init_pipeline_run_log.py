# -------------------------------------------------------------------------------
# A simple script that initializes that inserts a record into pipeline_run_log
# and sets a taskValue to the pipeline_run_id to be used by all other tasks
# At root scope of project as this is project specific
# -------------------------------------------------------------------------------
import time
from datetime import datetime, timezone
import sys
sys.path.append("/Workspace/Shared")

#  %load_ext autoreload
# %autoreload 2
from pipeline_logging import pipeline_log_upsert


PIPELINE_RUN_ID = int(time.time() * 1_000_000)
PIPELINE_START_TS = datetime.now(timezone.utc)
PIPELINE_NAME = "Vinoworld TEST LOAD"
PIPELINE_STATUS = "running"
PIPELINE_END_TS = None 
ERROR_MESSAGE = None

dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)

pipeline_log_upsert(spark, PIPELINE_RUN_ID, PIPELINE_NAME, PIPELINE_STATUS, PIPELINE_START_TS)