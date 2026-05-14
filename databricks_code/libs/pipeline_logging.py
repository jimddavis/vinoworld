# pipeline_logging.py
# ---------------------------------------------------------------------------
# Shared audit-logging helpers for the Vinoworld ELT pipeline.
#
# Imported by libs/notebook_init.ipynb after notebook_init has resolved
# shared_lib_path and prepended it to sys.path. Notebooks never call
# sys.path.append themselves; notebook_init handles that.
#
# Public functions:
#   configure(audit_schema)               — call once with f"{CATALOG}.audit"
#   pipeline_log_upsert(...)              — run-level audit row
#   pipeline_log_finalize(...)            — close out a run by scanning step log
#   pipeline_step_log_upsert(...)         — notebook-level audit row
#   transform_detail_log_insert(...)      — table-level audit row (insert-only)
#   ingestion_log_insert(...)             — file-level audit (bronze only)
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone
from pyspark.sql import functions as F
from pyspark.sql.types import (
    Row, StructType, StructField,
    StringType, IntegerType, LongType, TimestampType, DoubleType, BooleanType
)

# ---------------------------------------------------------------------------
# Status vocabulary — single source of truth for the audit-row status column.
# notebook_init re-exports these so notebooks see STATUS_RUNNING etc; the
# spark_python_task scripts (init_pipeline_run_log, finalize_pipeline_run_log)
# import them directly since they don't run notebook_init.
# ---------------------------------------------------------------------------

STATUS_RUNNING   = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED    = "failed"
STATUS_NO_FILES  = "no_files"


# ---------------------------------------------------------------------------
# Audit schema is set at runtime by notebook_init via configure().
# All audit table names derive from this prefix so the module honors the
# bundle target's catalog (dev_vinoworld / staging_vinoworld / vinoworld).
# ---------------------------------------------------------------------------

_AUDIT_SCHEMA_NAME = None


def configure(audit_schema):
    global _AUDIT_SCHEMA_NAME
    _AUDIT_SCHEMA_NAME = audit_schema


def _audit(table):
    if _AUDIT_SCHEMA_NAME is None:
        raise RuntimeError(
            "pipeline_logging.configure(audit_schema) must be called "
            "before any logging function (typically from notebook_init)."
        )
    return f"{_AUDIT_SCHEMA_NAME}.{table}"


