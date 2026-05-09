# CI/CD Setup Plan — Vinoworld Bundle

**Goal:** Take the Vinoworld bundle from "deploys manually from my laptop" to "automated validate on every PR, automated deploy on merge, gated promotion to staging and prod" — using GitHub Actions and the Databricks Asset Bundle CLI you already know.

**Audience:** Jim — has done git/GitHub before but not in 5+ months. Every step is spelled out.

**Status:** Planned, not yet implemented. Step through one phase at a time and don't move on until the validation gate passes.

---

## Why CI/CD?

Right now, deploying changes is a manual ritual: edit code → `databricks bundle deploy --target dev` → run pipeline → if good, repeat for staging and prod. That works for one developer, but it has three problems:

1. **No validation gate.** Nothing stops you from deploying broken YAML to prod.
2. **No history of who deployed what when.** You rely on terminal scrollback.
3. **Manual prod deploys are dangerous.** A typo in `--target` and your prod environment is overwritten.

CI/CD solves all three by moving the deploy commands into a GitHub Actions workflow that runs in response to git events.

**What we're building:**

| Trigger | What runs | Where it deploys |
|---|---|---|
| Open a PR | `bundle validate` against dev | Nothing — validation only |
| Merge PR to `main` | `bundle deploy --target dev` | Dev catalog (auto) |
| Manually run "deploy-staging" workflow | `bundle deploy --target staging` | Staging catalog (gated) |
| Push a `v*` tag (e.g. `v1.0.0`) | `bundle deploy --target prod` | Prod catalog (gated, requires reviewer) |

---

## Authentication strategy

CI needs to authenticate to Databricks somehow. Three options exist:

| Option | Free Edition? | Setup effort | Maintenance |
|---|---|---|---|
| **Personal Access Token (PAT)** | ✅ Yes | Low | Token expires; rotate periodically |
| Service principal | ❌ No (Premium-only) | Medium | None |
| OIDC federated auth | ❌ No (Premium-only) | High | None |

**We're using a PAT** because Free Edition leaves no choice. You'll generate a token in the Databricks UI, store it as a GitHub repository secret, and the workflow will read it via `${{ secrets.DATABRICKS_TOKEN }}`.

**Security note:** A PAT in CI is roughly equivalent to running `databricks` as you. Don't paste it into chat, the YAML, or anywhere except the GitHub Secrets UI. If it ever leaks, revoke it in Databricks immediately.

---

## Prerequisites checklist

Before Phase 0:

