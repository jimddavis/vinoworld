# catalog_setup.py
# Provisioning utilities for the Vinoworld Databricks environment.
# Called from setup/catalog_ddl.ipynb — never imported by pipeline notebooks.

import traceback


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(message, objects_created=None):
    return {
        "status":          "succeeded",
        "message":         message,
        "objects_created": objects_created or [],
        "error":           None,
    }


def _fail(message, exc):
    return {
        "status":          "failed",
        "message":         message,
        "objects_created": [],
        "error":           f"{type(exc).__name__}: {exc}\n{''.join(traceback.format_exception(exc))}",
    }


def _run_ddl(spark, statements):
    """
    Execute a list of (table_name, sql) pairs in order.
    Stops and returns a failed result on the first error.
    """
    created = []
    for table_name, sql in statements:
        try:
            spark.sql(sql)
            created.append(table_name)
        except Exception as e:
            return _fail(f"Failed to create '{table_name}'.", e)
    return _ok(f"{len(created)} table(s) ready.", created)


# ---------------------------------------------------------------------------
# Group A: Catalog and Schemas
# ---------------------------------------------------------------------------

def create_catalog(spark, catalog, managed_location=None):
    try:
        location_clause = f"\n    MANAGED LOCATION '{managed_location}'" if managed_location else ""
        spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}{location_clause}")
        return _ok(f"Catalog '{catalog}' is ready.", [catalog])
    except Exception as e:
        return _fail(f"Failed to create catalog '{catalog}'.", e)


def create_schemas(spark, schemas):
    """schemas: list of fully-qualified schema names, e.g. ['vinoworld.bronze', ...]"""
    created = []
    for schema in schemas:
        try:
            spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            created.append(schema)
        except Exception as e:
            return _fail(f"Failed to create schema '{schema}'.", e)
    return _ok(f"{len(created)} schema(s) ready.", created)


def create_volume_schema(spark, catalog):
    schema = f"{catalog}.datafiles"
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        return _ok(f"Volume schema '{schema}' is ready.", [schema])
    except Exception as e:
        return _fail(f"Failed to create volume schema '{schema}'.", e)


# ---------------------------------------------------------------------------
# Group B: Volumes and Directories
# ---------------------------------------------------------------------------

def create_volumes(spark, dbutils, catalog, volume_definitions):
    """
    volume_definitions: list of {"name": str, "needs_archive": bool}
    Creates each volume under catalog.datafiles and, when needs_archive is True,
    creates the archive subfolder inside the volume path.
    """
    created = []
    for vol in volume_definitions:
        name      = vol["name"]
        full_name = f"{catalog}.datafiles.{name}"
        vol_path  = f"/Volumes/{catalog}/datafiles/{name}"
        try:
            spark.sql(f"CREATE VOLUME IF NOT EXISTS {full_name}")
            if vol.get("needs_archive"):
                dbutils.fs.mkdirs(f"{vol_path}/archive")
            created.append(full_name)
        except Exception as e:
            return _fail(f"Failed to create volume '{full_name}'.", e)
    return _ok(f"{len(created)} volume(s) ready.", created)


# ---------------------------------------------------------------------------
# Group C: Table DDL
# ---------------------------------------------------------------------------

