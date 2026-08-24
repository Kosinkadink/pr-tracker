---
name: delegation-orchestration
description: Minimal feature-owner delegation for multi-thread Amp development. Use when owning a feature end to end, launching machine-local worker or reviewer threads, keeping issue and PR evidence, or handing a feature to a fresh thread.
---

# Delegation Orchestration

One thread owns one feature end to end. The workspace `DELEGATION.md` is
authoritative when present. There is no Ops Desk, integrator, continuity
monitor, broker role, schedule, or succession protocol. The user is the only
approver and the only escalation point.

## Feature ownership

The owner investigates, implements, tests, reviews, merges, deploys, and
live-verifies its feature. Routine work needs no approval from anyone:
branches, commits, PRs, issue updates, merging after one independent review
passes, and deploying feature-dedicated services with a stated rollback plan.

Escalate to the user only for: destructive or shared-infrastructure actions;
the user's personal machines, services, money, or legal exposure; a genuinely
ambiguous product decision; and the final done/blocked report.

### Intake: becoming a feature owner

When the user brings a new idea to you, hop into the system yourself:

1. Clarify scope with the user until acceptance criteria are clear.
2. Create the canonical issue in the owning repo (scope, acceptance criteria,
   non-goals).
3. Add one owner row to the workspace `CURRENT-PRIORITIES.md` (feature, issue
   link, your own thread ID).
4. Label yourself with the feature slug and set a descriptive title:
   `amp threads label <own-id> <slug>` and `amp threads rename <own-id>
   "<title>"` (standing user authorization).
5. Proceed as owner. No registration anywhere else.

## Message rules

- Report results directly to the user in your own thread, as visible text.
- When relaying a user message to another thread, quote it in full, unedited,
  marked `VERBATIM USER MESSAGE`. Never paraphrase or filter the user.
- Workers reply to their parent through exactly one channel: one consolidated
  completion or blocked message. Never combine reply-back with
  `wait_for_threads`.
- Never write "steer: false" (or any steer marker) in a message body. No
  steering control exists on thread messages; the old thread_interact tool
  that honored that flag is gone, and the marker is dead text. Minimize
  disruption instead: batch progress into one consolidated message per
  milestone, put routine status in issue comments, and message a thread only
  when it must act on or reply to something.
- Nothing fires on a timer: no schedules, dues, or periodic audits.

## Launching workers

Use a worker only for real parallelism or context isolation; otherwise do the
work yourself.

1. Call `list_runners` immediately before `create_thread`; runner IDs are
   ephemeral.
2. Launch on the live runner of the machine whose files the worker touches.
   Never an orb for station work. Fresh clone per concurrent worker.
3. Create every worker with a label naming the feature's issue slug (for
   example `domfy-30`) and a descriptive title, so the delegate tree is
   discoverable via `find_thread label:...` and the dashboard (standing user
   authorization for these labels). Delegates are never hidden.
4. No SSH, remote filesystems, or cross-machine runtime dependencies.
5. Write a self-contained prompt: goal, repo, exact base, branch, constraints,
   tests, non-goals, and "send one consolidated reply when done".
6. Verify the worker's diff and rerun the checks yourself before merging.

An independent reviewer is read-only, receives exact commits and paths, and
returns concrete findings. A source author never reviews its own work.

## Accountability

- One issue per feature in the owning repo: scope, acceptance criteria, and
  evidence comments. No separate ledgers, labels taxonomies, or priority rows.
- Same-repo branches and PRs, squash-merged by default (one commit per PR on
  main). `Refs #N` while work remains; `Closes #N` when merge finishes it.
- No bookkeeping or reconcile commits; status goes in issue comments.

## Safety

- Confirm `hostname` + `pwd` once per session before mutating anything, and
  again after an executor change.
- Do not touch another thread's checkout, branch, service, port, or process.
- Rollback plan before any deploy. User-reserved resources and user-owned
  services stay untouched without explicit user permission.
- Retired machines stay retired.

## Continuity

When you grow long, slow, or context-bloated (or the user says "succeed
yourself"), load the `succeeding-yourself` skill and roll over to a fresh
successor thread. If a thread dies outright: start a fresh thread, point it
at the issue and PR, and note the new owner thread on the issue. The issue is
the handoff document; nothing else is required.
