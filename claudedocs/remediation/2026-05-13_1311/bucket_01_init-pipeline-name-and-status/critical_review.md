# Critical review — bucket 01 fix-init-pipeline-name-and-status

- **Verdict:** DEFECTS FOUND

---

## Lens 1 — Assumption audit

**Change 1: `PIPELINE_NAME = "vinoworld_elt_pipeline"`**

Assumes `"vinoworld_elt_pipeline"` is the durable, environment-invariant name
to record in every `pipeline_log` row. This is correct: the bundle job key in
`databricks.yml` line 82 is `vinoworld_elt_pipeline` and that key does not vary
per target. The previous value `"Vinoworld TEST LOAD"` was a development
artefact. **Assumption verified from primary source (`databricks.yml:82`).**

**Change 2: `PIPELINE_STATUS = STATUS_RUNNING`**

Assumes `STATUS_RUNNING` is now importable from `pipeline_logging` at the point
`init_pipeline_run_log.py` runs. It is — the constant block is placed
immediately after the import section of `pipeline_logging.py`, before any
function definitions. No conditional or lazy definition. **Assumption verified.**

**Change 3: `notebook_init.ipynb` — four local literal assignments removed;
constants imported from `pipeline_logging`**

Assumes `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`, `STATUS_NO_FILES`
are available in the notebook namespace after the `from pipeline_logging import
(…, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_NO_FILES,)` call.
They are — all four are module-level constants in `pipeline_logging.py` and the
import is unconditional. **Assumption verified.**

One implicit assumption: `finalize_pipeline_run_log.py` does NOT need a
matching change because it never references the status constants directly — it
calls `pipeline_log_finalize(spark, PIPELINE_RUN_ID)` and leaves status logic
entirely inside `pipeline_logging.pipeline_log_finalize`. Confirmed by reading
the sibling file: `finalize_pipeline_run_log.py` imports only
`pipeline_log_finalize, configure`. **Assumption verified.**

---

## Lens 2 — Standards conformance

**CLAUDE.md (workspace) — "No module-level side effects" (Shared Module Conventions)**

Rule: "No module-level side effects: no Spark actions, no log writes, no network
calls at import time."

The four new constants are bare string assignments — no side effects.
**PASS.**

**CLAUDE.md (workspace) — "import statements at module top"**

Rule: "`import` statements at module top: not inside functions, not mid-file."

The new constants are not imports, but the expanded `from pipeline_logging
import (…)` in `notebook_init.ipynb` remains a top-of-cell import. In
`init_pipeline_run_log.py` the import is unchanged in position (line 21, top of
post-path-setup section). **PASS.**

**migrations.md — Forbidden string: `` `status = "running"`, `status =
"succeeded"`, `status = "failed"` (string literals at assignment) ``**

Rule: "Replacement: the constants `STATUS_RUNNING`, `STATUS_SUCCEEDED`,
`STATUS_FAILED`, `STATUS_NO_FILES` from `notebook_init`."

In `pipeline_logging.py` the three literal assignments inside
`pipeline_log_finalize` (`status = "failed"`, `status = "succeeded"`) are
replaced with `STATUS_FAILED` and `STATUS_SUCCEEDED`. The SQL f-string
`status = 'failed'` is replaced with `status = '{STATUS_FAILED}'`. **PASS.**

In `notebook_init.ipynb` the four local literal assignments
(`STATUS_RUNNING = "running"` etc.) are removed and replaced by the grouped
import. **PASS.**

In `init_pipeline_run_log.py` `PIPELINE_STATUS = "running"` is replaced with
`PIPELINE_STATUS = STATUS_RUNNING`. **PASS.**

Grep of the three changed files shows zero remaining bare string literal status
assignments. **PASS.**

**migrations.md — Forbidden string: `"Vinoworld TEST LOAD"`**

This string is not in the forbidden-strings list (it was not previously
migrated), but the finding P1-6 makes it the explicit subject of this bucket.
The literal is gone from the repository. **PASS.**

**helpers.md — Constants exported by `notebook_init`**

`helpers.md` lists the constants injected by `notebook_init` into the notebook
namespace:

> `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`, `STATUS_NO_FILES`,
> `PIPELINE_RUN_ID`

> **Also**: `REPORTING`

The post-edit `notebook_init.ipynb` injects `STATUS_RUNNING`, `STATUS_SUCCEEDED`,
`STATUS_FAILED`, `STATUS_NO_FILES` via the expanded import. All four are now
present. **PASS for the four STATUS constants.**

**DEFECT D-1** — `REPORTING` constant is documented in `helpers.md` as
injected by `notebook_init`, but it is not present in the post-edit
`notebook_init.ipynb`. A grep of the notebook returns no match for `REPORTING`.
This is a pre-existing gap (not introduced by this diff), but the diff removed
the four `STATUS_*` local assignments and restructured the import block,
creating a natural checkpoint. The helpers.md contract states notebooks receive
`REPORTING` from `notebook_init`. The contract is unmet. This is an existing
defect surfaced — not introduced — by the diff.

