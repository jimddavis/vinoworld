# Branching Strategy — Reading List and Notes

**Context:** While drafting `cicd_setup_plan.md`, the question came up of whether
"auto-deploy to dev on merge to `main`" implies the wrong branching model. The
intuition — that `main` should mean "in production" and a separate long-lived
`develop` branch should be the integration target — describes **Git Flow**.
The plan as written assumes **trunk-based development**, where `main` means
"latest reviewed and integrated code" and promotion to staging/prod is gated
by separate triggers (manual dispatch, version tags).

This document is a reading list for deciding which model to use, plus notes on
why search results skew so heavily toward Git Flow even though current research
points the other way.

---

## The most important article to read first

- **[A successful Git branching model — Vincent Driessen](https://nvie.com/posts/a-successful-git-branching-model/)**
  This is the 2010 post that launched Git Flow. Read the full original argument,
  *then* read the **"Note of reflection"** the author added at the top in March
  2020 where he explicitly walks the model back for web and SaaS workloads and
  points readers toward simpler trunk-based approaches. When the inventor of
  Git Flow no longer recommends it for your kind of project, that carries weight.

---

## Research-backed perspective (DORA / Accelerate)

DORA is the research program behind the *Accelerate* book and the annual State
of DevOps reports. Their multi-year survey data is the strongest empirical
evidence available on branching strategy.

- **[DORA — Trunk-based development capability](https://dora.dev/capabilities/trunk-based-development/)**
  Headline finding: trunk-based development correlates with elite delivery
  performance (deployment frequency, lead time, change failure rate, time to
  restore service). Short, dense, citation-heavy.
- **[DORA — Continuous integration capability](https://dora.dev/capabilities/continuous-integration/)**
  Companion piece explaining *why* long-lived branches hurt CI specifically:
  integration is delayed, merge conflicts pile up, and "it works on my branch"
  bugs are discovered late.

---

## Balanced comparison articles

- **[Atlassian — Trunk-based development](https://www.atlassian.com/continuous-delivery/continuous-integration/trunk-based-development)**
  Notable because Atlassian sells tools (Bitbucket, Jira) that pair naturally
  with Git Flow's structure — yet even they recommend trunk-based for CI/CD
  workflows. Good plain-English overview.
- **[Mergify — Trunk-Based Development vs Gitflow: Which Branching Model Actually Works?](https://mergify.com/blog/trunk-based-development-vs-gitflow-which-branching-model-actually-works/)**
  Head-to-head with concrete examples of where each model falls down.
- **[Flagsmith — Trunk-Based Development vs Gitflow: Choosing the Right Branching Strategy](https://www.flagsmith.com/blog/trunk-based-development-vs-gitflow)**
  Decision-tree framing. Useful if you want "pick based on your situation"
  rather than an advocacy piece.

---

## Why search results skew toward multi-branch models

A few things to keep in mind while reading:

1. **Git Flow is older (2010) and has a memorable diagram.** It dominates older
   blog posts and tutorial sites. Trunk-based and GitHub Flow content is newer
   and less visually iconic, so it ranks lower in search.
2. **Many "best practice" articles are written by tooling vendors** whose
   products (release managers, branch protection dashboards, multi-environment
   promotion UIs) have more surface area to sell in a Git Flow world. Watch
   for that bias.
3. **Industry context matters a lot.** Embedded software, mobile apps with
   App Store review cycles, regulated industries (banking, medical devices)
   often *do* benefit from Git Flow's structure. Web apps, SaaS, and data
   pipelines usually don't — they want fast, frequent, reversible deploys.
4. **"Multiple branches" ≠ "Git Flow."** Trunk-based development still uses
   short-lived feature branches (typically a day or two). What it rejects is
   the *long-lived* `develop` branch that lives in parallel to `main` for
   weeks. Articles that say "use feature branches" are compatible with both
   models — don't read them as an endorsement of Git Flow specifically.

---

## How this maps to the Vinoworld CI/CD plan

The plan in `cicd_setup_plan.md` is trunk-based-leaning but conservative:

| Concern | How the plan addresses it |
|---|---|
| Direct commits to `main` | Not allowed — every change goes through a PR with `bundle validate` running on it |
| Auto-deploy to prod | Not allowed — prod requires a `v*` git tag, which is a deliberate human action |
| Staging deploys | Manual `workflow_dispatch` only — no trigger from a branch push |
| Dev environment | `main` auto-deploys to the dev *target* (a sandbox catalog), not to anything user-facing |

So `main` in this plan does **not** mean "in production." It means "passed PR
review and validation, deployed to the dev sandbox." Promotion to prod is a
separate, deliberate step.

If after reading the articles above the conclusion is still that a permanent
`develop` branch is preferred, the changes to the plan are small:

1. Create a `develop` branch in Phase 1 alongside `main`.
2. Change PR target from `main` to `develop` in Phase 2.
3. Change the auto-deploy-to-dev trigger from `push to main` to
   `push to develop` in Phase 3.
4. Keep the `v*` tag → prod flow, but only cut tags from `main` after a
   `develop → main` merge (which represents "promoted to prod-ready").

---

## Recommendation

For a solo learning project deploying a Databricks pipeline, either model
will work — the change volume is too low for Git Flow's drift problems to
bite hard. But if the goal is to build habits that match how modern data
and web teams actually ship, trunk-based is the current default and the one
the research supports.

Read Driessen's 2020 note first. Decide after that.
