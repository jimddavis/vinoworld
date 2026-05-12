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

### Step-log success close-out — `slvr_01` and `slvr_03`

- **Surfaced**: 2026-05-12 on `new-claudemd` (Phase 1 audit).
- **Problem**: both notebooks write `pipeline_step_log` at start with
  `STATUS_RUNNING` but never close out to `STATUS_SUCCEEDED`. On a clean run
  the row stays "running" forever, which is misleading for the audit views
  and would suppress success in any downstream success-rate calculation.
- **Canonical fix**: mirror the bronze / `slvr_02` / `slvr_04` / `gold_01`
  pattern — call `pipeline_step_log_upsert(... STATUS_SUCCEEDED ...,
  rows_read, rows_written, ended_timestamp, error_message)` on the success
  path. See `.claude/project/migrations.md` "Step-log success close-out"
  for the canonical contract.
- **Scope**: dedicated branch, e.g. `fix-step-log-close-out`. Two files
  changed, no cross-cutting impact.
- **Atomic-migration protocol**: § 5 of `.claude/CLAUDE.md` applies.
  Verify migration is complete by greping the success path of every
  notebook for a final `pipeline_step_log_upsert` call.

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

*(empty — items move here when their branch merges)*

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
