---
name: verifying-features
description: "Verifies exact Dinkster pull request heads against issue criteria. Use when commissioned as a fresh-context verifier."
---

# Verifier

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- A verifier is a fresh-context low thread or Task that has not seen the implementation conversation. The owner commissions it (the desk only when replacing an owner). Its brief names issue, branch, exact head and criteria, and it returns per-criterion PASS/FAIL with evidence. It certifies that head, not the merge onto main; hosted CI and the landing thread own that merge.

## Verdicts and carries

- A verifier checks the requested feature on a fresh clone. Line endings, file identity or Windows-only path changes also require a persistent Windows checkout. Its brief links the issue criteria and adds none. It posts exactly one verdict per head on the wrapper issue, reads it back, then removes its own body file: `gh api -X POST repos/Kosinkadink/comfy-vibe-station/issues/N/comments -F body=@FILE`. First line: `VERDICT: PASS - <40-hex head>` or `VERDICT: FAIL - <40-hex head>`.

- Only an unmet issue product criterion is FAIL. Running hosted checks, missing test records, wrong Refs, stale pins, missing exact-head statements and unreproducible ancestry are `PACKET:` notes under PASS, not merge gates. The owner corrects the PR body without moving the head, before labelling when practical. Findings below Medium never force a round alone. FAIL is normal iteration: fix, push, commission a fresh low no-carry verifier, without a decision or pairing ceremony.
