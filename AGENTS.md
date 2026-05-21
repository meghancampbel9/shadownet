# shadownet-local — Agent Guide

Instructions for AI coding assistants working on this codebase.

## What This Is

A single-tenant, self-hosted **Sidecar** implementing the Shadownet v0.1 protocol.
It sits between a host agent (Hermes, Claude Code, or any MCP-compatible framework)
and the network, handling identity, transport, contacts, permissions, message
storage, and webhook notifications.

The host agent owns all business logic. This sidecar never interprets message
content — it only routes, stores, and authenticates.

## Architecture

```
┌───────────────────────────────────────────────────┐
│  Host Machine / VPS                               │
│                                                   │
│  ┌───────────────────┐    ┌───────────────────┐  │
│  │ shadownet         │    │ shadownet-test    │  │
│  │ Port: 8340 (API)  │    │ Port: 8350 (API)  │  │
│  │ Port: 8341 (MCP)  │    │ Port: 8351 (MCP)  │  │
│  └────────┬──────────┘    └────────┬──────────┘  │
│           │ webhook                │ webhook      │
│           ▼                        ▼              │
│  ┌───────────────────┐    ┌───────────────────┐  │
│  │ Host Agent A      │    │ Host Agent B      │  │
│  │ (webhook port)    │    │ (webhook port)    │  │
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
├── notifications.py     Webhook dispatch (routing by data_type)
├── deps.py              Auth dependencies
├── mcp_server.py        MCP tool definitions (all social_* tools)
├── mcp_run.py           MCP standalone runner
└── routers/
    ├── a2a.py           A2A HTTP endpoints (/a2a/message:send)
    ├── auth.py          User auth (register/login)
    ├── contacts.py      Contact CRUD + API
    ├── interactions.py  Interaction list/detail
    └── messages.py      Message history

skills/social/
├── shadownet/SKILL.md               Base skill (identity, contacts, messaging)
└── shadownet-coordination/SKILL.md  Coordination skill (negotiate, confirm, accept)

frontend/src/                        React + Vite UI
```

## Key Concepts

### Webhook Routing

Inbound messages are routed to different host agent webhook endpoints based on `data_type`:

| data_type | Webhook route | deliver mode | Purpose |
|-----------|---------------|--------------|---------|
| `coordination_request` | `a2a-negotiate` | `log` (silent) | Agent handles autonomously |
| Everything else | `a2a-inbox` | `auto` (user-facing) | Delivered to user's chat |

Config vars: `NOTIFICATION_WEBHOOK_URL` (a2a-inbox), `NOTIFICATION_NEGOTIATE_URL` (a2a-negotiate).

### MCP Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `social_coordinate` | `(contactId, activity, details)` | Start coordination (sends `coordination_request`) |
| `social_respond` | `(intentId, payload)` | Reply to an interaction (payload is JSON string) |
| `social_confirm_plan` | `()` | Confirm a proposed plan (finds latest pending automatically) |
| `social_accept_plan` | `()` | Accept a confirmed plan (finds latest pending automatically) |
| `social_send` | `(contact_id, content, data_type)` | Send a generic message |
| `social_inbox` | `(limit, data_type, contact_id)` | List inbound messages |
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

Step 2: Sidecar B → Agent B (webhook: a2a-negotiate, deliver: log)
        Agent B loads user-profile skill, picks plan
        Agent B calls social_respond(intentId, payload='{"type":"response","status":"agreed","plan":{...}}')
        Sidecar B → Sidecar A: response

Step 3: Sidecar A → Agent A (webhook: a2a-inbox, deliver: auto)
        Agent A outputs plan summary to User A: "Coffee Friday 10am at The Daily Grind. Confirm?"
        (one-shot session, no tools called)

Step 4: User A → Agent A: "yes"
        Agent A calls social_confirm_plan() [no args needed]
        Sidecar A → Sidecar B: confirmation

Step 5: Sidecar B → Agent B (webhook: a2a-inbox, deliver: auto)
        Agent B outputs to User B: "A confirmed: Coffee Friday 10am. Accept?"
        (one-shot session, no tools called)

Step 6: User B → Agent B: "yes"
        Agent B calls social_accept_plan() [no args needed]
        Sidecar B → Sidecar A: confirmed

Step 7: Sidecar A → Agent A (webhook: a2a-inbox, deliver: auto)
        Agent A outputs to User A: "All set! Coffee Friday 10am at The Daily Grind."
        (one-shot session, no tools called)
```

## Development

```bash
cd backend
uv sync --group dev
cp .env.example .env  # then edit
uv run uvicorn app.main:app --host 0.0.0.0 --port 8340
uv run uvicorn app.mcp_run:app --host 0.0.0.0 --port 8341

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev

# Lint (must pass before push — CI enforces this)
cd backend && uv run ruff check .

# Tests
cd backend && uv run pytest tests/
```

## Deployment

Use `deploy.sh` (gitignored — copy from [`deploy.sh.example`](deploy.sh.example) and customize).
A deploy script should:

1. Rsync source to the target host
2. Sync skills to host agent containers
3. Build and restart sidecar containers
4. Wipe agent memory + sessions (prevents stale tool-failure beliefs)
5. Clear `interaction_contexts` tables (clean coordination state)
6. Restart host agent gateways

## E2E Testing (Social Coordination)

The full coordination flow can be tested programmatically using the host agent's
CLI (e.g., `hermes chat -q "..." -Q --yolo`). No messaging platform needed.

### Test Pattern

```bash
# Step 1: Initiator sends coordination request
docker exec <agent-b> hermes chat -q "coordinate drinks with <contact> friday" -Q --yolo --max-turns 5

# Verify: check sidecar-a logs for type=coordination_request
docker logs <sidecar-a> --since='1m ago' | grep 'A2A message:send'

# Wait ~15s for autonomous negotiation (Step 2)

# Verify: check sidecar-b logs for type=response received
docker logs <sidecar-b> --since='2m ago' | grep 'A2A message:send'

# Step 4: User confirms
docker exec <agent-b> hermes chat -q "yes confirm it" -Q --yolo --max-turns 5

# Step 6: Receiver accepts
docker exec <agent-a> hermes chat -q "yes accept" -Q --yolo --max-turns 5
```

### Database Verification

```bash
docker exec <sidecar> python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/shadownet.db')
rows = conn.execute('SELECT data_type, direction, status FROM interaction_contexts ORDER BY created_at DESC LIMIT 6').fetchall()
for r in rows: print(r)
conn.close()
"
```

Expected chain on initiator sidecar:
```
('coordination_request', 'outbound', 'sent')
('response', 'inbound', 'responded')
('confirmation', 'outbound', 'sent')
```

Expected on receiver sidecar:
```
('coordination_request', 'inbound', 'responded')
('response', 'outbound', 'sent')
('confirmation', 'inbound', 'received')
```

### Reset State Between Tests

```bash
# Clear interaction history
docker exec <sidecar> python3 -c "import sqlite3; c=sqlite3.connect('/app/data/shadownet.db'); c.execute('DELETE FROM interaction_contexts'); c.commit(); c.close()"

# Wipe agent memory + sessions (prevents stale beliefs)
docker exec <agent> sh -c 'echo "" > /opt/data/memories/MEMORY.md; rm -f /opt/data/sessions/session_*.json; echo "{}" > /opt/data/sessions/sessions.json'
```

## Common Failures

| Symptom | Check | Fix |
|---------|-------|-----|
| 401 on A2A send | Sidecar logs for `PresentationRequired` | Contact missing `did` in DB |
| Agent says "coordination failed" | Check if skill loaded in session | Wipe MEMORY.md, ensure skills synced |
| Webhook 401 | Sidecar logs for HTTP 401 on POST | Secret mismatch between .env and agent config |
| `social_confirm_plan` fails | Query `interaction_contexts` for `data_type='response', status='received'` | Payload missing `"type": "response"` |
| Agent loops/polls | Session shows `social_inbox` calls | Stale memory. Wipe and restart gateway. |
| "Instance not bound to Session" | SQLAlchemy detached error in logs | ORM object accessed outside `with _get_session()` |
| Gateway not running | `hermes status` | `hermes gateway stop; hermes gateway run --replace` |

## Known Constraints

- **No SCA infrastructure yet** — VP auth bypassed for known contacts via `_TrustedCache`
- **One-shot webhook sessions** — `deliver: auto` cannot call tools or wait for input
- **LLM non-determinism** — Agents may misinterpret. Wipe memory for clean state.
- **Auto-resolving tools** — `social_confirm_plan()` and `social_accept_plan()` find the most recent pending interaction when called with no arguments
- **Envelope format** — `{"message": {"role": "ROLE_AGENT", "parts": [{"type": "data", "data": {...}}]}}` wrapping `shadownet/v1+envelope`

## Dependencies

- `shadownet[fastapi]>=0.3.0` — Protocol SDK (DID, handshake, SNS, trust)
- FastAPI + uvicorn
- SQLModel (SQLAlchemy + Pydantic)
- httpx (async HTTP client)

See `backend/pyproject.toml` for the full list.