def create_audit_tables(spark, audit_schema):
    statements = [
        (f"{audit_schema}.pipeline_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.pipeline_log (
                pipeline_run_id      STRING      NOT NULL,
                pipeline_name        STRING      NOT NULL,
                status               STRING      NOT NULL,
                started_timestamp    TIMESTAMP   NOT NULL,
                ended_timestamp      TIMESTAMP,
                duration_seconds     DOUBLE,
                error_message        STRING
            )
        """),
        (f"{audit_schema}.pipeline_step_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.pipeline_step_log (
                step_log_id          STRING      NOT NULL,
                pipeline_run_id      STRING      NOT NULL,
                step_sequence        INT         NOT NULL,
                notebook_folder      STRING      NOT NULL,
                notebook_name        STRING      NOT NULL,
                layer                STRING,
                target_table         STRING,
                status               STRING      NOT NULL,
                rows_read            BIGINT,
                rows_written         BIGINT,
                started_timestamp    TIMESTAMP   NOT NULL,
                ended_timestamp      TIMESTAMP,
                duration_seconds     DOUBLE,
                error_message        STRING
            )
        """),
        (f"{audit_schema}.transform_detail_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.transform_detail_log (
                transform_id                STRING      NOT NULL,
                pipeline_run_id             STRING      NOT NULL,
                step_log_id                 STRING      NOT NULL,
                source_table                STRING      NOT NULL,
                target_table                STRING      NOT NULL,
                status                      STRING      NOT NULL,
                rows_read                   BIGINT,
                rows_written                BIGINT,
                rows_inserted               BIGINT,
                rows_updated                BIGINT,
                rows_expired                BIGINT,
                rows_rejected               BIGINT,
                rows_deduplicated           BIGINT,
                validation_rules_applied    STRING,
                schema_drift_detected       BOOLEAN,
                schema_drift_detail         STRING,
                error_message               STRING,
                started_timestamp           TIMESTAMP   NOT NULL,
                ended_timestamp             TIMESTAMP,
                duration_seconds            DOUBLE
            )
        """),
        (f"{audit_schema}.ingestion_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.ingestion_log (
                ingestion_id         STRING      NOT NULL,
                pipeline_run_id      STRING      NOT NULL,
                step_log_id          STRING      NOT NULL,
                source_system        STRING      NOT NULL,
                source_file_path     STRING      NOT NULL,
                target_table         STRING      NOT NULL,
                error_message        STRING,
                ingested_timestamp   TIMESTAMP   NOT NULL
            )
        """),
    ]
    return _run_ddl(spark, statements)


def create_bronze_tables(spark, bronze_schema):
    statements = [
        (f"{bronze_schema}.sales_arancione", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.sales_arancione (
                online_retailer     STRING,
                sales_month         STRING,
                title               STRING,
                vintage             STRING,
                variety             STRING,
                score               STRING,
                list_price          STRING,
                quantity            STRING,
                row_hash            STRING      NOT NULL,
                inserted_ts         TIMESTAMP,
                run_id              STRING,
                source_file_path    STRING,
                store_name          STRING
            )
        """),
        (f"{bronze_schema}.sales_celeste", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.sales_celeste (
                transaction_id      STRING,
                transaction_date    STRING,
                online_retailer     STRING,
                sales_month         STRING,
                sales_region        STRING,
                sales_currency      STRING,
                title               STRING,
                vintage             STRING,
                variety             STRING,
                score               STRING,
                list_price          STRING,
                quantity            STRING,
                row_hash            STRING      NOT NULL,
                inserted_ts         TIMESTAMP,
                run_id              STRING,
                source_file_path    STRING,
                store_name          STRING
            )
        """),
        (f"{bronze_schema}.sales_verde", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.sales_verde (
                year_month          STRING,
                store_name          STRING,
                product             STRING,
                vintage             STRING,
                variety             STRING,
                score               STRING,
                sales_price         STRING,
                sales_qty           STRING,
                row_hash            STRING      NOT NULL,
                inserted_ts         TIMESTAMP,
                run_id              STRING,
                source_file_path    STRING
            )
        """),
        (f"{bronze_schema}.products", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.products (
                store_name          STRING,
                product_no          STRING,
                country             STRING,
                score               STRING,
                dealer_price        STRING,
                markup              STRING,
                list_price          STRING,
                province            STRING,
                region_1            STRING,
                region_2            STRING,
                title               STRING,
                vintage             STRING,
                variety             STRING,
                winery              STRING,
                year                STRING,
                row_hash            STRING      NOT NULL,
                inserted_ts         TIMESTAMP,
                run_id              STRING,
                source_file_path    STRING
            )
        """),
    ]
    return _run_ddl(spark, statements)


