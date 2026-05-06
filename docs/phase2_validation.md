# Phase 2 Validation — Copy-Paste Commands

Run each block in order. All commands are single-line — no backslash continuation issues.

## Step 1 — Pre-flight: clear sync snapshot and deploy

```bash
rm -rf /home/dev/work/AI/databricks/vinoworld_bundle/databricks_code/.databricks/bundle/dev/sync-snapshots/
```

```bash
cd /home/dev/work/AI/databricks/vinoworld_bundle/databricks_code && databricks bundle deploy --target dev
```

## Step 2 — Prove the new code reached the workspace

If the next two commands fail with "not found", first list the deployed libs to confirm the path:

```bash
databricks workspace list /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files/libs/
```

Then export and grep:

```bash
databricks workspace export --file /tmp/deployed_pipeline_logging.py /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files/libs/pipeline_logging.py
```

```bash
grep -nE '_audit\(|_AUDIT_SCHEMA_NAME|^def configure' /tmp/deployed_pipeline_logging.py
```

Expected: at least 6 hits — 1× `_AUDIT_SCHEMA_NAME = None`, 1× `def configure`, 4× `_audit("...")` call sites.

If you see 0 hits, stop — the workspace file is stale.

## Step 3 — Run the job

```bash
cd /home/dev/work/AI/databricks/vinoworld_bundle/databricks_code && databricks bundle run vinoworld_elt_pipeline --target dev
```

Note: `init_pipeline_log` task is expected to fail (Phase 3 hasn't fixed it yet). What matters is whether the notebook tasks downstream wrote to `pipeline_step_log`.

## Step 4 — Validation SQL

Run in a SQL editor or `%sql` cell:

```sql
SELECT 'dev'  AS where_, COUNT(*) AS step_logs_last_30min
  FROM dev_vinoworld.audit.pipeline_step_log
  WHERE started_timestamp > current_timestamp() - INTERVAL 30 MINUTES
UNION ALL
SELECT 'prod', COUNT(*)
  FROM vinoworld.audit.pipeline_step_log
  WHERE started_timestamp > current_timestamp() - INTERVAL 30 MINUTES;
```

Expected: `dev` row > 0; `prod` row = 0.

## Step 5 — Report back

Tell Claude:
- Step 2 grep hit count (should be ≥ 6)
- Did the job run past `init_pipeline_log`? (yes/no, and which steps did fire)
- The two row counts from Step 4
