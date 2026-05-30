# Design

## Purpose

Agent-to-agent communication Sidecar implementing the Shadownet v0.2 protocol.
Handles identity, transport, contacts, permissions, and message storage. Never
interprets message content — the host agent owns all business logic.

## Architecture

```
Host Agent ──MCP (Bearer access token)──► shadownet-local ──A2A message:send──► peer Sidecar
                                               │
                                          ┌────┴────┐
                                          │ SQLite  │
                                          │ Ed25519 │
                                          └─────────┘
```

Each instance manages:
- **Identity** — Ed25519 key encoded multibase (`z6Mk…`); the key is the identity
- **AgentCard** — self-signed direct-mode card at `/.well-known/agent-card.json`
  (or provider-signed at `/identity/<local>` in Shadowname mode)
- **Contact graph** — peers with identifier, endpoint, public key, grants, profile
- **Message store** — every inbound/outbound envelope persisted, keyed by
  `messageId` / `contextId`
- **MCP control surface** — RFC 0002 tools at `/u/<label>/mcp`
- **Onboarding** — RFC 0003 `shadow://connect`, handoff redemption, refresh

The SDK wire layer (`shadownet.receiver`, `shadownet.a2a`, `shadownet.agentcard`,
`shadownet.provider`) is synchronous; the async FastAPI app calls it through
`run_in_threadpool`.

## Identity and addressing (RFC 0001 §3, §5)

Two modes, both ride the same wire:

- **Direct** (default): identity = the Ed25519 key. The Sidecar self-signs its
  AgentCard and is reachable at `shadow://key:z6Mk…@host:port`. No DNS, no provider.
- **Shadowname**: the Sidecar acts as its own single-tenant provider for
  `provider_domain`. It publishes `_shadownet.<domain>` DNS TXT and serves a
  provider-signed AgentCard at `/identity/<local>`.

Outbound resolution supports either peer mode via `protocol.resolve_recipient`
(`parse_shadow_address` → provider/DNS or direct AgentCard fetch).

## Trust (RFC 0001 §6, §7)

- Inbound credentials (`org_affiliation` JWTs) are verified by the receiver
  pipeline against a configurable `TrustStore` and `AcceptancePolicy`
  (`fromContact` / `fromStranger`). The default trust store is empty.
- This Subject's own credentials load from `CREDENTIALS_PATH` and are attached
  to outbound envelopes (`creds`).

## Receiver pipeline (RFC 0001 §8.6, §9)

`/a2a/message:send` calls `shadownet.receiver.ReceiverPipeline.receive(body)`,
which validates the envelope JWS (typ/alg, claims, `kid==from`, signature),
recomputes `msgHash`, checks the replay cache, validates credentials, and
classifies the sender into `inbox`, `stranger_review`, or rejection. Storage is
backed by DB adapters (`DbReplayCache`, `DbContactGraph`) in `protocol.py`.
Errors serialize to RFC 7807 `application/problem+json` with
`urn:shadownet:error:<code>` types; classification state is never leaked.

`DbContactGraph` implements §9 auto-add: an inbound whose `contextId` matches a
recent outbound to that peer graduates the sender into the contact graph.

## Message flow

```
Outbound (executor.send_message):
  MCP tool (send/respond/coordinate/confirm_plan/accept_plan)
    → resolve_recipient(to)
    → mint EnvelopePayload + build_and_sign_message (msgHash + JWS)
    → send_envelope to peer /a2a/message:send  (re-mint iat/exp/messageId per retry, §8.10)
    → persist outbound Message + record (contextId, peer)

Inbound (routers/a2a.message_send):
  peer POST /a2a/message:send
    → ensure_extension_declared(A2A-Extensions)
    → ReceiverPipeline.receive (validate + classify)
    → persist inbound Message by route, wake inbox_wait
    → return A2A Message response (not a Task)
```

## Data model

| Model | Purpose |
|-------|---------|
| **User** | Operator account for the portal UI (issues access tokens) |
| **Contact** | Peer: identifier, public_key, endpoint, grants, profile, last_seen |
| **AccessGrant** | Per-contact permission (`messaging`: allow/deny) |
| **Message** | Inbound/outbound envelope (messageId, contextId, route, intent, body) |
| **ReplayEntry** | `(sender, messageId)` replay cache (RFC 0001 §8.9) |
| **OutboundContext** | `(contextId, peer)` log backing the §9 auto-add rule |
| **OnboardToken** | Opaque access / refresh / handoff tokens (RFC 0003) |

The coordinate→confirm→accept flow is expressed entirely through `body.intent`
URIs (`coordinate_v1` / `confirm_plan_v1` / `accept_plan_v1`) — there is no
`data_type` state machine.

## File layout

```
backend/app/
├── main.py          FastAPI app + lifespan
├── config.py        Settings (SHADOWNET_ env prefix)
├── database.py      SQLite engine (WAL); drops legacy v0.1 schema
├── models.py        User, Contact, AccessGrant, Message, ReplayEntry, OutboundContext, OnboardToken
├── identity.py      Ed25519 key + multibase pk + direct/provider AgentCard + connection URI
├── protocol.py      ReceiverPipeline + DB adapters + trust store + resolve_recipient
├── executor.py      Outbound envelope dispatch (+ §8.10 retry) + inbound persistence
├── grants.py        Contact lookup + messaging-grant check
├── onboarding.py    RFC 0003 shadow://connect mint + handoff/refresh + token validation
├── mcp_server.py    RFC 0002 bare-name MCP tools
├── mcp_auth.py      Access-token bearer middleware for the MCP mount
├── deps.py          Portal auth dependency
└── routers/
    ├── a2a.py       /a2a/message:send + AgentCard endpoints
    ├── auth.py      Portal register/login
    ├── contacts.py  Contact CRUD API
    └── messages.py  Message history API
```

## Envelope (RFC 0001 §8)

The envelope is a JWS-compact string (`typ: shadownet-env+jwt`) carried in the
A2A message's `metadata["urn:shadownet:0.2"]` and bound to the message via
`msgHash` (SHA-256 over the canonical message minus the Shadownet metadata key).
There is no `shadownet/v1+envelope` part type; the body lives in the JWS payload.

## Dependencies

- `shadownet>=0.5.0` — protocol SDK (envelope, agentcard, receiver, provider,
  credential, trust, onboarding, mcp models)
- FastAPI + uvicorn, FastMCP, SQLModel, httpx, PyJWT (portal tokens), cryptography
