---
name: hermes-social
description: Agent-to-agent communication via Hermes Social MCP. Send messages, check inbox, respond to other agents.
version: 2.1.0
metadata:
  hermes:
    tags: [social, contacts, agent-to-agent, MCP, messaging, coordination]
    category: social
---

# Hermes Social — Agent-to-Agent Communication

Generic A2A messaging layer. hermes-social handles transport, contacts, and
permissions. You handle all business logic.

## Available Tools

All tools are native (prefixed `mcp_hermes_social_`). Call them directly.

| Tool | Purpose |
|------|---------|
| `social_contacts(query?)` | List/search contacts |
| `social_contact_detail(contact_id)` | Full contact info |
| `social_send(contact_id, content, data_type)` | Send a message to another agent |
| `social_inbox(limit?, data_type?, contact_id?)` | Check inbound messages |
| `social_respond(interaction_id, content, data_type)` | Reply to an inbound message |
| `social_interactions(data_type?, status_filter?, direction?, limit?)` | List all interactions |

## How Replies Work

You do NOT need to poll. When the other agent replies, hermes-social fires a
webhook that starts a new session. Each step of the coordination is a separate
short session:

1. **Session 1** (user-initiated): send request → "Sent! I'll let you know when they respond."
2. **Session 2** (webhook): response arrives → present plan → "Confirm?"
3. **Session 3** (user reply): send confirmation → "Waiting for final confirmation."
4. **Session 4** (webhook): `confirmed` arrives → "All set!"

Do NOT loop or sleep waiting for replies. Just send and end the session.

## Rules

- **Always re-fetch contacts** before any operation. IDs change on restarts.
- **No old tools** — `social_coordinate`, `social_check_proposals`, `social_respond_proposal` do not exist.
- **Don't narrate tool calls** — the user wants results, not a play-by-play.
- **Don't diagnose MCP** — tools are native, never curl endpoints.
- **Don't poll** — webhooks handle reply notifications automatically.
