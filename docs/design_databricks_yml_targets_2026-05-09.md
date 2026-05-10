# Design — databricks.yml target restructure

**Date:** 2026-05-09
**Source:** `claudedocs/research_dab_dual_deployer_2026-05-09.md`
**Goal:** Eliminate duplicate-jobs symptom by separating local-laptop iteration from CI-deployed shared environments. Local and CI never deploy to the same target.
**Scope:** `databricks_code/databricks.yml` only. CI workflow (`ci.yml`) and notebook code stay unchanged in this round.

---

## Target structure (the answer)

| Target name | `mode` | Deployer | Resource name | Catalog | Root path |
|---|---|---|---|---|---|
| `user` (default) | `development` | Laptop CLI | `[dev <short>] Vinoworld_…` | `dev_vinoworld` | `/Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}` |
| `dev` | `production` | CI only | `Vinoworld_… (dev)` | `dev_vinoworld` | `/Workspace/Users/zieder0022@gmail.com/.bundle/${bundle.name}/${bundle.target}` |
| `staging` | `production` | CI only | `Vinoworld_… (staging)` | `staging_vinoworld` | (same as dev) |
| `prod` | `production` | CI only (gated) | `Vinoworld_… (prod)` | `vinoworld` | (same as dev) |
| `azure_prod` | `production` | CI only (Azure host) | `Vinoworld_… (azure_prod)` | `vinoworld` | `/Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}` |

`user` is `default: true` — `databricks bundle deploy` with no flag deploys there. `dev`/`staging`/`prod` are CI-only, never typed by hand on the laptop.

---

## Decisions resolved

### D1 — Catalog for the `user` target: shared `dev_vinoworld`

**Chosen:** the `user` target writes to the same `dev_vinoworld` catalog as the CI `dev` target.

**Why:** solo developer, single workspace, learning project. A per-user catalog (`dev_zieder0022_vinoworld`) buys nothing here and adds another piece of state to track. If a teammate is added later, switch to per-user catalogs at that point — it's a one-line change.

**Tradeoff accepted:** while iterating locally, you may overwrite the CI-deployed `dev` data. The `[dev zieder0022]` *resource* prefix keeps the jobs separate, but they read/write the same Bronze/Silver/Gold tables. For a learning project, fine; for a real team, separate catalogs.

### D2 — `${workspace.current_user.userName}` for the `user` target's root_path

**Chosen:** use `userName` (full email) rather than `short_name`.

**Why:** matches the path scheme already used by `dev`/`staging`/`prod` (also `userName`-style). Consistency across targets > the slightly shorter path. `short_name` saves ~10 characters and isn't worth the inconsistency.

### D3 — Keep hardcoded email in `dev`/`staging`/`prod` `root_path` for now

**Chosen:** leave the existing `/Workspace/Users/zieder0022@gmail.com/.bundle/...` hardcoded paths on `dev`/`staging`/`prod`. Do not generalize to `${workspace.current_user.userName}`.

**Why:** these targets are CI-only deployers, and the CI principal is consistently `zieder0022@gmail.com`. Generalizing makes sense only when CI starts using a service principal (Premium-tier, future). For now, the hardcoded path is explicit and unambiguous about *where* the canonical deployment lives.

**Reconsider when:** Free Edition is replaced or supplemented by Premium with service principals; or a teammate is added.

### D4 — `azure_prod` gets the same restructure

**Chosen:** apply `mode: production` to `azure_prod`, generalize its `root_path` to `${workspace.current_user.userName}` (it already does this), and remove the `profile: Azure` line so CI auth via env vars works the same way.

**Why:** consistency. Today the Azure target's profile reference would block CI just like the original Free profile did. Fix it now while we're already in the file.

---

## Final YAML shape (proposal)

