# Vinoworld Databricks Bundle Project

## Learning Mode

This project is Jim's primary Databricks learning environment. Lean toward MORE
explicitness, not less:

- **State confidence levels on platform-specific claims** (verified / projected /
  guessing). Don't state Databricks-specific behavior with the same confidence as
  general Python or SQL.
- **Offer to verify** via WebFetch (Databricks docs) or a cheap probe before
  committing to a non-trivial platform behavior. The cost of a doc lookup is
  seconds; the cost of a failed deploy + diagnosis is tens of minutes.
- **Repeat reminders** even if stated earlier in the session — Jim is absorbing
  many new concepts and can't be expected to retain every one.
- **When a gotcha is hit, persist it** — add to the anti-patterns table in
  `databricks/.claude/CLAUDE.md`, or a memory feedback file, or this CLAUDE.md.
  Don't just resolve in the moment.

Token usage is a secondary concern while learning. Optimize for retention and
verification, not brevity.

---

## Project Purpose

This is a **learning project** for converting an existing Databricks notebook pipeline into a
Databricks Asset Bundle (DAB). The pipeline is already working in Azure Databricks. The goal
is not to change what the pipeline does — it is to learn how to package, configure, and deploy
it using the Bundle framework.

**Teach as you go.** Before making any change, explain what you are about to do and why.
Introduce Bundle concepts as they become relevant. Do not silently apply best practices;
surface them with a brief explanation so Jim can learn the pattern, not just the output.

---

## Developer Background

Jim has strong SQL Server and dimensional modeling experience, and has been learning
Databricks/PySpark over the past several months. He understands the Medallion Architecture
(Bronze/Silver/Gold), Unity Catalog hierarchy (catalog → schema → table), and notebook-based
orchestration. He is new to Databricks Asset Bundles, the Databricks CLI. He does have YAML-driven
configuration experience from Drupal, and has explored Azure Bicep.

Do not over-explain PySpark or SQL concepts. Do explain Bundle-specific concepts
(targets, resources, artifact paths, variable substitution, etc.) every time they appear.

---

## Project Structure

```
.
├── Shared/                        # Shared Python utilities (canonical versions)
│   ├── catalog_setup.py
│   ├── notebook_init.ipynb
│   ├── pipeline_logging.py
│   └── pipeline_utils.py
├── data/                          # Source CSV/JSON files
│   ├── Arancione_2022_01.csv
│   ├── Arancione_Products.csv
│   ├── Celeste_2022_01.csv
│   ├── Celeste_Products.csv
│   ├── Currency.csv
│   ├── Dates.csv
│   ├── ExchangeRates.csv
│   ├── Store.csv
│   ├── Territory.csv
│   ├── Verde_2022_01.json
│   └── Verde_Products.csv
├── jobs/
│   └── Vinoworld_ELT_Pipeline.yaml   # Original job YAML exported from Databricks UI
├── notebooks/
│   ├── 000-MoveFilesFromArchiveToBronze.ipynb
│   ├── 000-Pipeline_Logging_test.ipynb
│   ├── 01-Pipeline_Orchestrator.ipynb
│   ├── bronze/
│   │   ├── brz_01_arancione_sales.ipynb
│   │   ├── brz_02_celeste_sales.ipynb
│   │   ├── brz_03_verde_sales.ipynb
│   │   └── brz_04_products.ipynb
│   ├── gold/
│   │   └── gold_01_load_sales_fact.ipynb
│   ├── init_pipeline_run_log.py
│   ├── notebook_init.ipynb           # STALE — canonical version is in Shared/
│   └── silver/
│       ├── slvr_01_load_dim_fromcsv.ipynb
│       ├── slvr_02_load_dim_product.ipynb
│       ├── slvr_03_load_dim_region.ipynb
│       └── slvr_04_load_sales.ipynb
├── setup/
│   └── catalog_ddl.ipynb
├── src/
│   └── init_pipeline_run_log.py
└── databricks.yml                    # CREATED DURING THIS PROJECT — Bundle root config
```

**Authoritative sources:**
- `Shared/` contains the canonical shared utilities. `notebooks/notebook_init.ipynb` is stale.
- `jobs/Vinoworld_ELT_Pipeline.yaml` is the source job definition but will be superseded by
  the Bundle resource definition in `databricks.yml`.

