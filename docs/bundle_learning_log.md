# Databricks Asset Bundle — Learning Log

This document captures the session output, commands, results, and explanations from each
phase of converting the Vinoworld pipeline into a Databricks Asset Bundle.

---

## Phase 2 — Minimal Bundle Scaffold

### Goal
Create a minimal `databricks.yml` that passes `databricks bundle validate` with a clean
result. No job resources yet. Just the skeleton.

### What `databricks.yml` needs at minimum

```yaml
bundle:
  name: vinoworld_bundle

workspace:
  host: https://dbc-d0f295f4-d028.cloud.databricks.com/

targets:
  dev:
    mode: development
    default: true
```

**Section meanings:**
- `bundle.name` — the identifier for this bundle across all targets. Think of it like a project/solution name.
- `workspace.host` — tells the CLI which workspace to deploy to. Applies to all targets unless overridden.
- `targets` — named deployment environments. `mode: development` tells Databricks to prefix deployed resource names with your username, preventing collisions with others on the same workspace. `default: true` means you can run `databricks bundle validate` without specifying `--target dev` every time.

### First validate attempt — error

```
Error: cannot resolve bundle auth configuration: resolve:
https://dbc-d0f295f4-d028.cloud.databricks.com: multiple profiles matched:
DEFAULT, Vinoworld Bundle: please set DATABRICKS_CONFIG_PROFILE or provide
--profile flag to specify one.
```

**Cause:** Two entries in `~/.databrickscfg` both point to the same workspace host.
The CLI doesn't know which authentication profile to use.

- `DEFAULT` — PAT token (raw `dapi...` value)
- `Vinoworld Bundle` — OAuth-based login via `databricks auth login` (preferred)

**Fix:** Add `profile` to the `workspace:` section.

**Security note:** `~/.databrickscfg` contains a raw PAT token in the `DEFAULT` profile.
That file must never be committed to version control.

### Final `databricks.yml` after fix

```yaml
bundle:
  name: vinoworld_bundle

workspace:
  host: https://dbc-d0f295f4-d028.cloud.databricks.com/
  profile: "Vinoworld Bundle"

targets:
  dev:
    mode: development
    default: true
```

### Validate output

```
Name: vinoworld_bundle
Target: dev
Workspace:
  Host: https://dbc-d0f295f4-d028.cloud.databricks.com/
  User: zieder0022@gmail.com
  Path: /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev

Validation OK!
```

**What the validate output tells you:**
- **User** — confirms which identity the CLI authenticated as.
- **Path** — where the bundle will deploy its files in the workspace. Pattern:
  `/Workspace/Users/<you>/.bundle/<bundle-name>/<target>`. The `dev` at the end
  comes from the target name — a `prod` target would deploy to a separate path.
- **Validation OK!** — YAML is syntactically valid and the CLI can reach the workspace.

**What `profile` does:** Tells the CLI which entry in `~/.databrickscfg` to use for
authentication when running any `bundle` command.

---

## Phase 3 — Learning Exercise: Simple Non-Trivial Bundle

### Goal
Get hands-on experience with the full `deploy → run` workflow before touching the real
pipeline. Create a standalone notebook that creates a schema and table, inserts rows,
and reads them back — wire it up as a Bundle job, deploy, and run it.

**New concepts introduced:** `resources.jobs`, how Bundle deploys notebook files to the
workspace and rewrites their paths, and the `bundle deploy` → `bundle run` workflow.

### File created: `learning/hello_bundle.ipynb`

A self-contained notebook with no dependency on `notebook_init` or `pipeline_utils`.
Three cells:

**Cell 1 — Create schema and table**
```python
spark.sql("CREATE SCHEMA IF NOT EXISTS vinoworld.sandbox")

spark.sql("""
    CREATE TABLE IF NOT EXISTS vinoworld.sandbox.bundle_test (
        id         BIGINT GENERATED ALWAYS AS IDENTITY,
        message    STRING,
        loaded_ts  TIMESTAMP
    )
    USING DELTA
""")

print("Schema vinoworld.sandbox and table bundle_test are ready.")
```

