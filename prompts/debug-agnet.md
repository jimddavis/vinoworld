/sc:design

# Generalized code-remediation agent — design request

## Context

I want a reusable agentic workflow for code remediation that I can apply across
projects. This is a learning project, so the design document and supporting
artifacts should preserve enough reasoning that I can revisit them months from
now and understand the why, not just the what.

The workflow has two phases:

1. **Self-generated review.** The agent reviews the codebase against project
   standards and produces a findings document.
2. **Remediation.** The agent works through the findings in bucketed, branched,
   reviewed increments.

An example of the review document this workflow should produce already exists
at `code_review_2026-05-12.md` in this repo. Treat it as a reference for output
quality and structure, not as input. The agent runs its own review each time.

Design the workflow. Do not implement it — `/sc:implement` consumes this design
document separately.

## Phase 0 — Self-generated review

The agent reviews the project against its documented standards and produces a
findings document.

Requirements:

1. **Scope.** The agent declares the directories and file types it will review,
   confirms with the user, then sticks to that scope. The example review scoped
   itself to `databricks_code/libs/*`, `notebooks/**/*.ipynb`,
   `setup/*.ipynb`, `dashboards/*.lvdash.json`, and `databricks.yml`.

2. **Source-of-truth discipline.** Files on disk are truth. The agent reads
   directly — for notebooks, parsing the `.ipynb` JSON, not assuming content
   from prose or filenames. Not git, not memory, not the prior review. This
   discipline is non-negotiable and should be visible in the output document.

3. **Standards to check against.** Project standards live in `.claude/CLAUDE.md`
   and everything it references, `.claude/project/*.md`, and `docs/BACKLOG.md`.
   The agent reads all of these before starting. If standards documents
   reference each other or external rules, follow the chain.

4. **Categories of findings.** At minimum:
   - Runtime / data-correctness defects (will fail or produce wrong data).
   - Documented-rule violations (forbidden strings, deviations, gotchas the
     standards explicitly call out).
   - Consistency and hygiene (sibling objects that diverge without reason,
     dead code, copy-paste rot, inert debug scaffolding).
   - Documentation drift (cosmetic — stale comments, wrong cell numbers,
     scratch notes left in).

5. **Severity tiers.** Findings are tiered. The example uses P0/P1/P2/P3;
   the designer may keep that or propose a different scheme as long as the
   tiers map to clear action semantics (must-fix, should-fix, hygiene,
   cosmetic).

6. **Each finding includes:** the exact file path, the relevant location
   (line numbers, cell numbers, function names — whatever locates it
   unambiguously), the current content quoted, the rule or pattern it
   violates with a citation, the risk if left unfixed, and a suggested fix.

7. **Branch groupings.** The review proposes how findings should be bucketed
   for remediation — coherent sets of changes addressing one problem, scoped
   so a single branch can hold them without bleeding across concerns. The
   remediation phase consumes these groupings directly.

8. **Parked vs actionable.** Findings that require a design decision rather
   than a mechanical fix are flagged as parked. The review surfaces the open
   question; it does not decide. The remediation phase skips parked items
   until the user resolves them.

9. **Output location and naming.** Review documents land in `claudedocs/`
   with a dated filename (e.g. `code_review_YYYY-MM-DD.md`). Multiple reviews
   accumulate; none are overwritten.

10. **Tone.** Senior software engineer audience. Prose where prose is clearer,
    structure where structure is clearer. No padding, no recap of the obvious.

## Phase 1+ — Remediation

These are requirements the design must satisfy. How they're realized — skill
files, slash commands, agent personas, YAML rubrics, inline prompts — is the
designer's call.

1. **Source-of-truth hierarchy.** Files on disk are truth. Project standards
   are the rules. The Phase 0 review is a guide to where to look. If a finding
   no longer reproduces on disk by the time remediation starts, it's
   resolved-on-disk and skipped.

2. **Bucket-gated execution.** Fixes proceed in the buckets the review
   proposed. The agent may propose regrouping with reasoning, but cannot
   regroup silently. Bucket X closes before bucket Y starts.