- [ ] Working tree is clean (`git status` shows nothing)
- [ ] You're on `main` branch
- [ ] You have a GitHub account (`zieder0022@gmail.com` or similar — same email isn't required but typical)
- [ ] You can run `databricks bundle deploy --target dev` from `databricks_code/` and it succeeds

If any are false, fix them before continuing.

---

## Phase 0 — Verify GitHub auth and SSH key

**Goal:** Confirm you can authenticate to GitHub from this machine without re-typing a password.

**Time:** 5–15 minutes (longer if a new SSH key is needed).

### Step 0.1 — Check what auth you already have

In any directory:

```bash
ls -la ~/.ssh/
```

You're looking for one of these key files:
- `id_ed25519` and `id_ed25519.pub`  ← modern, recommended
- `id_rsa` and `id_rsa.pub`  ← older but still works

If you see any of those, you have an SSH key already. Now check **which GitHub account** that key authenticates as:

```bash
ssh -T git@github.com
```

- If the response is `Hi <the-account-you-want-to-use>!` — **skip to Step 0.5.**
- If the response is `Hi <some-other-account>!` (the key is tied to a different GitHub account than the one you want for this project) — **continue to Step 0.1a.** GitHub enforces one-key-per-account, so you cannot reuse the existing key; you need a second key plus SSH config to keep both accounts working in parallel.
- If you get "Permission denied (publickey)" — the key isn't loaded into the agent. Run `eval "$(ssh-agent -s)"` then `ssh-add ~/.ssh/id_ed25519` (or `id_rsa`) and re-test.

If `~/.ssh/` doesn't exist or has no key files, **continue to Step 0.2.**

### Step 0.1a — Multi-account: existing key is tied to a different GitHub account

**When this applies:** You already have a working SSH key, but `ssh -T git@github.com` authenticates you as a GitHub account you don't want to use for this project (e.g. a work or bot account), and you want to keep that account working too.

**Why a new key is required:** GitHub rejects any public key that is already attached to another account. You cannot share one key across two accounts. The standard fix is a second key plus an SSH `Host` alias so each account has its own dedicated key.

#### 0.1a.1 — Generate a second key with a distinct filename

```bash
ssh-keygen -t ed25519 -C "<your-email-for-the-new-account>" -f ~/.ssh/id_ed25519_<account_nickname>
```

Replace `<account_nickname>` with a short label for the account (e.g. `id_ed25519_jim`). The `-f` flag puts the key at a custom path so it doesn't collide with the existing `id_ed25519`. Press Enter twice for no passphrase, or set one if you prefer.

Verify both keys now exist side by side:

```bash
ls -la ~/.ssh/id_ed25519*
```

#### 0.1a.2 — Add the new public key to the target GitHub account

```bash
cat ~/.ssh/id_ed25519_<account_nickname>.pub
```

Copy the entire output. Then in the GitHub web UI, **logged in as the account you want to use for this project** (double-check the avatar — easy to add it to the wrong account):

1. Top-right avatar → **Settings**
2. Left sidebar → **SSH and GPG keys** → **New SSH key**
3. **Title:** something like `WSL2 Ubuntu — vinoworld`
4. **Key type:** Authentication Key
5. **Key:** paste the public key
6. Click **Add SSH key**

#### 0.1a.3 — Configure `~/.ssh/config` with a host alias

Edit (or create) `~/.ssh/config`:

```
# Default account — keep whatever was working before
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes

# Project account — used when the remote URL says github.com-<nickname>
Host github.com-<account_nickname>
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_<account_nickname>
    IdentitiesOnly yes
```

`IdentitiesOnly yes` is critical. Without it, SSH offers every loaded key to GitHub and the **first one accepted wins** — which is exactly how you end up authenticated as the wrong account. With the flag, SSH only offers the one key listed for that host alias.

Lock down permissions so SSH will accept the file:

```bash
chmod 600 ~/.ssh/config
```

#### 0.1a.4 — Test the new alias

```bash
ssh -T git@github.com-<account_nickname>
```

Expected output:

```
Hi <your-target-account>! You've successfully authenticated, but GitHub does not provide shell access.
```

If you still see the wrong account name, clear the SSH agent's cached identities and retry:

```bash
ssh-add -D
ssh -T git@github.com-<account_nickname>
```

#### 0.1a.5 — Use the alias when adding the git remote in Phase 1

This is the step people forget. When Phase 1 (Step 1.4) tells you to run `git remote add origin git@github.com:...`, you must instead use the alias:

```bash
git remote add origin git@github.com-<account_nickname>:<github_username>/vinoworld.git
```

Note the `-<account_nickname>` suffix on the host portion. SSH rewrites it back to `github.com` via the config, so GitHub itself never sees the suffix — it's purely a local routing hint to pick the right key.

If you've already added the remote with the wrong host, fix it with:

```bash
git remote set-url origin git@github.com-<account_nickname>:<github_username>/vinoworld.git
```

#### 0.1a.6 — Set per-repo git author identity

Your global `git config --global user.name` / `user.email` are probably set for the *other* GitHub account. Override them for this repo only so commits are authored as the right person:

```bash
cd ~/work/AI/databricks/vinoworld
git config user.name  "Your Name"
git config user.email "<your-email-for-the-new-account>"
```

No `--global` — that scopes the setting to `.git/config` for this repo only. Verify:

```bash
git config user.email
```

Should print the new account's email. Other repos continue to use the global default.

**After completing 0.1a, skip Steps 0.2–0.4 and go to Step 0.5** (the Phase 0 validation gate).

### Step 0.2 — Generate a new SSH key (only if Step 0.1 found nothing)

```bash
ssh-keygen -t ed25519 -C "zieder0022@gmail.com"
```

When prompted:
- **File location:** press Enter (accept default `~/.ssh/id_ed25519`)
- **Passphrase:** press Enter twice for no passphrase, OR type a passphrase (more secure but you'll type it on every push unless you use `ssh-agent`)

Verify the key exists:

```bash
ls -la ~/.ssh/id_ed25519*
```

You should see two files: `id_ed25519` (private — never share) and `id_ed25519.pub` (public — safe to share).

### Step 0.3 — Add the key to GitHub (only if you generated a new one)

Print the public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the entire output (starts with `ssh-ed25519 AAAA...` and ends with your email).

Then in GitHub web UI:
1. Top-right avatar → **Settings**
2. Left sidebar → **SSH and GPG keys**
3. Click **New SSH key**
4. **Title:** `WSL2 Ubuntu` (or however you want to remember it)
5. **Key type:** Authentication Key
6. **Key:** paste the public key
7. Click **Add SSH key**

### Step 0.4 — Test the connection

```bash
ssh -T git@github.com
```

Expected output:

```
Hi <your-username>! You've successfully authenticated, but GitHub does not provide shell access.
```

If you get **"Permission denied (publickey)"**: SSH agent isn't running or the key isn't loaded. Run:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
ssh -T git@github.com
```

### Step 0.5 — Confirm git config has your name and email

```bash
git config --global user.name
git config --global user.email
```

Both should print non-empty values. If either is empty:

```bash
git config --global user.name "Jim D"
git config --global user.email "zieder0022@gmail.com"
```

### Validation gate — Phase 0

- [ ] `ssh -T git@github.com` shows the success message
- [ ] `git config --global user.name` and `user.email` both return values

**Don't proceed to Phase 1 until both are true.**

---

## Phase 1 — Create the GitHub repo and push the project

**Goal:** Get the local repo's `main` branch onto GitHub.

**Time:** 10–15 minutes.

### Step 1.1 — Review `.gitignore` before pushing

The repo will be public (or at least visible to anyone you add as a collaborator). Make sure no secrets, generated files, or sync state are about to be committed.

```bash
cd ~/work/AI/databricks/vinoworld_bundle
cat .gitignore
```

Verify these patterns are present (add any that are missing):

```
# Databricks CLI sync state — large, machine-specific, contains paths
.databricks/

# Python bytecode
__pycache__/
*.pyc

# Local env files (NEVER commit secrets)
.env
.env.local

# OS noise
.DS_Store
Thumbs.db

# Editor temp files
*.swp
.vscode/
```

If you needed to add anything, commit it:

```bash
git add .gitignore
git commit -m "Update .gitignore before initial GitHub push"
```

### Step 1.2 — Sanity check: nothing sensitive about to be pushed

```bash
git ls-files | xargs grep -l -E "(password|token|secret|api_key)" 2>/dev/null
```

If this returns any file paths, **stop and inspect them.** False positives are fine (e.g., a comment that mentions "password" generically); real secrets must be removed before pushing.

### Step 1.3 — Create the empty repo on GitHub

In GitHub web UI:

1. Top-right `+` → **New repository**
2. **Repository name:** `vinoworld_bundle` (matches your local folder — easier to remember, but not required)
3. **Description:** "Databricks Asset Bundle conversion of the Vinoworld ELT pipeline (learning project)"
4. **Visibility:** Private (recommended for now — you can flip it later)
5. **DO NOT** check "Add a README", "Add .gitignore", or "Choose a license" — your local repo already has commits and adding files on the remote first will create a merge conflict before you've even pushed
6. Click **Create repository**

GitHub will show you a "Quick setup" page with three sections. Use the **"…or push an existing repository from the command line"** section, but the next steps walk through it explicitly.

### Step 1.4 — Add the remote and push

Back in WSL:

```bash
cd ~/work/AI/databricks/vinoworld_bundle
git remote -v
```

If you see any existing `origin` remote, that's odd — investigate before continuing. Otherwise (no output), add the remote:

```bash
git remote add origin git@github.com:<YOUR_GITHUB_USERNAME>/vinoworld_bundle.git
```

Replace `<YOUR_GITHUB_USERNAME>` with your actual GitHub username (visible in the URL of any GitHub page when logged in).

Verify:

```bash
git remote -v
```

Should print:
```
origin  git@github.com:<username>/vinoworld_bundle.git (fetch)
origin  git@github.com:<username>/vinoworld_bundle.git (push)
```

Then push:

```bash
git push -u origin main
```

The `-u` flag sets `origin/main` as the upstream so future `git push` and `git pull` work without arguments.

### Validation gate — Phase 1

- [ ] Refresh the GitHub repo page; you should see your project files (`databricks_code/`, `docs/`, etc.)
- [ ] Recent commits visible in the GitHub commit history (you should see the catalog-mapping fix commits)
- [ ] `git status` locally shows: "Your branch is up to date with 'origin/main'."

---

## Phase 2 — First CI workflow: validate on PR

**Goal:** When anyone opens a PR against `main`, GitHub Actions automatically runs `databricks bundle validate` against the dev target. A red X if it fails, a green check if it passes.

**Time:** 30 minutes.

**Concepts introduced:** GitHub Actions workflow YAML, GitHub repo secrets, `databricks/setup-cli` action, PAT-based auth in CI.

### Step 2.1 — Generate a Databricks Personal Access Token

In the Databricks Free Edition workspace UI:

1. Top-right avatar → **User Settings**
2. Left sidebar → **Developer**
3. **Access tokens** section → **Manage**
4. **Generate new token**
5. **Comment:** `GitHub Actions CI` (so future-you remembers what it's for)
6. **Lifetime (days):** 90 (or whatever maximum Free Edition allows — note the expiration date in your calendar)
7. Click **Generate**
8. **Copy the token immediately** — it's shown ONCE and never again

### Step 2.2 — Add the token as a GitHub repository secret

In the GitHub repo (`github.com/<username>/vinoworld_bundle`):

1. **Settings** tab (top of repo page)
2. Left sidebar → **Secrets and variables** → **Actions**
3. **New repository secret**
4. **Name:** `DATABRICKS_TOKEN` (exact spelling, case-sensitive)
5. **Secret:** paste the token from Step 2.1
6. Click **Add secret**

Repeat for the workspace host:

7. **New repository secret**
8. **Name:** `DATABRICKS_HOST`
9. **Secret:** `https://dbc-d0f295f4-d028.cloud.databricks.com` (no trailing slash)
10. Click **Add secret**

You should now see two secrets listed (values hidden as `***`).

### Step 2.3 — Create the workflow file

Workflows live at `.github/workflows/<name>.yml` from the **repo root** (NOT inside `databricks_code/`).

```bash
cd ~/work/AI/databricks/vinoworld_bundle
mkdir -p .github/workflows
```

Create `.github/workflows/validate.yml` with this content:

```yaml
name: Validate Bundle

on:
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: databricks_code   # bundle root is here, not repo root
    steps:
      - name: Check out PR
        uses: actions/checkout@v4

      - name: Install Databricks CLI
        uses: databricks/setup-cli@main

      - name: Validate bundle (dev target)
        env:
          DATABRICKS_HOST:  ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: databricks bundle validate --target dev
```

**Concepts to call out:**

- `on: pull_request:` — workflow runs only when someone opens, updates, or reopens a PR
- `working-directory: databricks_code` — your bundle root isn't at the repo root; without this, the CLI wouldn't find `databricks.yml`
- `databricks/setup-cli@main` — official action that installs the Databricks CLI into the runner
- `${{ secrets.X }}` — pulls the secret value at runtime; never appears in logs

### Step 2.4 — Commit and push the workflow on a feature branch

You can't open a PR if there's nothing different from `main`. Make a small no-op change on a branch:

```bash
git checkout -b ci/add-validate-workflow
git add .github/workflows/validate.yml
git commit -m "Add CI workflow: bundle validate on PR"
git push -u origin ci/add-validate-workflow
```

GitHub will print a URL like `https://github.com/<username>/vinoworld_bundle/pull/new/ci/add-validate-workflow`. Open it and create the PR.

### Step 2.5 — Watch the CI run

On the PR page, scroll to the bottom — you'll see a "checks" section that says **"Validate Bundle / validate" — Queued / In progress / Success**.

Click **Details** to see the live log. Expected output ends with something like:

```
Name: vinoworld_bundle
Target: dev
Workspace:
  Host: https://dbc-d0f295f4-d028.cloud.databricks.com
  ...
Validation OK!
```

If it fails:
- **"Cannot find databricks.yml"** → `working-directory:` is missing or wrong
- **"401 Unauthorized"** → Secret name typo, or PAT is expired/revoked
- **"403 Forbidden"** → PAT doesn't have permission for the workspace (unlikely on Free Edition since you're the only user)

### Step 2.6 — Merge the PR

Once green, click **Merge pull request** → **Confirm merge**. Then locally:

```bash
git checkout main
git pull
git branch -d ci/add-validate-workflow
```

### Validation gate — Phase 2

- [ ] Open a new test PR with any trivial change (e.g., a comment in a notebook). The validate check runs automatically and passes.
- [ ] Close the test PR without merging.

### Reference — Anatomy of a CI run

Once the workflow is green, it's worth understanding *exactly* what happened end-to-end. This is the mental model to carry into Phases 3–5.

**1. Trigger.** The workflow file declares:
```yaml
on:
  pull_request:
    branches: [main]
```
When you opened the PR targeting `main`, GitHub fired a `pull_request` event. GitHub's workflow engine scanned `.github/workflows/` in the PR's branch, found `validate.yml`, and matched the trigger.

**2. Runner provisioning.** `runs-on: ubuntu-latest` told GitHub to spin up a **fresh ephemeral VM** — a clean Ubuntu container with nothing project-specific on it. No code, no CLIs, no secrets, no `~/.databrickscfg`. This VM exists only for this one workflow run and is destroyed when it finishes. That's why local config files on your laptop are irrelevant — the runner has never seen them.

**3. Step 1 — `actions/checkout@v4`.** A pre-built GitHub Action (a reusable script) that runs `git clone` of *your PR branch* into the runner's working directory. After this step, the runner has a copy of your repo at the PR's commit SHA.

**4. Step 2 — `databricks/setup-cli@main`.** Another pre-built action, this one published by Databricks. It downloads the Databricks CLI binary, installs it on the runner's PATH, and prints the version. After this step, `databricks` is a runnable command on the runner.

**5. Step 3 — `databricks bundle validate --target dev`.** With CLI installed and auth env vars set from secrets, the CLI:
   - Read `databricks_code/databricks.yml` (working directory was set to `databricks_code` via `defaults.run.working-directory`).
   - Resolved variable substitutions for the `dev` target (e.g., `${var.catalog}` → `dev_vinoworld`).
   - Authenticated to the Free Edition workspace using the env-var token.
   - Made API calls to verify the workspace is reachable, the user exists, and the resource definitions are syntactically and semantically valid.
   - Printed `Validation OK!`

**6. Cleanup.** The runner VM is destroyed. Logs are retained on GitHub for 90 days (default). The PR's "Checks" tab shows green because the workflow exited 0.

**Things to internalize:**

- **Runners are stateless and ephemeral.** Every run starts from zero. Anything you need has to either be checked into the repo, fetched by an action, or injected as a secret.
- **Secrets are environment variables, not files.** GitHub only exposes them to steps that explicitly opt in via `env:` or `with:`. They're masked in logs (that's why `Host:` shows as `***`).
- **The CLI on the runner is the same binary you'd run locally.** It just sees a different auth source (env vars instead of `~/.databrickscfg`) and a fresh checkout instead of your laptop's working tree.
- **`bundle validate` is not just YAML syntax checking.** It calls the Databricks API to verify the workspace exists and the auth works. That's why missing/wrong credentials surface here, not at file-parse time.

