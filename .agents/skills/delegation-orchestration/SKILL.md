---
name: delegation-orchestration
description: "Owns Dinkster features from issue plan through verification and landing. Use when acting as a feature owner or commissioning workers and verifiers."
---

# Feature owner

Read shared DELEGATION.md first for cross-role contracts; load this policy only when acting as owner.

## Roles

- Owners, workers, verifiers and security-gap probes use `openai/gpt-6.1-sol`, never Anthropic. Owners set this model explicitly on every created thread, not by inheritance.

- One owner of record plans, implements, commissions workers/verifiers, integrates, tests, freezes, obtains PASS, labels, lands and continues until issue closure, in its own machine/lane. Machine assignment and service/lane cleanup follow shared Machines and safety.

- Owners are top-level with creation tools; desk spawning/replacement follows `coordinating-programs`. `create_thread` makes linked children, not owners. Equivalent global User plugins `spawn_thread`/`spawn_thread_alt` hide their own tools in created threads, so use the other. If neither exists, `reload_plugins` once and quote tool list before reporting a defect. Tool-spawned threads cannot select `executor: orb`/`executor: runner`; queue other-machine work to that machine's worker with `queue_thread_message`.

- Create workers and fresh-context verifiers at low on the owner's runner; a medium worker needs a one-line reason in the plan. Nothing above medium without the user's quoted authorization under the desk tier rule.

## Feature lifecycle

- The owner of record fixes missing parallel owners or units in the issue owner block.

- Before code, post units, worker assignments and commands/observations proving every criterion; assign each criterion.

- Shared-file claims are not posted; mention overlap once in the plan or ask the integrator to sequence landings. Maintain one edited progress table on the issue, with at most one short progress comment daily or when blocked, not per push. Every posted status row/comment has `Remaining:` naming unmet acceptance bullets by number, measured scope and next item (registry: `N absent / M differing of K`).

- Verify: development pushes have no per-push gates or receipts. Run touched tests while developing; once offering a head for landing, run applicable format/lint/types, hosted checks and a fresh low no-carry verifier concurrently. Mark the PR ready for review in the freeze turn; return it to draft on resumed development. No freeze receipt or full-validation dispatch is needed. Repository "before any commit" checks mean before freeze. Commission the verifier immediately on the pushed frozen head, without waiting for GPU/numerical evidence. Every smoke/packet wrapper is tracked in a Kosinkadink repository and its exact head is on the issue. See "Testing and CI" for gates and "Verdicts and carries" for verdicts.

## Testing and CI

- During service setup, owners may create/rotate/delete Actions secrets and deploy keys their issue needs, recording names, never values; authority after setup is not ruled. Identity and its dependent publisher-sign-in work may set repository variables, rerun failed workflows and deploy, recording each action. The official pack publication owner may dispatch catch-up for main-declared versions missing from the public registry and records result.

- A PR check caused by an external service may be rerun once only after the owner records job, measured outside cause and evidence it is gone. It is not verifier FAIL; a second failure belongs to the PR until measured otherwise. This never permits main full-validation reruns.

- An intermittent test may be rerun once when it is the PR's only red, the diff touches neither the test nor exercised code, and the test has passed on main. Record job/evidence on the issue and file an intermittent-failure issue with the code's owner, or link the open one, before rerunning the failed job. If it fails again, the PR waits for that issue's fix. This exception covers PR checks only, not main full validation.

## Messages and reporting

- Queue the design thread only for a finished look ready for review (dark pictures and their head), one blocking design-ruling question per note, or a built correction it requested with the showing picture. Progress, partial evidence, tests/gates, plans, ruling receipts and fixtures go on the issue only. Never send a "no reply needed" note.

## Owner liveness and remaining scope

- Registry/census owners post measured comparison command, main SHA and `N absent / M differing of K` every twelve hours or ten landings, whichever first. Desk freshness/reporting duties follow `coordinating-programs`. Landing counts, main CI and PR activity are not owner progress.

## Schedules and wake budgets

- Freeze a whole unit after at most five bounded behavior heads offered for PR verification; ordinary development pushes do not count. After five, freeze or ask the desk to split with new criteria. Issue comment cap 2,500 or PR body near 262,144 characters means stop, post a one-screen summary and ask the desk to split, not open a continuation yourself.

- Use `succeeding-yourself` when the thread degrades (slow, loses state, repeats work or rising per-turn cost); 2,000 messages is an additional backstop unless the user sets another. Handoff only at a PR landing/issue closure, not mid-PR. The desk orders it for those conditions, not message count below the backstop.

- [The first-party pack owner](https://github.com/Kosinkadink/comfy-vibe-station/issues/638) and its successors run high under the user's existing role authorization. When it has doable work, a turn ending with a push gets one immediate `COUNT=1` wake within a minute (or desk-equivalent), without a comment/Remaining requirement. The same push-only chaining applies to desk-authorized owners, beginning with [the compositor owners](https://github.com/Kosinkadink/comfy-vibe-station/issues/645). Wait backstops are unchanged.

## Decisions

- After each stable tag, post exact obsolete dev versions for user web deletion on PyPI, never pinned ones; delete, do not yank, only after one more stable release exists.

- Kosinkadink tags/releases/publication and required official pack version bumps are preapproved, never user decision issues. Owner bumps required versions in its PR and records exact landed SHA/version/tag and approved carried pins on the issue; desk decides publishing time under "Repositories and branches".
