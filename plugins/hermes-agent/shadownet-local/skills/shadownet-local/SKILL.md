---
name: shadownet-local
description: Agent-to-agent communication via shadownet-local MCP. Send messages, check inbox, respond to other agents.
version: 4.0.0
metadata:
  hermes:
    tags: [social, contacts, agent-to-agent, MCP, messaging, coordination]
    category: social
---

# shadownet-local — Agent-to-Agent Communication

Generic A2A messaging layer. shadownet-local handles transport, contacts, and
permissions. You handle all business logic.

## Coordination (meetings, coffee, dinner, etc.)

**If the user asks to plan, schedule, or coordinate a meeting, coffee,
dinner, or any activity with a contact: load `shadownet-local-coordination` skill.**

Do NOT use `social_send` for coordination. Use `social_coordinate()`.

## Available Tools

All tools are native MCP (prefixed `mcp_shadownet_local_`). Call them directly.

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
2. Webhook arrives → new session starts → you output to user → end session
3. User replies → new session starts → you call one tool → end session

Do NOT loop, sleep, or poll. Webhooks handle all notifications.

## Rules

- **Re-fetch contacts** before any operation. IDs can change.
- **Use coordination tools for meetups** — never `social_send`.
- **Don't narrate tool calls** — the user wants results, not play-by-play.
- **Don't poll** — never call `social_inbox` after sending. Webhooks notify you.
- **One tool call per session** for coordination flows.
