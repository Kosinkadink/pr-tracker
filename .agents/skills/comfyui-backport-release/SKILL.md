---
name: comfyui-backport-release
description: Backports commits from ComfyUI master to a patch release (v0.X.Y) by cherry-picking, opening a PR with the exact title the Backport Release workflow expects, and avoiding the attribution and CI pitfalls Amp tends to hit. Use when asked to cut a ComfyUI patch release, backport a commit, or open a "ComfyUI backport release vX.Y.Z (patch version bump)" PR.
---

# ComfyUI Backport Release

End-to-end workflow for cutting a `vMAJOR.MINOR.PATCH` patch release of ComfyUI by cherry-picking commits from `master` onto the latest stable tag and opening a PR that the **Backport Release** workflow (`.github/workflows/backport_release.yaml`) will accept.

> Shell note: commands are given in **bash** and **PowerShell**. Pick the block that matches your machine. On Windows this workspace runs PowerShell, so `head`/`grep`/`tail`/`cat` do not exist -- use the PowerShell block.

## How the workflow works (read this first)

The workflow is dispatched (`workflow_dispatch`) with one input: `commit`, the **full 40-char SHA of your backport branch tip**. It does NOT take a version or a branch name. It derives everything:

1. **Resolves the source branch** from that SHA -- exactly one branch on `origin` must have that SHA as its tip. So your branch must be pushed, and no other branch can point at the same commit.
2. **Determines the new version automatically.** It finds the highest `vMAJOR.MINOR.PATCH` tag, adds 1 to the patch, and that is the release. Release branch is `release/vMAJOR.MINOR`.
   - Latest tag `v0.27.0` -> new version `v0.27.1`, branch `release/v0.27`.
   - Latest tag `v0.27.1` -> new version `v0.27.2`, branch `release/v0.27`.
