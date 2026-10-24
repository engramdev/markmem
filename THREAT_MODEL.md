# Threat model

markmem is a **local, offline memory engine** — a set of CLI tools over a Markdown + git corpus. It
is not a server and opens no network port. This document states plainly what its design protects
against and, just as important, what it deliberately does **not**. If a guarantee is not listed under
"What it protects against," do not assume it.

> **One-line version:** your memory is plain Markdown on your disk; markmem derives indexes from it
> locally and never sends it anywhere by default. The engine is public; your notes stay private.

---

## Assets and trust boundary

| Asset | Where it lives |
|---|---|
| Your memory corpus (`*.md` cards, the real notes) | your disk, **outside this repo**, referenced by `MARKMEM_MEMORY_DIR` |
| Derived indexes (vector SQLite, graph, tier cache) | your disk, rebuildable from the Markdown; never authoritative |
| The engine | this public repo — code only, plus synthetic `*.sample.md` demo cards |

Trust boundary: **everything markmem reads and writes stays on your machine.** There is no daemon, no
listening socket, no telemetry, no outbound call — except the embedding/compaction requests you
explicitly configure, which go to your **local Ollama** by default.

---

## What it protects against

| Threat | Mitigation (in code / repo) |
|---|---|
| **Your real notes leaking into the public repo** | the real corpus lives outside the repo (`MARKMEM_MEMORY_DIR`); `.gitignore` blocks `/memory/`, `/data/`, `*.private.md`, `*.sqlite` and generated metrics; `scripts/privacy_check.sh` runs in CI and fails the build on any tracked private marker; only synthetic `*.sample.md` cards are committed |
| **Secrets ending up in the vector index** | the indexer redacts secret patterns from card text **before** embedding |
| **A learned memory silently poisoning the store** | nothing is auto-written — every learned candidate lands in an inbox and requires human review before it becomes a card |
| **A component outage corrupting results** | retrieval is **fail-open**: if Ollama/numpy/the index is absent, the vector leg drops and BM25 ⊕ entity still answer; the result is flagged `degraded` rather than wrong-but-silent. (Risky *write* actions are fail-closed.) |
| **No attack surface from a running service** | there is no server and no open port; integration is via CLI + hooks, not a daemon |

---

## What it does NOT defend against (stated honestly)

- **Confidentiality of the corpus on your own disk.** markmem does not encrypt your notes. File
  permissions and disk encryption are the operating system's job, not markmem's.
- **What you point it at.** If `MARKMEM_MEMORY_DIR` targets sensitive data, the derived indexes,
  metrics and logs reflect it — all local, but your responsibility to keep local.
- **The LLM you configure.** Compaction and embedding send card text to the model endpoint you set.
  The default is local Ollama (nothing leaves the machine); if you point it at a remote API, you are
  sending your notes there. markmem does not stop you — it just defaults to local.
- **Not a multi-tenant / isolation system.** It is a single-user, single-machine tool. It makes no
  isolation claims between users or tenants.
- **The privacy gate is a net, not a proof.** `scripts/privacy_check.sh` catches known patterns
  (home paths, identity markers, private-path forms). It reduces the chance of an accidental leak; it
  does not guarantee its absence. Human review before any publish stays mandatory.
- **Your machine, shell and git host are out of scope.** markmem assumes the host it runs on and the
  account it pushes from are themselves trustworthy.

---

## Reporting a security issue

If you find a way markmem leaks the corpus it shouldn't, writes a memory without review, or otherwise
behaves outside what this document describes, please open a GitHub **security advisory** (Security →
Report a vulnerability) rather than a public issue, so it can be fixed before it is widely known. See
[SECURITY.md](SECURITY.md).