```yaml
bundle:
  name: vinoworld

# Top-level workspace: only host. Each target sets its own root_path.
workspace:
  host: https://dbc-d0f295f4-d028.cloud.databricks.com/

# Bundle ACL — applies to deployed resources (jobs, pipelines).
permissions:
  - user_name: zieder0022@gmail.com
    level: CAN_MANAGE

variables:
  catalog:
    description: Unity Catalog name for this deployment target
    default: vinoworld
  shared_lib_path:
    description: Workspace path to the shared Python utility modules
    default: ${workspace.root_path}/files/libs
  managed_location:
    description: >
      ADLS abfss:// path for catalog MANAGED LOCATION (Azure only).
      Leave empty for Free Edition — omits the clause entirely.
    default: ""

resources:
  # (unchanged — both job definitions stay as-is)

targets:
  # ---------------------------------------------------------------
  # user — laptop-only iteration target. Default for `bundle deploy`
  # with no --target. mode: development gives [dev <short_name>]
  # prefixes and per-user state isolation.
  # ---------------------------------------------------------------
  user:
    mode: development
    default: true
    workspace:
      root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}
    variables:
      catalog: dev_vinoworld

  # ---------------------------------------------------------------
  # dev — CI-deployed shared dev. mode: production = single deployer,
  # no per-user prefix. Never deployed from laptop.
  # ---------------------------------------------------------------
  dev:
    mode: production
    workspace:
      root_path: /Workspace/Users/zieder0022@gmail.com/.bundle/${bundle.name}/${bundle.target}
    variables:
      catalog: dev_vinoworld

  staging:
    mode: production
    workspace:
      root_path: /Workspace/Users/zieder0022@gmail.com/.bundle/${bundle.name}/${bundle.target}
    variables:
      catalog: staging_vinoworld

  prod:
    mode: production
    workspace:
      root_path: /Workspace/Users/zieder0022@gmail.com/.bundle/${bundle.name}/${bundle.target}
    # catalog inherits default: vinoworld

  azure_prod:
    mode: production
    workspace:
      host: https://adb-7405612365242928.8.azuredatabricks.net/
      root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}
    variables:
      managed_location: "abfss://dbrks-vinoworld@stgvinworldjdd1.dfs.core.windows.net/managed_data"
    # catalog inherits default: vinoworld
```

---

## What changes vs. current YAML

1. **Remove top-level `workspace.root_path`** — moved into each target.
2. **Remove top-level `mode: development` from `dev`/`staging`** — those become `mode: production`. (`prod` already was.)
3. **Add new `user` target** with `mode: development`, `default: true`, and a `userName`-templated root_path.
4. **Remove `profile: Azure` from `azure_prod`.**
5. **Permissions block stays** (added in earlier session) — applies to all resources via root scope.

Top-level `workspace.host` is the Free Edition host. Both `dev`/`staging`/`prod` (Free Edition) and `user` (Free Edition) inherit it; only `azure_prod` overrides.

---

## Out of scope (handled in later changes)

- `.github/workflows/ci.yml` — currently deploys `--target dev`. That stays correct after this change. (CI continues to own `dev`.) No edit needed for this round.
- The `databricks_code/databricks.yml-WithStartCleanTasks` backup file in the repo — orphaned, but unrelated to this fix. Delete in a separate housekeeping commit.
- `mode: production` enforces a `git.branch` check on deploy. Free Edition + GitHub Actions: deploy runs from a runner where the local branch is `main` (after merge), so the default check passes. No need to set `git.branch` explicitly. **If `bundle deploy` ever fails with a Git-branch validation error in CI, add `git.branch: main` to the prod-mode targets.** Not pre-emptive.
- Service principal config — Free Edition doesn't have them. Out of scope until/unless Premium upgrade.

---

## One-time cleanup (manual, before/after deploy)

These are runtime actions, not file edits, but `/sc:implement` should remind the user to do them:

1. **Databricks workspace UI → Workflows → Jobs:** delete every duplicate `[dev zieder0022] Vinoworld_…` and `Vinoworld_… (dev)` job.
2. **Databricks workspace UI → Workspace browser:** delete `/Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld/dev/` folder so state is recreated cleanly by the next CI deploy.
3. **GitHub Actions:** after merging the YAML change, the next CI deploy to `dev` will recreate the resources cleanly. Verify in the workspace UI that exactly one job of each name exists.
4. **Local laptop:** `databricks bundle deploy` (no flag) now hits the `user` target, not `dev`. Resources will appear with the `[dev zieder0022]` prefix.

---

## Acceptance criteria

- `databricks bundle validate --target user` passes.
- `databricks bundle validate --target dev` passes.
- `databricks bundle validate --target staging` passes.
- `databricks bundle validate --target prod` passes.
- `databricks bundle validate --target azure_prod` passes (or fails only on Azure-auth absence, not on YAML errors).
- After cleanup + one CI deploy: workspace shows exactly **two** jobs from CI: `Vinoworld_Environment_Setup (dev)` and `Vinoworld_ELT_Pipeline (dev)`. No `[dev …]` prefix on those.
- After one local laptop deploy: workspace also shows `[dev zieder0022] Vinoworld_Environment_Setup (user)` and `[dev zieder0022] Vinoworld_ELT_Pipeline (user)`. Distinct from CI's set.
- A second laptop deploy followed by a second CI deploy produces no duplicates of either set.

---

## Risks

- **`mode: production` on Free Edition without service principals.** Most docs assume service principals for production-mode targets. Free Edition has no service principals, so the deployer for `dev`/`staging`/`prod` is still the user PAT. This means `mode: production`'s `run_as` enforcement is loose. Acceptable for a learning project; flag for any teammate handoff.
- **The hardcoded email `zieder0022@gmail.com` in three target paths.** If you ever change accounts or hand the project off, those become stale. Not blocking; document in a comment.
- **Test-deploy from laptop now needs `--target user` mental model**, not `--target dev`. Document in CLAUDE.md or wherever the dev workflow lives.
