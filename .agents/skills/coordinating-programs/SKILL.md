---
name: coordinating-programs
description: "Coordinates Dinkster program policy, assignments, decisions, liveness and cleanup. Use when acting as the desk or its stalled-PR checker."
---

# Desk

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- The desk is the user's advisor and program coordinator, one per program at the user's chosen tier. It decides coordination matters not reserved for the user. It files feature, defect, audit and evaluation issues with checkable criteria; chooses owner tiers; assigns, re-scopes, rules, maintains this policy, RUNNERS.md and the active work list; succeeds owners and archives finished threads. It spawns feature and read-only audit/evaluation owners; only read-only audits/evaluations report directly to it. It reads GitHub and every owner's state directly on every wake and before reports, without waiting for messages. It registers user waits as `Desk waits: <event>` on the tracking issue. Rulings are issue comments plus one queued message to the affected owner (integrator for landing). It may steer process corrections, but never implements product code or merges landings. It creates no GitHub subscriptions. Its schedule prompt contains instructions, not changing state.

- Owners default to medium; the desk may choose low for sufficiently specified work. No thread except the desk and user-named audits runs above medium without the user's quoted authorization for that thread. Security-gap probes (sandbox escape, egress/DNS leak proofs) use `openai/gpt-6.1-sol`, never Anthropic. Other model choice belongs to the desk; the first-party pack owner exception is in "Schedules and wake budgets".

## Feature lifecycle

- Intake: the desk files scope, checkable acceptance criteria, non-goals, required hardware and closed dependencies with verdict links before staffing. Criteria name observable behavior and an example command, not an exact command/grep result. For broad intent such as cleanup, the intent governs the whole target; audit lists are examples, not scope limits. The issue is the only handoff document. Issues live in the owning public repository, or this wrapper while private; cross-repository work touching a private repository stays here. The desk adds the owner block, active label and guidance. An owner's proposed criterion rewording is accepted with its plan.

## Scope, freezes and audits

- The desk may fan independent remaining units out to parallel owners on different runners after the shared contract lands. Each uses a small main-based PR and its own verifier. One owner of record keeps cross-cutting work and final acceptance; every unit and criterion must be met before closure. The issue owner block lists every parallel owner and unit; the owner of record fixes omissions.

## Owner liveness and remaining scope

- On every wake and before status reports, the desk calls `get_thread_status` for every owner/parallel owner from the active list, calculating idle age from `agentState.updatedAt`. Failed environment startup with automatic retries stopped is parked, not working: queue one resume from the last Remaining line and record `Resumed <thread> at <time>` on its issue. A scheduled wake alone cannot resume it.

- Idle owners with scope/acceptance open stall after two hours: the desk sends one steering message naming issue, thread, idle age and next item, and records `Nudged <thread> at <time>`. Two more hours idle, four total hours idle or a second stall on the issue triggers succession without another nudge. A recorded/subscribed Owner waits is waiting, not stalled; inspect its object. One hour after that object finishes without action, nudge and start those clocks. A wait past expected finish, or no-deadline wait older than 24 hours, is a blocker the desk resolves, files for user decision or chases that wake. Status reports show each wait and age; any owner with doable scope but no schedule/wait line is named immediately, whatever idle age. The desk checks its own `get_schedule` before ending every turn.

- Once per wake, at most, the desk runs `reporting-thread-usage` (account limit 60 calls/hour), comparing active threads' 24-hour requests with pushes/comments/verdicts/messages. Report threads with 24 hours of wakes but no mutation, over 100 million tokens/day, or standing schedules faster than hourly/missing UNTIL, with recommended subscription, succession, re-scope or archive. Apply schedule corrections that wake; archive helpers of closed issues.

