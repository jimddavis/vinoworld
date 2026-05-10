# Research — Databricks Asset Bundles: dual-deployer (laptop + CI) on the same target

**Date:** 2026-05-09
**Scope:** Solo developer on Databricks Free Edition. Currently deploying the *same* `dev` target from both laptop CLI (browser-OAuth as `zieder0022@gmail.com`) and GitHub Actions (PAT as the same user). Symptom: duplicate jobs accumulate with the same name, different IDs.
**Confidence:** High on the diagnosis; high on the recommended pattern. Some details about state-file ACL behavior are inferred from observed symptoms rather than explicit Databricks documentation.

---

## Executive summary

You're hitting the **dual-deployer / shared-state collision** that Databricks Asset Bundles (DABs) is *not* designed to handle. DABs assumes a target has exactly one deployer identity. When two distinct deploying *sessions* (laptop OAuth and CI PAT — even with the same email) write to the same target, the underlying terraform state diverges, and resources whose IDs the new deployer can't see get recreated rather than updated.

The Databricks-recommended pattern, supported by the documentation and consistent across multiple recent community/blog sources, is **two distinct targets**: a per-developer "user" target (`mode: development`) for laptop testing, and a shared "dev" target (`mode: production`, deployer = CI only) for the integration environment. This is the durable answer — not a workaround.

---

## Why duplicates appear

DABs uses a Terraform-compatible state file to map declared resources to real Databricks resource IDs. State lives in two places:

1. **Local cache:** `.databricks/bundle/<target>/terraform.tfstate` on the deployer's machine.
2. **Authoritative remote copy:** in the workspace, typically under `<root_path>/state/`.

Quoting the community knowledge base: *"When deploying a Databricks bundle, the local `.bundle/<target>/terraform.tfstate` file contains job IDs from your first deployment, and Terraform uses these existing job IDs to update those jobs in place rather than creating new ones."*

The deployer's identity has two consequences here:
- **State file ownership/ACL:** the workspace state folder is created with the deployer's identity. A *different* deployment session may not be able to read/write that file even when the email matches, because Databricks treats the OAuth-token principal and the PAT-token principal as distinct security principals on workspace files. (This is consistent with the "permission error on /files" issue you hit earlier — same shape of problem.)
- **State recreation:** if a deployer can't read existing state, the CLI proceeds with empty state. Empty state means "create fresh." The previously-deployed jobs are now orphaned (still there, no longer in state) and a new set is created with the same names but new IDs.

A community post titled *"Databricks asset bundle occasionally duplicating jobs"* describes exactly this: *"state files appear to be recreated during deployment incidents, which results in the assignment of new job IDs and creation of new jobs with the same name but different IDs, causing duplication."*

A Databricks doc passage on bundle identity confirms the model: *"A bundle's identity is comprised of the bundle name, the bundle target, and the workspace."* Note what's *missing*: the deployer. DABs does not natively coordinate state across multiple deployers of the same `(name, target, workspace)` tuple.

## What `mode: development` is actually for

The official deployment-modes doc states: *"Deploying a target in development mode prepends all resources with the prefix `[dev ${workspace.current_user.short_name}]` and tags each deployed job and pipeline with a `dev` Databricks tag."*

The intent: **per-developer isolation in a shared workspace**. Two developers (e.g., `alice` and `bob`) can both deploy the same bundle to the same workspace; alice gets `[dev alice] my_job` and bob gets `[dev bob] my_job`. Each developer has their own state folder under their own home path. They don't collide.

What `mode: development` is **not** for:
- A single shared environment that multiple deployers (e.g., CI + a developer) write to. The prefix is a per-user namespace, not an environment namespace.
- A target where you've overridden the default root_path to a non-user-namespaced location. That defeats the isolation guarantee — you keep the prefix but lose the path separation.

The doc confirms hardcoded `root_path` is not the development-mode workflow: *"production mode validates that `artifact_path`, `file_path`, `root_path`, or `state_path` mappings are not overridden to a specific user."* The validation exists *because* hardcoding those paths is the production pattern, not the dev one.

## The recommended pattern (multi-source agreement)

