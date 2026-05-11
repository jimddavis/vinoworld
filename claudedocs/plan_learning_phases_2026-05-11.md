# Phased Learning Plan — Post-Pipeline Next Steps

**Date:** 2026-05-11
**Status:** Proposed
**Prereqs met:** Working medallion pipeline, reporting views in place, DAB packaging, CI/CD Phases 0–4.

---

## Why this sequence

The Vinoworld pipeline is functionally complete: bronze ingests, silver conforms, gold aggregates, reporting views expose the star schema, and CI/CD deploys to `dev` (auto) and `staging` (manual). Next steps split into two threads:

1. **Make the pipeline visible** — dashboards, alerts. The audit log and reporting views exist; nothing consumes them yet.
2. **Mature operations** — Phase 5 CI/CD and Unity Catalog system tables. Both round out skills that production deployments depend on.

The sequence below interleaves the two threads, leading with the highest value-for-time work.

---

## Phase 1 — AI/BI Dashboard + Bundle Resource

**Goal:** Consume the reporting views from an AI/BI Dashboard, and declare that dashboard as a bundle resource so it deploys alongside the pipeline.

**Why first:** The reporting views (`vw_sales_fact`, `vw_sales_monthly_by_store`, `vw_top_products`, `vw_sales_by_variety_winery`) and the audit diagnostic views (`vw_pipeline_run_summary`, `vw_pipeline_step_drilldown`) just landed. A dashboard is the natural consumer and will surface any shape-of-data problems immediately — much faster feedback than waiting until Power BI integration. Adding the dashboard to the bundle also extends DAB skill to a new resource type without learning a new tool.

**New concepts to introduce:**
- AI/BI Dashboards (the successor to legacy "Dashboards"; sometimes called Lakeview)
- `resources.dashboards` bundle resource type
- `.lvdash.json` serialized dashboard format
- `file_path` and `display_name` parameters

**Steps:**
1. Build a dashboard manually in the Databricks UI in the `user` target's workspace. Suggested panels:
   - Monthly sales by store (line chart from `vw_sales_monthly_by_store`)
   - Top 25 products (table from `vw_top_products`)
   - Variety/winery revenue bubble chart (from `vw_sales_by_variety_winery`)
   - Pipeline run status (table from `vw_pipeline_run_summary`)
2. Export the dashboard from the UI ("Export as JSON" / "Source" view) into a new local folder, e.g. `databricks_code/dashboards/sales_overview.lvdash.json`.
3. Declare the dashboard in `databricks.yml` under `resources.dashboards`:
   ```yaml
   resources:
     dashboards:
       sales_overview:
         display_name: "Vinoworld — Sales Overview"
         file_path: ../dashboards/sales_overview.lvdash.json
         warehouse_id: ${var.warehouse_id}
   ```