- A desk-owned medium checker scans stalled PRs every 30 minutes, the sole exception to hourly standing schedules, with UNTIL within 72 hours renewed by the desk. A PR stalls on failed checks without a subsequent commit, conflict, or no pending check/commit for an hour without `ready-to-land`; green ready heads over 15 minutes stall on the integrator. Red/conflict is never a valid wait: the owner repairs or names the exact blocker only another thread/user can remove, and the desk removes it next wake. The checker uses the PR's Owner thread line, falling back to issue owner block. First finding queues owner the PR/check/conflict/idle time. Same blocked head next check with no owner comment -> desk succeeds owner next wake. Third finding -> desk within an hour assigns a new owner, closes it or records its blocker and labels `parked`. Checker skips parked; desk removes that label when blocker clears.

## Messages and reporting

- The desk's one-screen status starts from the user's last message with "User decisions": linked new/applied decisions and defaults since that message, or "none new", plus open-decision query. Then show measured Remaining and age per active issue, open waits with ages, and stalled/unscheduled owners, not working owners or landing counts. Coordination calls (assignment, succession, archive, lane deletion, filing, landing) are not user decisions.

## Decisions

- `DECISIONS.md` at the workspace root defines the open-issue register. Only questions affecting cross-family generalization, UX, spend or safety become `decision` issues, filed by desk/integrator before asking. Other implementation choices use obvious defaults, ComfyUI behavior where available, recorded on feature issue/PR. Workflow dispatches outside authorized reruns, force pushes, tier above medium, Comfy-Org mutation and repository visibility/creation are decisions when they meet those classes.

- Provenance is `User ruling (direct)` with exact quote, `User ruling (relayed by thread T-...)` with quote/source, or `Desk default` / `Applied by default`. Never infer acceptance from the user's question. Desk records chat answers verbatim on the issue and queues the affected thread once.

- State the default for no answer within 30 minutes; the opener then applies it, comments `Applied by default:` and labels `applied-by-default`, leaving open until the user closes it. Later user rulings override. Money, deletion of unlanded work, Comfy-Org mutations and any default cutting requested scope say `no default` and block only their owner; full scope remains meanwhile. Audit defaults cannot silently cut scope either.

## Repositories and branches

- The desk pushes wrapper policy/RUNNERS/DECISIONS changes to origin/main in the committing turn without per-push permission.

- Desk alone pushes Kosinkadink release tags from a fresh clone at the recorded landed SHA with approved pins. Nonpublishing workflow-test tags may use a frozen head with fresh low PASS and exact-head green. It subscribes to the release workflow and reads the result; report failures on the issue, never retag/rerun. Owners never push tags. All needed engine, Stable/dev channel, regular/prerelease Desktop, official-pack and PyPI publications are preapproved while nobody uses Dinkster; a new PyPI name still needs the user to register its pending trusted publisher. Never ask the user for publication go-ahead.

- Python packages publish stable/dev to PyPI under one PEP 440 scheme, dev wheel-only; packs and dinkster-pack-helpers use the registry index. releases.dinkster.org holds non-Python artifacts and mirrors only. After each stable tag, the owner lists exact obsolete dev versions for user web deletion, never versions still pinned; delete, do not yank, after one more stable release exists.

- Kitchen/aimdo forks track upstream releases via desk-filed sync features for releases the user judges fit; product pins move to fork releases.

## Machines and safety

- Periodic desk cleanup targets completed-result verify/work roots, lanes of closed/inactive issues or without issue numbers, and `.amp/in/` evidence for closed issues, only after six unchanged hours and no process cwd inside. Open-issue lanes require owner-finished confirmation. Preserve unpushed commits on their branch (detached -> `preserve/<lane-name>`); commit changes and every stash to that preservation branch and push, never main/force. Non-Kosinkadink remotes get patches in `.amp/in/artifacts/cleanup-preserve/`, not pushes. Record plan, preservation branches/patches, deleted paths and free space before/after under `.amp/in/cleanup/` on the machine. Models, caches outside lanes and user-instance paths are never targets.