**Advancing Analytics blog** ("Stop Wasting Time on Databricks Deployments: Master Asset Bundles Today"):

> "[Add] a 'user' target, which acts as a predevelopment environment. This target should be marked as `mode: development` in the YAML and all other targets set to production."

> "`mode: production` should be understood as deploying through a service principal, ensuring one code deployment per target without developer-specific name modifications."

**Xebia blog** ("Simplify Workflow Deployment With Databricks Asset Bundles"):

> "You can run this command under your username and deploy it to production if wanted, although we highly recommend that you deploy your pipelines to non-development environments through a CI/CD application such as Github Actions or Azure DevOps."

**Databricks docs** ("Sharing bundles and bundle files"):

> "Within an organization, bundles are often developed, deployed, and run by different individuals... all users needing to view bundles, some needing to deploy and run in development, a select few in production, and automated workflows using service principals."

The convergent pattern across all three sources:

| Target | Mode | Deployer | Purpose | Catalog (your project) |
|---|---|---|---|---|
| `user` (or named per-developer) | `mode: development` | laptop CLI, the developer | local iteration before push | `dev_<short_name>_vinoworld` (per-developer, optional) or just `dev_vinoworld` |
| `dev` | `mode: production` | **CI only** | shared integration env, what merged code looks like | `dev_vinoworld` |
| `staging` | `mode: production` | CI only | pre-prod validation | `staging_vinoworld` |
| `prod` | `mode: production` | CI only (gated) | production | `vinoworld` |

Crucially, **`user` and `dev` are different targets**, with different state, different deployers. They never collide.

For the Free Edition constraint (no service principals): the CI PAT acts as your "deployer principal" for the `dev`/`staging`/`prod` targets. Your laptop OAuth session is the deployer principal for the `user` target. They never overlap on state.

## Why the explicit hardcoded `root_path` is part of the problem

You currently have:

```yaml
workspace:
  root_path: /Workspace/Users/zieder0022@gmail.com/.bundle/${bundle.name}/${bundle.target}
```

at the top level of `databricks.yml`. This applies to *every* target — `user`, `dev`, `staging`, `prod`. Two issues:

1. The `dev` target inherits this fixed path, and so does any future `user` target. Both deployers (laptop, CI) write to the same `dev/state/` folder, which is the root of the duplicate-jobs problem.
2. Hardcoding `zieder0022@gmail.com` means the path doesn't adapt if you ever add a teammate, switch accounts, or port to Azure. The Databricks-recommended substitution is `${workspace.current_user.userName}`, which resolves automatically to whoever is deploying.

## Recommendation for your project

Restructure `databricks.yml` along these lines (high-level shape; adapt naming to your taste):

```yaml
bundle:
  name: vinoworld

# Top-level workspace block: only the host. No root_path — let each target decide.
workspace:
  host: https://dbc-d0f295f4-d028.cloud.databricks.com/

variables:
  catalog:
    description: Unity Catalog name for this deployment target
    default: vinoworld
  # ... others as today

resources:
  # ... unchanged

targets:
  # Personal local-iteration target. Default for `databricks bundle deploy`
  # with no --target flag. mode: development gives you the [dev <short_name>]
  # prefix and a default per-user root_path.
  user:
    mode: development
    default: true
    workspace:
      root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}
    variables:
      catalog: dev_vinoworld   # or dev_${workspace.current_user.short_name}_vinoworld for per-user catalogs

  # CI-deployed shared dev. mode: production = single deployer, no prefix.
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
```

**The discipline that makes this work:**

- Your laptop only ever runs `databricks bundle deploy` with no `--target` flag (or explicitly `--target user`). Resources land in `[dev zieder0022] Vinoworld_ELT_Pipeline (user)` — visibly distinct from the CI deployments.
- CI runs `databricks bundle deploy --target dev` (or staging, prod). Resources land as `Vinoworld_ELT_Pipeline (dev)` etc. with no developer prefix.
- The two never write to the same state file.

**Free Edition adjustments:**

- `mode: production` validates the current Git branch matches the target's specified branch. On Free Edition you may want to skip that validation by *not* setting a `git.branch` field — or set it explicitly (`git.branch: main`) so CI is happy.
- `mode: production` also recommends `run_as: <service_principal>`. Free Edition doesn't have service principals; omit `run_as` entirely (defaults to deployer identity).