**Cell 2 — Insert rows**
```python
spark.sql("""
    INSERT INTO vinoworld.sandbox.bundle_test (message, loaded_ts)
    VALUES
        ('Hello from Databricks Asset Bundle!', current_timestamp()),
        ('Phase 3 learning exercise',           current_timestamp())
""")

print("Two rows inserted.")
```

**Cell 3 — Read back**
```python
df = spark.table("vinoworld.sandbox.bundle_test")
df.orderBy("id").show(truncate=False)
print(f"Total rows: {df.count():,}")
```

### `resources:` added to `databricks.yml`

The `resources:` section is where Bundle learns about things it manages — jobs, pipelines,
etc. Each named entry under `resources.jobs` becomes a deployable job.

The notebook path `./learning/hello_bundle.ipynb` is a path **relative to the bundle root**,
not a workspace path. Bundle deploys the file to the workspace and rewrites this path
automatically in the deployed job definition.

```yaml
resources:
  jobs:
    hello_bundle:
      name: hello_bundle
      tasks:
        - task_key: run_hello_notebook
          notebook_task:
            notebook_path: ./learning/hello_bundle.ipynb
          environment_key: Default
      environments:
        - environment_key: Default
          spec:
            environment_version: "5"
```

### First validate attempt — error

```
Error: notebook "learning/hello_bundle" not found.
Did you mean "learning/hello_bundle.ipynb"?
Local notebook references are expected to contain one of the following
file extensions: [.py, .r, .scala, .sql, .ipynb]
```

**Cause:** Bundle requires the file extension in local notebook paths.
**Fix:** Changed `./learning/hello_bundle` to `./learning/hello_bundle.ipynb`.

### Validate after fix

```
Name: vinoworld_bundle
Target: dev
Workspace:
  Host: https://dbc-d0f295f4-d028.cloud.databricks.com/
  User: zieder0022@gmail.com
  Path: /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev

Validation OK!
```

### Deploy

```
$ databricks bundle deploy --target dev

Uploading bundle files to /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files...
Deploying resources...
Updating deployment state...
Deployment complete!
```

### Run

```
$ databricks bundle run hello_bundle --target dev

Run URL: https://dbc-d0f295f4-d028.cloud.databricks.com/?o=7474649167980843#job/1023028067595221/run/972373831421257

2026-05-03 15:59:53 "[dev zieder0022] hello_bundle" RUNNING
2026-05-03 16:01:05 "[dev zieder0022] hello_bundle" TERMINATED SUCCESS
```

### Verification — table created and populated

```
$ databricks tables list vinoworld sandbox

Full Name                      Table Type
vinoworld.sandbox.bundle_test  MANAGED
```

### Final `databricks.yml` after Phase 3

```yaml
bundle:
  name: vinoworld_bundle

workspace:
  host: https://dbc-d0f295f4-d028.cloud.databricks.com/
  profile: "Vinoworld Bundle"

resources:
  jobs:
    hello_bundle:
      name: hello_bundle
      tasks:
        - task_key: run_hello_notebook
          notebook_task:
            notebook_path: ./learning/hello_bundle.ipynb
          environment_key: Default
      environments:
        - environment_key: Default
          spec:
            environment_version: "5"

targets:
  dev:
    mode: development
    default: true
```

### Key takeaways from Phase 3

1. **`bundle deploy` does two things:** uploads local files to the workspace, then creates
   or updates the job to point at those deployed files. The UI is never touched.

2. **`mode: development` renames the job:** The run showed `[dev zieder0022] hello_bundle`
   — not just `hello_bundle`. Bundle auto-prefixes with `[dev <username>]` in development
   mode. This prevents name collisions when multiple developers share a workspace and makes
   dev vs prod immediately visible in the UI.

