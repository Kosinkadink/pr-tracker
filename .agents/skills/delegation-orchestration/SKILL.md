---
name: delegation-orchestration
description: Orchestrates autonomous whole-feature ownership for multi-thread Amp development. Use when assigning or adopting a complete feature and canonical issue, launching machine-local internal delegates or independent reviewers, maintaining issue and PR evidence, verifying merge readiness, or preparing feature-scoped succession.
---

# Delegation Orchestration

One long-running autonomous feature owner owns each complete user-visible
feature and canonical issue from source discovery through live acceptance.
Delegation changes execution capacity, not accountability. The workspace
`DELEGATION.md` and `COORDINATION-POLICY.md` are authoritative when present.

## Feature-owner contract

A complete feature assignment authorizes the owner to:

1. Investigate source, tests, history, issue/PR evidence, and runtime behavior.
2. Revise inherited plans when direct evidence contradicts them, within the
   accepted feature scope and safety boundaries.
3. Design and implement across linked repositories through isolated,
   machine-local work and internal delegates.
4. Run authorized tests, benchmarks, reproductions, proof, and acceptance.
5. Commission independent review, fix findings, and verify delegate claims.
6. Push routine same-repository branches, create/update draft PRs, and maintain
   canonical issue lifecycle/evidence without repeated approval.
7. Coordinate authorized deployment with the service custodian and own live,
   visual, physical, and cleanup acceptance.

Routine bootstrap, MATRIX-GO, stage-GO, micro-slice portfolio planning,
per-stage approval, and progress phone-home are not required. The feature owner
contacts the integrator or Ops Desk only for a consequential product decision,
a need for new destructive, shared-infrastructure, safety, security, legal,
privilege, cost, or user-owned-service mutation authority, a true external
blocker needing coordinator action, merge readiness, a deployment incident, or
final live completion.

Outside standard path A below, merge and deployment remain separately
controlled. Destructive/shared-infrastructure action, mutation of a user-owned
service, and new legal or cost authority always remain separately controlled.

Already-authorized resource and service operations route to the applicable
machine/service custodian. Requests for new authority route to the integrator
or Ops Desk.

## Standard delivery path A

For future feature changes, the integrator may proceed without another
per-change A/B/C decision only when the exact merge-ready source is independently
reviewed with no unresolved actionable findings, exact-source checks bind the
reviewed commit/tree and clean deployment source, a bounded deployment plan
names dedicated service ownership, health/live acceptance is explicit, and a
named owner has an explicit rollback plan/artifact and authority to use it.

The sequence is merge -> scoped deployment by the service custodian -> health
and live acceptance -> rollback on failure. Ordinary source or feature
ownership is insufficient service authority. Missing conditions require the
integrator to obtain the missing decision or authority first.

Path A never authorizes destructive/shared-infrastructure changes, unrelated or
user-owned service mutation, history rewrites, dirty/unreviewed source,
deployment without rollback, or new legal/cost authority.

## Role boundaries

- **Feature owner**: owns the complete feature, canonical issue, linked
  branches/PRs, delegates, reviews, verification, deployment coordination, and
  live acceptance.
- **Program integrator**: owns feature assignment/adoption, cross-feature
  conflicts, independent merge-readiness verification, issue-to-PR evidence
  reconciliation, and feature succession. It is not a routine delegate router,
  slice planner, or stage approval queue.
- **Ops Desk**: is the separate user-facing decision/status surface. It does
  not code, merge, dispatch routine work, or control machines. It is exempt
  from time-based rotation.
- **Machine/service custodian**: controls direct executor identity, GPUs,
  ports, persistent or user-owned services, and exclusive-resource safety. It
  does not own routine feature source work.
- **Internal delegate/reviewer**: works for one feature owner in a fresh
  checkout local to the runner of the machine whose files or resources it uses
  and reports only to that owner through one reply channel with `steer: false`.

## Executor and checkout invariants

Before any repository, service, or process mutation, directly record and
compare the shell's hostname, primary LAN IP, cwd, and relevant GPU identities
with the workspace fleet map plus the task's explicit expected identity tuple.
That tuple states expected hostname, primary LAN IP, cwd root, and relevant GPU
model, UUID, and count. Repeat after executor reconnect/replacement or a
tool-lease/executor change. Runner names, `list_runners`, broker presence, role
labels, and thread metadata are routing hints, not identity proof.

Stop on mismatch. Never substitute SSH, a remote filesystem, cross-machine
checkout, cross-machine runtime dependency, another station, or retired
machine. Preserve user-reserved resources and custodian authority. Never use
an orb for station work.

Concurrent threads use separate local checkouts, preferably fresh clones under
the target machine station's `delegates/` folder. A primary-machine feature
owner may launch a worker on another machine's correct live runner when that
machine owns the affected repository, files, or resources. The owner never uses
SSH, a remote filesystem, or a cross-machine runtime dependency to access that
worker or checkout. No owner or delegate mutates another active owner's
checkout, branch, process, service, port, GPU, or uncommitted artifact. There
are no cross-machine holds.