---

## Lens 3 — Cross-object consistency

**Sibling: `finalize_pipeline_run_log.py` vs `init_pipeline_run_log.py`**

Both scripts:
- Guard `sys.argv[1]` with the same `len(sys.argv) < 2` / `raise RuntimeError` pattern. **Consistent.**
- Use `sys.path.insert(0, sys.argv[1])` to bootstrap imports. **Consistent.**
- Derive `catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"`. **Consistent.**
- Call `configure(f"{catalog}.audit")` immediately after import. **Consistent.**

`finalize_pipeline_run_log.py` does NOT import `STATUS_*` constants; it
delegates entirely to `pipeline_log_finalize`. `init_pipeline_run_log.py` now
imports only `STATUS_RUNNING` (the one it needs). The asymmetry is correct and
intentional: `finalize` never writes a status value directly. **Consistent.**

**Module-level state in `pipeline_logging.py`: `_AUDIT_SCHEMA_NAME`,
`configure()`, `_audit()`**

The four new constant definitions are placed immediately after the import block
and before `_AUDIT_SCHEMA_NAME = None`. The block comment documents purpose and
re-export contract. This matches the style of other module-level constant blocks
in the file. **Consistent.**

**`notebook_init.ipynb` — import group shape**

Before: single flat `from pipeline_logging import pipeline_log_upsert,
pipeline_step_log_upsert, ingestion_log_insert`.

After: multi-line parenthesized group adding the four constants; trailing
comma on last item.

The `helpers.md` inventory of `pipeline_logging` functions lists
`pipeline_log_upsert`, `pipeline_step_log_upsert`, `ingestion_log_insert`
but not `transform_detail_log_insert`. The post-edit `notebook_init.ipynb`
import also omits `transform_detail_log_insert`. Grep confirms it is absent
from the notebook. Whether notebooks need it is out of this bucket's scope,
but the diff did not regress the pre-existing state. **No regression.**

---

## Lens 4 — Pattern deviations

All deviations documented in `deviations.md` are orthogonal to this diff:
- PascalCase silver dim columns — unchanged.
- `INSERT OVERWRITE` for silver/gold sales — unchanged.
- Bronze MERGE `WHEN NOT MATCHED` only — unchanged.
- Gold `dim_*` as views — unchanged.
- `BEGIN ATOMIC` for SCD2 — unchanged.
- `F.lit(started_timestamp)` in bronze `inserted_ts` — unchanged.
- `_target_catalog_map` dual-maintenance — unchanged; the map itself is
  byte-identical in the diff.

The diff introduces no new deviation from project standards and does not
"normalize" any intentional deviation to upstream best practice.

The SQL f-string change `status = '{STATUS_FAILED}'` (interpolating the
constant into the SQL string) is consistent with the project's pattern of
building SQL with f-strings where table names and filter values are already
parameterized. The resulting SQL text is identical to the prior literal.
**No unjustified deviation.**

---

## Defects (if any)

1. **D-1 — `helpers.md` contract: `REPORTING` constant missing from
   `notebook_init.ipynb`**
   - **File**: `databricks_code/libs/notebook_init.ipynb` (cell 0)
   - **Lines**: the full constant block — `REPORTING` is absent.
   - **Rule violated**: `helpers.md` § "libs/notebook_init.ipynb" — "Constants:
     `CATALOG`, `BRONZE`, `SILVER`, `GOLD`, `AUDIT`, `REPORTING`, `RAW_FILES`,
     `STATUS_RUNNING`, …`"
   - **Why it's wrong**: Any pipeline notebook that calls
     `spark.table(REPORTING + ".some_view")` or references `REPORTING` as
     injected by `notebook_init` will raise `NameError` at runtime. The
     contract document says the constant is injected; the notebook does not
     inject it. Not introduced by this diff, but the diff restructured the
     exact block where it would live and the discrepancy is a confirmed
     defect against a primary-source document in the packet.

---

## Notes for the next reviewer pass

- D-1 is pre-existing, not regression from this diff. The diff is clean for
  its stated scope (P1-6 and P1-7). The REPORTING gap should be triaged
  separately: either `helpers.md` is stale (the constant was never added to
  `notebook_init`) or `notebook_init` is missing it. A grep of all notebooks
  for `REPORTING` would confirm which. Parked here per § 10 of `CLAUDE.md`.

- `finalize_pipeline_run_log.py` does not import any `STATUS_*` constant (it
  relies entirely on `pipeline_log_finalize` for status logic). If the
  `pipeline_log_finalize` internals ever need to be called from a context that
  also records a `STATUS_FAILED` outside the helper, the sibling would need
  the same import treatment. Not an issue today.

- The `pipeline_log_upsert` docstring still says `status: 'running' |
  'succeeded' | 'failed'` (string literals, not constant names). Minor
  documentation drift — not a runtime defect, but worth updating when the
  file is next touched.
