---
name: delegation-orchestration
description: "Owns Dinkster features from issue plan through verification and landing. Use when acting as a feature owner or commissioning workers and verifiers."
---

# Feature owner

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- A feature has one owner of record until its issue closes. Owners plan, implement, commission workers/verifiers, integrate, test, freeze, obtain PASS, label, land and continue. They own one machine and their own lane. Any listed runner is eligible, but new work uses only X570 or 270K-Plus2; LesserRipperPC gets none while it has no CUDA. X570 owners send full suites, browser suites, real-stack engines and byte comparisons to a bounded machine worker on 270K-Plus2 (64 GB), preserving preview ports 5199/8765. Work needing X570 hardware stays there, one such job at a time. Whoever starts an engine, suite, container, database or service stops and removes it when its work ends; nothing stays running between steps.

- Owners are top-level threads with creation tools. The desk uses a spawn plugin with `link_parent` false; `create_thread` creates linked children, not owners. An owner lacking `create_thread` and both spawn tools is replaced by the desk. `spawn_thread` and `spawn_thread_alt` are equivalent global User plugins; the creating plugin hides its own tools, so use the other. If neither exists, call `reload_plugins` once and quote the tool list before reporting a defect. Tool-spawned threads cannot select `executor: orb` or `executor: runner`; send other-machine work to that machine's worker with `queue_thread_message`.

## Feature lifecycle

- Plan before code: post units, worker assignments and the command/observation proving each criterion. Every criterion is assigned.

- Shared-file claims are not posted; mention overlap once in the plan or ask the integrator to sequence landings. Maintain one edited progress table on the issue, with at most one short progress comment daily or when blocked, not per push. Every posted status row/comment has `Remaining:` naming unmet acceptance bullets by number, measured scope and next item (registry: `N absent / M differing of K`).

- Verify: development pushes have no per-push gates or receipts. Run touched tests while developing; once offering a head for landing, run applicable format/lint/types, hosted checks and a fresh low no-carry verifier concurrently. Mark the PR ready for review in the freeze turn; return it to draft on resumed development. No freeze receipt or full-validation dispatch is needed. Repository "before any commit" checks mean before freeze. Commission the verifier immediately on the pushed frozen head, without waiting for GPU/numerical evidence. Every smoke/packet wrapper is tracked in a Kosinkadink repository and its exact head is on the issue. See "Testing and CI" for gates and "Verdicts and carries" for verdicts.

## Testing and CI

- During service setup, owners may create/rotate/delete Actions secrets and deploy keys their issue needs, recording names, never values; authority after setup is not ruled. Identity and its dependent publisher-sign-in work may set repository variables, rerun failed workflows and deploy, recording each action. The official pack publication owner may dispatch catch-up for main-declared versions missing from the public registry and records result.

- A PR check caused by an external service may be rerun once only after the owner records job, measured outside cause and evidence it is gone. It is not verifier FAIL; a second failure belongs to the PR until measured otherwise. This never permits main full-validation reruns.

- An intermittent test may be rerun once when it is the PR's only red, the diff touches neither the test nor exercised code, and the test has passed on main. Record job/evidence on the issue and file an intermittent-failure issue with the code's owner, or link the open one, before rerunning the failed job. If it fails again, the PR waits for that issue's fix. This exception covers PR checks only, not main full validation.

## Owner liveness and remaining scope

- Registry/census owners post measured comparison command, main SHA and `N absent / M differing of K` every twelve hours or ten landings, whichever first. Desk reports latest count and age, marks older counts stale and asks for a refresh that wake. Landing counts, main CI and PR activity are not owner progress.

## Schedules and wake budgets

- Freeze a whole unit after at most five bounded behavior heads offered for PR verification; ordinary development pushes do not count. After five, freeze or ask the desk to split with new criteria. Issue comment cap 2,500 or PR body near 262,144 characters means stop, post a one-screen summary and ask the desk to split, not open a continuation yourself.

- Use `succeeding-yourself` when the thread degrades (slow, loses state, repeats work or rising per-turn cost); 2,000 messages is an additional backstop unless the user sets another. Handoff only at a PR landing/issue closure, not mid-PR. The desk orders it for those conditions, not message count below the backstop.

- [The first-party pack owner](https://github.com/Kosinkadink/comfy-vibe-station/issues/638) and its successors run high under the user's existing role authorization. When it has doable work, a turn ending with a push gets one immediate `COUNT=1` wake within a minute (or desk-equivalent), without a comment/Remaining requirement. The same push-only chaining applies to desk-authorized owners, beginning with [the compositor owners](https://github.com/Kosinkadink/comfy-vibe-station/issues/645). Wait backstops are unchanged.

## Decisions

- Kosinkadink tags/releases/publication and required official pack version bumps are preapproved, never user decision issues. Owner bumps required versions in its PR and records exact landed SHA/version/tag and approved carried pins on the issue; desk decides publishing time under "Repositories and branches".
