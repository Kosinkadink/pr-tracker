# pr-tracker AGENTS

## Git Author Identity

**NEVER override the git author or committer identity.** Do not pass `-c user.name=...` or `-c user.email=...` to `git commit`, do not edit `.git/config`, and do not invent an email based on the GitHub username. Always let git use the repo's already-configured `user.name` / `user.email`.

If you need to confirm before committing, run `git config user.name` and `git config user.email`. Do not guess.

```powershell
# CORRECT — uses configured identity
git commit -m "..."
```

```powershell
# WRONG — overrides identity, attributes commits to whoever you make up
git -c user.name=SomeName -c user.email=fake@example.com commit -m "..."
```
