# Research Report — Defeating Databricks Caching: CLI Sync, File Upload, and Runtime Module State

**Date:** 2026-05-05
**Author:** Synthesis of four parallel research agents
**Scope:** Practical, evidence-based answers to "why did `bundle deploy` not actually deploy my new code, and how do I stop being burned by it?"

---

## Executive summary

There are **three independent caching layers** that each can serve stale code, and confusing them is the source of the time-loss pain. Two have documented mitigations. The third is an open product gap that requires a workaround.

| Layer | Where it lives | What it caches | Documented mitigation |
|---|---|---|---|
| **A. CLI sync-snapshot** | `.databricks/bundle/<target>/sync-snapshots/` on dev machine | Per-file mtime → "I already uploaded this" | `databricks bundle destroy` (also clears snapshot) or manual `rm -rf` |
| **B. Notebook-vs-file upload paths** | Server-side, decided by file content | Plain `.py` files go through a different upload route than `.py` files with the `# Databricks notebook source` magic comment — first deploy can silently miss the plain-file branch | Re-deploy until count matches; OR rename plain `.py` → `.py` with magic comment; OR package as wheel |
| **C. Serverless warm pool + `sys.modules`** | Inside the running Databricks Python interpreter | Imported modules retained across job runs on warm-pool reuse | `dbutils.library.restartPython()` (notebook tasks only); wheel + `dynamic_version: true`; or re-import workaround |

**Single most actionable change:** convert the shared `libs/*.py` modules into a **Python wheel** built by the bundle with **`artifacts.<name>.dynamic_version: true`** (CLI ≥ 0.245.0). This breaks the runtime cache deterministically on every deploy, matches the documented Databricks pattern, and side-steps the file-upload-path quirk because wheels go through `artifacts:` not file-sync.

Short term, before the wheel migration, the four-step pre-flight (destroy snapshot → deploy → workspace list to verify file count → workspace export to verify content) is the right defensive workflow.

---

## Layer A — CLI sync-snapshot

### Mechanism (high confidence)

The CLI stores per-target sync state in `.databricks/bundle/<target>/sync-snapshots/<md5(host+remotePath)[:16]>.json`. Each snapshot records:

- Schema version (`v1`)
- Workspace host
- Remote path
- Three maps: `LastModifiedTimes` (path → mtime), `LocalToRemoteNames`, `RemoteToLocalNames`

**Comparison is by mtime, not content hash.** Any change that doesn't bump mtime — restoring from backup, remote-side deletion via UI, branch switches that preserve mtimes — leaves the CLI thinking remote state is current.

### Forced-reset options (high confidence)

- **No `--full` / `--reset-snapshot` flag exists on `databricks bundle deploy`.** That flag exists only on the standalone `databricks sync` command.
- **`databricks bundle destroy` clears the sync snapshot** as part of its cleanup. So `bundle destroy && bundle deploy` is a documented authoritative reset.
- **`--force` on `bundle deploy` is git-branch-validation override only**, not a cache reset. Don't confuse the two.
- Manual `rm -rf .databricks/bundle/<target>/sync-snapshots/` is the unofficial fast path — no public docs but used widely in community threads.

### Known bug class (high confidence)