4. Add a `warehouse_id` variable to the bundle (per-target, since each target's workspace has its own warehouse).
5. `bundle validate` → fix errors → `bundle deploy --target user` → confirm dashboard appears with `[dev <name>]` prefix.
6. PR → deploy to `dev` via push-to-main.

**Deliverables:**
- `databricks_code/dashboards/sales_overview.lvdash.json`
- `databricks.yml` updated with `resources.dashboards` and `warehouse_id` variable
- Dashboard visible in `user` and `dev` workspaces, populated by the pipeline's data

**Acceptance:**
- Dashboard renders without error in the `dev` workspace
- All panels show non-empty data after a pipeline run
- Bundle redeploy after a small dashboard edit (e.g., add a tooltip) works end-to-end

**Tradeoffs / gotchas:**
- `.lvdash.json` is a serialization format Databricks owns. It can change without notice. Plan for occasional manual re-export rather than hand-editing.
- Variables in dashboards (warehouse_id especially) are the part most likely to bite — they're not auto-resolved at deploy like notebook paths are.

**Estimated effort:** 2–4 hours

---

## Phase 2 — Alerts on the Audit Views

**Goal:** Get an email when a pipeline run fails. Implemented as a bundle resource so it deploys alongside the rest.

**Why second:** The audit hierarchy is fully wired (`pipeline_log` → `pipeline_step_log` → `transform_detail_log`), but nothing watches it. A single alert on `vw_pipeline_run_summary` closes that loop. Also continues bundle-resource learning with a small, contained scope.

**New concepts to introduce:**
- Databricks Alerts (the SQL-query-based alert product, not workflow notifications)
- `resources.alerts` bundle resource type
- Alert query + condition + notification destination
- Notification destinations on Free Edition (email-to-workspace-user is the simplest)

**Steps:**
1. Build the alert query manually in the SQL editor:
   ```sql
   SELECT failed_steps
   FROM audit.vw_pipeline_run_summary
   ORDER BY run_started DESC
   LIMIT 1
   ```
2. Configure the alert in the UI with condition `failed_steps > 0` and an email destination. Verify it fires by deliberately running a failing notebook.
3. Export the alert definition. (Like dashboards, alerts have a serialized YAML form when expressed as a bundle resource.)
4. Add to `databricks.yml`:
   ```yaml
   resources:
     alerts:
       pipeline_failure:
         display_name: "Vinoworld — pipeline failure"
         query_text: |
           SELECT failed_steps
           FROM audit.vw_pipeline_run_summary
           ORDER BY run_started DESC
           LIMIT 1
         condition:
           op: GREATER_THAN
           operand:
             column:
               name: failed_steps
           threshold:
             value:
               double_value: 0
         warehouse_id: ${var.warehouse_id}
         notify:
           subscriptions:
             - user_name: ${var.alert_recipient}
   ```
5. Per-target `alert_recipient` variable so dev/staging/prod can email different addresses (e.g., the developer in dev, a shared inbox in prod).
6. Validate → deploy to `user` → trigger a failure → confirm email arrives.

**Deliverables:**
- `resources.alerts.pipeline_failure` in `databricks.yml`
- `alert_recipient` variable per target
- Verified end-to-end email-on-failure

**Acceptance:**
- A deliberate pipeline failure (e.g., bad source path injected into a bronze notebook) produces an email within the alert's poll interval
- The alert does NOT fire on a clean run

**Tradeoffs / gotchas:**
- Free Edition's notification destinations may be limited to email-to-user. Slack/Teams/PagerDuty needs paid-tier connector configuration.
- Alerts poll on a schedule (default 5 min). They're not push. If you want instant notification, the pipeline notebooks themselves would need to send the email — out of scope for this phase.
- The alert's `query_text` runs whether or not the pipeline ran today. Add a freshness check (`WHERE run_started > current_timestamp() - INTERVAL 24 HOURS`) if you only want to alert on recent failures.

**Estimated effort:** 2–3 hours

---

## Phase 3 — CI/CD Phase 5 (Prod Deploy via Tag-Trigger)

**Goal:** `git tag v0.X.Y && git push origin v0.X.Y` → CI deploys to `--target prod`. Closes the CI/CD plan.

**Why third:** Smallest scope of the four. ~30–60 min of work that completes the deployment story end-to-end. Doing it before system-tables exploration means you can use the v-tag deploy mechanism for that work if needed.

**New concepts to introduce:**
- `push: tags: ['v*']` workflow trigger
- GitHub Environments (optional) for required-reviewer gating on prod
- Semantic-version tagging discipline
- Why prod uses a different trigger than staging (immutable artifact ID, intentional promotion gesture)

**Steps:**
1. Decide: separate workflow file (`deploy-prod.yml`) or new job in existing `ci.yml`. Recommendation: separate file — keeps the YAML smaller and the trigger logic clear.
2. Trigger config:
   ```yaml
   on:
     push:
       tags:
         - 'v*'
   ```
3. (Optional) Add a `prod` GitHub Environment with required reviewers — the deploy pauses until approved.
4. Deploy step mirrors the dev/staging pattern but with `--target prod`.
5. Test with a `v0.1.0` tag. Verify resources appear in the prod workspace with no `[dev ...]` prefix and using the `vinoworld` catalog.
6. Update `docs/cicd_setup_plan.md` to mark Phase 5 done and document the tagging convention.

**Deliverables:**
- `.github/workflows/deploy-prod.yml` (or new job in `ci.yml`)
- Optional: `prod` GitHub Environment with required reviewers
- A real `v0.1.0` tag that deployed successfully
- Updated `docs/cicd_setup_plan.md`

**Acceptance:**
- Pushing a `v*` tag triggers a successful prod deploy
- Pushing a non-matching tag (e.g., `release-1`) does NOT trigger the workflow
- The `prod` deploy uses the `vinoworld` catalog, no name prefix on resources

**Tradeoffs / gotchas:**
- Tag-trigger workflows do NOT inherit the same `GITHUB_TOKEN` permissions as branch-trigger ones. If anything in the workflow writes back to the repo (it shouldn't, here), you'll need explicit `permissions:` config.
- `git tag` is local; `git push origin <tag>` is what triggers CI. Easy to forget the push step.
- Tags are immutable conventionally — re-tagging the same name is technically possible but rude. Use semantic versioning: bump the patch number for hotfixes.

**Estimated effort:** 1–2 hours

---

## Phase 4 — Unity Catalog System Tables Exploration

**Goal:** Build a working familiarity with the `system.*` schemas — Databricks's built-in operational metadata. Produces a utility notebook with reusable queries, optionally an extra dashboard tab.

**Why fourth:** Pure read-only learning, no deploy required. Good "I have an hour" exercise. The dashboards and alerts from Phases 1–2 give a foundation that system-tables data can extend (e.g., "which user queried our reporting views in the last 7 days?" → a panel on the dashboard).

**New concepts to introduce:**
- `system` catalog and its sub-schemas
- `system.access.audit` — every workspace action (query, table read, login)
- `system.access.table_lineage` — derived from query plans, not declared
- `system.compute.*` — clusters, warehouses, node types
- `system.billing.usage` — only meaningful on paid tiers, but worth knowing it exists
- Enabling system schemas (one-time per metastore via `databricks unity-catalog metastores`)

**Steps:**
1. Confirm system-schema access. On Free Edition, `system.access.*` is typically pre-enabled; some schemas need explicit enablement. Run `SHOW SCHEMAS IN system;` to inventory.
2. Build `databricks_code/notebooks/utilities/explore_system_tables.ipynb` with one section per useful query:
   - Who has read `vinoworld.gold.sales_fact` in the last 24 hours? (`system.access.audit`)
   - Which tables does `gold.sales_fact` depend on? (`system.access.table_lineage`)
   - What compute did the last 10 jobs run on? (`system.compute.*`)
3. Optionally add a "Pipeline observability" tab to the Phase 1 dashboard pulling from `system.access.audit` filtered to the `vinoworld`/`dev_vinoworld` catalogs.
4. Document any queries that surfaced surprises (privileges you didn't realize you had, lineage you didn't realize you'd built, etc.) in `claudedocs/`.

**Deliverables:**
- `databricks_code/notebooks/utilities/explore_system_tables.ipynb` with ≥5 working queries spanning ≥3 system schemas
- Optional dashboard tab
- Optional `claudedocs/findings_system_tables_<date>.md` for any "huh, that's useful" discoveries

**Acceptance:**
- Notebook runs end-to-end against the `dev` workspace
- At least one query produces actionable info (e.g., a list of users/services that accessed your tables)
- You can articulate when you'd reach for each system schema

**Tradeoffs / gotchas:**
- `system.access.audit` has a 90-day retention. Some queries that "should" return data may be empty if the action happened too long ago.
- `system.access.table_lineage` is inferred from query plans. Tables read only via path-based reads (which the project doesn't use) won't appear.
- `system.billing.usage` requires a paid tier. The schema may exist but be empty in Free Edition. Don't waste time chasing this.

**Estimated effort:** 1–3 hours, depending on appetite

---

## Cross-cutting notes

**Bundle-resource learning curve:** Phases 1 and 2 both add new `resources.*` types. After those, you'll have hands-on experience with `jobs`, `dashboards`, `alerts` — the three most common Databricks resource categories. That covers most of what production bundles look like.

**Deferred topics (intentionally out of this plan):**
- Power BI direct query — eventual destination per `CLAUDE.md`, but better tackled after AI/BI Dashboards have validated the reporting layer.
- Delta Live Tables / Lakeflow Declarative Pipelines — out of scope per `CLAUDE.md`.
- Performance tuning (Z-ORDER, OPTIMIZE, VACUUM) — flag and defer per `CLAUDE.md`.
- Workflow scheduling beyond what bundles already provide — Free Edition has limited scheduling; revisit on a paid tier.
- Azure port — separate workstream per project memory.

**After Phase 4:** The natural next step is **Power BI** — point it at the prod workspace via the Databricks connector, build the same star-schema queries against `reporting.*`, and compare with AI/BI Dashboards. That's where this learning project transitions from "learn Databricks" to "use Databricks alongside the tool the business actually uses."

---

## Open questions for Jim before starting

1. **Alert recipient(s)** — single inbox for all targets, or per-target addresses? (Affects Phase 2 variable shape.)
2. **Warehouse for dashboards** — use the existing serverless SQL warehouse or create a dedicated one? (Affects Phase 1 variable.)
3. **GitHub Environment for prod** — gate on required-reviewer approval, or trust the tag-cut as the gesture? (Phase 3 design choice.)
4. **System tables enablement** — confirm Free Edition has `system.access.*` enabled by default; if not, Phase 4 starts with a small admin step.

Answer these inline or as we begin each phase.
