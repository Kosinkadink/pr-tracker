---
name: executing-worker-packets
description: "Executes bounded Dinkster worker and machine-worker assignments. Use when commissioned for implementation or hardware evidence, not feature ownership."
---

# Worker

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Roles

- Workers are low threads or Tasks for bounded units with exact written specs and commands; a medium worker needs a one-line reason in the plan. They reply in their thread and spawn no threads unless authorized. Use Task for bounded fresh context that needs no addressable thread.

- Machine workers are bounded threads commissioned by the feature owner, released on completion, allowed local children and setup but never merges, tags or publication. There are no standing GPU workers; the current GPU-worker creation owner is [the GPU-worker creation owner](https://github.com/Kosinkadink/comfy-vibe-station/issues/459).

## Machines and safety

- Wrong-GPU workers fix their command, record the incident in the receipt and continue, without extra release/proof/registry ceremonies. Before persistent-environment packets claim GPUs, verify each launched interpreter's first-party pack digests equal committed locks and retain each package inventory in evidence; mismatch stops before GPU use with interpreter and both digests.
