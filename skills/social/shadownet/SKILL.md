---
name: shadownet
description: Agent-to-agent communication via ShadowNet MCP. Send messages, check inbox, respond to other agents.
version: 4.0.0
metadata:
  hermes:
    tags: [social, contacts, agent-to-agent, MCP, messaging, coordination]
    category: social
---

# ShadowNet — Agent-to-Agent Communication

Generic A2A messaging layer. shadownet handles transport, contacts, and
permissions. You handle all business logic.

## Coordination (meetings, coffee, dinner, etc.)

**If the user asks to plan, schedule, or coordinate a meeting, coffee,
dinner, or any activity with a contact: load `shadownet-coordination` skill.**

Do NOT use `social_send` for coordination. Use `social_coordinate()`.

## Available Tools

All tools are native MCP (prefixed `mcp_shadownet_`). Call them directly.

### Coordination tools

| Tool | Purpose |
|------|---------|
| `social_coordinate(contactId, activity, details)` | Start coordinating — agents negotiate silently |
| `social_confirm_plan()` | Confirm an agreed plan (after your user approves) |
| `social_accept_plan()` | Accept a plan proposed to your user |

### General messaging tools

| Tool | Purpose |
|------|---------|
| `social_contacts(query?)` | List/search contacts |
| `social_contact_detail(contact_id)` | Full contact info |
| `social_send(contact_id, content, data_type)` | Send a generic message |
| `social_inbox(limit?, data_type?, contact_id?)` | Check inbound messages |
| `social_respond(intentId, payload)` | Reply to an interaction (payload is JSON string) |
| `social_interactions(data_type?, status_filter?, direction?, limit?)` | List all interactions |

## Session Model

Each step of a coordination is a **separate session**:

1. User asks → you call one tool → output result → end session
2. `social_inbox_wait` picks up a message → new session starts → you output to user → end session
3. User replies → new session starts → you call one tool → end session

Do NOT loop or sleep. Use `social_inbox_wait` for notifications.

## Rules

- **Re-fetch contacts** before any operation. IDs can change.
- **Use coordination tools for meetups** — never `social_send`.
- **Don't narrate tool calls** — the user wants results, not play-by-play.
- **Don't poll** — use `social_inbox_wait` to be notified of new messages.
- **One tool call per session** for coordination flows.
