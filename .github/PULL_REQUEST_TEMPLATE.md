## What & why

<!-- What does this change and why? Link any issue. -->

## Checklist

- [ ] `scripts/privacy_check.sh` exits 0 — **no real path, host, identity, or secret** in any tracked file
- [ ] No new heavy dependency; stdlib core stays installable without extras
- [ ] Tests added/updated and `pytest` is green
- [ ] `ruff` is clean
- [ ] Docs updated if behavior or config changed (and `CHANGELOG.md` under `Unreleased`)
- [ ] The change is scoped — no unrelated reformatting

## Notes for the reviewer

<!-- Anything non-obvious: tradeoffs, follow-ups, measured numbers. -->
