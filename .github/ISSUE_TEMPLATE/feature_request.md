---
name: Feature request
about: Suggest an idea
title: "[feat] "
labels: enhancement
---

**The problem**
What are you trying to do that markmem makes hard today?

**Proposed direction**
What you'd like. Keep in mind markmem's constraints: stdlib core, no daemon, no heavy DB, fail-open,
Markdown + git as the single source of truth, and **no memory written without human review**.

**Alternatives considered**

**Scope check**
Does this keep the engine small and auditable? If it needs a new heavy dependency or a background
service, say why it's worth it.
