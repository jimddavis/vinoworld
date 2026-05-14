# Bucket 01 — `fix-init-pipeline-name-and-status`

- **Branch:** `fix/01-init-pipeline-name-and-status`
- **Parent branch:** `feat/remediation-agent-workflow`
- **Findings addressed:** P1-6, P1-7
- **Findings skipped (resolved-on-disk):** none — both still reproduced at start.
- **Files touched:**
  - `databricks_code/libs/init_pipeline_run_log.py` (+3 / -3)
  - `databricks_code/libs/pipeline_logging.py` (+13 / -3 — new STATUS_* block + 3 internal substitutions)
  - `databricks_code/libs/notebook_init.ipynb` (cell 0 rewrite — STATUS_* now re-exported from `pipeline_logging` instead of defined locally)

## Gates

| Gate | Result |
|---|---|
| Layer 1 (self-verify) | PASS — all 8 checks (attribution / standards / forbidden strings / helpers / deviations / scope / notebook hygiene / ambiguity) green. |
| Deploy + Test | PASS — bundle deploy, verify-deploy ritual, `vinoworld_reset_pipeline`, `vinoworld_elt_pipeline` (11/11 child tasks SUCCESS). |
| Layer 2 (critical review) | PASS for diff; **D-1 surfaced and handled outside scope** (see below). |

## Layer 2 disposition — verdict-header override

The critical reviewer wrote `Verdict: DEFECTS FOUND` because while reading
`helpers.md` it noticed a documented `REPORTING` constant that is not present
in `notebook_init.ipynb`. The reviewer itself stated *"D-1 is pre-existing,
not regression from this diff. The diff is clean for its stated scope (P1-6
and P1-7)."*

D-1 is the **already-parked** Phase 0 finding **P2-6** ("REPORTING constant
documented but not exported"). The original review's "Suggested fix"
explicitly offered two directions:

> Fix: add `REPORTING = f"{CATALOG}.reporting"` to `notebook_init` (cheap;
> aligns code to docs), OR remove the claim from helpers.md.

**Decision** (user-confirmed mid-bucket): `helpers.md` is the drifted side,
not the notebook. No notebook in `databricks_code/` references `REPORTING`
as an injected constant from `notebook_init`; the only `REPORTING` reference
in the repo is a local assignment in `setup/catalog_ddl.ipynb`. The correct
fix direction is to trim the false claim from `helpers.md`.

`helpers.md` lives at `.claude/project/helpers.md` — outside the remediation
workflow's `databricks_code/` scope. **This bucket does not modify it.**
Logged as a Layer-2-surfaced parked item for separate handling.

The reviewer's prose was substantively correct; the verdict-header mechanism
was too coarse to distinguish "diff defects" from "pre-existing defects I
happened to notice while reading docs." Per feedback memory
`feedback_layer2_doc_drift.md`, the workflow trusts the prose and overrides
the header in this class of finding.

## Retries: 0 (clean first pass on every gate)

## Next

Branch `fix/01-init-pipeline-name-and-status` left with three files staged,
no commit. User owns the commit. Workflow auto-advances to bucket 02.
