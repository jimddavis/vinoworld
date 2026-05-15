# Backlog

Items deferred from in-progress work, organized by status. Pull from "Next
up" when planning the next branch. Move completed items to "Done" with the
branch that resolved them.

This file is the parking lot for findings that are **out of scope for the
current branch**. New items land in "Next up" with the surfacing branch
and date so context is preserved across sessions.

See `.claude/CLAUDE.md` § 10 *Evaluating new findings raised mid-task* for
the protocol that puts items here.

---

## Next up (pull from here when planning the next branch)

### `vw_pipeline_run_summary.run_started` is STRING, not TIMESTAMP

- **Surfaced**: 2026-05-15 on `feat/audit-failure-alert` (Phase 2 alert work).
- **Problem**: the audit view exposes `run_started` as
  `date_format(p.started_timestamp, 'yyyy-MM-dd HH:mm:ss')` — a string. Any
  consumer that wants to filter on start time (alert, dashboard tile, ad-hoc
  query) must wrap it in `to_timestamp(run_started, 'yyyy-MM-dd HH:mm:ss')`.
  The current alert dodges this by filtering on `run_ended` instead.
- **Canonical fix**: drop the `date_format` wrapper in
  `libs/catalog_setup.create_audit_views`, expose the raw timestamp. Apply
  any UI-side formatting at the consumer (dashboards, alerts), not in the
  view.
- **Scope**: one DDL change in `catalog_setup.py`; views are recreated by
  re-running `setup/catalog_ddl.ipynb` (or the environment-setup job).
  Verify nothing downstream — including the existing `sales_overview`
  dashboard tiles — depends on the string format before changing.

---

## Future / nice to have

### Centralize `_target_catalog_map`

- **Surfaced**: 2026-05-12 on `new-claudemd` (Phase 1 audit).
- **Problem**: the target → catalog mapping is hand-mirrored between
  `libs/notebook_init.ipynb` (cell 0) and `databricks.yml`
  `targets.<target>.variables.catalog`. A header comment in `notebook_init`
  flags this. Adding/renaming a target requires updating both files in the
  same commit — easy to miss.
- **Possible designs**: emit a JSON/YAML mapping at bundle deploy time and
  read it in `notebook_init`; or move all catalog resolution into the
  spark_python_task scripts and pass it via taskValue. Either adds
  complexity for a small payoff at this scale.
- **Out of scope for current learning project**. Revisit if/when target
  count grows or a naming bug surfaces.

---

## Done

### Step-log success close-out — `slvr_01` and `slvr_03`

- **Resolved**: 2026-05-13 on `fix/05-chore-hygiene` (PR #13, part of the
  first `/remediate-run` cycle). Both notebooks now close their step-log
  row with `STATUS_SUCCEEDED` and `ended_timestamp` on the success path.
  Forbidden-string tripwire added to `.claude/project/migrations.md` on
  `chore/doc-drift-2026-05-15` (PR #14).

---

## How to add an entry

Use one of the templates above. Required fields:

- **Surfaced**: date + branch where the finding came up.
- **Problem**: 1–3 sentences. What's wrong, why it matters.
- **Canonical fix** OR **Possible designs**: the intended resolution, or
  candidate approaches if undecided.
- **Scope**: rough size, dependencies, suggested branch name.

Keep entries scannable. Detailed design work belongs in a separate
`docs/design_*.md` document; link to it from the backlog entry.

When a backlog entry no longer makes sense (problem disappeared, scope
shifted, no longer relevant), don't delete it silently — move it to "Done"
with a one-line note explaining why it's resolved without code change.
