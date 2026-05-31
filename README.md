# shadownet-local

Self-hosted agent-to-agent communication Sidecar implementing the
[Shadownet v0.2 protocol](https://github.com/shadownet-protocol/shadownet-specs).

shadownet-local handles identity, transport, contacts, permissions, and message
storage. The host agent (Claude Code, Hermes, or any MCP host) owns all business
logic and connects over the MCP control surface (RFC 0002).

## Features

- **Identity** — Ed25519 key (multibase `z6Mk…`); the key *is* the identity
- **Two addressing modes** — direct (`shadow://key:z6Mk…@host:port`, no DNS) by
  default, or Shadowname (`you@your-domain`) if you run as your own provider
- **Transport** — A2A `message:send` carrying a signed Shadownet envelope JWS in
  `metadata["urn:shadownet:0.2"]`, bound to the message by `msgHash`
- **Trust** — verify inbound `org_affiliation` credentials against a configurable
  trust store + acceptance policy; present your own credentials on outbound
- **Contacts** — contact graph with auto-add-on-outbound (RFC 0001 §9)
- **MCP control surface** — RFC 0002 bare-name tools (`identity`, `resolve`,
  `send`, `coordinate`, `inbox_wait`, …)
- **Onboarding** — RFC 0003 `shadow://connect` links (handoff + refresh)

## Quick Start

```bash
git clone https://github.com/shadownet-protocol/shadownet-local.git
cd shadownet-local
./setup.sh              # writes .env (direct mode by default)
docker compose up -d    # builds and starts the sidecar
```

Then open the UI, create an account, and use **Connect → Generate connect link**
to pair a host agent.

## Deployment

```bash
docker compose up -d                                                   # plain port 8340
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d   # Traefik HTTPS
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d      # local test peer
```

Use a reverse proxy (Caddy, Traefik, Nginx) for HTTPS. Direct-mode endpoints may
serve a self-signed certificate (the envelope JWS is the authoritative
authenticator); production deployments typically front this with WebPKI TLS.

## Agent integration

The portal's **Connect** page mints a single-use `shadow://connect?mcp=…&handoff=…`
link. The host plugin redeems it (or you paste the `mcp=` URL + access token) and
opens an MCP session with `Authorization: Bearer <access-token>`.

```json
{
  "mcpServers": {
    "shadownet": {
      "type": "http",
      "url": "https://your-instance.example.com/u/<label>/mcp",
      "headers": { "Authorization": "Bearer <access-token>" }
    }
  }
}
```

## MCP tools (RFC 0002)

| Group | Tools |
|-------|-------|
| Identity / discovery | `identity`, `resolve` |
| Contacts | `contacts`, `contact_detail`, `add_contact`, `grant`, `set_contact_profile` |
| Messaging | `send`, `respond`, `inbox`, `inbox_wait` |
| Coordination | `coordinate`, `confirm_plan`, `accept_plan` |

Recipients are addressed by Shadowname or connection URI — never a database id.

## Coordination flow

```mermaid
sequenceDiagram
    actor UA as User A
    participant AA as Agent A
    participant SA as Sidecar A
    participant SB as Sidecar B
    participant AB as Agent B
    actor UB as User B

    UA->>AA: coordinate coffee with bob@host
    AA->>SA: coordinate (intent coordinate_v1)
    SA->>SB: A2A message:send (envelope JWS)
    AA-->>UA: Sent — I'll let you know.

    Note over SB: inbox_wait delivers event
    AB->>SB: respond (intent confirm_plan_v1, typed plan)
    SB->>SA: A2A message:send

    Note over SA: inbox_wait delivers event
    AA-->>UA: Coffee at The Daily Grind, Fri 10am. Confirm?
    UA->>AA: yes
    AA->>SA: confirm_plan (intent confirm_plan_v1)
    SA->>SB: A2A message:send

    Note over SB: inbox_wait delivers event
    AB-->>UB: A confirmed. Accept?
    UB->>AB: yes
    AB->>SB: accept_plan (intent accept_plan_v1)
    SB->>SA: A2A message:send

    Note over SA: inbox_wait delivers event
    AA-->>UA: All set — Coffee Friday 10am.
```

## Configuration

All settings use the `SHADOWNET_` env prefix. See [`.env.example`](.env.example).

| Variable | Description |
|----------|-------------|
| `EXTERNAL_URL` | Public URL; the AgentCard + connection URI derive from it |
| `ADDRESSING_MODE` | `direct` (default) or `shadowname` |
| `SHADOWNAME` / `PROVIDER_DOMAIN` | Shadowname-mode identity + provider domain |
| `TRUST_STORE` | JSON list of `{issuer, accept}` (empty = trust nobody yet) |
| `ACCEPTANCE_POLICY` | JSON `{fromContact, fromStranger}` (default requires `org_affiliation` from strangers) |
| `CREDENTIALS_PATH` | File/dir of `org_affiliation` JWTs this Subject presents |
| `JWT_SECRET` | Signs the portal's opaque access/refresh tokens |

## Local development

Requires [uv](https://docs.astral.sh/uv/). The Shadownet SDK (v0.5.0) resolves
from the public monorepo git source pinned in `uv.lock` until it ships on PyPI
(no sibling checkout needed).

```bash
cd backend && uv sync --group dev && cp ../.env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8340
cd frontend && npm ci && npm run dev      # UI
cd backend && uv run ruff check . && uv run pytest    # gate
```

## Architecture

See [DESIGN.md](DESIGN.md) for internals and [AGENTS.md](AGENTS.md) for the
agent-facing guide.

## License

MIT
