---
name: integrating-changes
description: "Lands reviewed Dinkster pull requests with exact-head guards and carries verdicts over main. Use as the integrator, a landing owner, or a verifier enabling auto-merge."
---

# Landing

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- The integrator is one medium thread per program, or per repository when the desk splits it. It owns landings, conflicts, carries and recording completed landings; it moves required cross-repository pins. It polls merge state at least every 15 minutes, landing ready heads in parallel without a queue, batch, dependency-order or red-main hold. Red-main duties belong to the main health owner, not the integrator.

## Feature lifecycle

- Land: the owner confirms ready-for-review, adds `ready-to-land` and posts freeze/verdict links on the issue. Verifier label/auto-merge writes follow `verifying-features`, Verdicts and carries. Brief it to wait whenever a landing gate is not a target-branch required check, including all PRs into feature branches without required checks. Dinkster-Frontend main requires "format, lint, types and unit subset", which depends on visual and native-startup. Dinkster main requires "format, lint, types" and "tests"; contributor-setup, library-link-safety and archive admission are not covered, so required instances of those wait. Auto-merge waits only for required checks and is not pinned after later writer pushes: before any push to a PASS head, disable auto-merge and remove the label. Where auto-merge is unused, the owner exact-head-guarded squash-merges its own PASS/green head in the turn it reads both. The integrator lands any ready head it finds without waiting for its owner. Immediately before merging, reread verdict, API head, label and mergeability; only exact-head hosted fast green and PASS/carried PASS gate the PR. A verdict that states exact-head PASS counts despite a nonstandard first line. Ready heads are not held for draft/unlabelled heads sharing files, red main, another landing, a full run or packet hygiene. Never update a merely behind-main branch: plain-merge main only for a reported conflict or a needed check repair already on main, never rebase. Before PASS the owner updates it; after PASS the integrator handles conflicts/carries. Do not move a head still awaiting a verifier. Whoever reads back a landing checks the merged tree against the reviewed head merged onto main with `git merge-tree`, reverting a mismatch. The landing thread posts squash SHA and head, moves required pins, removes the label and closes the issue only when all criteria are met. GitHub deletes newly merged branches; nobody manually deletes these or existing merged branches without separate cleanup approval. A ready head unlanded for 60 minutes gets a blocker comment from the integrator, not a silent hold. Conflicts are resolved on the owner branch, never decision issues. Unmerged work is not completion.