3. **Validates your branch is cut directly from the latest stable tag**: first-parent history must reach the tag's commit, AND every commit you added must be on that first-parent chain (no merges, no commits pulled in from master's DAG). A clean linear cherry-pick satisfies this.
4. **Validates the PR**: open, base `master`, exact title, head SHA equals the dispatched `commit`, all checks passing.
5. **Prepares the release branch**: if `release/vX.Y` exists, its tip must equal the latest tag; if it does not exist (only valid when the latest tag's patch is `0`), it creates it from the tag.
6. Fast-forwards the release branch to your commit, **bumps the version files itself**, commits, tags, and pushes.

Because version and release branch are derived, **you do not ask the user for them** -- you read them off the latest tag. The only thing you must get exactly right by hand is the **PR title**.

## Before you start

- **Cherry-pick commit SHA(s)** -- the user provides these; use full 40-char hex SHAs from `master`. Verify each exists (`git log -1 <sha>`).
- **Confirm the latest stable tag** yourself (see step 2). This determines the version; do not assume. Auto-versioning is usually correct, but if the latest tag looks surprising (e.g. a stray `v0.99.99` test tag), flag it to the user before proceeding -- the workflow uses numeric major/minor/patch sorting, not `sort -V`.
- **Git identity** -- if `git config user.name` / `user.email` are unset in the repo and globally, ASK the user for both. Do not invent an email based on hostname. Do not assume the GitHub username.

The GitHub token (path varies by machine: `githubtoken.txt` at the workspace root, or the parent workspace root per `AGENTS.md`) is for GitHub API calls only -- it does NOT solve the local-commit-identity problem.

## The PR contract the workflow enforces

| Requirement | Detail |
|---|---|
| PR base | **`master`** -- NOT the release branch. The workflow fast-forwards `release/vX.Y` itself; the PR is the human-review gate against master. |
| PR head | The backport branch you push (e.g. `backport/v0.27.1-partner-and-audio`). |
| PR title | **Exactly** `ComfyUI backport release vMAJOR.MINOR.PATCH` -- no extra spaces, casing changes, or suffix. Exact string match. |
| PR state | Open. |
| Head SHA | Must match the SHA the workflow is dispatched against. Pushing new commits after dispatch invalidates the run. |
| Source branch lineage | First-parent history must include the latest stable tag's commit, with no off-chain commits. Achieved by branching from the tag and cherry-picking linearly. |
| All check runs on head SHA | Must be passing (success / neutral / skipped). |
| **Do NOT modify version files.** | The workflow runs the version bump (`comfyui_version.py`, `pyproject.toml`) itself. |

The PR description is free-form; the workflow does not parse it.

## Workflow

### 1. Verify identity

bash:
```bash
git -C ComfyUI config user.name
git -C ComfyUI config user.email
```
PowerShell (run from the `ComfyUI` dir, or use `git -C ComfyUI ...`):
```powershell
git config user.name
git config user.email
```
If either is empty AND `git config --global user.{name,email}` is also empty: stop and ask the user.

### 2. Fetch and determine the version

Find the highest stable tag; new version = patch + 1.

bash:
```bash
cd ComfyUI
git fetch --all --prune --tags
git tag --list 'v[0-9]*.[0-9]*.[0-9]*' \
  | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
  | awk -F'[v.]' '{ printf "%010d %010d %010d %s\n", $2, $3, $4, $0 }' \
  | sort -k1,1n -k2,2n -k3,3n | tail -n1 | awk '{print $4}'
```
PowerShell:
```powershell
git fetch --all --prune --tags
git tag --list "v*" |
  Where-Object { $_ -match '^v(\d+)\.(\d+)\.(\d+)$' } |
  Sort-Object { [version]($_.TrimStart('v')) } |
  Select-Object -Last 1
```
If the latest tag is `vX.Y.Z`, the release will be `vX.Y.(Z+1)` on branch `release/vX.Y`. Record the tag's SHA -- your branch must descend from it.

### 3. Cut the backport branch FROM THE LATEST STABLE TAG

Always branch from the tag, not from `release/vX.Y`. This is correct whether or not the release branch exists yet:
- Latest tag patch `> 0`: `release/vX.Y` exists and its tip already equals the tag, so branching from the tag is equivalent and safer.
- Latest tag patch `== 0`: `release/vX.Y` does not exist yet (the workflow will create it from the tag). Branching from the release branch would fail -- you MUST branch from the tag.

bash / PowerShell (same command):
```
git checkout -b backport/vMAJOR.MINOR.PATCH-<topic> vMAJOR.MINOR.<latest-patch>
```
Example: latest tag `v0.27.0` -> `git checkout -b backport/v0.27.1-partner-and-audio v0.27.0`.

`<topic>` is a short slug describing the cherry-pick (e.g. `partner-and-audio`, `security-fix`).

### 4. Cherry-pick, in chronological (oldest-first) order

Ordering by commit date keeps dependent commits applying cleanly (e.g. a "adjust category" fix after the feature that added the category).

```
git cherry-pick <SHA_OLDEST> <SHA_...> <SHA_NEWEST>
```
Cherry-pick preserves the **original author**; the committer becomes you. That is exactly what a backport wants -- do NOT use `--reset-author`.

**Conflicts are normal on dependency-bump commits** (see requirements.txt below). Resolve, `git add <file>`, then continue. Use a non-interactive editor so the continue does not hang:

bash:
```bash
GIT_EDITOR=true git cherry-pick --continue
```
PowerShell:
```powershell
git -c core.editor=true cherry-pick --continue
```

#### requirements.txt conflicts (standard on these backports)

Commits like "Update workflow templates to vX.Y.Z" bump a pinned dependency in `requirements.txt`. They almost always conflict because master's pins have drifted ahead of the stable tag. The three-way will show extra unrelated pins (e.g. `comfyui-embedded-docs`) that differ only because master moved on.

**Resolution rule: apply ONLY the change the cherry-picked commit actually made; keep every other pin at the stable-tag base value.** Check what the commit changed with `git show <sha> -- requirements.txt` and apply just that one bump. Do not pull in unrelated dependency bumps that happened to be ahead on master -- those belong to other releases.

### 5. Guarantee NO Amp trailers ended up on any commit -- always verify

**Why this matters:** a cherry-pick is a 1:1 copy of someone else's work, not collaboration with Amp. Amp trailers (`Co-authored-by: Amp <amp@ampcode.com>`, `Amp-Thread-ID: ...`) must **NEVER** appear on a backport commit. In practice `git cherry-pick` does NOT trigger the Amp commit hook, so usually the messages are already clean. But agent behavior is non-deterministic and the hook fires on `git commit`/`--amend`/conflict resolutions -- so **you must always verify, every time, and never assume.**

Verify author, committer, and full message of every backported commit:

bash:
```bash
git log v<TAG>..HEAD --format='=== %h ===%nAuthor: %an <%ae>%nCommitter: %cn <%ce>%n%B'
git log v<TAG>..HEAD --format='%B' | grep -nE 'Co-authored-by: Amp|Amp-Thread-ID:' && echo 'FOUND AMP TRAILERS' || echo 'clean'
```
PowerShell:
```powershell
git log v<TAG>..HEAD --format="=== %h ===`nAuthor: %an <%ae>`nCommitter: %cn <%ce>`n%B"
if (git log v<TAG>..HEAD --format="%B" | Select-String -Pattern 'Co-authored-by: Amp|Amp-Thread-ID:') { "FOUND AMP TRAILERS" } else { "clean" }
```

Confirm for every commit: original author preserved, committer is you, and the grep says `clean`.

**If any Amp trailer IS present**, strip it by rebuilding that commit with `git commit-tree` (this bypasses the hook; `git commit --amend` would re-append it). For the tip commit:

bash:
```bash
git log -1 --format='%B' HEAD | grep -vE '^(Co-authored-by: Amp|Amp-Thread-ID:)' > /tmp/msg.txt
NEW=$(GIT_AUTHOR_NAME="$(git log -1 --format='%an' HEAD)" \
      GIT_AUTHOR_EMAIL="$(git log -1 --format='%ae' HEAD)" \
      GIT_AUTHOR_DATE="$(git log -1 --format='%aI' HEAD)" \
      GIT_COMMITTER_NAME="$(git config user.name)" \
      GIT_COMMITTER_EMAIL="$(git config user.email)" \
      git commit-tree "$(git rev-parse HEAD^{tree})" -p "$(git rev-parse HEAD^)" -F /tmp/msg.txt)
git update-ref "refs/heads/$(git symbolic-ref --short HEAD)" "$NEW"
```
If a non-tip commit is affected, `git rebase -i v<TAG>` and reword is not safe (the hook re-appends). Instead, redo the cherry-picks cleanly from step 3, or rebuild each affected commit with `commit-tree` walking parent-by-parent. Then re-run the verification grep and confirm `clean` before moving on.

### 6. Sanity-check the branch before pushing

bash:
```bash
git diff --name-only v<TAG>..HEAD | grep -E 'comfyui_version.py|pyproject.toml' && echo 'VERSION FILES TOUCHED - REMOVE' || echo 'no version files (good)'
# linearity: full range == first-parent range
diff <(git rev-list v<TAG>..HEAD | sort) <(git rev-list --first-parent v<TAG>..HEAD | sort) && echo 'linear (good)'
```
PowerShell:
```powershell
if (git diff --name-only v<TAG>..HEAD | Select-String 'comfyui_version.py|pyproject.toml') { "VERSION FILES TOUCHED - REMOVE" } else { "no version files (good)" }
$full = git rev-list v<TAG>..HEAD | Sort-Object
$fp = git rev-list --first-parent v<TAG>..HEAD | Sort-Object
if (($full -join ',') -eq ($fp -join ',')) { "linear (good)" } else { "NOT LINEAR - has merges" }
```
Optional: compile-check changed Python (`python -m py_compile <files>`).

### 7. Push and open PR

Push directly to `origin` (per workspace `AGENTS.md`, Comfy-Org repos get same-repo branches, not forks):
```
git push -u origin backport/vMAJOR.MINOR.PATCH-<topic>
```

Open the PR with `base: master` and the exact title. **Never set `$env:GITHUB_TOKEN` as a persistent session variable** on Windows (it pollutes Credential Manager); pass it inline and remove it.

bash:
```bash
export GITHUB_TOKEN=$(cat <path-to-githubtoken.txt>)
TITLE="ComfyUI backport release vMAJOR.MINOR.PATCH"
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Comfy-Org/ComfyUI/pulls \
  -d "$(jq -n --arg t "$TITLE" --arg h "backport/vMAJOR.MINOR.PATCH-<topic>" \
        '{title:$t, head:$h, base:"master", body:"Backport for vMAJOR.MINOR.PATCH."}')"
unset GITHUB_TOKEN
```
PowerShell:
```powershell
$env:GITHUB_TOKEN = (Get-Content "<path-to-githubtoken.txt>" -Raw).Trim()
$body = @{
  title = "ComfyUI backport release vMAJOR.MINOR.PATCH"
  head  = "backport/vMAJOR.MINOR.PATCH-<topic>"
  base  = "master"
  body  = "Backport for vMAJOR.MINOR.PATCH."
} | ConvertTo-Json
$resp = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/Comfy-Org/ComfyUI/pulls" `
  -Headers @{ Authorization = "token $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "User-Agent" = "amp" } `
  -Body $body
Remove-Item Env:\GITHUB_TOKEN
"PR #$($resp.number): $($resp.html_url)"
```
After creating the PR, confirm `Env:\GITHUB_TOKEN` is not lingering (`if (Test-Path Env:\GITHUB_TOKEN) { Remove-Item Env:\GITHUB_TOKEN }`).

### 8. Hand off

Tell the user: the PR number/URL, the derived version and release branch, the head SHA, and that you did NOT modify version files. Once checks are green, they (or you, if asked) dispatch the **Backport Release** workflow with the **full head SHA**. Do not push new commits after dispatch -- it invalidates the run against that SHA.

## Pitfalls that have burned us -- do NOT repeat

1. **Do not ask the user for the version or release branch.** They are auto-derived from the latest stable tag. Read them yourself (step 2). Only escalate if the latest tag looks wrong.
2. **Branch from the tag, not from `release/vX.Y`.** When the latest tag's patch is `0`, the release branch does not exist yet and branching from it fails. Branching from the tag always works.
3. **Keep history linear.** No merges from master, no off-first-parent commits -- the workflow rejects them and the fast-forward would fail. Cherry-pick onto the tag.
4. **Always verify no Amp trailers landed** (step 5), every time, even though cherry-pick usually does not add them. This must NEVER slip through. If present, fix with `git commit-tree`, not `git commit --amend`.
5. **Preserve original authors; do not `--reset-author`.** Only the committer should be you.
6. **requirements.txt will usually conflict** on dependency-bump commits. Apply only the bump the commit made; keep all other pins at the stable-tag base.
7. **Do not target the release branch with the PR.** Base must be `master`, or the "Validate PR exists" step fails with `No open PR found ... into 'master'`.
8. **Do not modify version files.** The workflow's "Bump version files" step owns `comfyui_version.py` and `pyproject.toml`.
9. **Do not force-push after CI starts or after deploy.** It orphans CI runs, invalidates a dispatch pinned to the old SHA, can dismiss reviews, and may break deployed test instances. Ask first.
10. **Never persist `$env:GITHUB_TOKEN`** in a PowerShell session -- pass inline and remove it, to avoid Credential Manager popups on later git commands.
11. **Do not poll comfy-runner job status for `"completed"`** when deploying a test instance -- the terminal status is `"done"`. (See the comfy-runner skill.)
