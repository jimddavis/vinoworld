# Production Patterns for Multi-Source Text File Encoding

**Date:** 2026-05-15
**Surfaced from:** mojibake (`Paj�`) in Vinoworld bronze data — existing files
fixed by `windows-1252` decode, but new files from new stores may arrive in
different encodings.
**Question:** How do production data systems handle text files arriving with
unknown or varying encodings, and clean up diacritic corruption?

---

## Executive summary

1. **The dominant production pattern is `declare`, not `detect`.** Encoding is
   metadata about a source. Production systems require sources to commit to an
   encoding (via data contract, file metadata, or per-source pipeline config)
   and treat auto-detection as a *fallback*, not a primary strategy.
2. **Auto-detection is statistically unreliable for short or 8-bit-only files.**
   `windows-1252` and `latin-1` overlap on ~226 of 256 byte values; detectors
   confuse them silently. Recent benchmarks show `chardet` 7.x at 98.2% vs
   `charset-normalizer` 3.4 at 84.2% on the same suite — but accuracy is
   skewed by long documents in the test corpus.
3. **Spark's `encoding` option is per-read, not per-file.** Mixing encodings
   in a single directory requires either pre-conversion at the landing zone,
   or a per-source bronze notebook (which is what Vinoworld already has).
4. **For repairing already-corrupted historical data, `ftfy` is the standard
   tool.** It pattern-matches mojibake and round-trips it back to the
   original, with strong false-positive avoidance.
5. **A quarantine path is mandatory.** Files that fail decode probes go to a
   dead-letter location with the failure reason logged — never silently
   dropped, never silently best-effort decoded.

---

## The core question, framed

There are three distinct sub-problems that get conflated in encoding
discussions:

| # | Sub-problem | Strategy | Vinoworld status |
|---|---|---|---|
| 1 | New files: how do we know the encoding? | Declare via data contract; detect as fallback | **Open** |
| 2 | New files: how do we decode them into Delta? | Spark `encoding` option per source | Partially in place (`windows-1252` discovered for current sources) |
| 3 | Existing data: already-corrupted UTF-8 in a Delta table | `ftfy` or re-ingest from source files | Not in scope yet |

The user's question is mostly about #1 and #2. #3 only matters if mojibake
already landed in the silver/gold tables and source files aren't replayable.

---

## Pattern catalog

### Pattern 1 — Declare encoding per source via contract (production default)

**What:** Every source commits to an encoding as part of the data contract.
The encoding is metadata about the source, recorded once in the per-source
ingestion config (or a metadata table), and applied at read time. No
detection, no guessing.

**When it works:** Whenever you have any control over the source — internal
upstream system, partner with a documented file spec, vendor with an SLA.
Most enterprise pipelines fall here.

