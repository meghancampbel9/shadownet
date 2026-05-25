# shadownet-local — Agent Guide

Instructions for AI coding assistants working on this codebase.

## What This Is

A single-tenant, self-hosted **Sidecar** implementing the Shadownet v0.1 protocol.
It sits between a host agent (Hermes, Claude Code, or any MCP-compatible framework)
and the network, handling identity, transport, contacts, permissions, and message
storage.

The host agent connects via the plugin model (long-poll MCP with Bearer auth).
This sidecar never interprets message content — it only routes, stores, and authenticates.

## Architecture

```
┌───────────────────────────────────────────────────┐
│  Host Machine / VPS                               │
│                                                   │
│  ┌───────────────────┐    ┌───────────────────┐  │
│  │ shadownet         │    │ shadownet-test    │  │
│  │ Port: 8340 (API)  │    │ Port: 8350 (API)  │  │
│  │ /u/{name}/mcp     │    │ /u/{name}/mcp     │  │
│  └────────┬──────────┘    └────────┬──────────┘  │
│           │ long-poll             │ long-poll     │
│           ▼                        ▼              │
│  ┌───────────────────┐    ┌───────────────────┐  │
│  │ Host Agent A      │    │ Host Agent B      │  │
│  │ (plugin)          │    │ (plugin)          │  │
│  └───────────────────┘    └───────────────────┘  │
└───────────────────────────────────────────────────┘
```

The test instance (`shadownet-test`) is optional — used for A2A testing between
two sidecars on the same machine.

## File Layout

```
backend/app/
├── main.py              FastAPI application + lifespan
├── config.py            Settings (SHADOWNET_ env prefix)
├── database.py          SQLite engine + WAL mode
├── models.py            User, Contact, AccessGrant, InteractionContext
├── executor.py          A2A message building + inbound processing
├── grants.py            Grant enforcement + contact lookup
├── identity.py          Ed25519 keypair + DID + agent card
├── signing.py           SDK handshake verification + outbound headers
├── connect.py           RFC-0008 integration bundle + connect pages
├── mcp_auth.py          Bearer auth middleware for /u/{name}/mcp
├── deps.py              Auth dependencies
├── mcp_server.py        MCP tool definitions (all social_* tools)
├── mcp_run.py           MCP standalone runner (port 8341, legacy)
└── routers/
    ├── a2a.py           A2A HTTP endpoints (/a2a/message:send)
    ├── auth.py          User auth (register/login)
    ├── contacts.py      Contact CRUD + API
    ├── interactions.py  Interaction list/detail
    └── messages.py      Message history

frontend/src/                        React + Vite UI
plugins/claude-code/                 Claude Code MCP config + skills
```

## Key Concepts

### Agent Connection

Agents connect to the sidecar via the authenticated MCP endpoint at
`/u/{shadowname}/mcp` using a Bearer JWT token. The agent uses `social_inbox_wait`
for long-polling inbound messages.

The integration bundle endpoint (`/v1/account/me/integration-bundle`) provides
all config needed for plugin auto-discovery (RFC-0008).

### MCP Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `social_coordinate` | `(contactId, activity, details)` | Start coordination (sends `coordination_request`) |
| `social_respond` | `(intentId, payload)` | Reply to an interaction (payload is JSON string) |
| `social_confirm_plan` | `()` | Confirm a proposed plan (finds latest pending automatically) |
| `social_accept_plan` | `()` | Accept a confirmed plan (finds latest pending automatically) |
| `social_send` | `(contactId, payload)` | Send a message (payload: dict or str) |
| `social_inbox` | `(limit, data_type, contact_id)` | List inbound messages |
| `social_inbox_wait` | `(timeout_seconds, last_event_id)` | Long-poll for new messages |
| `social_contacts` | `(query)` | List/search contacts |
| `social_contact_detail` | `(contact_id)` | Get contact details |
| `social_interactions` | `(data_type, status_filter, direction, limit)` | List interactions |

### InteractionContext States

Each message exchange is tracked as an `InteractionContext` row:

| Field | Values |
|-------|--------|
| `data_type` | `coordination_request`, `response`, `confirmation`, `confirmed`, `message` |
| `direction` | `inbound`, `outbound` |
| `status` | `sent`, `received`, `responded` |

### A2A Authentication

Uses the SDK's `verify_handshake`. Known contacts (those with a `did` in the DB)
are pre-authorized via a `_TrustedCache` — no Verifiable Presentation needed.
Unknown DIDs are rejected. This is the intended solution until SCA infrastructure exists.

## Social Coordination Flow