3. **Notebook path is rewritten:** You wrote `./learning/hello_bundle.ipynb` (a local
   file path). Bundle translated that to the deployed workspace path when creating the job.
   Phase 6 goes deeper on this behavior.

4. **`bundle run hello_bundle`:** The argument `hello_bundle` matches the key name under
   `resources.jobs` in the YAML — not the job's display name.

5. **Validate → Deploy → Run** is the repeating cycle for every change going forward.

---

## Observations and Questions After Phase 3

### What `bundle deploy` uploads

**Question:** After deploying, the workspace UI shows a `.bundle/vinoworld_bundle/dev`
folder under my email containing ALL the folders and files in the project. When were
those created?

**Answer:** During `bundle deploy`. The first line of deploy output was:

```
Uploading bundle files to /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files...
```

Bundle treats the **entire project root** as the artifact source and uploads everything
to the `files/` subfolder of the deploy path — not just the notebook referenced in the
job. This is default behavior.

**Controlling what gets uploaded:** A `.bundleignore` file (same syntax as `.gitignore`)
tells Bundle what to exclude. For this project, candidates for exclusion include:

- `data/` — raw CSV/JSON source files belong in Volumes, not the workspace
- `docs/` — documentation, not pipeline code
- `jobs/` — the original exported YAML, superseded by `databricks.yml`
- `learning/` — once Phase 3 is retired

This is a housekeeping step to add before Phase 4.

---

### Notebook DDL vs. Infrastructure Code

**Question:** The Phase 3 notebook creates the schema and table directly — `CREATE SCHEMA`
and `CREATE TABLE IF NOT EXISTS` in notebook cells. My project does the same. Is this
standard production practice, or shop-dependent?

**Answer:** Shop-dependent, but there is a clear pattern that separates learning projects
from production shops.

**What the Phase 3 notebook does (and what many projects do) — notebook DDL:**
- Practical for learning, exploration, and one-time setup
- Common on small teams where one person owns the catalog
- Easy to develop with immediate feedback in a notebook

**What larger/more mature shops do — DDL as infrastructure code:**

DDL gets separated from the pipeline entirely and treated as infrastructure — something
versioned, reviewed, and applied deliberately, not run as a side effect of a pipeline
execution. Two common approaches:

1. **A dedicated setup notebook** (like `setup/catalog_ddl.ipynb`) run manually once by
   an admin. The pipeline notebooks assume the tables exist and fail loudly if they don't,
   rather than quietly creating them.

2. **A schema migration tool** — equivalent to Flyway or Liquibase. Each migration is
   numbered, applied once, and never re-run. `CREATE TABLE IF NOT EXISTS` in a notebook
   is effectively an unversioned migration.

**The core concern:** `CREATE TABLE IF NOT EXISTS` silently does nothing if the table
already exists — including if the existing table has the wrong schema. A renamed column,
a changed type, a new column — the notebook won't tell you. In production, schema drift
is a real incident risk.

**For this project:** `setup/catalog_ddl.ipynb` already shows the right instinct. The
production pattern is: DDL lives there, runs once (manually or as a one-time job step),
and pipeline notebooks contain zero DDL. The Phase 3 exercise blended them for
simplicity, which is fine for learning but not the pattern to carry into the real pipeline.

---

### Jobs vs. Notebook Orchestration

**Question:** My project has both a notebook orchestrator (`01-Pipeline_Orchestrator.ipynb`
using `dbutils.notebook.run()`) and a job definition (`jobs/Vinoworld_ELT_Pipeline.yaml`).
Before Phase 4, is the standard to use Jobs or Notebook Orchestration?

**Answer:** Both are legitimate, but they serve different purposes. Most mature shops use
both together — not as alternatives.

**Notebook Orchestration (`dbutils.notebook.run()`)**

The orchestrator notebook calls child notebooks in sequence, passes parameters, and
collects return values. It is self-contained and runnable interactively from the UI.