## Cleanup before adopting the new pattern

The duplicates already in your workspace need to be cleared once. From the Databricks UI:

1. Workflows → Jobs → delete every duplicate `[dev zieder0022] Vinoworld_ELT_Pipeline (dev)` and `[dev zieder0022] Vinoworld_Environment_Setup (dev)`.
2. Workspace → `Users/zieder0022@gmail.com/.bundle/vinoworld/dev/` → delete the whole folder so state starts fresh.
3. After the YAML is restructured and merged, the next CI deploy lays down the new `dev` cleanly.

## What you do *not* need to do

- You **do not** need to delete dev objects before every push. That's a brittle workaround. The two-target separation removes the root cause.
- You **do not** need to skip local testing. The `user` target is exactly for this — deploy locally as often as you like. It coexists peacefully with whatever CI does to `dev`.
- You **do not** need a service principal for Free Edition. The user PAT acts as the CI principal; the OAuth login acts as the laptop principal; they're separated by being on different targets, not by being different identities.

## Confidence and caveats

- **High confidence** that the recommended pattern (separate `user` target with `mode: development` for local + shared targets with `mode: production` for CI) is the canonical Databricks answer. Multiple independent sources align on it.
- **High confidence** that `mode: development` + hardcoded shared root_path is the trigger for your duplicate-jobs symptom. Documentation explicitly reserves overridden root/state paths for production mode.
- **Medium confidence** on the exact mechanism by which the OAuth-vs-PAT identity distinction causes state ACL friction. The community posts describe the symptom but Databricks doesn't formally document the principal-distinction behavior. The fix removes the trigger regardless of the precise mechanism.
- **Caveat for Free Edition:** all the cited best-practice articles assume Premium-tier features (service principals, OIDC). The pattern is still applicable; you simply substitute "the CI PAT" for "the CI service principal" wherever they appear.

## Sources

- [Declarative Automation Bundles deployment modes — Databricks docs (AWS)](https://docs.databricks.com/aws/en/dev-tools/bundles/deployment-modes)
- [Develop Declarative Automation Bundles — Databricks docs (AWS)](https://docs.databricks.com/aws/en/dev-tools/bundles/work-tasks)
- [Sharing bundles and bundle files — Databricks docs (AWS)](https://docs.databricks.com/aws/en/dev-tools/bundles/sharing)
- [Substitutions and variables in Declarative Automation Bundles — Databricks docs (AWS)](https://docs.databricks.com/aws/en/dev-tools/bundles/variables)
- [Specify a run identity for a Declarative Automation Bundles workflow — Databricks docs (AWS)](https://docs.databricks.com/aws/en/dev-tools/bundles/run-as)
- [Stop Wasting Time on Databricks Deployments: Master Asset Bundles Today — Advancing Analytics](https://www.advancinganalytics.co.uk/blog/master-asset-bundles-today)
- [Simplify Workflow Deployment With Databricks Asset Bundles, Part 2 — Xebia blog](https://xebia.com/blog/simplify-your-workflow-deployment-with-databricks-asset-bundles-part-2/)
- [Reliable Databricks Deployments with Terraform and Asset Bundles — Towards Data Engineering, Medium](https://medium.com/towards-data-engineering/reliable-databricks-deployments-with-terraform-and-asset-bundles-6edd02eedb46)
- [Asset Bundles Overriding Existing Jobs (despite different name_prefix) — Databricks Community](https://community.databricks.com/t5/data-engineering/asset-bundles-overriding-existing-jobs-despite-different-name/td-p/146232)
- [Databricks asset bundle occasionally duplicating jobs — Databricks Community](https://community.databricks.com/t5/data-engineering/databricks-asset-bundle-occasionally-duplicating-jobs/td-p/113757)
- [Databricks Asset Bundles - terraform.tfstate not matching when using databricks bundle deploy — Databricks Community](https://community.databricks.com/t5/get-started-discussions/databricks-asset-bundles-terraform-tfstate-not-matching-when/td-p/79054)