def create_silver_tables(spark, silver_schema):
    statements = [
        (f"{silver_schema}.dim_currency", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_currency (
                CurrencyId      BIGINT GENERATED ALWAYS AS IDENTITY,
                CurrencyCode    STRING      NOT NULL,
                CurrencyName    STRING,
                InsertedDate    TIMESTAMP   NOT NULL,
                UpdatedDate     TIMESTAMP   NOT NULL
            )
        """),
        (f"{silver_schema}.dim_date", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_date (
                DateId          BIGINT GENERATED ALWAYS AS IDENTITY,
                DateYear        SMALLINT    NOT NULL,
                DateMonth       SMALLINT    NOT NULL,
                YearMonth       STRING,
                LastDayOfMonth  DATE,
                Quarter         TINYINT     NOT NULL,
                Season          STRING
            )
        """),
        (f"{silver_schema}.dim_exchange_rate", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_exchange_rate (
                ExchangeRateId  BIGINT GENERATED ALWAYS AS IDENTITY,
                FromCurrency    STRING,
                ToCurrency      STRING,
                EffectiveDate   DATE,
                ExchangeRate    DOUBLE,
                InsertedDate    TIMESTAMP   NOT NULL,
                UpdatedDate     TIMESTAMP   NOT NULL
            )
        """),
        (f"{silver_schema}.dim_region", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_region (
                RegionId        BIGINT GENERATED ALWAYS AS IDENTITY,
                Province        STRING      NOT NULL,
                RegionName      STRING,
                SubRegionName   STRING,
                Latitude        DOUBLE,
                Longitude       DOUBLE,
                InsertedDate    TIMESTAMP   NOT NULL,
                UpdatedDate     TIMESTAMP   NOT NULL
            )
        """),
        (f"{silver_schema}.dim_store", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_store (
                StoreId         BIGINT GENERATED ALWAYS AS IDENTITY,
                StoreName       STRING      NOT NULL,
                StoreType       STRING      NOT NULL,
                Description     STRING,
                InsertedDate    TIMESTAMP   NOT NULL,
                UpdatedDate     TIMESTAMP   NOT NULL
            )
        """),
        (f"{silver_schema}.dim_territory", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_territory (
                TerritoryId     BIGINT GENERATED ALWAYS AS IDENTITY,
                TerritoryCode   STRING      NOT NULL,
                TerritoryName   STRING      NOT NULL,
                TradeRegion     STRING      NOT NULL,
                Continent       STRING,
                InsertedDate    TIMESTAMP   NOT NULL,
                UpdatedDate     TIMESTAMP   NOT NULL
            )
        """),
        (f"{silver_schema}.dim_product", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_product (
                ProductId        BIGINT GENERATED ALWAYS AS IDENTITY,
                ProductNo        STRING      NOT NULL,
                ProductName      STRING      NOT NULL,
                Province         STRING      NOT NULL,
                Region           STRING,
                Variety          STRING,
                Winery           STRING,
                Vintage          SMALLINT,
                Score            SMALLINT    NOT NULL,
                DealerPrice      INT         NOT NULL,
                Markup           DECIMAL(5,2) NOT NULL,
                ListPrice        INT         NOT NULL,
                RowHash          STRING      NOT NULL,
                IsRowCurrent     BOOLEAN     NOT NULL,
                EffectiveDate    TIMESTAMP   NOT NULL,
                EndDate          TIMESTAMP   NOT NULL,
                UpdatedDate      TIMESTAMP   NOT NULL
            )
        """),
         (f"{silver_schema}.sales", f"""
            CREATE TABLE IF NOT EXISTS  {silver_schema}.sales (
				product_no          STRING          NOT NULL,
				online_retailer     STRING,
				sales_month         STRING,
				sales_territory     STRING,
				sales_currency      STRING,
				title               STRING,
				vintage             INT,
				variety             STRING,
				score               INT,
				list_price          INT,
				quantity            INT,
				row_hash            STRING,
				source_inserted_ts  TIMESTAMP,
				run_id              STRING,
				inserted_ts         TIMESTAMP,
				updated_ts          TIMESTAMP
			)
        """),
    ]
    result = _run_ddl(spark, statements)
    if result["status"] == "succeeded":
        try:
            spark.sql(
                f"ALTER TABLE {silver_schema}.dim_product "
                f"SET TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported')"
            )
        except Exception as e:
            return _fail(
                f"Failed to set table properties on '{silver_schema}.dim_product'.", e
            )
    return result


def create_gold_tables(spark, gold_schema, silver_schema):
    statements = [
        (f"{gold_schema}.sales_fact", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.sales_fact (
                sales_fact_id           BIGINT          GENERATED ALWAYS AS IDENTITY,
                date_id                 BIGINT          NOT NULL,
                product_id              BIGINT          NOT NULL,
                store_id                BIGINT          NOT NULL,
                territory_id            BIGINT          NOT NULL,
                region_id               BIGINT          NOT NULL,
                currency_id             BIGINT          NOT NULL,
                product_no              STRING          NOT NULL,
                sales_month             STRING          NOT NULL,
                quantity                INT             NOT NULL,
                list_price_local        DECIMAL(10,2)   NOT NULL,
                total_sales             DECIMAL(10,2)   NOT NULL,
                exchange_rate_applied   DECIMAL(10,6),
                list_price_converted    DECIMAL(10,2),
                total_sales_converted   DECIMAL(10,2),
                row_hash                STRING          NOT NULL,
                inserted_ts             TIMESTAMP       NOT NULL,
                updated_ts              TIMESTAMP       NOT NULL,
                CONSTRAINT pk_sales_fact PRIMARY KEY (sales_fact_id)
            )
        """),
        (f"{gold_schema}.dim_product", f"""
            CREATE OR REPLACE VIEW {gold_schema}.dim_product AS
                SELECT
                    ProductId,
                    ProductNo,
                    ProductName,
                    Province,
                    Region,
                    Variety,
                    Winery,
                    Vintage,
                    Score,
                    DealerPrice,
                    Markup,
                    ListPrice
                FROM {silver_schema}.dim_product
                WHERE IsRowCurrent = true
        """),
        (f"{gold_schema}.dim_currency", f"""
            CREATE OR REPLACE VIEW {gold_schema}.dim_currency AS
                SELECT
                    CurrencyId,
                    CurrencyCode,
                    CurrencyName
                FROM {silver_schema}.dim_currency
        """),

        (f"{gold_schema}.dim_date", f"""
                    CREATE OR REPLACE VIEW {gold_schema}.dim_date AS
                        SELECT
                            DateId,
                            DateYear,
                            DateMonth,
                            YearMonth,
                            LastDayOfMonth,
                            Quarter,
                            Season
                        FROM {silver_schema}.dim_date
                """),

        (f"{gold_schema}.dim_exchange_rate", f"""
                CREATE OR REPLACE VIEW {gold_schema}.dim_exchange_rate AS
                    SELECT
                        ExchangeRateId,
                        FromCurrency,
                        ToCurrency,
                        EffectiveDate,
                        ExchangeRate
                    FROM {silver_schema}.dim_exchange_rate
            """),


        (f"{gold_schema}.dim_region", f"""
                CREATE OR REPLACE VIEW {gold_schema}.dim_region AS
                    SELECT
                        RegionId,
                        Province,
                        RegionName,
                        SubRegionName,
                        Latitude,
                        Longitude
                    FROM {silver_schema}.dim_region
            """),


        (f"{gold_schema}.dim_store", f"""
                CREATE OR REPLACE VIEW {gold_schema}.dim_store AS
                    SELECT
                        StoreId,
                        StoreName,
                        StoreType,
                        Description
                    FROM {silver_schema}.dim_store
            """),

        (f"{gold_schema}.dim_territory", f"""
                CREATE OR REPLACE VIEW {gold_schema}.dim_territory AS
                    SELECT
                        TerritoryId,
                        TerritoryCode,
                        TerritoryName,
                        TradeRegion,
                        Continent
                    FROM {silver_schema}.dim_territory
            """),
    ]
    return _run_ddl(spark, statements)


