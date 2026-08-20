---
name: succeeding-yourself
description: "Hands a feature-owner Amp thread off to a fresh successor thread when the current one grows long, slow, or context-bloated. Use when the user says 'succeed yourself', asks for a context rollover or handoff, or the thread is degrading. The issue is the handoff document; the successor takes ownership with zero other ceremony."
---

# Succeeding Yourself

You are the outgoing thread. Your context is disposable; the feature is not.
Durable state lives in the canonical issue, the branch, and
`CURRENT-PRIORITIES.md` - never in this conversation. The whole rollover is
three steps: park the work, write one handoff comment, launch the successor.

## 1. Park the work safely

- Get the checkout to a resumable point: commit WIP to the feature branch
  (marked WIP if not review-ready) or stash with a named message. Leave the
  tree clean and record branch + HEAD commit.
- Do not merge, deploy, or rush anything just to finish before handing off.

## 2. Write the handoff comment on the canonical issue

One comment on the feature's issue containing everything a stranger needs:

- Current state: branch, HEAD commit, what is done and verified.
- Next steps, in order, with file paths.
- Gotchas and decisions already settled (so they are not relitigated).
- Validation commands and their last known result.
- Your thread ID (successors can `read_thread` you for detail).

## 3. Launch the successor

1. `list_runners`, then `create_thread` on the SAME runner and machine.
2. Give it the feature's label (issue slug) and a descriptive title.
3. The prompt must be self-contained: feature issue URL, checkout path,
   branch, the handoff comment's content or link, predecessor thread ID, and
   these successor duties:
   - confirm `hostname` + `pwd` before mutating anything;
   - read the canonical issue and the handoff comment;
   - update the feature's owner row in the workspace
     `CURRENT-PRIORITIES.md` to its own thread ID;
   - comment on the issue: "Owner thread is now T-... (succeeded T-...)";
   - label itself with the feature slug and set a descriptive title
     (standing user authorization);
   - continue as owner under the workspace `DELEGATION.md`.

## 4. Stand down

- Rename yourself with a `(superseded)` suffix; keep your feature label so
  the lineage stays visible in the dashboard.
- Reply to the user with the successor's thread URL, then do no further work
  on the feature. Answer questions if asked, but route new work to the
  successor.

## Rules

- Never run two active owners: the successor is the owner the moment its
  issue comment lands.
- No handoff markdown files, ledgers, or copies of conversation history; the
  issue comment is the entire handoff document.
- If you are a worker (not an owner), reply to your parent that you need
  succession instead of launching your own successor.