Good for:
- Development and debugging — run the orchestrator manually, step through it, re-run a
  single child
- Passing parameters between notebooks at runtime
- Simple flows where you want execution visible as notebook output

Limitations:
- No parallel execution — `dbutils.notebook.run()` is sequential unless you use Python
  threads, which gets messy
- No per-task retry or timeout
- No built-in run history beyond what you log yourself
- No alerting per task

**Jobs (Databricks Workflow / Bundle `resources.jobs`)**

A Job defines tasks with explicit dependencies, compute config, retry policies, per-task
timeout, and alerting. The DAG is declared in YAML, not embedded in notebook code.

Good for:
- Production scheduling
- Parallel task execution
- Per-task retry, timeout, and failure alerting
- Audit trail — every run recorded with timing, logs, and status in the UI
- Bundle deployment — Jobs are first-class Bundle resources

**The typical production pattern**

The notebook orchestrator is retired (or kept only as a manual recovery tool), and the
Job becomes the orchestrator. Each notebook does one thing; the Job defines order and
dependencies.

**For the Vinoworld project specifically:**

The existing `jobs/Vinoworld_ELT_Pipeline.yaml` already has parallel Bronze tasks:
`brz_load_arancione_sales_files`, `brz_load_celeste_sales_files`, and
`brz_load_verde_sales_files` all fan out from `move_datafiles_from_archive`
simultaneously. The notebook orchestrator cannot do this without threading. That
parallel fan-out is the concrete payoff of the Job approach for this pipeline.

Phase 4 converts that job YAML into a proper Bundle resource — at which point the Job
becomes the orchestrator and the notebook orchestrator is set aside.

---

## Phase 4 — Add the Job Resource

### Goal
Convert `jobs/Vinoworld_ELT_Pipeline.yaml` into the `resources.jobs` section of
`databricks.yml`. Explain what changes between a standalone job YAML and a Bundle
resource definition.

### The three differences between standalone job YAML and Bundle resource

| | Standalone YAML | Bundle resource |
|---|---|---|
| **File structure** | `resources.jobs.JobName` is the whole file | Nested under `resources.jobs` in `databricks.yml` — same key, same shape |
| **Notebook paths** | Absolute workspace path + `source: WORKSPACE` | Relative local path — Bundle deploys the file and rewrites the path |
| **Python file paths** | Absolute workspace path | Relative local path — same treatment as notebooks |

### Missing file flagged: `001-Truncate_All_Tables`

The first task in the original job references
`/Workspace/Users/zieder0022@gmail.com/Vinoworld/001-Truncate_All_Tables` — a notebook
that was never exported from Azure Databricks and does not exist in the local project.

Decision: keep it as `source: WORKSPACE` with a comment as a placeholder. This also
teaches that `source: WORKSPACE` is still valid in Bundle for notebooks not managed
locally.

### Path mapping — original to Bundle

| Task | Original path | Bundle path |
|---|---|---|
| `truncate_all_tables` | `/Workspace/.../001-Truncate_All_Tables` + `source: WORKSPACE` | unchanged (placeholder — file missing) |
| `init_pipeline_log` | `/Workspace/.../init_pipeline_run_log.py` | `./src/init_pipeline_run_log.py` |
| `move_datafiles_from_archive` | `/Workspace/.../000-MoveFilesFromArchiveToBronze` | `./notebooks/000-MoveFilesFromArchiveToBronze.ipynb` |
| Bronze tasks | `/Workspace/.../bronze/brz_0N_...` | `./notebooks/bronze/brz_0N_....ipynb` |
| Silver tasks | `/Workspace/.../silver/slvr_0N_...` | `./notebooks/silver/slvr_0N_....ipynb` |
| Gold task | `/Workspace/.../gold/gold_01_...` | `./notebooks/gold/gold_01_....ipynb` |

