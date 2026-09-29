# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the shared-language glossary and the single source of truth for terms and surfaces. **Read it first; it is mandatory.**
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

This is a **single-context** repo (one `CONTEXT.md` at the root + `docs/adr/`). There is no `CONTEXT-MAP.md`.

## File structure

```
/
├── CONTEXT.md                  ← shared-language glossary (read first)
├── docs/adr/                   ← architecture decision records
├── docs/agents/                ← setup-matt-pocock-skills output (this file, issue-tracker.md)
├── .scratch/<feature>/         ← local-markdown issue tracker
└── core/                       ← the agent backend (single source of truth for logic)
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids (e.g. use `egress`, never `export`/`outbound`; use `approval`/`HITL`, never `review`/`check`).

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (desktop-first boundary), but worth reopening because…_