The full coordination flow between two agents (7 steps, 4 require user interaction):

```
Step 1: User A → Agent A: "coordinate dinner with B"
        Agent A calls social_coordinate(contactId, activity, details)
        Sidecar A → Sidecar B: coordination_request

Step 2: Sidecar B → Agent B (via inbox_wait event)
        Agent B loads coordination skill, picks plan
        Agent B calls social_respond(intentId, payload='{"type":"response","status":"agreed","plan":{...}}')
        Sidecar B → Sidecar A: response

Step 3: Sidecar A → Agent A (via inbox_wait event)
        Agent A outputs plan summary to User A: "Coffee Friday 10am at The Daily Grind. Confirm?"

Step 4: User A → Agent A: "yes"
        Agent A calls social_confirm_plan() [no args needed]
        Sidecar A → Sidecar B: confirmation

Step 5: Sidecar B → Agent B (via inbox_wait event)
        Agent B outputs to User B: "A confirmed: Coffee Friday 10am. Accept?"

Step 6: User B → Agent B: "yes"
        Agent B calls social_accept_plan() [no args needed]
        Sidecar B → Sidecar A: confirmed

Step 7: Sidecar A → Agent A (via inbox_wait event)
        Agent A outputs to User A: "All set! Coffee Friday 10am at The Daily Grind."
```

## Development

```bash
cd backend
uv sync --group dev
cp .env.example .env  # then edit
uv run uvicorn app.main:app --host 0.0.0.0 --port 8340

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev

# Lint (must pass before push — CI enforces this)
cd backend && uv run ruff check . && uv run ruff format --check .

# Tests
cd backend && uv run pytest tests/
```

## Deployment

Use `deploy.sh` to sync and restart containers on the target host. A deploy:

1. Rsyncs source to the target host (excluding .env, data, node_modules)
2. Builds and restarts sidecar containers via docker compose

## E2E Testing (Social Coordination)

The full coordination flow can be tested programmatically using the host agent's
CLI (e.g., `hermes chat -q "..." -Q --yolo`). No messaging platform needed.

### Test Pattern

```bash
# Step 1: Initiator sends coordination request
docker exec <agent-b> hermes chat -q "coordinate drinks with <contact> friday" -Q --yolo --max-turns 5

# Wait ~15s for autonomous negotiation (Step 2)

# Verify: check sidecar DB for interactions
docker exec <sidecar-a> python3 -c "
import sqlite3; c=sqlite3.connect('/app/data/shadownet.db')
for r in c.execute('SELECT data_type, direction, status FROM interaction_contexts ORDER BY created_at DESC LIMIT 6').fetchall():
    print(r)
c.close()
"

# Step 4: User confirms
docker exec <agent-a> hermes chat -q "yes confirm it" -Q --yolo --max-turns 5

# Step 6: Receiver accepts
docker exec <agent-b> hermes chat -q "yes accept" -Q --yolo --max-turns 5
```

### Reset State Between Tests

```bash
# Clear interaction history
docker exec <sidecar> python3 -c "import sqlite3; c=sqlite3.connect('/app/data/shadownet.db'); c.execute('DELETE FROM interaction_contexts'); c.commit(); c.close()"
```

## Common Failures

| Symptom | Check | Fix |
|---------|-------|-----|
| 401 on A2A send | Sidecar logs for `PresentationRequired` | Contact missing `did` in DB |
| Agent says "coordination failed" | Check if plugin connected | Verify `SHADOWNET_TOKEN` and MCP endpoint |
| `social_confirm_plan` fails | Query `interaction_contexts` for `data_type='response', status='received'` | Payload missing `"type": "response"` |
| "Instance not bound to Session" | SQLAlchemy detached error in logs | ORM object accessed outside `with _get_session()` |

## Known Constraints

- **No SCA infrastructure yet** — VP auth bypassed for known contacts via `_TrustedCache`
- **LLM non-determinism** — Agents may misinterpret tool outputs
- **Auto-resolving tools** — `social_confirm_plan()` and `social_accept_plan()` find the most recent pending interaction when called with no arguments
- **Envelope format** — `{"message": {"role": "ROLE_AGENT", "parts": [{"type": "data", "data": {...}}]}}` wrapping `shadownet/v1+envelope`

## Dependencies

- `shadownet[fastapi]>=0.3.0` — Protocol SDK (DID, handshake, SNS, trust, connect)
- FastAPI + uvicorn
- SQLModel (SQLAlchemy + Pydantic)
- httpx (async HTTP client)
- FastMCP (MCP server framework)

See `backend/pyproject.toml` for the full list.
