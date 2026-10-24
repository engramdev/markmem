# Security policy

markmem is a local, offline tool with no network service (see [THREAT_MODEL.md](THREAT_MODEL.md) for
the full trust boundary). The security surface that matters here is **data confidentiality** — that
your private memory corpus never leaks into the public repository — and **store integrity** — that no
memory is written without human review.

## Supported versions

markmem is `alpha` and pre-1.0. Security fixes land on `main` and in the next tagged release. Only the
latest tag is supported; there are no backports.

| Version | Supported |
|---|---|
| latest `main` / newest tag | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

Please report privately **before** disclosing publicly:

1. Open a **GitHub security advisory**: repository → **Security** → **Report a vulnerability**
   (GitHub Private Vulnerability Reporting). This keeps the report private until a fix ships.
2. Do **not** open a public issue for a vulnerability, and do **not** include real private data,
   secrets, or a working exploit against a third party in the report.

Please include: affected version/commit, a minimal reproduction, and the impact you observed.

## Scope

In scope:
- A path by which real corpus content, secrets, or operator identity could reach the **public repo**
  or the committed `examples/` despite `.gitignore` + `scripts/privacy_check.sh`.
- A way the engine **writes a memory without the human review gate**.
- Secret material surviving the indexer's redaction into a tracked index.

Out of scope (see THREAT_MODEL.md): confidentiality of your corpus on your own disk, a remote LLM
endpoint you deliberately configure, and anything requiring an already-compromised host or account.

## Response

This is a solo, best-effort project. Expect an acknowledgement within a few days and a fix or a clear
decision on a reasonable timeline. There is no bounty.
