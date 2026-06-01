# shadownet-local — Agent Guide

Instructions for AI coding assistants working on this codebase. Coding rules are
in [CLAUDE.md](CLAUDE.md); protocol authority is [`../shadownet-specs/`](../shadownet-specs).

## Deployment & Operations

Live deployment details (VPS, containers, deploy commands, adding new agents) are
in [`AGENTS.local.md`](AGENTS.local.md) (gitignored — private to the operator).

## What This Is

A self-hosted **Sidecar** implementing the Shadownet **v0.2** protocol. It sits
between a host agent (Claude Code, Hermes, any MCP host) and the network,
handling identity, transport, contacts, permissions, and message storage. It
never interprets message content — it routes, stores, signs, and verifies.

The host connects over the RFC 0002 MCP control surface (long-poll + Bearer
access token). The Sidecar is a client of the `shadownet` Python SDK
(`../shadownet/python-sdk`); prefer the SDK's primitives over rolling our own.

## Architecture

```
Host Agent ──MCP (Bearer access token)──► shadownet-local ──A2A message:send──► peer Sidecar
```

- Identity is an Ed25519 key, multibase-encoded (`z6Mk…`). The key *is* the
  identity. A Shadowname (`you@domain`) is an optional provider-bound alias.
- Addressing: **direct** mode (default, self-signed AgentCard, no DNS) or
  **shadowname** mode (run as your own provider with DNS TXT).
- The envelope is a JWS in A2A `metadata["urn:shadownet:0.2"]`, bound by `msgHash`.
- Credentials are `org_affiliation` JWTs; verified against a trust store + policy.

See [DESIGN.md](DESIGN.md) for the full internals and file layout.

## MCP Tools (RFC 0002)

Bare names (no `social_` prefix). Recipients are addressed by Shadowname or
`shadow://` URI, never a database id.

| Tool | Signature | Purpose |
|------|-----------|---------|
| `identity` | `()` | This Shadow's identity + credentials |
| `resolve` | `(name)` | Resolve a Shadowname/URI |
| `contacts` / `contact_detail` | `(query?)` / `(name)` | List / inspect contacts |
| `add_contact` | `(name, displayName?, grants?, profile?)` | Resolve + add |
| `grant` / `set_contact_profile` | `(name, grant, allowed)` / `(name, profile)` | Permissions / local notes |
| `send` / `respond` | `(to, body, contextId?)` / `(contextId, body)` | Send / reply |
| `coordinate` | `(name, activity, details?)` | Start a coordination (intent `coordinate_v1`) |
| `confirm_plan` / `accept_plan` | `(name, contextId, plan)` / `(name, contextId, acceptsMessageId)` | Confirm / accept a plan |
| `inbox` / `inbox_wait` | `(...)` / `(timeout_seconds?, last_event_id?)` | Read / long-poll inbound |

`body` is `{text?, intent?, data?}`. The coordination flow uses the typed intent
URIs `urn:shadownet:intent:{coordinate,confirm_plan,accept_plan}_v1`.

## Coordination Flow

`coordinate` → peer replies with `confirm_plan_v1` → initiator `confirm_plan` →
peer `accept_plan` (intent `accept_plan_v1`). The same `contextId` threads the
whole exchange; replies auto-add the sender on both sides (RFC 0001 §9). Each
step is a separate host session driven by `inbox_wait` events — no polling loop.

## Development

```bash
cd backend
uv sync --group dev          # SDK resolves from ../../shadownet/python-sdk
cp ../.env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8340

cd frontend && npm ci && npm run dev

# Gate (CI-enforced)
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run build
```

## E2E test (two sidecars)

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
```

Sidecar A on 8340, B on 8350. From A's host agent, `coordinate`/`send` to B's
`shadow://key:z6Mk…@…` connection URI (from B's Connect page). Verify B's
inbound via its `/api/messages` or the `inbox` tool.

## Known Constraints

- **Credentials**: this build verifies + holds/presents `org_affiliation` creds.
  There is no issuer/CSR client yet (issuance ceremonies are out of scope).
- **Direct-mode TLS**: the SDK's `make_pinned_httpx_client` enforces the
  `#sha256:` pin when supplied, else trusts on first use (TOFU, process-wide
  store); loopback uses http (§4.1). The envelope JWS is authoritative regardless.
- **Outbound retry**: uses the SDK's `asend_with_retries` (§8.10 remint + jitter),
  with the retry budget bounded to `AGENT_REQUEST_TIMEOUT` so the foreground MCP
  `send` returns promptly. Long-horizon background delivery (full 24h budget off
  the request path) is future work — would use a delivery queue.

## Common Failures

| Symptom | Check | Fix |
|---------|-------|-----|
| `creds_required` 401 to a stranger | acceptance policy requires `org_affiliation` | add the issuer to `TRUST_STORE`, or the peer presents a cred |
| `unknown_recipient` 404 | envelope `to` ≠ this Subject | confirm the connection URI / shadowname |
| `parse_error` 400 | tampered message or missing `A2A-Extensions` header | send `A2A-Extensions: urn:shadownet:0.2` |
| MCP `unauthorized` | access token expired/revoked | re-onboard via the Connect page |
| resolve fails (direct) | TLS cert fingerprint ≠ the URI's `#sha256:` pin, or a rotated self-signed cert vs the recorded TOFU pin | re-share the correct connection URI / pin |
