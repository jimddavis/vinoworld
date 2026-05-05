
# pipeline_utils.py
# ---------------------------------------------------------------------------
# Shared utilities for the Vinoworld ELT pipeline.
# Import from notebooks with:  from pipeline_utils import get_notebook_context
# ---------------------------------------------------------------------------
from pathlib import PurePosixPath
from datetime import datetime, timezone
from pyspark.sql.functions import current_timestamp, lit, col

def get_notebook_context(dbutils) -> dict:
    """
    Returns notebook identity fields for a log row.
    Strips /Workspace/Users/<email>/ OR /Users/<email>/ prefixes.
    """
    try:
        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
        full_path = ctx.notebookPath().get()
    except Exception as e:
        return {
            "notebook_folder":    "unknown",
            "notebook_name":      "unknown",
            "notebook_path_full": f"error: {e}",
        }

    p = PurePosixPath(full_path)
    parts = p.parts   # ('/', 'Users', 'zieder0022@gmail.com', 'Vinoworld', '000-...')

    # Find the index right after Users/<email> and slice from there.
    folder_parts = parts[1:-1]   # drop leading '/' and the notebook name itself
    if len(folder_parts) >= 2 and folder_parts[0] == "Workspace":
        folder_parts = folder_parts[1:]        # drop 'Workspace'
    if len(folder_parts) >= 2 and folder_parts[0] == "Users":
        folder_parts = folder_parts[2:]        # drop 'Users' and the email

    folder = "/".join(folder_parts) if folder_parts else "(root)"

    return {
        "notebook_folder":    folder,
        "notebook_name":      p.name,
        "notebook_path_full": full_path,
    }



# Capture exception details using stdlib TracebackException.
# Returns a dict with three keys suitable for separate audit columns:
#   error_type:      the exception class name (e.g. "ValueError")
#   error_message:   the exception's str() representation
#   error_traceback: the full formatted traceback as a string
#
# TracebackException handles chained exceptions (raise X from Y) and
# exception groups (Python 3.11+) automatically.

import traceback

def capture_exception(exc: BaseException) -> dict:
    te = traceback.TracebackException.from_exception(exc)
    return {
        "error_type":      te.exc_type.__name__,           # Python 3.13+
        "error_message":   str(exc),
        "error_traceback": "".join(te.format()),
    }



def move_all_files(
    dbutils, 
    source_path: str,
    target_path: str,
    create_target: bool = True,
    skip_dirs: bool = True,
    use_date_partition: bool = False
):
    """
    Moves all files from source_path to target_path.

    Parameters:
        source_path (str): Source directory
        target_path (str): Destination directory
        create_target (bool): Create target if missing
        skip_dirs (bool): Skip subdirectories
        use_date_partition (bool): Append YYYY-MM-DD folder

    Returns:
        dict: summary {moved, failed, errors}
    """

    result = {
        "moved": 0,
        "failed": 0,
        "errors": []
    }

    try:
        # optional date partitioning
        if use_date_partition:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            target_path = f"{target_path.rstrip('/')}/{date_str}/"

        # ensure target exists
        if create_target:
            dbutils.fs.mkdirs(target_path)

        files = dbutils.fs.ls(source_path)

        for f in files:
            try:
                # skip directories if requested
                if skip_dirs and f.isDir():
                    continue

                # avoid moving archive into itself
                if f.path.rstrip("/") == target_path.rstrip("/"):
                    continue

                destination = target_path.rstrip("/") + "/" + f.name

                dbutils.fs.mv(f.path, destination)

                result["moved"] += 1

            except Exception as e:
                result["failed"] += 1
                result["errors"].append({
                    "file": f.path,
                    "error": str(e)
                })

    except Exception as e:
        raise Exception(f"Fatal move_all_files error: {str(e)}\n{traceback.format_exc()}")

    return result













# ---------------------------------------------------------------------------
#  load_dim_from_csv - A helper function that loads csv files into a table.
#  Detailed description is in doc comments.  Quite long, but well documented
# ---------------------------------------------------------------------------

