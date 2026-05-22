---
name: comfyui-backport-release
description: Backports commits from ComfyUI master to a patch release (v0.X.Y) by cherry-picking, opening a PR with the exact title the Backport Release workflow expects, and avoiding the attribution and CI pitfalls Amp tends to hit. Use when asked to cut a ComfyUI patch release, backport a commit, or open a "ComfyUI backport release vX.Y.Z (patch version bump)" PR.
---

# ComfyUI Backport Release

End-to-end workflow for cutting a `vMAJOR.MINOR.PATCH` patch release of ComfyUI by cherry-picking commits from `master` into a backport branch and opening a PR that the **Backport Release** workflow (`.github/workflows/backport-release.yml`) will accept.

## Before you start — ask the user

Do NOT guess any of these:

- **Cherry-pick commit SHA(s)** — full 40-char hex SHAs from `master`.
- **Patch version** (`vMAJOR.MINOR.PATCH`) — used in the PR title.
- **Source release branch** (`release/vMAJOR.MINOR`).
- **Git identity** — if `git config user.name` / `user.email` are unset in the repo and globally, ASK the user for both. Do not invent an email based on hostname. Do not assume the GitHub username.

The token at `/Users/jedrzej/comfy-vibe-station/githubtoken.txt` (or `githubtoken.txt` at the workspace root on other machines) is for GitHub API calls only — it does NOT solve the local-commit-identity problem.

## The PR contract the workflow enforces

The `Create backport release` job validates **all** of these. Get any wrong and it fails before doing anything useful:

| Requirement | Detail |
|---|---|
| PR base | **`master`** — NOT the release branch. The workflow fast-forwards `release/vX.Y` itself; the PR is just the human-review gate against master. |
| PR head | The backport branch you push (e.g. `backport/v0.22.2-rodin-nodes`). |
| PR title | **Exactly** `ComfyUI backport release vMAJOR.MINOR.PATCH (patch version bump)` — no extra spaces, no different casing. |
| PR state | Open. |
| Head SHA | Must match the SHA the workflow was dispatched against. Pushing new commits after dispatch invalidates the run. |
| Source branch lineage | First-parent history must include the latest stable release tag's commit. Branching from `release/vX.Y` works only if that branch tip equals the latest stable tag. |
| All check runs on head SHA | Must be passing (or non-failing). |
| **Do NOT modify version files.** | The workflow runs the version bump itself in a later step. |

The PR description is free-form; the workflow does not parse it.

## Workflow

### 1. Verify identity

```bash
git -C ComfyUI config user.name
git -C ComfyUI config user.email
```

If either is empty AND `git config --global user.{name,email}` is also empty: stop and ask the user. Do not proceed.

### 2. Cut the backport branch from the release branch

```bash
cd ComfyUI
git fetch --all --prune
git checkout -b backport/vMAJOR.MINOR.PATCH-<topic> origin/release/vMAJOR.MINOR
```

`<topic>` is a short slug describing the cherry-pick (e.g. `rodin-nodes`, `security-fix`).

### 3. Cherry-pick

```bash
git cherry-pick <FULL_SHA_FROM_MASTER>
```

If conflicts: stop and ask the user before resolving anything non-trivial.

### 4. Fix attribution — bypass the Amp commit hook

**Critical:** `git commit` (including `git commit --amend`, even with `-F file` or `--no-verify`) is intercepted in the Amp environment and **automatically appends**:

```
Co-authored-by: Amp <amp@ampcode.com>
Amp-Thread-ID: https://ampcode.com/threads/T-...
```

This is wrong for a backport — a cherry-pick is a 1:1 copy of someone else's work, not collaboration with Amp. The only reliable way to commit a clean message is to bypass `git commit` entirely with `git commit-tree`:

```bash
# Build the clean message (preserves original)
git log -1 --format='%B' HEAD \
  | grep -vE '^(Co-authored-by: Amp|Amp-Thread-ID:)' > /tmp/msg.txt

PARENT=$(git rev-parse HEAD^)
TREE=$(git rev-parse HEAD^{tree})

# Preserve original author (from the cherry-picked commit).
# Committer is the human running the backport — use values from `git config` or what the user provided.
ORIG_AUTHOR_NAME=$(git log -1 --format='%an' HEAD)
ORIG_AUTHOR_EMAIL=$(git log -1 --format='%ae' HEAD)
ORIG_AUTHOR_DATE=$(git log -1 --format='%aI' HEAD)

NEW=$(GIT_AUTHOR_NAME="$ORIG_AUTHOR_NAME" \
      GIT_AUTHOR_EMAIL="$ORIG_AUTHOR_EMAIL" \
      GIT_AUTHOR_DATE="$ORIG_AUTHOR_DATE" \
      GIT_COMMITTER_NAME="$(git config user.name)" \
      GIT_COMMITTER_EMAIL="$(git config user.email)" \
      git commit-tree "$TREE" -p "$PARENT" -F /tmp/msg.txt)

git update-ref refs/heads/$(git symbolic-ref --short HEAD) "$NEW"
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>%n---%n%B'
```

Verify the printed message has **no** `Co-authored-by: Amp` / `Amp-Thread-ID:` lines and the original author is preserved.

### 5. Push and open PR

```bash
git push -u origin <branch>
```

Open the PR via API with `base: master` and the exact title:

```bash
export GITHUB_TOKEN=$(cat <path-to-githubtoken.txt>)
TITLE="ComfyUI backport release vMAJOR.MINOR.PATCH (patch version bump)"
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Comfy-Org/ComfyUI/pulls \
  -d "$(jq -n --arg t "$TITLE" --arg h "<branch>" '{title:$t, head:$h, base:"master", body:"Backport for vMAJOR.MINOR.PATCH."}')"
```

### 6. Hand off

Tell the user the PR number and that you are **not** modifying version files — they (or the workflow they dispatch) handle that. Wait for them to confirm before doing anything else.

## Pitfalls that have burned us — do NOT repeat

1. **Don't push without verifying committer attribution.** Even after setting `GIT_COMMITTER_*`, the standard `git commit --amend` will re-append the Amp trailers. Always use `git commit-tree` for the final commit. Verify with `git log -1 --format='%B'` before pushing.
2. **Don't use `--reset-author`** on a cherry-pick. The original author must be preserved; only the committer should be you.
3. **Don't target the release branch with the PR.** The workflow checks `base: master`. Targeting `release/vX.Y` causes step 8 ("Validate PR exists...") to fail with `No open PR found from '<branch>' into 'master'`.
4. **Don't force-push casually after CI starts.** Each force-push:
   - Cancels/orphans in-flight CI runs (you have to re-wait).
   - Invalidates any workflow dispatch tied to the old head SHA.
   - Can dismiss reviews depending on branch protection.
   - May break already-deployed test instances that pinned the old SHA.
   Ask before force-pushing once CI is running or anything has been deployed.
5. **Don't modify version files.** The workflow's "Bump version files" step does it. Adding a version bump commit yourself will diverge from what the workflow expects.
6. **Don't poll job status for `"completed"`** when using the comfy-runner API to deploy a test instance — the actual terminal status is `"done"`. (See `comfy-runner` skill.)