**Side observation:** `notebooks/init_pipeline_run_log.py` is a duplicate of
`src/init_pipeline_run_log.py`. The Bundle job points to `src/`. The `notebooks/` copy
can be removed during a future cleanup.

### Validate output

```
Name: vinoworld_bundle
Target: dev
Workspace:
  Host: https://dbc-d0f295f4-d028.cloud.databricks.com/
  User: zieder0022@gmail.com
  Path: /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev

Validation OK!
```

### Deploy output

```
$ databricks bundle deploy --target dev

Uploading bundle files to /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files...
Deploying resources...
Updating deployment state...
Deployment complete!
```

### What appears in the UI after deploy

In **Workflows → Jobs**, a new job appears:

```
[dev zieder0022] Vinoworld_ELT_Pipeline
```

The job shows the full task DAG with dependency arrows — including the parallel Bronze
fan-out from `move_datafiles_from_archive`.

---

## Questions During Phase 4

### Multiple YAML files per project

**Question:** Can there be multiple YAML files per project, and is this a good idea?
How would they be specified with `bundle deploy --target dev`?

**Answer:** Yes. Bundle supports an `include:` section in `databricks.yml` that merges
additional YAML files before validating or deploying:

```yaml
include:
  - resources/jobs.yml
  - resources/clusters.yml
```

Glob patterns work too: `include: - resources/*.yml`

`bundle deploy --target dev` is unchanged — the CLI assembles all files first, then
deploys. The split is invisible to the command.

**When splitting is worth doing:**

| Situation | Split makes sense |
|---|---|
| Multiple jobs | Yes — one file per job |
| Cluster or warehouse definitions growing large | Yes — separate `clusters.yml` |
| Team members owning different resources | Yes — reduces merge conflicts |
| Variables and targets section getting long | Yes — `variables.yml` |

For this project, the natural split point will come in Phase 5 when variables and
targets grow. The job definition would move to `resources/vinoworld_elt_pipeline.yml`
and `databricks.yml` would become top-level configuration only.

---

### `mode: development` and Unity Catalog objects

**Question:** Since the target is `dev` with `mode: development`, will this create
completely new objects in a new space or overwrite existing ones?

**Answer:** Neither. `mode: development` does not affect Unity Catalog objects at all.

What `mode: development` actually controls:
- **Job names** — prefixed with `[dev username]`
- **Deploy path** — files land under `.bundle/vinoworld_bundle/dev/`
- **Scheduled triggers** — paused automatically to prevent accidental production runs

It does NOT create new catalogs, schemas, or tables, and does not prefix table names.

**The implication:** Running `bundle run vinoworld_elt_pipeline --target dev` will
execute against the live `vinoworld` catalog — the same one the original job uses.
There is no data-layer sandboxing until Phase 5 (variable substitution) introduces
catalog prefixes like `dev_vinoworld`.

---

### Race condition: `MetadataChangedException` on parallel Bronze tasks

**Symptom:** After deploying and running the Bundle job, `brz_load_celeste_sales_files`
and `brz_load_product_files` fail with:

```
MetadataChangedException: The metadata of the Delta table has been changed
by a concurrent update.
```

The error occurs at `ingestion_log_insert()` in both tasks.

**Root cause:** The `ingestion_log` table uses `GENERATED ALWAYS AS IDENTITY` for its
primary key. When Delta appends a row to such a table it must update the table's
metadata to advance the identity high-water mark. Two parallel tasks hitting this write
at the same moment collide on that metadata update. The conflicting commit message
confirms it: `"delta.identity.schemaUpdate":"true"`.

**Why the original job does not fail:** The original notebook orchestrator uses
`dbutils.notebook.run()` which is sequential — tasks never overlap. The original
standalone job (with the same parallel DAG) likely succeeds due to timing — the tasks
happen to not reach `ingestion_log_insert` at the exact same millisecond. This is a
pre-existing race condition that the Bundle job's parallel execution exposes more
reliably. Check the original job's run history — occasional failures with this same
error would confirm it.

