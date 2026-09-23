---
name: succeeding-yourself
description: "Hands a feature-owner Amp thread off to a fresh successor thread when the current one grows long, slow, or context-bloated. Use when the user or dispatcher says 'succeed yourself', asks for a context rollover or handoff, or the thread is degrading. The issue plus its dependency verdicts are the handoff document."
---

# Succeeding Yourself

You are the outgoing thread. Your context is disposable; the feature is not.
Durable state lives in the canonical issue, the branch, the verifier verdicts
and `CURRENT-PRIORITIES.md` - never in this conversation. The rollover is
three steps: park the work, write one handoff comment, launch the successor.

## 1. Park the work safely

- Commit and push the work in progress to the feature branch; leave the tree
  clean and record branch plus the 40-hex HEAD from `git rev-parse HEAD`.
- Do not merge, freeze a head, or rush anything to finish before handing off.

## 2. Write the handoff comment on the canonical issue

One comment on the feature's issue containing everything a stranger needs:

- Current state: branch, HEAD, pull request URL and head, lane path, what is
  done and verified, the last verifier verdict link.
- Closed dependencies: for every closed issue this issue names as a
  dependency or your plan cites, its number, verdict link and one-line
  result, and the questions those results settled so the successor does not
  reopen them. A successor re-investigating a closed result is the failure
  this list prevents.
- Next steps, in order, with file paths.
- Validation commands and their last known result.
- Your thread ID.

## 3. Launch the successor

1. Use `spawn_thread` with `link_parent` false on your own runner, at the
   same tier you run at (never above medium). If `spawn_thread` is missing,
   call `reload_plugins` once; if it is still missing, message the
   dispatcher for succession instead.
2. The prompt is self-contained: feature issue URL, lane path, branch, the
   handoff comment link, predecessor thread ID, the dispatcher thread ID,
   and the sentence "Report via `queue_thread_message` to thread
   `T-<dispatcher>`; `send_thread_message` is forbidden for reports because
   it interrupts the recipient". It lists these successor duties:
   - confirm `hostname` and `pwd` before mutating anything;
   - read the canonical issue, the handoff comment and every listed verdict;
   - update the feature's owner row in the workspace
     `CURRENT-PRIORITIES.md` to its own thread ID;
   - comment on the issue: "Owner thread is now T-... (succeeded T-...)";
   - continue as owner under the workspace `DELEGATION.md`.
3. Grep the prompt for `send_thread_message` and the dispatcher ID before
   sending; do not send a prompt lacking either.

## 4. Stand down

- Rename yourself with a `(superseded)` suffix.
- Queue the dispatcher one message with the successor's thread URL so it can
  archive you, then do no further work on the feature.

## Rules

- Never run two active owners: the successor is the owner the moment its
  issue comment lands.
- No handoff markdown files, ledgers, or copies of conversation history; the
  issue comment is the entire handoff document.
- If you are a worker (not an owner), reply to your parent that you need
  succession instead of launching your own successor.