This same flow powers `bundle deploy` in Phases 3–5 — same runner, same auth pattern, just a different CLI command and (eventually) a GitHub Environment + branch/tag protection rules around it.

---

## Phase 3 — Auto-deploy to dev on merge to main

**Goal:** Every merge to `main` triggers a `databricks bundle deploy --target dev`. Validation already happened on the PR, so we know the YAML is good.

**Time:** 20 minutes.

**Concepts introduced:** Multiple workflow triggers, `on: push:` events, named jobs.

### Step 3.1 — Add a deploy job to the workflow

Edit `.github/workflows/validate.yml` and rename it to something more accurate. We'll handle that in Step 3.4 — for now, just add a new job:

Replace the file contents with:

```yaml
name: Validate and Deploy

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  validate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: databricks_code
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - name: Validate bundle (dev target)
        env:
          DATABRICKS_HOST:  ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: databricks bundle validate --target dev

  deploy-dev:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: databricks_code
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - name: Deploy to dev
        env:
          DATABRICKS_HOST:  ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: databricks bundle deploy --target dev
```

**Concepts to call out:**

- `on:` now lists two trigger types — pull_request AND push
- Each job has an `if:` filter so it only runs on the right trigger
- `validate` runs on PRs only; `deploy-dev` runs on pushes to main only
- `github.ref == 'refs/heads/main'` — extra safety so a push to a different branch (somehow) doesn't trigger a deploy