**Evidence:**
> "A data contract defines the expected structure, types, and **semantics**
> of ingested data… Any misalignment in field names, data types, or
> **encoding** can cause ingestion failures or silent data corruption."
> — [Salesforce Data 360 architecture guide](https://architect.salesforce.com/docs/architect/fundamentals/guide/data360_integration_patterns_and_practices)

> "Structure your data ingestion to **capture and store encoding metadata
> whenever available** from sources like HTTP responses, file metadata, or
> XML declarations, and only invoke heuristic detection when metadata is
> absent with appropriate logging."
> — Forage AI, [Encoding Bugs in Web Scraping](https://forage.ai/blog/character-encoding-bugs-web-scraping-guide/)

**How it's implemented:**
- Per-source pipeline notebook with an `ENCODING` constant alongside other
  source metadata (header schema, delimiter, date format).
- OR a metadata-driven ingestion table where each source row carries an
  `encoding` column, read by a generic ingestion job. ([MIND pattern](https://www.sciencedirect.com/science/article/pii/S2214579625000693))

**Confidence:** HIGH — this is the universally recommended primary strategy
across the sources reviewed.

---

### Pattern 2 — Cascade fallback (detection as last resort)

**What:** When the source genuinely cannot declare its encoding (web scraping,
public data feeds, user uploads), use a priority-ordered cascade:
1. BOM if present
2. HTTP `Content-Type` header / file metadata if present
3. Statistical detection (chardet)
4. Hardcoded fallback (typically UTF-8 → Windows-1252 → Latin-1)
5. Quarantine if all fail

**Evidence:**
> "Try UTF-8 first (covers 98.9% of the web). Fall back to Windows-1252
> (common in legacy systems). Use Latin-1 as a last resort. Log failures
> for manual review."
> — [Forage AI](https://forage.ai/blog/character-encoding-bugs-web-scraping-guide/)

**Why Latin-1 is the bottom of the stack:** ISO-8859-1 maps all 256 byte
values, so it *never* raises a decode exception. It will silently produce
garbage if the bytes were really UTF-8 — but it won't crash. This makes it
the "stop the bleeding" terminal fallback.

**Confidence:** MEDIUM — recommended *only* for genuinely
declaration-impossible sources. For controlled data ingestion (Vinoworld's
case) Pattern 1 is preferred.

---

### Pattern 3 — Detection libraries (when you must guess)

**Tool comparison:**

| Library | Latest accuracy | Speed | Threading | Notes |
|---|---|---|---|---|
| `chardet` 7.4 | 98.2% on test suite | 47× faster than 6.0 | thread-safe | Recently regained dominance via mypyc compilation ([source](https://chardet.readthedocs.io/en/latest/performance.html)) |
| `charset-normalizer` 3.4 | 84.2% on same suite | baseline | thread-safe | Was the modern default; accuracy gap re-emerged in 2025 |
| ICU (`PyICU`) | High | Slower (C++ binding) | thread-safe | Heavyweight; used in Java/JVM ecosystem |

**Critical limitations of ALL detectors:**
- **8-bit encoding ambiguity** — `windows-1252`, `latin-1`, `iso-8859-15`
  share most byte values. Detectors guess based on character frequency
  statistics; short files (< 1 KB) often get wrong results.
- **Silent failure** — a wrong guess returns a high-confidence result with
  no error. The corrupted text only surfaces downstream as `Paj�` or
  `Ã©` artifacts.
- **No round-trip** — once you've decoded with the wrong codec and stored
  to Delta, the original byte information is lost.

**Best practice when using a detector:**
- Pass `include_encodings=[...]` to chardet to constrain the candidate set
  to encodings you actually expect ([chardet FAQ](https://chardet.readthedocs.io/en/latest/faq.html))
- Require a confidence threshold (typically > 0.7) before accepting the
  result; otherwise quarantine
- Log the detected encoding + confidence per file, so you can audit
  misclassifications later

**Confidence:** HIGH on the comparison numbers; HIGH on the limitation
warnings (consistent across all sources).

---

### Pattern 4 — Pre-convert at landing zone vs. in-Spark decode

**Two architectures:**

#### 4a. In-Spark decode (preferred for declared-encoding sources)
```python
spark.read.format("csv") \
    .option("encoding", "windows-1252") \
    .schema(read_schema) \
    .load(source_path)
```
- Decode happens in the executor; bytes on disk in the Volume are unchanged.
- Bronze "raw fidelity" promise stays honest.
- Works **only** when all files in the read have the same encoding.

#### 4b. Pre-convert to UTF-8 at landing zone (when encodings vary)
- A landing-zone job runs *before* the bronze read, detects each file's
  encoding (or reads from per-file metadata), decodes, and re-writes as
  UTF-8 to a "normalized landing" path.
- The bronze read then operates on uniformly UTF-8 files.
- Cost: an extra hop, an extra storage copy, more orchestration.

**Evidence for the per-read limitation:**
> "The encoding option in Spark is a **global setting** applied to all files
> in a read operation… For scenarios where you have files with different
> encodings, the practical workaround is to detect each file's encoding
> separately, then re-encode them to UTF-8 before ingesting them into
> Spark."
> — [Databricks Community discussion on charset handling](https://community.databricks.com/t5/data-engineering/how-to-import-data-and-apply-multiline-and-charset-utf8-at-the/td-p/29116)

**Confidence:** HIGH on the per-read limitation; this is documented Spark
behavior.

---

### Pattern 5 — BOM handling

**What:** UTF-8, UTF-16, UTF-32 files may carry a Byte Order Mark prefix
(`EF BB BF` for UTF-8). If the CSV reader doesn't strip it, the first column
header becomes `﻿ColumnName` and string-equality column matching breaks.

**Standard fixes:**
- Python: read with `encoding='utf-8-sig'` — automatically strips the BOM if
  present, no-ops if absent.
- Java/Spark: most CSV libraries have a `bom` option; **disabled by default**
  in many modern parsers because BOM usage has declined.
- Detection: check first 3 bytes for `EF BB BF` before deciding.

**Why it matters in production:** Excel exports default to UTF-8-with-BOM
on Windows. Any pipeline ingesting human-saved CSVs should expect BOMs.

**Evidence:** [SplitForge BOM CSV guide](https://splitforge.app/blog/bom-csv-fix-guide/),
[FastCSV BOM examples](https://fastcsv.org/guides/examples/byte-order-mark/),
[BOM Wikipedia](https://en.wikipedia.org/wiki/Byte_order_mark)

**Confidence:** HIGH — well-documented pitfall with standard fixes.

---

### Pattern 6 — Quarantine / dead-letter for failed decodes

**What:** Files that fail the encoding probe (or rows that fail per-row
decoding under `errors='strict'`) get routed to a quarantine location,
not silently coerced or silently dropped.

**Evidence:**
> "Bad records including encoding issues should be anticipated in the
> bronze layer, and a good practice is to **separate bad records into a
> quarantine table for manual inspection**."
> — Bronze layer best-practice writeup ([source](https://medium.com/@divyansh9144/bronze-silver-gold-what-should-be-taken-care-of-at-each-stage-in-a-data-lakehouse-d99170df2feb))

**Spark's built-in support:**
- CSV/JSON parsers have `mode` of `PERMISSIVE`, `DROPMALFORMED`, `FAILFAST`
- `rescuedDataColumn` captures fields that don't match schema as JSON
  in a side column, so the row isn't lost
- `_metadata.file_name` traces corrupt records back to source files
  ([Auto Loader docs](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/))

**Confidence:** HIGH — this is the universal recommendation in the medallion
architecture literature.

---

### Pattern 7 — Mojibake repair (`ftfy`)

**What:** When mojibake has already landed in storage and re-ingestion isn't
possible, `ftfy` ("fixes text for you") detects byte patterns that prove text
was UTF-8-encoded then mis-decoded as something else, and round-trips it
back to the original.

**Example:** `'âœ" No problems'` → `'✔ No problems'`

**Production caveats:**
- Strong false-positive avoidance (per the project's design goal): "It
  should never change correctly-decoded text to something else."
- For audit, use `ftfy.fix_and_explain()` to log exactly what transformation
  was applied per string.
- Some practitioners describe it as a "black box for production data
  pipelines" — fine for repair, less appropriate as a production filter on
  the hot path.

**Evidence:** [ftfy on PyPI](https://pypi.org/project/ftfy/),
[ftfy docs](https://ftfy.readthedocs.io/),
[Alex Chan on `fix_and_explain`](https://alexwlchan.net/notes/2025/ftfy-fix-and-explain/)

**Confidence:** HIGH — `ftfy` is the de-facto standard for this niche.

---

## Reference architecture: encoding normalization layer

Synthesizing across sources (Forage AI, UnicodeCleaner, AWS data ingestion
patterns), the canonical multi-source encoding architecture has three tiers:

```
┌──────────────────────────────────────────────────────────────────┐
│  Tier 1: Detection / Declaration                                 │
│  - Per-source contract: declared encoding in pipeline config     │
│  - Verification probe: read first N bytes, validate against      │
│    declared encoding (BOM check, sample-decode test)             │
│  - On mismatch: quarantine + alert                               │
└────────────────────────┬─────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────┐
│  Tier 2: Conversion / Decode                                     │
│  - Spark .option("encoding", <declared>) for declared sources    │
│  - Pre-convert to UTF-8 in landing zone for mixed-encoding dirs  │
│  - Apply Unicode normalization (NFC) to canonicalize accents     │
│  - Capture: source_encoding column in bronze for traceability    │
└────────────────────────┬─────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────┐
│  Tier 3: Storage / Validation                                    │
│  - Delta / Parquet stores text as UTF-8 internally               │
│  - Monitor: mojibake-rate metric, quarantine count per source    │
│  - Alert on encoding-failure spike (new source breaking contract)│
└──────────────────────────────────────────────────────────────────┘
```

---

## Recommendations for Vinoworld (for human decision)

These are findings-grounded recommendations, *not* an implementation plan.

### Short term (covers the immediate `Paj�` problem and new sources)

1. **Add `SOURCE_ENCODING` as a per-source constant in cell 2 of every
   bronze notebook**, alongside `EXPECTED_SOURCE_COLS` and `read_schema`.
   For current stores, set to `"windows-1252"`. New stores get a value as
   part of onboarding.
2. **Pass the constant through to the Spark read:**
   `.option("encoding", SOURCE_ENCODING)`. This stays inside the existing
   bronze pattern — no new architecture, no new library dependency.
3. **Add a one-time encoding probe to the per-file validation step** (cell 4
   in bronze notebooks): read first ~4 KB, attempt decode under the declared
   encoding with `errors='strict'`. If it raises, the file goes to a
   quarantine subfolder with the failure reason logged in
   `ingestion_log.error_message`. Mirror the existing per-file header
   validation pattern — it's the same "fail fast" idea applied to bytes
   instead of column names.
4. **Capture `source_encoding` as a bronze audit column** (alongside
   `source_file_path`, `inserted_ts`, etc.). Cheap insurance: future
   debugging never has to reverse-engineer "what did we decode this with."

### Medium term (when more stores onboard)

5. **Treat encoding as part of the per-source onboarding checklist.** The
   right place for it is wherever you already document each source's
   delimiter, header row, file naming convention, and arrival cadence.
6. **If/when a source genuinely can't declare encoding** (vendor refuses to
   commit, files are user-uploaded, etc.) — implement Pattern 2 cascade
   with `chardet` constrained to a candidate set and a confidence
   threshold. Quarantine on low confidence.

### Out of scope unless mojibake already landed in silver/gold

7. **`ftfy` for after-the-fact repair.** Only relevant if you have corrupted
   strings already persisted *and* can't re-ingest from source files.
   Vinoworld's source files are still in Volumes, so re-ingestion with the
   correct encoding is the cleaner fix.

### Things to specifically NOT do

- **Don't auto-detect on the hot path** for a controlled multi-source data
  lake. The silent-misclassification risk dominates the convenience win.
- **Don't pre-convert files at the landing zone** unless multiple stores
  *require it because they share a directory and use different encodings*.
  The current per-store-folder layout means in-Spark decode at bronze is
  cleaner.
- **Don't normalize Unicode (NFC) at bronze** — that's a silver concern.
  Bronze stores what arrived; silver canonicalizes.

---

## Open questions worth sitting with

1. **Is "declared encoding mismatches actual content" a quarantine event or
   an alert event?** Strict approach: fail the load, page someone. Lenient:
   decode best-effort, flag in audit log, let it through. Most production
   pipelines pick strict for new sources, lenient for established ones with
   manual review.
2. **Where does the per-source encoding metadata live?** Three valid choices:
   (a) constant in each bronze notebook (mirrors existing pattern); (b) a
   small `audit.source_metadata` table queried at notebook init; (c) a
   `databricks.yml` variable per store. (a) is the lowest-ceremony path that
   matches the existing Vinoworld idiom.
3. **Is there a regulatory / data-residency dimension?** Some jurisdictions
   have requirements around character set handling for personal names,
   addresses, etc. (GDPR adjacent). Worth a one-line check before scaling
   to international stores.

---

## Sources

- [Forage AI — Character Encoding Bugs in Web Scraping](https://forage.ai/blog/character-encoding-bugs-web-scraping-guide/)
- [Salesforce Architect — Data 360 Integration Patterns](https://architect.salesforce.com/docs/architect/fundamentals/guide/data360_integration_patterns_and_practices)
- [Soda — Definitive Guide to Data Contracts](https://soda.io/blog/guide-to-data-contracts)
- [MIND: A metadata-driven INgestion design pattern](https://www.sciencedirect.com/science/article/pii/S2214579625000693)
- [chardet docs — Performance & FAQ](https://chardet.readthedocs.io/en/latest/performance.html)
- [chardet 7.x FAQ — `include_encodings` constraint](https://chardet.readthedocs.io/en/latest/faq.html)
- [charset-normalizer on PyPI](https://pypi.org/project/charset-normalizer/)
- [GitHub — `jawah/charset_normalizer`](https://github.com/jawah/charset_normalizer)
- [ftfy on PyPI](https://pypi.org/project/ftfy/) and [ftfy docs](https://ftfy.readthedocs.io/)
- [Alex Chan — Using `ftfy.fix_and_explain()`](https://alexwlchan.net/notes/2025/ftfy-fix-and-explain/)
- [GitHub — `rspeer/python-ftfy`](https://github.com/rspeer/python-ftfy)
- [Databricks Community — Charset + multiline CSV handling](https://community.databricks.com/t5/data-engineering/how-to-import-data-and-apply-multiline-and-charset-utf8-at-the/td-p/29116)
- [Apache Spark — CSV data source docs](https://spark.apache.org/docs/latest/sql-data-sources-csv.html)
- [Databricks AWS — Read CSV files](https://docs.databricks.com/aws/en/query/formats/csv)
- [Databricks AWS — Auto Loader options](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/options)
- [Databricks AWS — Auto Loader schema inference](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema)
- [Databricks Community — Auto Loader data audit & validation](https://community.databricks.com/t5/technical-blog/auto-loader-data-ingestion-with-built-in-data-audit-amp/ba-p/128587)
- [Wikipedia — Byte Order Mark](https://en.wikipedia.org/wiki/Byte_order_mark)
- [SplitForge — BOM CSV Fix Guide (2025)](https://splitforge.app/blog/bom-csv-fix-guide/)
- [FastCSV — BOM examples](https://fastcsv.org/guides/examples/byte-order-mark/)
- [Medium — Bronze/Silver/Gold layer responsibilities](https://medium.com/@divyansh9144/bronze-silver-gold-what-should-be-taken-care-of-at-each-stage-in-a-data-lakehouse-d99170df2feb)
- [LabEx — Python file text encoding tutorial](https://labex.io/tutorials/python-how-to-handle-python-file-text-encoding-421209)
