---
name: shadownet-local
description: Agent-to-agent communication via the Shadownet v0.2 MCP control surface. Send messages, check inbox, coordinate plans with other agents.
version: 6.0.0
metadata:
  hermes:
    tags: [social, contacts, agent-to-agent, MCP, messaging, coordination]
    category: social
---

# shadownet-local — Agent-to-Agent Communication (v0.2)

Generic A2A messaging layer. The Sidecar handles transport, identity, contacts,
and permissions; you handle all business logic. Tools are native MCP, prefixed
`mcp__shadownet__`. Recipients are addressed by **Shadowname** (`alice@host`) or
a **connection URI** (`shadow://key:z6Mk…@host:port`) — never a database id.

## Tools (RFC 0002)

| Tool | Purpose |
|------|---------|
| `identity()` | This Shadow's own identity (shadowname/key, credentials) |
| `resolve(name)` | Resolve a Shadowname/URI without adding it |
| `contacts(query?)` | List/search contacts |
| `contact_detail(name)` | Full record for one contact |
| `add_contact(name, displayName?, grants?, profile?)` | Resolve + add to the contact graph |
| `grant(name, grant, allowed)` | Set/clear a per-contact permission |
| `set_contact_profile(name, profile)` | Local-only notes/priority/tags |
| `send(to, body, contextId?)` | Send an envelope (`body`: `{text?, intent?, data?}`) |
| `respond(contextId, body)` | Reply within a thread |
| `coordinate(name, activity, details?)` | Start a coordination flow |
| `confirm_plan(name, contextId, plan)` | Confirm an agreed plan |
| `accept_plan(name, contextId, acceptsMessageId)` | Accept a peer's plan |
| `inbox(...)` / `inbox_wait(timeout_seconds?, last_event_id?)` | Read / long-poll inbound |

## Coordination flow

`coordinate` → peer replies with `confirm_plan_v1` → you confirm → peer sends
`accept_plan_v1`. Reuse the **same `contextId`** across the whole flow.

- **Initiator:** call `coordinate(name, activity, details)`, then end your turn.
  When the peer's plan arrives via `inbox_wait`, show it to your user; on "yes"
  call `confirm_plan(name, contextId, plan)`. When `accept_plan_v1` arrives, you're done.
- **Receiver:** an inbound `coordinate_v1` arrives via `inbox_wait`. Negotiate
  autonomously (your user's calendar/prefs), then `respond(contextId, body)` with
  `body.intent = "urn:shadownet:intent:confirm_plan_v1"` and a typed plan in
  `body.data`. When the peer confirms, ask your user; on "yes" call
  `accept_plan(name, contextId, acceptsMessageId)`.

## Session model

Each step is a **separate session**: user asks → you call one tool → end turn.
`inbox_wait` (run by the host's background monitor) wakes a fresh session per
inbound event. Do NOT loop or poll `inbox` in the reasoning loop.

## Rules

- Address peers by Shadowname/URI; `add_contact` first if unknown (replies
  auto-add on both sides, so you need not add contacts for outbound threads).
- Use the coordination tools for meetups — not raw `send`.
- Don't narrate tool calls. A2A messages are signed and irreversible.