def load_dim_from_csv(spark, source_path, target_table, merge_sql_fn, 
                    add_timestamps=True, df_transform=None, 
                    step_log_id=None, ):
    """
    Load a single dimension table from a CSV file into a Silver Delta table.

    This is a generic reusable helper designed to handle the repetitive
    CSV -> temp view -> MERGE/INSERT pattern used across all file-sourced
    dimension loads. Each dimension call passes its own SQL via merge_sql_fn,
    keeping this function stable while allowing full per-table flexibility.

    Called once per dimension table from the notebook orchestration cell.
    Results are logged individually to pipeline_step_log so each dimension
    has its own success/failure audit row, rather than the entire notebook
    failing silently mid-way through a single try/except block.

    Parameters
    ----------
    spark         : SparkSession
    source_path   : str  - Full path to the CSV file, e.g. f"{SOURCE_PATH}/Currency.csv"
    target_table  : str  - Fully qualified Silver table, e.g. f"{SILVER}.dim_currency"
    merge_sql_fn  : callable(target_table) -> str
                    Lambda or function that accepts the target table name and returns
                    the MERGE or INSERT SQL string. Keeps SQL co-located with the
                    call site rather than buried inside this function.
                    Example:
                        merge_sql_fn = lambda t: f"MERGE INTO {t} a USING temp_dim s ON ..."
    add_timestamps: bool - If True (default), adds InsertedDate and UpdatedDate columns
                    via F.current_timestamp() before creating the temp view.
                    Set to False for tables like dim_date that manage their own dates.
    df_transform  : callable(df) -> df, optional
                    Hook for file-specific DataFrame transforms applied after loading
                    and after timestamps (if enabled), but before the temp view is created.
                    Use a lambda for one or two columns, a named function for more:
                        # Single transform
                        df_transform = lambda df: df.withColumn(
                            "EffectiveDate", F.to_timestamp("EffectiveDate", 'M/d/yyyy')
                        )
                        # Multiple transforms
                        df_transform = lambda df: (
                            df.withColumn("EffectiveDate", F.to_timestamp("EffectiveDate", 'M/d/yyyy'))
                              .withColumn("Amount",        F.col("Amount").cast("decimal(18,4)"))
                        )
                        # Complex transforms - use a named function instead of lambda
                        df_transform = transform_exchange_rates
    step_log_id   : int/str - FK to pipeline_step_log. Passed through to the audit
                    logging calls so each dimension load gets its own log row.


    return {
            "target_table"  : target_table,
            "status"        : "succeeded",
            "rows_written"  : rows_written,
            "error_message" : None,
            "started"       : started,
            "ended"         : datetime.now(timezone.utc)
        }

    Execution Order
    ---------------
    1. Read CSV with header
    2. Add InsertedDate / UpdatedDate (if add_timestamps=True)
    3. Apply df_transform hook (if provided)
    4. Register as temp view 'temp_dim'
    5. Execute merge_sql_fn SQL against target_table
    6. Log success/failure to pipeline_step_log

    Notes
    -----
    - The temp view name 'temp_dim' is reused for every call. This is safe
      because each call completes before the next begins (sequential, not parallel).
    """

    started = datetime.now(timezone.utc)
	
    try:
        pre_write_count = spark.table(target_table).count()
        df = spark.read.format("csv").option("header", "true").load(source_path)

        file_row_count = df.count()

        if add_timestamps:
            df = (df.withColumn("InsertedDate", current_timestamp())
                    .withColumn("UpdatedDate",  current_timestamp()))

        if df_transform:          # apply file-specific transforms if provided
            df = df_transform(df)

        df.createOrReplaceTempView("temp_dim")
        spark.sql(merge_sql_fn(target_table))

        post_write_count = spark.table(target_table).count()
        rows_written     = post_write_count - pre_write_count


        return {
            "source_path"   : source_path,
            "file_row_count": file_row_count,
            "rows_written"  : rows_written,
            "target_table"  : target_table,
            "status"        : "succeeded",
            "rows_written"  : rows_written,
            "error_message" : None,
            "started"       : started,
            "ended"         : datetime.now(timezone.utc)
        }

    except Exception as e:
        err = capture_exception(e)
        return {
            "target_table"  : target_table,
            "status"        : "failed",
            "rows_written"  : 0,
            "error_message" : f"{err['error_type']}: {err['error_message']}",
            "started"       : started,
            "ended"         : datetime.now(timezone.utc)
        }
# ---------------------------------------------------------------------------
#  END of load_dim_from_csv
# ---------------------------------------------------------------------------




def run_stage(dbutils, stage_name, notebooks, shared_params, fail_fast=True):
    errors = []
    """
    Executes a logical pipeline stage by running a sequence of Databricks notebooks with shared parameters and consistent error handling.

    ## Parameters

    stage_name : str
    Logical name of the pipeline stage (e.g., "BRONZE", "SILVER", "GOLD").  Used for logging, traceability, and error reporting.
    
    notebooks : list[str]
    Ordered list of notebook paths to execute within the stage.
    Execution is sequential and respects the order provided, which should
    reflect any intra-stage dependencies.

    shared_params : dict
    Dictionary of parameters passed to each notebook via `dbutils.notebook.run`.
    Enables consistent configuration (e.g., load dates, environment flags, source paths) across all notebooks in the stage.


    fail_fast : bool, default=True
    Controls error handling behavior:
    - True  : Immediately stops execution on the first failure and raises a RuntimeError with context about the failing notebook.
    - False : Continues executing remaining notebooks, collects all errors, and raises a RuntimeError at the end summarizing failures.


    ## Behavior

    * Executes notebooks sequentially within the stage.
    * Logs start/end of the stage and the result of each notebook execution.
    * Captures and standardizes exceptions via `Utils.capture_exception`.
    * Ensures that failures are surfaced with sufficient context for debugging.

    ## Raises

    RuntimeError
    If one or more notebooks fail. The error message includes stage name, notebook identifier(s), and captured error details.


    ## Notes

    * This function enforces stage-level isolation: downstream stages should not  execute if an upstream stage fails. consider using Databricks 
    Workflows for DAG-based execution, retries,  and parallelism.
    
    """


    print(f"=== START {stage_name} ===")

    for nb in notebooks:
        try:
            result = dbutils.notebook.run(nb, timeout_seconds=1800, arguments=shared_params)
            print(f"[{stage_name}::{nb}] returned: {result}")
        except Exception as e:
            err = capture_exception(e)
            print(f"[{stage_name}::{nb}] FAILED: {err['error_message']}")

            if fail_fast:
                raise RuntimeError(f"{stage_name} failed on {nb}: {err['error_message']}")
            else:
                errors.append({"stage": stage_name, "notebook": nb, "error": err["error_message"]})

    if errors:
        raise RuntimeError(f"{stage_name} had {len(errors)} failure(s): {errors}")

    print(f"=== END {stage_name} ===")