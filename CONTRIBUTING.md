# Contributing to markmem

Thanks for your interest. `markmem` is deliberately kept small, honest, and measurable — contributions
should keep it that way. (Deutsche Fassung: [CONTRIBUTING.de.md](CONTRIBUTING.de.md).)

## Setup

```bash
git clone <repo-url>            # the markmem repository
cd markmem
pip install -e ".[vektor,dev]"   # vector leg + pytest/ruff
ollama pull bge-m3               # for the vector leg and evals
```

Quick functional check against the demo corpus:

```bash
bash examples/quickstart.sh
```

## Tests

```bash
pytest                    # core tests
pytest -m "not rerank"    # without torch/transformers
pytest -m "not ollama"    # without a running Ollama
ruff check .              # linting (line-length 120, target py311)
```

Tests that need external services are marked (`rerank`, `ollama`) and are skipped cleanly without them.

## Style

- **Code:** Python 3.11+, pure stdlib in the core; heavy dependencies (numpy, torch, transformers) only
  behind optional extras and imported **fail-open** — if the extra is missing, the feature degrades
  instead of crashing.
- **Comments & docstrings:** concise and factual. New contributions are welcome in English; existing
  German comments are being migrated over time, not in one churn.
- **Names ≥ 4 characters**, descriptive (no `x`, `tmp`, `d` as load-bearing variables).
- **Fail-open on retrieval, fail-closed on risky writes.** A synapse error must never block the session.
- **Never auto-write behavior-changing knowledge** — always a proposal behind a review gate.
- **Every performance claim is a measured number** (eval harness), not a promise. "Sounds clever"
  doesn't count; "is measurably better" does.

## Privacy rule (mandatory)

**Never commit real data.** Concretely:

- Only synthetic `*.sample.md` cards and the demo index files under `examples/` belong in the repo.
- Real memory databases, private notes, real target / person / project names, secrets, API keys and
  generated indexes stay **out** (blocked by `.gitignore`: `/memory/`, `/data/`, `*.private.md`,
  `*.sqlite`, metrics).
- Before every commit: review the diff — no real data, no secret. The indexer redacts secrets before
  embedding; do not rely on that alone. `scripts/privacy_check.sh` must exit 0.

## Pull requests

- small, reviewable, reversible steps;
- tests green, `ruff` clean;
- for retrieval/tuning changes: attach before/after eval numbers;
- update the docs when behavior or config changes (and add a `CHANGELOG.md` entry under `Unreleased`).

See the [pull-request template](.github/PULL_REQUEST_TEMPLATE.md) for the full checklist.
