# How `databricks bundle deploy` Works

## Two things Bundle deploys, two places they land

When you run `databricks bundle deploy`, the CLI uploads two categories of content:

| Category | What | Where it lands |
|---|---|---|
| **Files** | Notebooks, `.py` scripts, YAML | `${root_path}/files/` |
| **Artifacts** | Python wheels, JARs | `${artifact_path}` (defaults to `${root_path}/artifacts/`) |

For this project everything is files — notebooks and `.py` scripts. Nothing gets compiled into a wheel.

The `root_path` for the `dev` target is:
```
/Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev
```

So a notebook like `notebooks/bronze/brz_01_arancione_sales.ipynb` lands at:
```
/Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files/notebooks/bronze/brz_01_arancione_sales
```
(Databricks drops the `.ipynb` extension in workspace paths.)

---

## How relative paths get rewritten

In `databricks.yml`, notebook paths use a `./` prefix:

```yaml
notebook_path: ./notebooks/bronze/brz_01_arancione_sales.ipynb
```

The `./` prefix is a signal to Bundle: *this is a local file — deploy it and rewrite the path.*
During `bundle deploy`, the CLI:

1. Uploads the file to `${root_path}/files/notebooks/bronze/brz_01_arancione_sales`
2. Rewrites the job definition's `notebook_path` to that absolute workspace path before
   creating or updating the job in Databricks

The job that actually runs in Databricks has no relative paths — they have all been resolved
to `/Workspace/...` absolute paths. You can verify this by inspecting the job in the UI
after a deploy.

Paths that already start with `/Workspace/` are left alone — Bundle assumes they already
exist in the workspace. That is why hardcoded `%run "/Workspace/Shared/notebook_init"`
inside notebooks still works: Bundle does not touch strings inside notebook cells.

---

## artifact_path

`artifact_path` is a workspace-level setting, separate from `root_path`. It only matters
when your bundle builds something (a Python wheel, a JAR). Since this project uses plain
`.py` files and notebooks, `artifact_path` is not in play. It defaults to
`${root_path}/artifacts/` if not set explicitly.

---

## Verifying path resolution before deploying

Run this to see fully-resolved paths without deploying anything:

```bash
databricks bundle validate --output json | python3 -m json.tool | grep -A2 "notebook_path"
```

The output should show absolute `/Workspace/...` paths — not the `./` relative paths from
`databricks.yml`. That confirms Bundle is resolving them correctly.

---

## Deployment path summary (dev target)

| Local path | Deployed workspace path |
|---|---|
| `./notebooks/bronze/brz_01_arancione_sales.ipynb` | `.../files/notebooks/bronze/brz_01_arancione_sales` |
| `./notebooks/silver/slvr_01_load_dim_fromcsv.ipynb` | `.../files/notebooks/silver/slvr_01_load_dim_fromcsv` |
| `./src/init_pipeline_run_log.py` | `.../files/src/init_pipeline_run_log.py` |
| `./setup/catalog_ddl.ipynb` | `.../files/setup/catalog_ddl` |

Where `...` expands to `/Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev`.
