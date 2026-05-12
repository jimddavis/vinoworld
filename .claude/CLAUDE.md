# Project Operating Manual

This is a general operating framework for Claude Code sessions on this project.
Project-specific details — bespoke helpers, deviations from best practice,
in-flight migrations, gotchas, environment notes — live in `.claude/project/`
and are referenced below.

The general framework changes rarely. The project files change as the project
evolves.

> This template assumes a Databricks Asset Bundle project. For other project
> types, strip the Databricks-specific items in § 10–§ 11 and replace with
> the analogous workflow (e.g., `npm test`, `cargo check`, etc.).

---

## 1. Project context

See @.claude/project/environments.md — deployment targets, runtime
environments, and explicit out-of-scope topics for this project.

---

## 2. Prime directive: match existing patterns

Before writing any new file or function, **read the closest existing analog
in the repo and mirror its structure exactly.** Targeted, not exhaustive —
one file is enough.

If no analog exists, **stop and ask** before inventing a pattern. "It works"
is not the bar. "It works AND looks like the rest of the codebase" is.

### When in doubt, ASK — do not guess

If there is ANY ambiguity about the correct pattern to follow — multiple
analogs differ, the pattern is only partially clear, you can't tell whether
a deviation in @.claude/project/deviations.md applies, you're not sure which
of two helpers fits, you can't decide which value belongs in a constant —
**stop and ask.**

The cost of a clarifying question is seconds. The cost of guessing wrong
and writing inconsistent code is a manual cleanup task for the user and a
diluted convention for the next contributor. Default to asking, not to
proceeding on a hunch.

This applies everywhere — naming, structure, helper choice, log columns,
SQL idiom, YAML layout. If you find yourself thinking "I think this is
right," that thought IS the ambiguity signal. Surface it.

Default to **standard Databricks medallion best practices** (Unity Catalog
three-part names, MERGE for idempotent writes, explicit schemas not
`inferSchema`, `GENERATED ALWAYS AS IDENTITY` for surrogate keys, `F.current_timestamp()`
in DataFrame columns not `datetime.now()`, two-part task naming, etc.)
**EXCEPT** where this project has deliberately chosen otherwise.
See @.claude/project/deviations.md for that list.

---

## 3. Frequency does not equal correctness

When you find pattern A in some files and pattern B in others, **do not
normalize to the more frequent one.** The minority pattern may be the newer
canonical direction that hasn't finished propagating.

When you spot an inconsistency:
1. Stop.
2. Name it in chat: "I see X in these files and Y in these files."
3. Check @.claude/project/migrations.md. If listed, use the new pattern; do
   NOT propagate the old.
4. If not listed, ask which is canonical before proceeding.
5. Do not update old-pattern occurrences during the current task — park them.

Specifically, do NOT:
- "Fix" a file by changing it to match the majority pattern.
- Add new code using the majority pattern just because it's more common.
- Treat a minority pattern as a bug to be silently normalized away.

---

## 4. Load-bearing values must be centralized

A "load-bearing value" is any value that must be identical across multiple
files for the system to work — catalog names, paths, table names, status
strings, etc. These live in **exactly one place** and are referenced
everywhere else.

Rules:
- If a value appears (or is about to appear) in more than one file, treat it
  as load-bearing. Touching it requires the protocol in § 5.
- If you're about to type the same string in a second place, **stop and
  propose a constant** instead.
- **No hardcoded strings for values that have a constant.** Status literals,
  table names, catalog names, schema names, paths — if a constant exists, use
  it. If a constant doesn't exist for a load-bearing value, propose one
  before writing the second occurrence.

If you see a hardcoded value during normal work, **call it out** — don't
silently leave it for "someone" to clean up later, and don't silently replicate
it in your own additions.

---

## 5. Global replacements are atomic

When a load-bearing value or cross-file pattern must change, that is **one
task, not many**.

Protocol:
1. Before any edit, grep the entire repo for every occurrence of the old value.
2. Show the user the full list and confirm migration should proceed.
3. Update every occurrence in a single change set. No partial migrations.
4. Grep again to confirm zero remaining occurrences. Paste the output as
   evidence.
5. Run validation (`databricks bundle validate --target user`). Where
   possible, deploy and run one affected notebook to confirm nothing
   regressed.
