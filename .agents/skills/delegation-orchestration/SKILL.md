---
name: delegation-orchestration
description: Feature-owner delegation for multi-thread Amp development under the workspace DELEGATION.md. Use when owning a feature end to end, launching machine-local worker or verifier threads, keeping issue and PR evidence, or handing a feature to a fresh thread.
---

# Delegation Orchestration

The workspace `DELEGATION.md` is the coordination policy and wins over this
skill wherever the two differ. This skill is the owner's working checklist
for that policy. Coordination is three persistent threads: the desk (talks to
the user, files issues with acceptance criteria, rules on decisions), the
dispatcher (creates and succeeds owner threads, keeps `CURRENT-PRIORITIES.md`
and `RUNNERS.md`), and the integrator (lands finished pull requests, resolves
merge conflicts, may push to owner branches, owns red main). Owners never
merge to main and never merge main into a pull request that is waiting to
land; the integrator does both.

## Feature ownership

One thread owns one feature issue until it closes. The owner posts a plan on
the issue before coding, implements on one branch in its own lane, runs the
repository's fast gates, commissions a fresh-context verifier against the
issue's acceptance criteria, and on `VERDICT: PASS` adds the label
`ready-to-land` to the pull request. Landing is that label, not a message.
The owner then starts its next item; the integrator lands the pull request
and closes the issue.

Routine work needs no approval: branches, commits, pushes, draft pull
requests, issue comments, worker and verifier threads. Message the
dispatcher only for a blocker or a finding it must act on (a lost thread, a
machine problem). Design questions that need the user become `decision`
issues, never chat.

An owner never narrows its posted plan, never marks scope "later" or
"follow-up", and never closes an issue around a gap; only the user re-scopes.
Defects found outside the accepted scope get their own issues with measured
evidence and checkable acceptance criteria.

## Message rules

- Use `queue_thread_message` for every report between threads; it is a
  global User plugin (call `reload_plugins` if missing). Set `steer` true
  only for stops and corrections. Never use `send_thread_message` for a
  report; it interrupts the recipient.
- Every brief for another thread contains, with the recipient ID filled in:
  "Report via `queue_thread_message` to thread `T-...`;
  `send_thread_message` is forbidden for reports because it interrupts the
  recipient". Grep the brief for both before sending.
- Never write "steer: false" or any steer marker in a message body.
- Every instruction states its API precondition (exact PR head or main SHA)
  and the recipient checks it before acting.
- End every turn within 30 minutes; run long commands in the background so
  queued messages arrive. Pushes, plans and progress are visible on GitHub
  and are never messaged.
- Report to the thread that briefed you, never to the desk or the user
  directly unless the brief names them.

## Launching workers and verifiers

Owners are top-level threads with thread-creation tools. Two identical
global plugins provide `spawn_thread` and `spawn_thread_alt`; Amp hides a
plugin's own tool inside the threads that plugin creates, so a thread has
whichever one did not create it. Use whichever is present with
`link_parent` false so the child keeps its own creation tools (the child
then holds the other one). If neither is present, call `reload_plugins`
once and quote the tool list to the dispatcher if both are still missing.
`executor: orb` and `executor: runner` are refused for tool-spawned
threads, so work on another machine goes to that machine's persistent
machine worker (listed in `RUNNERS.md`) by `queue_thread_message`. Use Task
for a bounded fresh-context subagent that needs no thread of its own.

1. Use a worker only for real parallelism or context isolation; otherwise do
   the work yourself. Workers and verifiers are `low`; a medium worker needs
   a one-line reason in the plan. Nothing an owner creates runs above medium.
2. Write a self-contained brief: goal, repository, exact base and branch,
   lane path, constraints, exact commands, non-goals, the reporting sentence
   above, and "send one consolidated reply when done".
3. A verifier is fresh-context and has not seen the implementation
   conversation. Give it the issue link, branch, exact 40-hex head,
   acceptance criteria and a deleted-tests diff against the merge base. It
   posts `VERDICT: PASS - <head>` or `VERDICT: FAIL - <head>` on the wrapper
   issue; packet hygiene goes under `PACKET:` lines, never as a FAIL.
4. From the verification request until the verdict, push nothing to the
   branch; a push voids the verdict. After the second FAIL on one pull
   request, stop and let the dispatcher open a `decision` issue.
5. Verify a worker's diff and rerun its checks yourself before freezing a
   head that includes it.

## Accountability

- Committed means pushed: every commit reaches `origin` within the turn that
  made it. Heads are 40-hex SHAs pasted from `git rev-parse HEAD` or the API.
- Pull request body line 1: `Refs Kosinkadink/comfy-vibe-station#N`; no
  closing keyword; body carries what the diff does, evidence and the
  finished `TESTED.md` row. The integrator squash-merges and closes the
  issue.
- Cross-repository pins point at a landed main SHA the change is compatible
  with; never re-pin because a newer main exists.
- Never dispatch, rerun or cancel GitHub Actions workflows; never touch
  Actions secrets or deploy keys. Public repositories run hosted runners only.
- Evidence goes on issues, never as files committed to code repositories.

## Safety

- Confirm `hostname` and `pwd` once per session before mutating anything.
- Work only in your own lane under `lanes/`; never touch another thread's
  checkout, branch, service, port or process. Never edit the runner root's
  nested checkouts.
- GPU work on shared machines runs inside `flock ~/gpu-claims/gpuN.lock`;
  wait for holders, never kill them. RipperPC GPU0 is reserved for the user.
- Never print credentials; scope tokens to the single command that needs
  them. Never override Git identity.

## Continuity

When you grow long, slow or context-bloated, or the dispatcher says so, load
`succeeding-yourself`. The issue plus its dependency verdicts are the handoff
document. If you are a worker, ask your parent for succession instead of
launching your own successor.
