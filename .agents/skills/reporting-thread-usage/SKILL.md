---
name: reporting-thread-usage
description: Reports Amp thread spend (hourly and daily cost, tokens, model/tier mix) across all recent threads using the amp CLI. Use for usage reports, cost audits, finding overspending threads, and recommending tier downgrades or culls during heartbeat checks.
---

# Reporting Thread Usage

Aggregates cost across all of the account's recently active Amp threads so a
coordinator (or a cheap delegate) can report hourly + daily spend and flag
threads that should be culled or moved to a lower tier.

## Quick start

Run the bundled script (Python 3, stdlib only; requires the `amp` CLI to be
logged in on this machine):

```bash
python3 scripts/usage_report.py
```

Default output is a markdown report with:

- fleet daily total, plus an hourly total covering the top spenders
- a per-thread table (hourly $, daily $, requests, top model and inferred tier),
  sorted by daily cost descending
- a flags section: any ultra-tier usage, top spenders, and query errors

Useful options:

```bash
python3 scripts/usage_report.py --hourly-window 1 --daily-window 24  # defaults
python3 scripts/usage_report.py --budget 50     # max usage-API calls (see below)
python3 scripts/usage_report.py --hourly-top 10 # hourly detail for top N spenders
python3 scripts/usage_report.py --min-cost 0.10 # hide threads under $0.10/day
python3 scripts/usage_report.py --json          # machine-readable output
```

## CRITICAL: server rate limit - run at most once per hour

The usage endpoint allows **60 queries per hour account-wide**. The script
spends a strict budget (default 50): one daily-window `--details` call per
thread, most-recently-updated first, then hourly-window calls for the top
`--hourly-top` daily spenders with the remaining budget. On a rate-limit
error it stops querying and prints a clearly marked partial report.

Consequences:

- Run the script at most once per hour; it fits the hourly heartbeat exactly.
- Do not run it "again to double-check" - that burns the next report's budget.
- With more than ~40 active threads, the least-recently-updated ones are
  skipped and counted in the report; raise `--budget` only if nothing else
  will query usage that hour.
- The hourly total covers only the top spenders (the daily total is complete
  for all queried threads).

## How it works

1. `amp threads list --json --limit N` enumerates threads; only threads whose
   `updated` falls inside the daily window are queried (inactive threads cost
   $0 in the window).
2. Phase 1: `amp threads usage <id> --details --start <t0> --end <t1>` for the
   daily window per thread (cost, tokens, requests, per-model cost table).
3. Phase 2: plain hourly-window cost calls for the top daily spenders.
4. A thread's tier is inferred from its costliest model in the window.

Thread usage figures include Task-tool subagent spend in the parent thread, so
summing listed threads does not double count.

## Model -> tier mapping

The script maps model names to tiers with this table (as of 2026-08):

| Model name contains | Tier |
| --- | --- |
| Fable 5 | ultra |
| GPT-5.6 Sol | high/med (see below) |
| GLM-5.2 (Sub Discount) | subagent |
| GLM-5.2 | low |
| GPT-5.6 Luna | overhead (housekeeping, negligible cost) |

**GPT-5.6 Sol is ambiguous**: the high tier is Sol at xhigh reasoning effort
and the medium tier is Sol at medium effort, but usage output shows only the
model name (verified empirically 2026-08-29 by comparing `--details` output
of one known-medium and one known-high thread: both report exactly
`GPT-5.6 Sol`). The report therefore labels Sol threads `high/med`.

The script splits them automatically: its `--resolve-modes N` phase (default
10) reads the `agentMode` field from `amp threads export` for the top N
spenders still labeled `high/med`. The export JSON stays inside the script;
only the extracted `medium`/`high` string reaches the report, so long
threads never flood the calling agent's context. Export is a local amp call,
not a usage-API query, so it costs no rate-limit budget - but it is slow for
long threads, so keep N bounded. For a one-off manual check:

```bash
amp threads export <thread-id> | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('agentMode'))"
```

Do not guess mode from cost.

## Recommendations only - the user decides

The report RECOMMENDS downgrades, culls, and successions; it never executes
them. Any tier downgrade, thread cull, or succession triggered by a usage
report requires explicit user permission first. Flag ultra usage and
top-spender concerns in the report and wait for the user's decision.

Related fleet policy: an ultra thread the user requests for an AUDIT is
audit-only. It must never become the owner of the feature it audits; when
the audit ends, ownership stays with (or passes to) a medium/high owner
thread, and the ultra thread goes idle.

Model lineups drift. If the report shows `unknown(<model name>)`, verify the
tier by checking a thread of known mode with
`amp threads usage <thread-id> --details` and update `TIER_BY_MODEL` in
`scripts/usage_report.py` plus this table.

## Interpreting the report and making recommendations

Policy defaults (owner preference, 2026-08):

- **Ultra is forbidden without explicit user authorization.** Any nonzero
  ultra-tier cost in the window is an incident: name the thread and recommend
  immediate succession to a cheaper tier (see the succeeding-yourself /
  delegation-orchestration skills).
- **Prefer medium over high.** High tier is for genuinely hard reasoning work
  (architecture rulings, subtle correctness review). Feature owners doing
  routine slice execution, relaying, or bookkeeping belong at medium; report
  high-tier threads whose recent work looks routine as downgrade candidates.
- Reviewers and one-off delegates should be medium or low.
- Flag idle-but-expensive patterns: a thread with high cost but few requests in
  the window, or steady spend with no merged/shipped output, is a cull
  candidate.

The script only reports facts and mechanical flags; the downgrade/cull
judgment belongs to the agent reading the report. Include in the final report
to the user: both totals, the top 5 spenders with tier, any policy violations,
and concrete recommendations (which threads to succeed to which tier).

## Use from an hourly heartbeat

The coordinator handling the heartbeat should either run the script directly
(one command; cheapest) or spawn a single low/medium delegate that loads this
skill, runs the script once, and replies with the report plus recommendations
(queued, steer: false). Do not spawn a delegate per thread, and never run the
script more than once per heartbeat - the 60/hour server rate limit is shared
across the whole account.