6. Move the entry from "in-flight" to "forbidden strings" in
   @.claude/project/migrations.md.

**Half-migrated states are forbidden.** If a global replacement cannot be
completed in one session, do not start it.

If during unrelated work you notice an old value where it shouldn't be, do
NOT silently update it. Park the finding.

---

## 6. Canonical helpers

See @.claude/project/helpers.md — the bespoke helpers in `libs/`. **If a
helper exists, use it.** Do not write inline equivalents of logging, hash
generation, file moves, exception capture, or notebook-context discovery.

---

## 7. In-flight migrations and forbidden strings

See @.claude/project/migrations.md.

Before declaring any task complete, grep changed files for the forbidden
strings listed there. If found in NEW or MODIFIED code, stop and fix.

---

## 8. Project-specific deviations from best practice

See @.claude/project/deviations.md — the list of places where this repo
deliberately differs from standard best practice, and why. Do NOT "fix"
these to match best practice. They are intentional.

---

## 9. Project-specific gotchas

See @.claude/project/gotchas.md — real failure modes from this project that
training-data best practices won't warn you about.

---

## 10. Change protocol

### Verify branch before editing

Before any code change, check:

- `git branch --show-current` — is this branch's purpose appropriate for the
  planned work?
- `git status` — is the working tree clean, or are there uncommitted
  changes that don't belong to the current task?

If either answer is "no," stop and resolve before editing. Never make code
changes directly on `main`/`master`. If the current branch's name and
intent do not match the proposed work, propose a new branch instead.

### Propose before editing files under `databricks_code/`

For any change inside `databricks_code/` (notebooks, `.py` scripts,
`databricks.yml`, `libs/`, `setup/`, `dashboards/`), describe the planned
change first and wait for explicit go-ahead before invoking Write/Edit.
Files outside `databricks_code/` (`claudedocs/`, `docs/`, `.claude/`, the
memory dir, root-level notes) can be edited without the handshake — those
are notes and config, not deployable code.

### Evaluating new findings raised mid-task

When the user raises a new problem or concern mid-task:

1. **Investigate the relevant code** to categorize the finding: is it within
   the current branch's defined scope, or outside it? Read the relevant
   files — do not guess from intuition.
2. **If clearly within scope** → engage as part of the current task.
3. **If outside scope, or ambiguous** → document the finding in
   `docs/BACKLOG.md` under "Next up" with the surfacing branch and date,
   then **return to the current task**. Do NOT start solving, even if a
   solution is obvious or quick.

The bias is strongly toward deferring. If you find yourself thinking "I can
just quickly handle this too" — that temptation is the warning sign.
Entangling two unrelated changes on one branch makes debugging exponentially
harder; a clean branch-per-concern split is almost always cheaper end-to-end.

For findings you spot on your own (not raised by the user): the lighter
rule applies — name briefly in chat, move on, surface at end of task. Do
not invest tokens investigating your own tangents.

### Show diffs, not full-file rewrites

When modifying a file, show what changed and explain why. Never silently
overwrite when an `Edit` (old_string → new_string) would do.

### Validate after every change

Run `databricks bundle validate --target user`. A clean validate is the bar.
Don't commit if validate fails.

### Catalog name

Never infer the catalog from notebook code or memory. Ask the user, or read
it from `databricks.yml`'s `variables.catalog.default`.

### Confirm before destructive actions

`rm -rf`, force pushes, branch deletion, `git reset --hard`, dropping tables,
publishing to shared workspaces, etc. require explicit confirmation **each
time**. A historical "yes" doesn't authorize the same action in a new
context.

---

## 11. Confidence and verification

For platform-specific Databricks behavior, state confidence explicitly:

- **Verified** — read in docs this session or confirmed empirically
  (validate output, CLI command, probe SQL).
- **Projected** — extrapolating from general Python/Spark/SQL knowledge,
  not Databricks-specific. Offer to verify before committing.
- **Guessing** — don't ship. Say "I don't know — let me check the docs or
  run a probe."

For non-trivial platform behavior (resource schema fields, task-context
semantics, permission models, feature availability), default to a `WebFetch`
against the Databricks docs before recommending. Seconds of doc lookup
vs. tens of minutes of deploy + diagnose.
