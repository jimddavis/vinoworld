# Project context and environments

## Project status

The Vinoworld ELT pipeline is functionally complete and running in both
Databricks Free Edition and Azure Databricks. Bronze ingests three sales
sources + products, Silver conforms dimensions and a consolidated sales
staging table, Gold builds `sales_fact`, reporting and audit views are
in place, and the bundle deploys via CLI (local) and CI to `user`, `dev`,
`staging`, `prod`, and `azure_prod`.

The learning phase is over. Focus is now **maintenance, extension, and
consistency** — not concept tutorials.

## Deployment targets

| Target | Mode | Catalog | Purpose |
|---|---|---|---|
| `user` | development | `dev_vinoworld` | Laptop-driven iteration. Default for `bundle deploy` with no `--target`. Resources prefixed `[dev <user>]`. |
| `dev` | production | `dev_vinoworld` | CI-deployed shared dev. No per-user prefix. Never deployed from laptop. |
| `staging` | production | `staging_vinoworld` | Pre-production validation. |
| `prod` | production | `vinoworld` | Production on Free Edition. |
| `azure_prod` | production | `vinoworld` | Production on Azure Databricks. Same catalog name, separate workspace. Also sets `managed_location`. |

The catalog values above MUST match the `_target_catalog_map` dict in
`libs/notebook_init.ipynb` — see @.claude/project/deviations.md for that
load-bearing coupling.

## Environments

**Primary: Databricks Free Edition** (`dbc-d0f295f4-d028.cloud.databricks.com`)
- Serverless compute only — no classic clusters.
- No Workflows scheduling beyond what bundles provide.
- No Repos / Git integration in the UI.
- No cluster policies.
- Unity Catalog active, metastore auto-provisioned.

**Secondary: Azure Databricks** (`adb-7405612365242928.8.azuredatabricks.net`)
- Pipeline validated end-to-end here.
- NOT used for iterative learning — burns credits too quickly.
- Catalog requires explicit `managed_location` pointing to an ADLS
  `abfss://` path.

## Out of scope

Do not implement, recommend, or scaffold:

- **Delta Live Tables / Lakeflow Declarative Pipelines**.
- **Cluster policies** (Free Edition has none).
- **DBFS paths** (`/dbfs/...`). Unity Catalog Volumes only.
- **Performance tuning** (Z-ORDER, OPTIMIZE, VACUUM) without explicit ask.
- **Power BI integration** — eventual destination, but after AI/BI Dashboards
  validate the reporting layer.
- **Refactoring notebook logic for style** — the pipeline is working;
  do not rewrite on a hunch.
- **Workflow scheduling** beyond what bundles already provide.

## Repository layout

```
databricks_code/                  ← bundle root; databricks.yml lives here
    databricks.yml
    libs/                         ← shared Python + notebook_init
    notebooks/
        bronze/   silver/   gold/
        000-*.ipynb               ← lifecycle / maintenance notebooks
        001-*.ipynb
    setup/                        ← catalog DDL, volume seeding
    dashboards/                   ← .lvdash.json files

claudedocs/                       ← session notes, plans (local, not deployed)
docs/                             ← project docs
.claude/                          ← this directory
    project/                      ← project-specific Claude context
data/                             ← local sample files (gitignored)
```

Anything under `databricks_code/` is deployable bundle code. Everything else
is notes, config, or local-only.
