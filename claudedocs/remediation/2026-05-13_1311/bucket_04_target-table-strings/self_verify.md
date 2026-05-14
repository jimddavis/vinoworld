# Bucket 04 — Layer 1 self-verification

**Bucket:** `fix-target-table-strings`
**Branch:** `fix/04-target-table-strings`
**Findings addressed:** P1-5

## A. Diff attribution

| Change | Attributed to |
|---|---|
| `000-MoveFilesFromArchiveToBronze.ipynb` cell 1: `target_table = "Move datafiles from archive to re-run"` → `target_table = None` | P1-5 |
| `slvr_01_load_dim_fromcsv.ipynb` cell 3: `target_table = f"{SILVER} dim_currency, dim_date, dim_exchange_rate, dim_store, dim_territory"` → `target_table = None` | P1-5 |

No unattributed changes. Cells are otherwise byte-identical to their pre-bucket-4 state.

## B. Standards conformance

- `pipeline_step_log_upsert` signature accepts `target_table=None` as default — verified in `helpers.md` and `pipeline_logging.py`.
- The original review's P1-5 explicitly says `"either None or one canonical name is honest"` — None is the canonical "no single canonical name" choice for both notebooks (one moves files across 4 store volumes, one loads 5 different dim tables).
- No forbidden strings introduced.

## C. Cross-object consistency

The two changed cells now have identical structure to the bucket-03 truncate notebook's step-log init (also `target_table = None`). All three multi-target lifecycle notebooks now use the same null-table convention.

## D. Scope

Two files modified, both already in the bucket plan's "files touched" list.

## E. Ambiguity log

None — the original review explicitly recommended None.

---

## Overall verdict: **PASS**