### Step 3.2 — Rename the file

```bash
cd ~/work/AI/databricks/vinoworld_bundle
git mv .github/workflows/validate.yml .github/workflows/ci.yml
```

(The filename has no semantic meaning to GitHub Actions — it's purely for human readability. `ci.yml` makes more sense now that it does both validate and deploy.)

### Step 3.3 — Test it on a feature branch

```bash
git checkout -b ci/add-dev-deploy
git add .github/workflows/ci.yml
git commit -m "Add auto-deploy to dev on merge to main"
git push -u origin ci/add-dev-deploy
```

Open a PR. The `validate` job runs (because it's a PR). Merge the PR. Within 30 seconds the `deploy-dev` job runs (because the merge is a push to main).

### Step 3.4 — Verify the deploy worked

Watch the `deploy-dev` job log on GitHub. Then in WSL:

```bash
cd ~/work/AI/databricks/vinoworld_bundle/databricks_code
databricks workspace list /Workspace/Users/zieder0022@gmail.com/.bundle/vinoworld_bundle/dev/files/notebooks/bronze
```

You should see your bronze notebooks. To confirm CI did the deploy (not your last manual one), check the "Last modified" timestamp in the Databricks workspace UI — it should be within the last few minutes.

### Validation gate — Phase 3

- [ ] PR with any small change triggers `validate` (green check)
- [ ] Merging the PR triggers `deploy-dev` (green check)
- [ ] Bundle deployment in Databricks UI shows recent timestamps

---

## Phase 4 — Manual-trigger deploy to staging

**Goal:** A human deliberately clicks a button to deploy to staging. No accidental staging deploys from a stray push.

**Time:** 15 minutes.

**Concepts introduced:** `workflow_dispatch` (manual trigger), input parameters, GitHub Environments.

### Step 4.1 — Add the staging deploy job

Edit `.github/workflows/ci.yml` and add a new trigger to the `on:` block:

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      target:
        description: "Target to deploy"
        type: choice
        options: [staging]
        default: staging
        required: true
```

Then add this job to the `jobs:` block (after `deploy-dev`):

```yaml
  deploy-staging:
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment: staging
    defaults:
      run:
        working-directory: databricks_code
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - name: Deploy to staging
        env:
          DATABRICKS_HOST:  ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: databricks bundle deploy --target staging
```

### Step 4.2 — Create the GitHub Environment

In GitHub repo → **Settings** → **Environments** → **New environment**:

- **Name:** `staging`
- Click **Configure environment**

(Optional — Free GitHub doesn't allow required reviewers on private repos, but on public repos or paid plans you can require manual approval here.)

### Step 4.3 — Push and test

```bash
git checkout -b ci/add-staging-deploy
git add .github/workflows/ci.yml
git commit -m "Add manual staging deploy via workflow_dispatch"
git push -u origin ci/add-staging-deploy
```

Open PR → merge → workflow file is now on main.

To trigger the manual deploy:

1. GitHub repo → **Actions** tab
2. Left sidebar → **Validate and Deploy**
3. Top-right **Run workflow** button
4. Branch: `main`
5. Target: `staging`
6. Click **Run workflow**

Watch the `deploy-staging` job execute.

### Validation gate — Phase 4

- [ ] **Run workflow** button is visible in the Actions UI
- [ ] Triggering it deploys to `staging_vinoworld` catalog
- [ ] Pushing to `main` does NOT trigger `deploy-staging` (only `deploy-dev`)

---

## Phase 5 — Tag-triggered deploy to prod

**Goal:** Pushing a git tag like `v1.0.0` deploys to prod. No accidental prod deploys from anything else.

**Time:** 20 minutes.

**Concepts introduced:** Git tags, tag-based workflow triggers, environment protection.

### Step 5.1 — Add the prod deploy job

Edit `.github/workflows/ci.yml`. Add `tags:` to the push trigger:

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
    tags: ['v*']
  workflow_dispatch:
    inputs:
      target:
        description: "Target to deploy"
        type: choice
        options: [staging]
        default: staging
        required: true
```

Add this job to the `jobs:` block:

```yaml
  deploy-prod:
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: databricks_code
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - name: Deploy to prod
        env:
          DATABRICKS_HOST:  ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: databricks bundle deploy --target prod
```

Also update the `deploy-dev` job's `if:` to exclude tag pushes (otherwise tags would trigger BOTH dev and prod deploys):

```yaml
  deploy-dev:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```

(This was already correct — tags are at `refs/tags/v*`, not `refs/heads/main`. But double-check the line is exactly as shown.)

### Step 5.2 — Create the production environment

GitHub repo → **Settings** → **Environments** → **New environment** → name: `production`.

If you have GitHub Pro, Team, or are on a public repo: enable **Required reviewers** and add yourself. Then production deploys will pause until you click "Approve" — a useful safety net even when you're the only reviewer.

### Step 5.3 — Push, then tag

Push the workflow change first via the normal PR flow:

```bash
git checkout -b ci/add-prod-deploy
git add .github/workflows/ci.yml
git commit -m "Add tag-triggered deploy to prod"
git push -u origin ci/add-prod-deploy
```

Open PR → merge.

Now the workflow is on main. Cut a release:

```bash
git checkout main
git pull
git tag -a v1.0.0 -m "First production deploy via CI"
git push origin v1.0.0
```

The tag push triggers the `deploy-prod` job. Watch it in the Actions tab.

### Validation gate — Phase 5

- [ ] `git push origin v1.0.0` triggers `deploy-prod`
- [ ] `vinoworld` catalog has up-to-date deployed code
- [ ] Pushing a regular commit to main triggers `deploy-dev` only (not prod)

---

## Phase 6 (optional) — Add tests in CI

This is where CI/CD goes from "automation" to "quality gate." Out of scope for the initial setup, but the natural next layer:

- **Unit tests for `libs/`** — pytest tests that import `pipeline_utils` and `pipeline_logging` and assert their functions behave correctly. Run on every PR.
- **YAML linting** — `yamllint` on `databricks.yml` to catch formatting issues.
- **Notebook smoke tests** — run a single small cell in the deployed notebook and assert it succeeded.
- **Data quality checks post-deploy** — after `deploy-dev`, trigger the pipeline run and assert row counts match expectations.

Defer until Phases 1–5 are stable and you have something to test.

---

## Maintenance and gotchas

- **PAT expiration.** Whatever lifetime you set in Step 2.1, the token expires. When it does, every CI run starts failing with 401. Fix: regenerate, update the `DATABRICKS_TOKEN` secret. Set a calendar reminder for ~1 week before expiration.
- **Secrets are write-only.** Once you add a secret to GitHub, you can never view its value again — only update or delete it. If you forget what the value was, you regenerate.
- **`working-directory` everywhere.** Every CI step that runs `databricks` needs `working-directory: databricks_code` because that's where `databricks.yml` lives. Easy to forget when adding new jobs.
- **Don't enable the existing claude-code PreToolUse hook in CI.** Hooks fire in your local Claude Code session, not in GitHub Actions runners — irrelevant here. But if you ever copy commands from notes into a CI workflow, strip out anything `claude`-specific.
- **Free Edition rate limits.** A `bundle deploy` syncs files via the workspace API. If you push 50 commits in 5 minutes, you'll hit rate limits. Realistic dev pace doesn't hit this.
- **PAT API scope must be "All APIs" for CI deploys.** When generating the PAT in Step 2.1, the Databricks UI lets you select which API surfaces the token can call. **Always select "All APIs" for a CI deploy token.** A narrowly-scoped token will pass `bundle validate` (which only hits identity and resource-metadata APIs) but fail on `bundle deploy` with a misleading "Failed to update, encountered possible permission error: …/files" message. The actual cause is a missing API scope, not a folder ACL — but the error wording sends you down the wrong debugging path. For a token that already holds full deploy power, trimming scopes doesn't reduce blast radius (if it leaks, the attacker can rewrite your jobs either way) but does create future failures the day someone adds a new resource type. The real security boundary on a CI token is "who can read the GitHub secret," not "which APIs it can call." If you ever see the "permission error" on `/files` after fixing the obvious ACL paths, regenerate the token with "All APIs" before going further.

---

## Why each phase introduces only one concept

(For your reference if you skim this in 6 months.)

| Phase | New concept | Why isolated |
|---|---|---|
| 0 | SSH auth to GitHub | If this breaks, nothing else can work |
| 1 | Remote git, push | Foundation; can't run CI without code on GitHub |
| 2 | Workflow YAML, secrets, validate | One workflow file, one trigger, one command |
| 3 | Multiple triggers in one workflow | Adds push trigger alongside PR trigger |
| 4 | `workflow_dispatch` and Environments | New trigger type and a new GitHub feature |
| 5 | Tag triggers, environment protection | Different ref pattern, optional reviewer gate |

Same principle as the catalog-mapping fix plan: don't bundle two new concepts into one phase, because if it breaks you won't know which concept caused the break.

---

## Out of scope for this plan

- **Service principal or OIDC auth.** Premium-tier features; revisit if you ever upgrade.
- **Self-hosted GitHub runners.** Not needed for this workload.
- **Multi-environment matrices** (e.g., deploy to dev + Azure simultaneously). Possible but adds complexity; one target per workflow run is fine.
- **Reusable workflows.** When the YAML duplication starts hurting (probably after Phase 5), refactor into a reusable workflow. Until then, copy-paste is clearer.
- **Branch protection rules.** Recommended for a real team setup (require validate to pass before merge), but optional for a solo learning project.