---

## Environments

### Primary: Databricks Free Edition (learning)
- **Workspace**: Databricks.com Free Edition (not Azure)
- **Unity Catalog**: Included and active — metastore auto-provisioned
- **Compute**: Serverless only — no classic clusters. Bundle job definitions must use
  serverless compute config, not classic cluster specs.
- **Catalog name**: Ask Jim to confirm before referencing in any YAML
- **Authentication**: Databricks CLI with `databricks auth login`
- **CLI status**: Not yet installed — CLI setup is the first task in this project
- **Account console**: Not available in Free Edition — workspace-level only

### Secondary: Azure Databricks (validation only)
- The pipeline has been verified working in Azure Databricks.
- Azure is **not used for iterative learning** — it burns credits too quickly.
- After Bundle work is solid in Free Edition, a port to Azure is a future step.
- Do not reference Azure-specific config or connection strings during the learning phase.

---

## Multi-Environment Strategy

We are implementing a **single-workspace, multi-target** pattern. Since Free Edition provides
one workspace, environments are simulated via catalog/schema naming prefixes rather than
separate workspaces. This is the same pattern used in real single-workspace production setups.

| Target  | Catalog prefix  | Purpose                         |
|---------|----------------|---------------------------------|
| dev     | `dev_`         | Jim's personal development runs |
| staging | `staging_`     | Pre-production validation       |
| prod    | (no prefix)    | Production — the live pipeline  |

Bundle targets will use variable substitution to inject the correct prefix at deploy time.
`databricks bundle deploy --target dev` vs `--target prod` is the core workflow to teach.

GitHub Actions CI/CD is **out of scope for now** — focus is on local CLI-driven deployment.
The project structure should be CI/CD-ready (clean targets, no hardcoded values) so it can
be extended later without rework.

---

## Bundle Learning Sequence

Work through these phases in order. Complete and validate each phase before moving to the next.

### Phase 1 — CLI Setup and Authentication
- Install Databricks CLI in WSL2/Ubuntu
- Authenticate to the Azure Databricks workspace (`databricks auth login`)
- Verify with `databricks workspace list /`

### Phase 2 — Minimal Bundle Scaffold
- Create `databricks.yml` (bundle name, workspace host, one target)
- Run `databricks bundle validate` — get to a clean validate before adding resources
- Explain the YAML schema as each section is introduced

### Phase 3 - Learning Step: Create a Simple, but non-trivial bundle to create catalog, schema, table and notebooks in a new "space".  This step is to get a feel for how the CLI works before starting the conversion.

### Phase 4 — Add the Job Resource
- Convert `jobs/Vinoworld_ELT_Pipeline.yaml` into the `resources.jobs` section of `databricks.yml`
- Explain what changes between a standalone job YAML and a Bundle resource definition
- Run `databricks bundle deploy --target dev` and verify the job appears in the workspace

### Phase 5 — Variable Substitution for Multi-Environment
- Extract hardcoded catalog/schema names into Bundle variables
- Configure `dev`, `staging`, and `prod` targets with environment-specific variable values
- Deploy to dev and prod and show that each uses the correct catalog prefix

### Phase 6 — Artifact Paths and Notebook Deployment
- Understand how Bundle deploys notebooks to the workspace file system
- Configure `artifact_path` so notebooks land in a predictable, environment-specific location
- Verify notebook paths in the deployed job match what Bundle deployed

### Phase 7 — Run and Validate
- Trigger a job run via `databricks bundle run`
- Compare behavior of a Bundle-triggered run vs a manual UI-triggered run
- Review run output and logs

---

## Working Conventions

- **Propose code changes before applying them.** For any change under
  `databricks_code/` (notebooks, `.py` scripts, `databricks.yml`, `libs/`,
  `setup/`), describe the planned change first and ask before invoking
  Write/Edit. Wait for explicit go-ahead. Files outside `databricks_code/`
  (claudedocs/, docs/, .claude/, the memory dir, root-level files like
  test_views.sql) can be edited without the propose-then-ask handshake —
  those are notes, plans, and config, not deployable bundle code.

