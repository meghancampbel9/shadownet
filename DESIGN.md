# Design

## Purpose

Agent-to-agent communication sidecar implementing the Shadownet v0.1 protocol.
Handles identity, transport, contacts, permissions, and message storage. Never
interprets message content — the host agent owns all business logic.

## Architecture

```
Host Agent ──MCP (Bearer auth)──► shadownet-local ──A2A HTTP──► Remote shadownet-local
                                       │
                                  ┌────┴────┐
                                  │ SQLite  │
                                  │ Ed25519 │
                                  └─────────┘
```

Each instance manages:
- **Identity** — Ed25519 keypair → DID:key → agent card at `/.well-known/agent-card.json`
- **Contact graph** — known peers with DID, endpoint, public key, grants
- **Message store** — every inbound/outbound interaction persisted
- **MCP endpoint** — authenticated tool surface at `/u/{shadowname}/mcp`
- **Integration bundle** — RFC-0008 auto-discovery at `/v1/account/me/integration-bundle`

## Authentication

### Identity

On first startup, the sidecar generates an Ed25519 keypair and derives a
`did:key` identifier. The public key and DID are published in the agent card.

### Inbound (verifying senders)

Uses `shadownet.a2a.server.verify_handshake` from the SDK:
1. Extracts the sender's DID from the `Authorization` header (JWT `sub` claim)
2. Checks if the DID is in a **trusted cache** (built from known contacts)
3. Known DIDs are accepted without a Verifiable Presentation
4. Unknown DIDs are rejected with `401 Unauthorized`

This trust model is intentional for pre-SCA deployments. Once a Shadow
Certification Authority exists, full VP-based verification will be enforced.

### Outbound (proving identity)

Uses `shadownet.a2a.client.build_handshake_headers` from the SDK:
- Signs a JWT with the local private key
- Sets `audience` to the peer's DID
- Includes `A2A-Version` header

### MCP (agent connection)

The host agent connects to `/u/{shadowname}/mcp` with a Bearer JWT token.
The `BearerAuthMiddleware` validates the token before proxying to FastMCP.

## Message Flow

```
Outbound:
  Host Agent → social_send/social_respond/social_coordinate
    → build_envelope (shadownet/v1+envelope)
    → wrap in A2A message structure
    → POST to peer's /a2a/message:send
    → store as outbound InteractionContext

Inbound:
  Remote → POST /a2a/message:send
    → verify_inbound (SDK handshake check)
    → check grant (messaging permission)
    → extract envelope → store as inbound InteractionContext
    → signal inbox_wait subscribers
    → return 200 OK
```

The host agent receives inbound messages by long-polling via `social_inbox_wait`.

## Data Model

| Model | Purpose |
|-------|---------|
| **User** | Operator account for the management UI |
| **Contact** | Known remote agent (name, DID, endpoint, public key JWK, shadowname) |
| **AccessGrant** | Per-contact permission (messaging: allow/deny) |
| **InteractionContext** | Every message (data_type, direction, status, context_data JSON) |

### InteractionContext Lifecycle

| data_type | direction | status progression |
|-----------|-----------|-------------------|
| `coordination_request` | outbound | `sent` |
| `coordination_request` | inbound | `received` → `responded` |
| `response` | outbound | `sent` |
| `response` | inbound | `received` → `responded` (on confirm) |
| `confirmation` | outbound | `sent` |
| `confirmation` | inbound | `received` |

## Grant System

Binary allow/deny per contact. A contact with `grant_type=messaging` and
`allowed=True` can communicate. The transport layer does not filter by
`data_type` — the host agent interprets message types.

## File Layout

```
backend/app/
├── main.py              FastAPI application + lifespan
├── config.py            Settings (SHADOWNET_ env prefix)
├── database.py          SQLite engine (WAL mode)
├── models.py            User, Contact, AccessGrant, InteractionContext
├── executor.py          A2A envelope building + message dispatch
├── grants.py            Grant enforcement + contact lookup by DID
├── identity.py          Ed25519 keypair + DID:key derivation + agent card
├── signing.py           SDK handshake init, verify_inbound, outbound headers
├── connect.py           RFC-0008 integration bundle + connect pages
├── mcp_auth.py          Bearer auth middleware for MCP endpoint
├── deps.py              Auth dependencies (UI sessions)
├── mcp_server.py        MCP tool definitions (social_* tools)
├── mcp_run.py           MCP standalone HTTP runner (legacy port 8341)
└── routers/
    ├── a2a.py           /a2a/message:send endpoint
    ├── auth.py          User auth (register/login)
    ├── contacts.py      Contact CRUD API
    ├── interactions.py  Interaction list/detail API
    └── messages.py      Message history API

plugins/claude-code/     Claude Code MCP config + skills
frontend/                React + Vite management UI
```

## Envelope Format

Messages use the `shadownet/v1+envelope` format wrapped in a standard A2A
message structure:

```json
{
  "message": {
    "role": "ROLE_AGENT",
    "parts": [{
      "type": "data",
      "data": {
        "type": "shadownet/v1+envelope",
        "sender": "did:key:z6Mk...",
        "recipient": "did:key:z6Mk...",
        "interaction": "uuid",
        "timestamp": "2026-01-01T00:00:00Z",
        "payload": {
          "type": "coordination_request",
          "activity": "coffee",
          "details": "Friday morning"
        }
      }
    }]
  }
}
```

## Dependencies

- `shadownet[fastapi]>=0.3.0` — Protocol SDK (DID, handshake, SNS, trust, connect)
- FastAPI + uvicorn — HTTP server
- FastMCP — MCP server framework
- SQLModel — ORM (SQLAlchemy + Pydantic)
- httpx — Async HTTP client
- cryptography — Ed25519 key management