def _to_utc_aware(dt):
    """Normalize a datetime to offset-aware UTC. None → None.

    Naive datetimes are assumed to be UTC. Used at the entry of audit
    helpers because callers may pass freshly-minted aware datetimes
    (`datetime.now(timezone.utc)`) or naive datetimes read back from
    Spark TIMESTAMP columns; mixing the two in subtraction raises
    TypeError.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

_AUDIT_SCHEMA = StructType([
    StructField("pipeline_run_id",    StringType(),    False),
    StructField("pipeline_name",      StringType(),    False),
    StructField("status",             StringType(),    False),
    StructField("started_timestamp",  TimestampType(), False),
    StructField("ended_timestamp",    TimestampType(), True),
    StructField("duration_seconds",   DoubleType(),    True),
    StructField("error_message",      StringType(),    True),
])


def pipeline_log_upsert(
    spark,
    pipeline_run_id:    str,
    pipeline_name:      str,
    status:             str,
    started_timestamp:  datetime,
    ended_timestamp:    datetime = None,
    error_message:      str      = None,
):
    """
    Upsert a single row into the pipeline audit log.

    Args:
        spark:             Active SparkSession.
        pipeline_run_id:   UUID string PK.
        pipeline_name:     Logical name of the pipeline, e.g. 'nightly_sales_etl'.
        status:            'running' | 'succeeded' | 'failed'
        started_timestamp: datetime when the run started.
        ended_timestamp:   datetime when the run ended (None if still running).
        error_message:     Exception message on failure (None otherwise).
    """

    started_timestamp = _to_utc_aware(started_timestamp)
    ended_timestamp   = _to_utc_aware(ended_timestamp)

    duration_seconds = (
        (ended_timestamp - started_timestamp).total_seconds()
        if ended_timestamp else None
    )

    row = Row(
        pipeline_run_id   = pipeline_run_id,
        pipeline_name     = pipeline_name,
        status            = status,
        started_timestamp = started_timestamp,
        ended_timestamp   = ended_timestamp,
        duration_seconds  = duration_seconds,
        error_message     = error_message,
    )

    df_log_row = spark.createDataFrame([row], schema=_AUDIT_SCHEMA)

    from delta.tables import DeltaTable

    DeltaTable.forName(spark, _audit("pipeline_log")) \
        .alias("target") \
        .merge(df_log_row.alias("source"),
               "target.pipeline_run_id = source.pipeline_run_id") \
        .whenMatchedUpdateAll() \
        .whenNotMatchedInsertAll() \
        .execute()


def pipeline_log_finalize(spark, pipeline_run_id: str):
    """
    Close out a pipeline_log row at end of run.

    Reads pipeline_name + started_timestamp from the existing row, scans
    pipeline_step_log for failures attributable to this run, and upserts
    the row with final status, ended_timestamp, duration, and an
    aggregated error_message.

    Status derivation:
        - Any pipeline_step_log row with status='failed' → pipeline
          status='failed', error_message lists the failed notebooks.
        - Otherwise → 'succeeded'.

    Args:
        spark:           Active SparkSession.
        pipeline_run_id: FK to pipeline_log. Must already exist (created
                         by pipeline_log_upsert at run start).

    Raises:
        ValueError: if no pipeline_log row exists for pipeline_run_id.
    """
    header = spark.sql(f"""
        SELECT pipeline_name, started_timestamp
        FROM {_audit('pipeline_log')}
        WHERE pipeline_run_id = '{pipeline_run_id}'
    """).collect()

    if not header:
        raise ValueError(
            f"No pipeline_log row exists for pipeline_run_id='{pipeline_run_id}'. "
            f"Call pipeline_log_upsert at run start before pipeline_log_finalize."
        )

    pipeline_name     = header[0]["pipeline_name"]
    started_timestamp = header[0]["started_timestamp"]
    ended_timestamp   = datetime.now(timezone.utc)

    # pipeline_step_log is the source of truth for what happened. Any
    # 'failed' step row means the pipeline failed, regardless of how the
    # surrounding Databricks job tasks reported.
    failed = spark.sql(f"""
        SELECT
            COUNT(*)                    AS failed_count,
            COLLECT_LIST(notebook_name) AS failed_notebooks
        FROM {_audit('pipeline_step_log')}
        WHERE pipeline_run_id = '{pipeline_run_id}'
          AND status = '{STATUS_FAILED}'
    """).collect()[0]

    if failed["failed_count"] > 0:
        status        = STATUS_FAILED
        error_message = (
            f"{failed['failed_count']} step(s) failed: "
            f"{', '.join(failed['failed_notebooks'])}. "
            f"See {_audit('pipeline_step_log')} for details."
        )
    else:
        status        = STATUS_SUCCEEDED
        error_message = None

    pipeline_log_upsert(
        spark, pipeline_run_id, pipeline_name, status,
        started_timestamp, ended_timestamp, error_message,
    )


# ----------------------------------------------------------
# Setup Schema for the pipeline_step_log table
# ----------------------------------------------------------

_STEP_LOG_SCHEMA = StructType([
    StructField("step_log_id",        StringType(),    False),
    StructField("pipeline_run_id",    StringType(),    False),
    StructField("step_sequence",      IntegerType(),   False),
    StructField("notebook_folder",    StringType(),    False),
    StructField("notebook_name",      StringType(),    False),
    StructField("layer",              StringType(),    True),
    StructField("target_table",       StringType(),    True),
    StructField("status",             StringType(),    False),
    StructField("rows_read",          LongType(),      True),
    StructField("rows_written",       LongType(),      True),
    StructField("started_timestamp",  TimestampType(), False),
    StructField("ended_timestamp",    TimestampType(), True),
    StructField("duration_seconds",   DoubleType(),    True),
    StructField("error_message",      StringType(),    True),
])


def pipeline_step_log_upsert(
    spark,
    step_log_id:        str,
    pipeline_run_id:    str,
    step_sequence:      int,
    notebook_folder:    str,
    notebook_name:      str,
    status:             str,
    started_timestamp:  datetime,
    layer:              str      = None,
    target_table:       str      = None,
    rows_read:          int      = None,
    rows_written:       int      = None,
    ended_timestamp:    datetime = None,
    error_message:      str      = None,
):
    """
    Upsert a single row into the pipeline step audit log.

    Args:
        spark:             Active SparkSession.
        step_log_id:       UUID string PK for this step row.
        pipeline_run_id:   FK to pipeline_log.
        step_sequence:     Ordinal position of this step (1, 2, 3...).
        notebook_folder:   Folder portion of the notebook path.
        notebook_name:     Name of the notebook.
        status:            'running' | 'succeeded' | 'failed'
        started_timestamp: datetime when the step started.
        layer:             'bronze' | 'silver' | 'gold' (optional).
        target_table:      Table being written (optional).
        rows_read:         Row count read by this step (optional).
        rows_written:      Row count written by this step (optional).
        ended_timestamp:   datetime when the step ended (None if still running).
        error_message:     Exception message on failure (None otherwise).
    """

    started_timestamp = _to_utc_aware(started_timestamp)
    ended_timestamp   = _to_utc_aware(ended_timestamp)

    duration_seconds = (
        (ended_timestamp - started_timestamp).total_seconds()
        if ended_timestamp else None
    )

    row = Row(
        step_log_id       = step_log_id,
        pipeline_run_id   = pipeline_run_id,
        step_sequence     = step_sequence,
        notebook_folder   = notebook_folder,
        notebook_name     = notebook_name,
        layer             = layer,
        target_table      = target_table,
        status            = status,
        rows_read         = rows_read,
        rows_written      = rows_written,
        started_timestamp = started_timestamp,
        ended_timestamp   = ended_timestamp,
        duration_seconds  = duration_seconds,
        error_message     = error_message,
    )

    df_log_row = spark.createDataFrame([row], schema=_STEP_LOG_SCHEMA)

    from delta.tables import DeltaTable

    DeltaTable.forName(spark, _audit("pipeline_step_log")) \
        .alias("target") \
        .merge(df_log_row.alias("source"),
               "target.step_log_id = source.step_log_id") \
        .whenMatchedUpdateAll() \
        .whenNotMatchedInsertAll() \
        .execute()





# ----------------------------------------------------------
# Setup Schema for the transform_detail_log table
# ----------------------------------------------------------

_TRANSFORM_DETAIL_SCHEMA = StructType([
    StructField("transform_id",               StringType(),    False),
    StructField("pipeline_run_id",            StringType(),    False),
    StructField("step_log_id",                StringType(),    False),
    StructField("source_table",               StringType(),    False),
    StructField("target_table",               StringType(),    False),
    StructField("status",                     StringType(),    False),
    StructField("rows_read",                  LongType(),      True),
    StructField("rows_written",               LongType(),      True),
    StructField("rows_inserted",              LongType(),      True),
    StructField("rows_updated",               LongType(),      True),
    StructField("rows_expired",               LongType(),      True),
    StructField("rows_rejected",              LongType(),      True),
    StructField("rows_deduplicated",          LongType(),      True),
    StructField("validation_rules_applied",   StringType(),    True),
    StructField("schema_drift_detected",      BooleanType(),   True),
    StructField("schema_drift_detail",        StringType(),    True),
    StructField("error_message",              StringType(),    True),
    StructField("started_timestamp",          TimestampType(), False),
    StructField("ended_timestamp",            TimestampType(), True),
    StructField("duration_seconds",           DoubleType(),    True),
])


def transform_detail_log_insert(
    spark,
    pipeline_run_id:            str,
    step_log_id:                str,
    source_table:               str,
    target_table:               str,
    status:                     str,
    started_timestamp:          datetime,
    rows_read:                  int      = None,
    rows_written:               int      = None,
    rows_inserted:              int      = None,
    rows_updated:               int      = None,
    rows_expired:               int      = None,
    rows_rejected:              int      = None,
    rows_deduplicated:          int      = None,
    validation_rules_applied:   str      = None,
    schema_drift_detected:      bool     = None,
    schema_drift_detail:        str      = None,
    error_message:              str      = None,
    ended_timestamp:            datetime = None,
):
    """
    Insert a single row into the transform detail audit log.
    Insert-only — no upsert. Each transform attempt is a permanent
    immutable record. Called once per source/target table pair from
    load_dim_from_csv() or equivalent transform helper after the
    MERGE/INSERT completes or fails.

    This is the third tier of the three-tier audit hierarchy:
        pipeline_run_log          (pipeline level)
          pipeline_step_log       (notebook level)
            transform_detail_log  (table level)  ← this table

    Args:
        spark:                    Active SparkSession.
        pipeline_run_id:          FK to pipeline_log.
        step_log_id:              FK to pipeline_step_log.
        source_table:             Fully qualified source table or file path,
                                  e.g. 'bronze.orders' or 'Currency.csv'.
        target_table:             Fully qualified target Silver/Gold table,
                                  e.g. 'silver.dim_currency'.
        status:                   'succeeded' | 'failed' | 'skipped'.
                                  'skipped' when a prior dim in the same
                                  notebook failed and this one never ran.
        started_timestamp:        datetime when this table's transform started.
        rows_read:                Rows read from source before any filtering.
        rows_written:             Total rows affecting target (inserted + updated).
        rows_inserted:            Net new rows added, from DESCRIBE HISTORY.
        rows_updated:             Rows matched and updated, from DESCRIBE HISTORY.
        rows_expired:             SCD2 rows expired (IsCurrent set to 0).
                                  Meaningful only for SCD2 dimension loads.
        rows_rejected:            Rows failing validation, written to quarantine.
        rows_deduplicated:        Rows removed by dropDuplicates() before load.
        validation_rules_applied: JSON array string of rules checked, e.g.
                                  '["CurrencyCode NOT NULL", "Rate > 0"]'.
                                  Manually constructed alongside validation code.
        schema_drift_detected:    True if source schema differs from last run.
        schema_drift_detail:      JSON string describing drift, e.g.
                                  '{"added": ["NewCol"], "removed": [], "changed": []}'.
        error_message:            Exception message on failure, None on success.
        ended_timestamp:          datetime when transform ended. None if the
                                  process died unexpectedly before completion.

    Notes:

        - Unlike pipeline_step_log_upsert this method uses append-only write,
          not a MERGE. Audit records are immutable once written.
        - For BEGIN ATOMIC SCD2 merges, rows_inserted/rows_updated come from
          pre/post count difference or InsertedDate/UpdatedDate query, not
          DESCRIBE HISTORY (which returns zeros for atomic blocks).
    """

    started_timestamp = _to_utc_aware(started_timestamp)
    ended_timestamp   = _to_utc_aware(ended_timestamp)

    duration_seconds = (
        (ended_timestamp - started_timestamp).total_seconds()
        if ended_timestamp else None
    )

    # transform_id is the table's PK; auto-generated here so callers don't
    # need to manage it. Caller has no reason to know this id (the table is
    # a leaf in the audit hierarchy — nothing references transform_id).
    transform_id = str(uuid.uuid4())

    row = Row(
        transform_id             = transform_id,
        pipeline_run_id          = pipeline_run_id,
        step_log_id              = step_log_id,
        source_table             = source_table,
        target_table             = target_table,
        status                   = status,
        rows_read                = rows_read,
        rows_written             = rows_written,
        rows_inserted            = rows_inserted,
        rows_updated             = rows_updated,
        rows_expired             = rows_expired,
        rows_rejected            = rows_rejected,
        rows_deduplicated        = rows_deduplicated,
        validation_rules_applied = validation_rules_applied,
        schema_drift_detected    = schema_drift_detected,
        schema_drift_detail      = schema_drift_detail,
        error_message            = error_message,
        started_timestamp        = started_timestamp,
        ended_timestamp          = ended_timestamp,
        duration_seconds         = duration_seconds,
    )

    df_log_row = spark.createDataFrame([row], schema=_TRANSFORM_DETAIL_SCHEMA)

    df_log_row.write \
        .format("delta") \
        .mode("append") \
        .saveAsTable(_audit("transform_detail_log"))






# ------------------------------------------------
# ingestion_log Using spark.sql and a SQL Insert statement
# ------------------------------------------------

def ingestion_log_insert(
    spark,
    df_files:           "DataFrame",
    pipeline_run_id:    str,
    step_log_id:        str,
    source_system:      str,
    target_table:       str,
    error_message:      str      = None,
    ingested_timestamp: datetime = None,
):
    """
    Append one row per file into the ingestion audit log.

    Delta generates ingestion_id via IDENTITY — do not supply it.
    Uses INSERT INTO ... SELECT so column names are explicit and the
    IDENTITY column is skipped automatically.

    Args:
        spark:              Active SparkSession.
        df_files:           DataFrame with a single column 'source_file_path',
                            one row per file read from the Volume.
        pipeline_run_id:    FK to pipeline_log.
        step_log_id:        FK to pipeline_step_log.
        source_system:      'arancione' | 'celeste' | 'verde'
        target_table:       Table being written, e.g. 'vinoworld.bronze.sales'.
        error_message:      Error message if ingestion failed (None otherwise).
        ingested_timestamp: Defaults to datetime.now(timezone.utc) if not supplied.
    """


    if ingested_timestamp is None:
        ingested_timestamp = datetime.now(timezone.utc)

    df_log = (
        df_files.select("source_file_path")
        .withColumn("ingestion_id",       F.expr("uuid()"))
        .withColumn("pipeline_run_id",    F.lit(pipeline_run_id))
        .withColumn("step_log_id",        F.lit(step_log_id))
        .withColumn("source_system",      F.lit(source_system))
        .withColumn("target_table",       F.lit(target_table))
        .withColumn("error_message",      F.lit(error_message))
        .withColumn("ingested_timestamp", F.lit(ingested_timestamp).cast("timestamp"))
    )

    # Register  DataFrame as a temporary table name that SQL can reference
    df_log.createOrReplaceTempView("_ingestion_log_staging")

    spark.sql(f"""
        INSERT INTO {_audit("ingestion_log")}
            (ingestion_id, pipeline_run_id, step_log_id, source_system, source_file_path,
             target_table, error_message, ingested_timestamp)
        SELECT
             ingestion_id, pipeline_run_id, step_log_id, source_system, source_file_path,
             target_table, error_message, ingested_timestamp
        FROM _ingestion_log_staging
    """)