# ---------------------------------------------------------------------------
# Group D: Diagnostic / reporting views
# ---------------------------------------------------------------------------

def create_audit_views(spark, audit_schema):
    """
    Diagnostic views over the pipeline-logging audit tables. Call AFTER
    create_audit_tables — these views reference pipeline_log,
    pipeline_step_log, and transform_detail_log.
    """
    statements = [
        (f"{audit_schema}.vw_pipeline_run_summary", f"""
            CREATE OR REPLACE VIEW {audit_schema}.vw_pipeline_run_summary AS
            SELECT
                p.pipeline_run_id,
                p.pipeline_name,
                p.status                                                AS run_status,
                date_format(p.started_timestamp, 'yyyy-MM-dd HH:mm:ss') AS run_started,
                p.ended_timestamp                                       AS run_ended,
                p.duration_seconds                                      AS run_duration_seconds,
                COUNT(s.step_log_id)                                    AS step_count,
                SUM(CASE WHEN s.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_steps,
                SUM(CASE WHEN s.status = 'failed'    THEN 1 ELSE 0 END) AS failed_steps,
                SUM(CASE WHEN s.status = 'running'   THEN 1 ELSE 0 END) AS running_steps,
                SUM(s.rows_read)                                        AS total_rows_read,
                SUM(s.rows_written)                                     AS total_rows_written,
                p.error_message                                         AS run_error_message
            FROM {audit_schema}.pipeline_log p
            LEFT JOIN {audit_schema}.pipeline_step_log s
                ON s.pipeline_run_id = p.pipeline_run_id
            GROUP BY
                p.pipeline_run_id, p.pipeline_name, p.status,
                p.started_timestamp, p.ended_timestamp, p.duration_seconds,
                p.error_message
        """),
        (f"{audit_schema}.vw_pipeline_step_drilldown", f"""
            CREATE OR REPLACE VIEW {audit_schema}.vw_pipeline_step_drilldown AS
            SELECT
                p.pipeline_name,
                date_format(p.started_timestamp, 'yyyy-MM-dd HH:mm:ss') AS run_started,
                s.pipeline_run_id,
                s.step_sequence,
                s.layer,
                s.notebook_folder,
                s.notebook_name,
                s.target_table                                  AS step_target_table,
                s.status                                        AS step_status,
                s.rows_read                                     AS step_rows_read,
                s.rows_written                                  AS step_rows_written,
                s.started_timestamp                             AS step_started,
                s.ended_timestamp                               AS step_ended,
                s.duration_seconds                              AS step_duration_seconds,

                t.source_table                                  AS transform_source,
                t.target_table                                  AS transform_target,
                t.status                                        AS transform_status,
                t.rows_read                                     AS transform_rows_read,
                t.rows_written                                  AS transform_rows_written,
                t.rows_inserted                                 AS transform_rows_inserted,
                t.rows_updated                                  AS transform_rows_updated,
                t.rows_expired                                  AS transform_rows_expired,
                t.rows_rejected                                 AS transform_rows_rejected,
                t.duration_seconds                              AS transform_duration_seconds,

                COALESCE(t.error_message, s.error_message)      AS error_message
            FROM {audit_schema}.pipeline_step_log s
            INNER JOIN {audit_schema}.pipeline_log p
                ON p.pipeline_run_id = s.pipeline_run_id
            LEFT JOIN {audit_schema}.transform_detail_log t
                ON t.step_log_id = s.step_log_id
        """),
    ]
    return _run_ddl(spark, statements)