[`databricks/cli` issue #1976](https://github.com/databricks/cli/issues/1976) — "Bundles don't deploy correctly if remote was deleted." The local snapshot lies about what's already remote → silent partial sync. Manual snapshot delete is the documented workaround. Issue is open, no fix has shipped.

[Community thread 95945](https://community.databricks.com/t5/data-engineering/asset-bundle-doesn-t-sync-files-to-workspace/td-p/95945) and [thread 137731](https://community.databricks.com/t5/data-engineering/bug-in-asset-bundle-sync/td-p/137731) report the same class of "deploy reports success, files missing, second deploy fixes it."

---

## Layer B — Notebook vs file upload paths (the 2-of-5 mystery)

### What we observed

In Phase 2 of the fix plan, after clearing the sync snapshot, the first `databricks bundle deploy --target dev` uploaded only 2 of 5 files in `databricks_code/libs/`:

- ✅ `pipeline_logging.py` (uploaded)
- ✅ `notebook_init.ipynb` (uploaded)
- ❌ `pipeline_utils.py` (skipped silently)
- ❌ `catalog_setup.py` (skipped silently)
- ❌ `init_pipeline_run_log.py` (skipped silently)

A second deploy uploaded all five.

### Likely cause (medium-high confidence — to verify)

Databricks classifies workspace files into two categories at upload time:

1. **Notebooks** — `.ipynb` OR `.py/.r/.scala/.sql` files whose **first line contains the magic comment `# Databricks notebook source`**. These go through the Workspace Import API and land as `Type=NOTEBOOK`.
2. **Plain workspace files** — everything else. These go through the regular file-sync path and land as `Type=FILE`.

The reported `databricks workspace list` output matches this perfectly:
- `pipeline_logging.py` → `Type=FILE` (so it does NOT have the magic comment)
- `notebook_init` → `Type=NOTEBOOK PYTHON` (notebook .ipynb)
- (the missing 3) → would also be `Type=FILE` if they uploaded

So pipeline_logging.py and the missing three files are all in the same upload-path bucket. That weakens the "different upload path" hypothesis. The remaining explanation: a known race in the file-sync code path where on the first run after a snapshot clear, only a subset of plain files lands. The second deploy reconciles state and picks them up. This matches the community-reported pattern in threads 95945 and 137731.

**Action to confirm next session:** check the first line of `pipeline_logging.py` for `# Databricks notebook source`. If absent, the cause is purely the partial-sync bug. If present, there's a more subtle interaction worth filing upstream.

### Refs
- [Notebook format magic comment](https://docs.databricks.com/aws/en/notebooks/notebook-format)
- [Notebook export/import detection rule](https://docs.databricks.com/aws/en/notebooks/notebook-export-import)
- [databricks/cli issue #1976](https://github.com/databricks/cli/issues/1976)
- [databricks/cli issue #1263 — 0-byte notebook on deploy](https://github.com/databricks/cli/issues/1263)

### What this means for the iteration workflow

**Never trust a single `bundle deploy`.** Always verify the deployed file count matches local before running anything against it. The four-step pre-flight from the project memory does this:

```bash
rm -rf databricks_code/.databricks/bundle/dev/sync-snapshots/
cd databricks_code && databricks bundle deploy --target dev
databricks workspace list /Workspace/Users/<email>/.bundle/<bundle>/dev/files/libs/
# expect: same file count as `ls databricks_code/libs/`
```

If counts differ, run `databricks bundle deploy --target dev` a second time and re-list. Don't proceed until counts match.

---

## Layer C — Serverless warm pool + `sys.modules`

### Mechanism (high confidence)

[Databricks documents](https://docs.databricks.com/aws/en/compute/serverless/best-practices) that serverless caches the notebook/job virtual environment so dependencies aren't reinstalled on reconnect. **"Performance-optimized" mode (the default) explicitly keeps a pool of warm compute resources ready.** When a job task runs on a warm interpreter, that interpreter's `sys.modules` already holds previously-imported `pipeline_logging`, `pipeline_utils`, etc. Re-importing returns the cached module — even if the workspace `.py` file was correctly updated.

This is the layer that bites you when:
- The workspace file is provably fresh (export + grep confirms new code)
- ...but a job run still executes the old code

### Mitigations (in order of robustness)

**1. `dbutils.library.restartPython()` — works for notebook tasks** (high confidence)
- [Documented behavior](https://docs.databricks.com/aws/en/libraries/restart-python-process): "The Python notebook state is reset after running restartPython; the notebook loses all state including but not limited to local variables, imported libraries..."
- Place it as **cell 1** of every pipeline notebook task during dev iteration.
- **Does NOT apply to `spark_python_task`** (Python script tasks). For those, the warm-pool cache cannot be cleared from inside the task.

**2. Wheel + `dynamic_version: true` — the documented fast-iteration answer** (high confidence)
- CLI v0.245.0 added [`artifacts.<name>.dynamic_version: true`](https://github.com/databricks/cli/issues/2784) specifically for the "I redeployed but old code runs" problem. It auto-patches the wheel's version suffix from the file mtime on every `bundle deploy`, so each deploy produces a new version → serverless's package cache is invalidated → the new code is loaded.
- Without `dynamic_version`, even a wheel-based workflow keeps running yesterday's code if the version string didn't change. [Confirmed in CLI release notes](https://docs.databricks.com/aws/en/release-notes/dev-tools/bundles) and community thread 103975.

**3. `%load_ext autoreload` + `%autoreload 2` — interactive notebook iteration only** (high confidence)
- Driver-only — does NOT reload code into Spark executors.
- Known holes: `from x import y` aliases don't track later `from x import z`; classes with new methods don't propagate to existing instances; module-level state captured into closures at first import is not re-bound (which is exactly what our Phase 2 `_AUDIT_SCHEMA_NAME` would hit).
- Useful for typing speed during dev; never the answer for job-run validation.

**4. `importlib.reload(module)` — the manual nuclear option** (high confidence)
- Works in any context, including `spark_python_task`.
- Has to be remembered every time. Not a workflow.

### Refs
- [Serverless dependencies caching](https://docs.databricks.com/aws/en/compute/serverless/dependencies)
- [Serverless best practices (warm pool)](https://docs.databricks.com/aws/en/compute/serverless/best-practices)
- [restartPython docs](https://docs.databricks.com/aws/en/libraries/restart-python-process)
- [databricks/cli #2784 — dynamic_version](https://github.com/databricks/cli/issues/2784)
- [Community 103975 — wheel cache after bundle deploy](https://community.databricks.com/t5/data-engineering/error-databricks-bundle-deploy-with-changes-in-the-wheel-file/td-p/103975)
- [autoreload docs and caveats](https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html)

---

## Recommended iteration workflow

### Short term — keep current architecture (`%run` + plain `.py` in `libs/`)

For each deploy during the catalog-mapping fix plan:

```bash
# Step 1 — Clear local sync state
rm -rf databricks_code/.databricks/bundle/dev/sync-snapshots/

# Step 2 — Deploy
cd databricks_code && databricks bundle deploy --target dev

# Step 3 — Verify file count
LOCAL=$(ls libs/ | wc -l)
REMOTE=$(databricks workspace list /Workspace/Users/<email>/.bundle/vinoworld_bundle/dev/files/libs/ | tail -n +2 | wc -l)
[ "$LOCAL" = "$REMOTE" ] || { echo "PARTIAL SYNC — re-deploying"; databricks bundle deploy --target dev; }

# Step 4 — Verify content of file you're testing
databricks workspace export --file /tmp/check.py /Workspace/Users/<email>/.bundle/vinoworld_bundle/dev/files/libs/<file>.py
grep -nE '<expected-token>' /tmp/check.py

# Step 5 — Add `dbutils.library.restartPython()` as cell 1 of any notebook you're iterating on
#          to defeat warm-pool sys.modules cache during dev.
```

When in doubt, `databricks bundle destroy --target dev && databricks bundle deploy --target dev` clears both the local snapshot and remote state authoritatively.

### Medium term — after Phase 9 of the catalog fix plan

Repackage the shared modules as a Python wheel and let the bundle build it:

1. Create `databricks_code/libs/pyproject.toml` with `[project]` declaring `vinoworld-utils` (or similar) version `0.0.1`.
2. Reorganize `libs/` into a package directory (`vinoworld_utils/__init__.py`, `vinoworld_utils/pipeline_logging.py`, ...).
3. Add to `databricks.yml`:
   ```yaml
   artifacts:
     vinoworld_utils:
       type: whl
       path: ./libs
       dynamic_version: true   # CLI ≥ 0.245.0 — auto-bumps version on every deploy
   ```
4. In each job task spec, add:
   ```yaml
   libraries:
     - whl: ../dist/vinoworld_utils-*.whl
   ```
5. Replace `%run notebook_init` + `from pipeline_logging import ...` with proper imports:
   ```python
   from vinoworld_utils.pipeline_logging import pipeline_log_upsert, configure
   ```

This eliminates Layer B (wheels go through `artifacts:` upload, not file sync) and Layer C (every deploy bumps the version → cache invalidates).

**Trade-off:** larger restructuring, departs from the original `%run` pattern, requires understanding `pyproject.toml` and how Databricks installs wheels into job environments. Worth doing once the catalog fix is shipped, not during it.

### Reference workflows

- [`databricks/bundle-examples` — `python_wheel_poetry`](https://github.com/databricks/bundle-examples/tree/main/knowledge_base/python_wheel_poetry) — canonical Poetry-built wheel pattern in a DAB.
- [`datakickstart/datakickstart_dabs`](https://github.com/datakickstart/datakickstart_dabs) — monorepo with externally-built wheel, multi-bundle structure.
- [Dustin Vannoy's advanced DAB guide](https://dustinvannoy.com/2024/06/25/databricks-asset-bundles-advanced/) — covers wheel builds, environments, and Connect-based inner loop.

---

## What NOT to do

- **Don't trust deploy success without verification.** "Deployment complete!" only means the CLI didn't error — it does NOT mean every file landed.
- **Don't use `databricks bundle deploy --force`** as a cache fix. `--force` is solely a git-branch-validation override (overrides the dev-mode safety check that you're deploying from a different branch). It does not affect sync or upload.
- **Don't rely on `dbutils.library.restartPython()` inside `spark_python_task`.** It's a notebook utility. For Python script tasks the only cache fix is wheel + version bump.
- **Don't use `dbx`.** [Officially deprecated](https://docs.databricks.com/aws/en/archive/dev-tools/dbx/dbx-migrate). Migration target is DAB + Databricks Connect.
- **Don't expect a `bundle deploy --watch`.** No first-party watch-and-deploy exists. Only `bundle generate dashboard --watch` (different feature).

---

## Open questions for follow-up

1. **Confirm Layer B hypothesis.** Check first line of `databricks_code/libs/pipeline_logging.py` for `# Databricks notebook source`. If present, it explains why that file uploaded while siblings didn't. If absent, the partial-sync bug is purely #1976 class and we should consider opening a new issue with the reproduction.
2. **Test wheel migration cost.** Estimate hours for the package restructure, given the `notebook_init` + `%run` pattern that all 10 pipeline notebooks currently rely on. May be a second milestone after the catalog isolation is shipped.
3. **Free Edition warm-pool behavior.** Documentation describes warm pools for paid serverless; Free Edition's behavior is not separately documented. Worth a controlled test: deploy a module change, run job back-to-back twice, see if the second run picks up changes without `restartPython()`.

---

## All sources

### Layer A — CLI sync-snapshot
- https://github.com/databricks/cli/issues/1976
- https://github.com/databricks/cli/issues/943
- https://github.com/databricks/cli/blob/main/libs/sync/snapshot.go
- https://docs.databricks.com/aws/en/dev-tools/cli/bundle-commands
- https://docs.databricks.com/aws/en/dev-tools/cli/reference/sync-commands
- https://community.databricks.com/t5/data-engineering/asset-bundle-doesn-t-sync-files-to-workspace/td-p/95945

### Layer B — File upload paths
- https://docs.databricks.com/aws/en/dev-tools/bundles/reference
- https://docs.databricks.com/aws/en/dev-tools/bundles/settings
- https://docs.databricks.com/aws/en/dev-tools/bundles/deployment-modes
- https://docs.databricks.com/aws/en/dev-tools/bundles/workspace-deploy
- https://docs.databricks.com/aws/en/notebooks/notebook-format
- https://docs.databricks.com/aws/en/notebooks/notebook-export-import
- https://github.com/databricks/cli/issues/1263
- https://community.databricks.com/t5/data-engineering/bug-in-asset-bundle-sync/td-p/137731
- https://docs.databricks.com/aws/en/dev-tools/bundles/artifact-private

### Layer C — Runtime module caching
- https://docs.databricks.com/aws/en/compute/serverless/dependencies
- https://docs.databricks.com/aws/en/compute/serverless/best-practices
- https://docs.databricks.com/aws/en/libraries/restart-python-process
- https://docs.databricks.com/aws/en/files/workspace-modules
- https://kb.databricks.com/libraries/modulenotfound-error-on-serverless-compute-after-package-install-and-python-restart
- https://community.databricks.com/t5/data-engineering/error-databricks-bundle-deploy-with-changes-in-the-wheel-file/td-p/103975
- https://community.databricks.com/t5/data-engineering/job-run-failing-to-import-modules/td-p/119060
- https://github.com/databricks/cli/issues/2784
- https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html

### Iteration workflows
- https://github.com/databricks/cli/issues/2958
- https://github.com/databricks/cli/issues/1284
- https://docs.databricks.com/aws/en/release-notes/dev-tools/bundles
- https://docs.databricks.com/aws/en/archive/dev-tools/dbx/dbx-migrate
- https://docs.databricks.com/aws/en/dev-tools/vscode-ext/bundles
- https://github.com/databricks/bundle-examples/tree/main/knowledge_base/python_wheel_poetry
- https://github.com/datakickstart/datakickstart_dabs
- https://dustinvannoy.com/2024/06/25/databricks-asset-bundles-advanced/
- https://learn.microsoft.com/en-us/answers/questions/5528224/dbx-execute-equivalent-in-databricks-asset-bundles