## Creating an internal delegate or reviewer

Use a delegate only when it gives concrete parallelism or context isolation.
The feature owner may also implement directly; it chooses decomposition.

1. Call `list_runners` immediately before `create_thread`; runner IDs are
   ephemeral.
2. Launch on the correct live runner of the machine whose repository, files, or
   resources the worker uses, never an orb.
3. Use a fresh checkout local to that runner and an exact public base.
4. Pick exactly one result channel. Require a reply to the feature owner with
   `steer: false`; never also call `wait_for_threads` for that worker.
5. Archive only after the result is independently reconciled and its durable
   execution record is closed.

Routine source-only delegation requires no machine/service custodian approval.
Identify the custodian and existing authority before a concrete GPU, service,
port, persistent-process, or exclusive-resource operation.

An independent reviewer is read-only. It receives immutable commit SHAs/ranges,
exact paths, the canonical issue acceptance contract, and a request for
concrete actionable findings. It does not fix its own findings unless assigned
a separate correction task.

## Writing the prompt

Internal workers have no feature-owner conversation context. Include:

1. The canonical issue, feature owner thread, bounded outcome, and terminal
   evidence required in the `steer: false` reply.
2. The expected hostname, primary LAN IP, cwd root, and relevant GPU model,
   UUID, and count for direct executor attestation, plus the absolute local
   checkout, exact base/branch, public remote, and environment bootstrap.
3. Source grounding, accepted behavior, safety/resource boundaries, and files
   or evidence in scope.
4. Tests, benchmarks, review checks, and exact acceptance criteria.
5. Explicit non-goals and forbidden actions/resources.
6. An escape hatch: report a source contradiction rather than silently widen
   product scope or authority.

The feature owner may revise the plan after source discovery without stage
approval unless a revision crosses an escalation boundary.

## Durable accountability

Each independently shippable outcome has exactly one canonical issue in its
owning repository, even when it requires linked PRs in multiple repositories.
Internal slices, broker topics, priority rows, and delegation ledgers are
evidence and execution lineage, not competing product parents.

Every issue records the owner, scope/non-goals, dependencies, acceptance, and
closure evidence, with exactly one lifecycle label: `status: planned`,
`status: queued`, `status: active`, `status: blocked`, `status: landed`,
`status: deployed`, or `status: live-verified`.

The owner updates lifecycle and evidence truthfully. Substantive work defaults
to same-repository branches and PRs. Use `Refs #N` while acceptance remains and
`Closes #N` only when merge completes all criteria. Planning, delegation,
review, a commit, or a PR alone does not close an issue.

Where a repository maintains a delegation ledger, record internal execution
under the feature's canonical issue. Do not create duplicate slice issues
unless the slice is independently shippable.

## Owner review and integrator gate

Delegate and reviewer reports are claims, not proof. The feature owner:

1. Inspects the actual diff/evidence and verifies referenced contracts.
2. Reruns applicable checks in its isolated checkout.
3. Fixes every actionable independent-review finding.
4. Reviews full diffs against exact public bases and reruns affected/full gates.
5. Updates draft PRs and the canonical issue with immutable evidence.

At merge readiness, the integrator independently verifies immutable commit
SHAs and reconciles the issue, linked PRs, review receipt, checks, and remaining
acceptance. Independent review may gate landing but not unrelated feature work.

## Feature continuity and succession

Prepare a soft handoff at any threshold:

- 600 messages;
- 2 compactions;
- 7 active days; or
- 1 context-loss incident.

Soft preparation inventories the canonical issue, owner generation, inbox and
decisions, branches/commits/PRs, checkouts, delegates/reviewers,
services/resources, tests/evidence, uncommitted artifacts, blockers, and next
acceptance action. It does not automatically rotate a healthy owner.

Feature-scoped succession is mandatory at any threshold:

- 1,200 messages;
- 5 compactions;
- 14 active days, unless merge readiness is expected within 24 hours;
- 2 context-loss incidents;
- explicit inability; or
- error or runner-missing for 24 hours plus 2 missed checkpoint intervals.

Freeze new work, ready the successor on the correct machine with read-only
attestation, transfer only the affected feature, and reconcile every checkout,
branch, commit, PR, delegate, service/resource, artifact, and issue receipt.
The successor adopts existing work without duplication and never reopens
unrelated machine roles or features. Integrator succession remains separate.

The future broker design must use feature-scoped generations and CAS so stale
generations cannot mutate ownership. Current harness support does not provide
that guarantee; it is a later additive dependency under a separate issue/PR.
Until then, canonical issues, immutable commits, local inventories, and explicit
Amp handoff messages are the succession source of truth.