def create_reporting_views(spark, reporting_schema, silver_schema, gold_schema):
    """
    Reporting views over the gold sales_fact. Call AFTER create_gold_tables —
    these views reference gold.sales_fact and silver.dim_*.

    vw_sales_fact is the base view (joins to all dims); the others aggregate
    from vw_sales_fact, so creation order matters within the statement list.
    """
    statements = [
        # Base view — joins gold.sales_fact to silver dims directly. Joining
        # silver.dim_product (not gold.dim_product) so historical SCD2 rows
        # still resolve — gold.dim_product filters IsRowCurrent = TRUE.
        (f"{reporting_schema}.vw_sales_fact", f"""
            CREATE OR REPLACE VIEW {reporting_schema}.vw_sales_fact AS
            SELECT
                dd.YearMonth                AS year_month,
                dd.DateYear                 AS sales_year,
                dd.DateMonth                AS sales_month_num,
                dd.Quarter                  AS sales_quarter,
                dd.Season                   AS sales_season,

                dp.ProductNo                AS product_no,
                dp.ProductName              AS product_name,
                dp.Variety                  AS variety,
                dp.Winery                   AS winery,
                dp.Vintage                  AS vintage,
                dp.Score                    AS score,

                ds.StoreName                AS store_name,
                ds.StoreType                AS store_type,
                dt.TerritoryName            AS territory_name,
                dt.TradeRegion              AS trade_region,
                dt.Continent                AS continent,
                dr.Province                 AS province,
                dr.RegionName               AS region_name,

                dc.CurrencyCode             AS currency_code,
                dc.CurrencyName             AS currency_name,

                f.quantity                  AS quantity,
                f.list_price_local          AS list_price_local,
                f.total_sales               AS total_sales_local,
                f.exchange_rate_applied     AS exchange_rate_applied,
                f.list_price_converted      AS list_price_eur,
                f.total_sales_converted     AS total_sales_eur,

                f.inserted_ts               AS fact_inserted_ts
            FROM {gold_schema}.sales_fact          f
            LEFT JOIN {silver_schema}.dim_date      dd  ON dd.DateId      = f.date_id
            LEFT JOIN {silver_schema}.dim_product   dp  ON dp.ProductId   = f.product_id
            LEFT JOIN {silver_schema}.dim_store     ds  ON ds.StoreId     = f.store_id
            LEFT JOIN {silver_schema}.dim_territory dt  ON dt.TerritoryId = f.territory_id
            LEFT JOIN {silver_schema}.dim_region    dr  ON dr.RegionId    = f.region_id
            LEFT JOIN {silver_schema}.dim_currency  dc  ON dc.CurrencyId  = f.currency_id
        """),
        (f"{reporting_schema}.vw_sales_monthly_by_store", f"""
            CREATE OR REPLACE VIEW {reporting_schema}.vw_sales_monthly_by_store AS
            SELECT
                year_month,
                sales_year,
                sales_month_num,
                store_name,
                store_type,
                currency_code,
                SUM(quantity)               AS total_quantity,
                SUM(total_sales_local)      AS total_sales_local,
                SUM(total_sales_eur)        AS total_sales_eur,
                COUNT(*)                    AS fact_row_count
            FROM {reporting_schema}.vw_sales_fact
            GROUP BY
                year_month, sales_year, sales_month_num,
                store_name, store_type, currency_code
        """),
        (f"{reporting_schema}.vw_top_products", f"""
            CREATE OR REPLACE VIEW {reporting_schema}.vw_top_products AS
            SELECT
                product_no,
                product_name,
                variety,
                winery,
                vintage,
                score,
                SUM(quantity)               AS total_quantity,
                SUM(total_sales_eur)        AS total_sales_eur,
                RANK() OVER (
                    ORDER BY SUM(total_sales_eur) DESC, SUM(quantity) DESC
                )                           AS revenue_rank
            FROM {reporting_schema}.vw_sales_fact
            GROUP BY
                product_no, product_name, variety, winery, vintage, score
        """),
        (f"{reporting_schema}.vw_sales_by_variety_winery", f"""
            CREATE OR REPLACE VIEW {reporting_schema}.vw_sales_by_variety_winery AS
            SELECT
                variety,
                winery,
                COUNT(DISTINCT product_no)  AS distinct_products,
                SUM(quantity)               AS total_quantity,
                SUM(total_sales_eur)        AS total_sales_eur,
                AVG(CAST(score AS DOUBLE))  AS avg_score
            FROM {reporting_schema}.vw_sales_fact
            GROUP BY variety, winery
        """),
    ]
    return _run_ddl(spark, statements)

