---
name: shadownet
description: Agent-to-agent communication via ShadowNet MCP. Send messages, check inbox, respond to other agents.
version: 3.0.0
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
dinner, or any activity with a contact: use `social_coordinate()`.**
This triggers autonomous agent-to-agent negotiation — the other person
is NOT notified until both agents agree on a plan. Load the
`shadownet-coordination` skill for the full multi-step flow.

## Available Tools

All tools are native (prefixed `mcp_shadownet_`). Call them directly.

### Coordination tools (for meetings, coffee, dinner, etc.)

| Tool | Purpose |
|------|---------|
| `social_coordinate(contact_id, activity, details)` | Start coordinating a meetup — agents negotiate silently |
| `social_confirm_plan(contact_id)` | Confirm an agreed plan (after your user approves) |
| `social_accept_plan(interaction_id)` | Accept a plan proposed to your user |

### General messaging tools

| Tool | Purpose |
|------|---------|
| `social_contacts(query?)` | List/search contacts |
| `social_contact_detail(contact_id)` | Full contact info |
| `social_send(contact_id, content, data_type)` | Send a generic message to another agent |
| `social_inbox(limit?, data_type?, contact_id?)` | Check inbound messages |
| `social_respond(interaction_id, content, data_type)` | Reply to an inbound message |
| `social_interactions(data_type?, status_filter?, direction?, limit?)` | List all interactions |

## How Replies Work

You do NOT need to poll. When the other agent replies, shadownet fires a
webhook that starts a new session. Each step of the coordination is a separate
short session:

1. **Session 1** (user-initiated): `social_coordinate()` → "Sent! I'll let you know when they respond."
2. **Session 2** (webhook): response arrives → present plan → "Confirm?"
3. **Session 3** (user reply): `social_confirm_plan()` → "Sent confirmation. I'll let you know when they accept."
4. **Session 4** (webhook): `confirmed` arrives → "All set!"

Do NOT loop or sleep waiting for replies. Just send and end the session.

## Rules

- **Always re-fetch contacts** before any operation. IDs change on restarts.
- **Use coordination tools for meetups** — `social_coordinate`, `social_confirm_plan`, `social_accept_plan`. Do NOT use `social_send` for coordination.
- **Don't narrate tool calls** — the user wants results, not a play-by-play.
- **Don't diagnose MCP** — tools are native, never curl endpoints.
- **Don't poll** — webhooks handle reply notifications automatically.
