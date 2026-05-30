# CLAUDE.md

Coding and development rules for `shadownet-local` — the self-hosted Shadownet
**Sidecar** (FastAPI backend + React frontend + host-agent plugins). Architecture
and component map live in [`AGENTS.md`](./AGENTS.md). Ported from the monorepo
conventions in [`../shadownet/CLAUDE.md`](../shadownet/CLAUDE.md) and
[`../shadownet/python-sdk/CLAUDE.md`](../shadownet/python-sdk/CLAUDE.md).

> Note: `AGENTS.md` still describes the v0.1 surface (`social_*` tools, DID/VP
> handshake). It is being migrated to v0.2 alongside the code.

## Spec authority

The protocol's source of truth is [`../shadownet-specs/`](../shadownet-specs)
(sibling clone). Reading order for v0.2: `rfcs/0001-shadownet.md` (wire) →
`rfcs/0002-shadownet-mcp.md` (MCP control surface) → `rfcs/0003-shadownet-onboarding.md`.

- If code and an RFC disagree, the RFC wins.
- If an RFC is silent or ambiguous, ask — do not invent semantics.
- Every wire artifact carries `"v": "0.2"` (`urn:shadownet:0.2`); unknown
  versions are rejected at the boundary.

## SDK dependency

The Sidecar is a client of the `shadownet` Python SDK, not a reimplementation.
The canonical clone is at [`../shadownet/python-sdk/`](../shadownet/python-sdk)
(PyPI: `shadownet`). Prefer the SDK's primitives (`envelope`, `agentcard`,
`receiver`, `provider`, `credential`, `trust`, `onboarding`, `mcp`) over rolling
our own crypto or wire handling.

**Verify the API before calling it.** Read the SDK module (or `a2a-sdk` / `mcp`
docs) and confirm the signature — do not work from memory. Stale recall of a
library surface has burned us before.

## Code conventions

- **Comments and docstrings: terse.** One-sentence module / class / function
  docstrings. No banner comments, no multi-paragraph docstrings, no restating
  what the code says. Add a comment only to explain a non-obvious *why*.
- **No section divider lines** in source (`# ──`, `# ----`, `# ====`,
  `// ===`). Function and class boundaries are the structure; if a file needs
  hard sub-divisions, split it into modules.
- **Naming** (RFC 0001 §2): JSON wire keys camelCase, value strings snake_case,
  JWS `typ` kebab + `+jwt`. Python identifiers snake_case; expose camelCase on
  the wire only via pydantic aliases.
- **No backwards-compatibility shims** while the protocol is pre-1.0. Delete old
  types and functions; do not deprecate-and-keep.
- **No mocks or placeholders in shipped code.**
- **No emojis** in code, comments, or commits.

## Local gate

Run before pushing. All must pass.

```sh
# backend
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest

# frontend
cd frontend && npm run build   # tsc -b && vite build
```

## Commit conventions

- Conventional-commit prefixes: `feat:`, `fix:`, `style:`, `chore:`, `docs:`,
  `refactor:`. Imperative summary.
- One logical change per commit; code and its tests land together.
- Branch off `main`; never push to `main` without the gate green.