**The proper production fix:** Change `ingestion_log` to use `uuid()` instead of
`GENERATED ALWAYS AS IDENTITY`. UUIDs are generated in-process with no metadata update
required — concurrent writers never conflict. This requires a DDL change in
`setup/catalog_ddl.ipynb` and one line added to `pipeline_logging.py`. It is a
contained change that does not touch Bronze/Silver/Gold notebook logic.

**The band-aid fix:** Add `max_retries: 2` and `min_retry_interval_millis: 5000` to
each parallel Bronze task. `MetadataChangedException` is transient — a retry succeeds
once the first writer finishes.

**Decision:** Before making this fix, set up Git source control so the change is
properly tracked with a branch, commit message describing the problem, and a merge back
to main. This is the right professional workflow.

---

## Setting Up Git Source Control

### Why now

The `ingestion_log` fix is the first change that should be tracked — a real bug with
a real fix. The habit of "identify problem → branch → fix → commit → merge" is the
foundation of professional workflow. Setting up Git before making the fix teaches the
workflow, not just the code change.

### Approach: local Git only (Option A)

A remote (GitHub/GitLab) is not required to get the core workflow benefit. Local Git
provides commit history, branching, and the ability to merge. A remote can be added
later with no rework.

### Step-by-step — run these commands yourself

**Step 1 — Confirm you are in the project root**
```bash
pwd
```
Expected: `/home/dev/work/AI/databricks/vinoworld_bundle`

**Step 2 — Initialize the repository**
```bash
git init
```
Creates a hidden `.git/` folder. Nothing is committed yet — this just establishes the
directory as a Git repo.

**Step 3 — Check what Git sees**
```bash
git status
```
Shows all project files as "untracked". Nothing staged or committed yet.

**Step 4 — Check for existing `.gitignore`**
```bash
cat .gitignore 2>/dev/null || echo "no .gitignore yet"
```
Must be created before the first commit so sensitive and irrelevant files never enter
history. See next section for recommended contents.

### `.gitignore` contents

```gitignore
# Sensitive credentials — never commit these
Databricks_CLI_Login_Method.txt

# Raw source data — belongs in Volumes, not source control
/data

# Local Python cache
__pycache__/
*.pyc
*.pyo

# VS Code / editor settings
.vscode/

# Bundle state files — generated by CLI, not source code
.databricks/
```

**What is intentionally NOT excluded:**
- `docs/` — learning log is worth keeping in history
- `learning/` — Phase 3 exercise is part of the project record
- `jobs/` — original exported YAML kept as reference
- `Shared/` — canonical shared utilities
- `notebooks/` — the pipeline notebooks
- `databricks.yml` — the bundle config, must be tracked

VS Code shows ignored files and folders greyed out — visual confirmation that
`.gitignore` is working correctly.

### Initial commit completed

All project files except `Databricks_CLI_Login_Method.txt` and `/data` were staged
and committed to the local repository as the baseline.

### Fix branch created

```bash
git checkout -b fix/ingestion-log-identity-collision
```

Branch naming convention: `fix/` prefix signals a bug fix; the description names the
problem. Currently on this branch — ready to make the `ingestion_log` identity column
fix in the next session.

### What the fix involves (to be implemented next session)

Two files need to change:

1. **`setup/catalog_ddl.ipynb`** — change `ingestion_log` primary key from
   `BIGINT GENERATED ALWAYS AS IDENTITY` to `STRING`

2. **`Shared/pipeline_logging.py`** — add `F.expr("uuid()").alias("id")` to the
   insert so each row gets a UUID generated in-process, requiring no table metadata
   update and eliminating the concurrency conflict.

After the fix:
- Commit on the fix branch with a message describing the problem and solution
- Merge back to main
- Redeploy and re-run to confirm parallel Bronze tasks succeed