- **One task at a time. Park new findings, don't act on them.** If a
  separate problem is spotted mid-task (drift in another file, an
  inconsistency, a missing feature), name it briefly in chat and move on.
  Do not edit code to fix it. After the current task is committed, surface
  the parked items so Jim can decide whether each belongs on the same
  branch, a follow-up branch, or the backlog. This protects branch scope
  and keeps PR diffs aligned with their stated purpose.

- **Validate constantly.** After every YAML change, run `databricks bundle validate` before
  proceeding. Treat a clean validate as the checkpoint before each next step.

- **One concept at a time.** Do not introduce variable substitution and job resources in the
  same step. Sequence changes so each step has one new concept.

- **Preserve the existing pipeline logic.** Do not refactor notebook code during this project.
  The notebooks work. The goal is packaging, not rewriting.

- **Show diffs, not replacements.** When modifying `databricks.yml`, show what changed and
  explain why. Do not silently overwrite the whole file.

- **Ask before assuming catalog name.** The Unity Catalog name must be confirmed with Jim
  before it appears in any YAML. Do not infer it from notebook code.

- **WSL paths apply.** All CLI commands run in WSL2/Ubuntu. File paths use Linux conventions.
  The project root is in the WSL filesystem (not `/mnt/c/...`).

- **Only upload files required by Databricks at runtime.** The bundle sync should contain
  only notebooks, Python scripts, and YAML that the pipeline actually executes. Documentation,
  learning notes, CLI reference files, local scratch files, and project tooling (`.claude/`,
  `docs/`, `learning/`, `jobs/`, `git/`, `val.json`, `.gitignore`) must be excluded via
  `sync.exclude` in `databricks.yml`. Use `.gitignore` for files that should be excluded
  from both git and the workspace. Use `sync.exclude` for files that belong in git but
  not in the workspace. Validate the exclusion list is current whenever new non-runtime
  folders are added to the project.

- **Force a clean sync when files are missing.** The CLI maintains a local sync snapshot in
  `.databricks/bundle/<target>/sync-snapshots/` to avoid re-uploading unchanged files.
  After a laptop restart or any time files are deleted/moved in the Databricks UI, this
  snapshot gets out of sync and the CLI silently skips re-uploading files it thinks are
  already there. Delete the snapshot directory to force the CLI to re-evaluate from scratch:
  ```
  rm -rf .databricks/bundle/dev/sync-snapshots/
  databricks bundle deploy --target dev
  ```

---

## Troubleshooting

### Files missing after bundle deploy (ghost sync)

**Symptom:** After restarting or switching environments, notebooks or Python files that exist
locally do not appear in the Databricks workspace after `databricks bundle deploy`.

**Cause:** The CLI keeps a local sync snapshot (`.databricks/bundle/<target>/sync-snapshots/`)
tracking what it has already uploaded. If the remote workspace state changed (files deleted via
UI, laptop restarted, etc.) without a corresponding local change, the CLI considers those files
already in sync and skips uploading them.

**Fix (fastest):** Delete the snapshot so the CLI does a full comparison on the next deploy:
```bash
rm -rf .databricks/bundle/dev/sync-snapshots/
databricks bundle deploy --target dev
```

**Prevention:** Delete the sync snapshot before deploying to force a complete upload:
```bash
rm -rf .databricks/bundle/dev/sync-snapshots/
databricks bundle deploy --target dev
```

---

## Key Concepts to Introduce (with brief definition each time they appear)

- **Bundle** — a project-level packaging format that defines jobs, clusters, and other
  Databricks resources as code, deployable via CLI
- **Target** — a named deployment environment within a bundle (dev, staging, prod)
- **Variable substitution** — `${var.name}` syntax that injects environment-specific values
  at deploy time
- **artifact_path** — where the bundle deploys files (notebooks, wheels) in the workspace
- **bundle validate** — CLI command that checks YAML syntax and resource references without
  deploying anything
- **bundle deploy** — CLI command that pushes the bundle to the workspace for a given target
- **bundle run** — CLI command that triggers a job or pipeline defined in the bundle

---

## Out of Scope for This Project

- Refactoring or improving notebook logic
- DLT (Delta Live Tables / Declarative Pipelines)
- GitHub Actions or CI/CD automation
- Terraform or alternative IaC approaches
- Adding new data sources or pipeline stages
- Azure Databricks port (future step after Bundle work is solid in Free Edition)
