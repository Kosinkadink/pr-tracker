---
name: delegation-orchestration
description: Coordinator/delegate workflow for multi-thread Amp development - long-lived ultra/high coordinator threads design and review while medium/low delegate threads implement on station runners. Use when orchestrating work across Amp threads, delegating an implementation slice to a runner thread, setting up a delegation ledger, reviewing delegate output, or recovering delegations after an orchestrator thread dies.
---

# Delegation Orchestration

Proven workflow (2026-07, Domfy backend/inference/frontend programs):
plan on an expensive tier, implement on a cheap tier, review on the
expensive tier. Multiple long-lived coordinator threads - one per
program of work - each delegate implementation to faster/cheaper
threads. Coordinators never implement slices inline when a delegate
can; expensive context is spent on design, specs, review, and
cross-thread contracts.

## Roles and tiers

- **Coordinator threads** (ultra or high): long-lived, one per program
  of work. They read roadmaps, plan slices, write delegation specs,
  review delegate output, and message each other. Their thread IDs are
  recorded in the target repo's AGENTS.md so peers and successors can
  find them.
- **Delegate threads** (medium or low): short-lived, one task each,
  running on a station runner. They implement exactly what the spec
  says, reply back with evidence, and end.
  - `low`: mechanical, bounded tasks - smoke tests, scripted checks,
    repo state reports.
  - `medium`: well-specified implementation slices where the design is
    already decided.
  - `high`/`ultra`: planning, review, judgment - normally the
    coordinator itself, not a delegate.

## One-time prerequisites

- An **Amp project** must exist for the repo (ampcode.com -> create
  project -> "existing repository"). Without it, `create_thread` fails
  with "Available Amp project refs: none". The project ref is
  organizational metadata only; the runner decides where code executes.
- A **live runner per station**: an Amp CLI process running in the
  station's workspace root. Runner names derive from hostname + station
  (e.g. `kosin-x570-aorus-ultra-station14`).

## Mechanics

- Call `list_runners` immediately before creating a thread - runners
  are ephemeral; never reuse stale results.
- `create_thread` with `executor: "runner"`, the `runner_id`, the
  repo's project ref, and the `agent_mode` for the role.
- Runner threads execute **locally** on the runner's machine with full
  access to that machine's checkouts, venvs, and GPUs (an orb is a
  cloud sandbox that sees none of that - never use orbs for station
  work).
- Pick exactly **one** result channel: instruct the delegate to reply
  to the coordinator thread when done or blocked. Never also
  `wait_for_threads` on a thread that was told to reply.

## Sidebar visibility and archival (user-facing tracking)

The user tracks delegation from the Amp TUI sidebar, which shows the
threads of the session they are watching. Standing directive
(2026-07-27):

- **Create delegate threads on the coordinator's own station runner**
  (the session the user watches) so they appear in that sidebar. The
  runner's working directory does not constrain where work happens:
  the delegate prompt directs all commands at the delegate station's
  clone by ABSOLUTE path, so execution still lands in the right tree.
- **Archive settled delegate threads** (`thread_interact` action
  `archive`) once their work is reviewed and their ledger row is
  closed AND the next wave of delegations is starting - the sidebar
  then shows only current work. Never archive a thread whose row is
  still open or whose diff has not been reviewed; the ledger row (not
  the thread's archive state) is the durable record either way.

## Writing the delegation prompt

Delegates have zero context from the coordinator's conversation. The
prompt must be self-contained:

1. **Reply contract**: the coordinator thread's ID and the exact
   evidence the reply must contain - commit hash, pushed or not, exact
   gate pass counts, measurement outcomes, review findings, deviations
   from spec.
2. **Setup**: absolute working directory, expected git baseline
   (commit hash), pull instruction, environment bootstrap steps. Pull
   the STATION WORKSPACE ROOT first (the wrapper repo), then the
   nested target repo - the wrapper carries AGENTS.md and skill
   updates, and a stale wrapper leaves the delegate without them.
3. **The design, fully decided**: exact files, APIs, semantics, and
   edge-case rules. Coordinators design; delegates implement. A prompt
   that says "figure out the right approach" is a coordinator shirking
   its job.
4. **Grounding pointers**: file paths and line ranges for every piece
   of existing code the design leans on, so the delegate verifies
   instead of guessing.
5. **Tests and gates**: what to test, which gate commands must be
   clean, and the target repo's discipline (its AGENTS.md, ledger
   rules, review-before-commit).
6. **Constraints**: what NOT to touch, no new dependencies, ASCII
   punctuation, any ownership boundaries with other threads.
7. **Escape hatch**: if the spec contradicts the actual code, stop and
   reply with the contradiction instead of improvising a different
   design.

## Delegation ledger (durability across coordinator loss)

Each target repo keeps a durable ledger of its delegations (e.g.
`docs/DELEGATION-LEDGER.md`), committed and PUSHED on every mutation:

1. A row goes in BEFORE the delegate starts (thread ID - use PENDING
   until `create_thread` returns, then replace and push immediately -
   one-line task, expected deliverable, status open). A delegation
   known only to a possibly-dying thread's context is a delegation
   lost.
2. On landing, the row flips to `done` with the resulting commit
   hash(es), pushed. Abandoned or superseded work flips to `abandoned`
   with a one-line reason. Rows are never deleted.
3. The CURRENT coordinator thread ID is pinned at the top of the
   ledger.
4. Takeover procedure for a successor coordinator: update the pointer
   (and any peer-facing pointers in AGENTS.md), commit, push FIRST,
   then check every `open` row via read_thread/preview - delegates
   reply to the thread that spawned them, so completion messages route
   to the dead thread and the successor must pull each open delegate's
   state proactively.

## Station etiquette

- Delegate work into a checkout that is **not** in use by another
  thread. Fixed station assignments per coordinator prevent two
  coordinators racing one clone; check the target repo's delegation
  ledger for open rows on a station before delegating anywhere new.
- **Per-delegate clones (delegates folder)** - preferred when slices
  can run in parallel or a shared station clone would be contended:
  the prompt directs the delegate to create
  `stations/<station>/delegates/<slice-id>/` and fresh-clone the
  target repo inside it (proven by the Domfy-Frontend program, e.g.
  `station11/delegates/slice63-memoryviz/`). Each delegate owns its
  clone outright: no tree contention, a known-clean baseline verified
  against origin/main at start, and parallel delegates on one station
  stay isolated. Name the folder after the ledger row/slice id.
  Delegates still sync only through origin (clone from origin, push
  only where authorized). When the slice settles and its row is
  closed, the folder is disposable; the delegate or coordinator may
  remove it, and any folder left behind must be a clean checkout.
- Stations are independent clones that sync only through origin:
  delegates commit (and, where the repo grants standing authorization,
  push) to origin main; coordinators pull-rebase. A delegate must
  leave its station's tree clean so the next delegation starts from a
  known state.

## Review (coordinator, after the delegate reports)

Delegate reports are claims, not proof. The coordinator must:

- Pull the pushed commit and review the **actual diff**, not the
  report's summary of it.
- Verify every API or behavior the new code leans on exists and works
  as claimed (grep the real code; do not trust the report's citations).
- **Rerun the gates independently** on the coordinator's own checkout.
- Confirm ledger/doc updates landed in the same commit per the target
  repo's discipline.
- Only then flip the ledger row, archive per the archival rule, and
  report the slice as done.
