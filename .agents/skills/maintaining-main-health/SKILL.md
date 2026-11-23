---
name: maintaining-main-health
description: "Attributes and repairs red Dinkster main validation runs. Use as the main health owner or the owner of a change that broke main."
---

# Main health

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- The main health owner is one medium thread for Dinkster and Dinkster-Frontend. It reads every completed main full-validation run, queries the newest completed run per poll (including dinkster-evidence where applicable), and keeps the ledger on [the main-health issue](https://github.com/Kosinkadink/comfy-vibe-station/issues/389). For an unexplained failure it adds evidence to the issue for that signature and tells its owner once, or files criteria and repairs it through verification. It never skips, retries, quarantines, weakens assertions or widens deadlines to manufacture green.

## Testing and CI

- Full validation runs once per commit: Linux on batched main pushes, Windows daily on main. Do not rerun a completed red or green commit, dispatch it for PRs, or treat cancelled/incomplete jobs as PR failures. The main health ledger records last-green/first-red runs, commits, signatures and all intervening PRs, once per distinct red head, not per rerun; a later green on that head closes it.

- On red main, the main health owner attributes the bounded intervening PR set and queues the culprit owner in the same poll. That owner puts a minimal repair-only PR into hosted fast and freezes it for verification within one hour; it pushes no other PR until main is green. No fix in flight within that hour means revert the single culprit. New failures require separate repair PRs or revert, not a growing repair. Two hours from first red is a hard revert deadline if no repair merged, even if an unmerged repair has green/PASS. A merged repair stops that deadline; under the desk default, the first completed full run containing it closes the entry if green, or triggers immediate culprit-and-repair revert if the original failure recurs, without a new clock. Re-land reverted features with their repair through ordinary verification. Other landings continue. The desk reports red main older than an hour with first-red time, culprit, repair PR/head. An owner whose push/landing turned main red fixes or reverts within four hours before new work; the desk gets a finding for a red lane older than four hours without a fix in flight.