3. **Git branch per bucket.** Agent creates the branch when the user
   approves the bucket plan. Agent makes changes and stages them. The user
   commits. Agent does not push or merge.

4. **Parked items are honored.** Skipped with a one-line note. The agent
   does not lobby for them.

5. **No drive-by edits.** Changes outside the current bucket's findings are
   forbidden. The workflow should make this structurally difficult.

6. **Two-layer review.**

   *Layer 1 — internal verification by the fix agent.* Before declaring a
   bucket complete, the agent self-checks against project standards,
   forbidden strings, invariants the project documents, and diff attribution
   (every changed line traceable to a planned fix). The specific rubric is
   the designer's to propose.

   *Layer 2 — critical review in a fresh Claude Code thread.* User-triggered,
   not automatic. The fix agent's reasoning must not be in the reviewer's
   context. The reviewer sees only the diff, the project standards, the
   relevant sibling objects, and the original review excerpt for the bucket.
   Four review lenses:

   - **Assumption audit** — what did the fix take for granted?
   - **Standards conformance** — exact-quote citations from project standards.
   - **Cross-object consistency** — does this object behave the way its
     siblings do? The designer proposes a concrete procedure here, not a
     vague directive.
   - **Pattern deviations** — silent deviation is the failure mode; either
     flag as a defect or justify explicitly.

   The reviewer produces a markdown document, prose suitable for a senior
   software engineer. Short and declarative if clean; detailed and specific
   if problems found. The reviewer documents defects; it does not propose
   fixes — a later step handles remediation.

7. **User-triggered review command.** Suggested: `/critical-review`. The
   trigger produces a handoff packet (diff, branch name, relevant siblings,
   standards docs, the review excerpt for this bucket) and a self-contained
   reviewer prompt to paste into the fresh thread.

8. **User gate between buckets.** After fix-agent self-verification AND user
   runtime testing AND (when invoked) critical review, the user explicitly
   approves bucket closure. No auto-advance.

9. **Escalation on stalemate.** If the critical review rejects a bucket and
   the fix agent's next attempt is also rejected, escalate to the user
   rather than loop indefinitely. The designer proposes the cap.

## Deliverables

A design document written to `.claude/project/remediation-agent-design.md`,
covering at minimum:

- Workflow overview and rationale — why this shape, what risks it mitigates.
- The review-phase prompt — a self-contained block suitable for invoking
  Phase 0 on any project the workflow is applied to.
- Agent personas — review agent, fix agent, critical reviewer. Each with
  persona, capabilities, tools, and prompt template.
- State machine — the full lifecycle from "user invokes the workflow" to
  "all buckets closed," with every state, transition, and gate explicit.
- Internal verification rubric — Layer 1 checks, as the designer proposes.
- Critical reviewer prompt — self-contained text for pasting into a fresh
  Claude Code thread with no prior context. A deliverable in its own right.
- Handoff packet schema — what the fix agent produces for the reviewer.
- Cross-object consistency procedure — concrete steps, not vague directives.
- Git workflow — branch naming, who creates, who commits, what the agent
  is and isn't allowed to do.
- Bucket report format — what the fix agent produces at bucket close.
- Escalation rules and retry caps.
- Open questions and design alternatives considered but rejected, with
  reasoning. This is a learning project; the rejected-alternatives section
  is often more instructive than the chosen design.

## Documentation conventions

- **Design documents** (workflow design, agent specs) → `.claude/project/`.
  Version-controlled, durable, treated as project standards once approved.
- **Review documents** (point-in-time findings) → `claudedocs/`.
  Dated filenames, accumulate over time, not overwritten.

## Tone and style

Senior software engineer audience. Prose where prose is clearer, structure
where structure is clearer. Avoid vague directives — if something is a
judgment call, name the judgment.

## Out of scope for this design

- Running the workflow against any specific codebase. The design is
  general; the agent applies it per-project.
- External best-practices research. Critical review relies on fresh-eyes
  re-examination, not internet research.
- Implementation. `/sc:implement` consumes this design separately.
