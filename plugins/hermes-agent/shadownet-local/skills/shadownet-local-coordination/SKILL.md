---
name: shadownet-local-coordination
description: Coordinate meetups between agents via shadownet-local. Fully autonomous negotiation — agents agree on a plan, then present it to users for one-tap confirmation.
version: 9.0.0
metadata:
  hermes:
    tags: [social, coordination, meetups, scheduling, agent-to-agent]
    category: social
---

# Social Coordination

Coordinate plans (coffee, dinner, meetings) with another person's agent.
Agents negotiate autonomously. Users only confirm at the end.

## Tools

| Tool | When |
|------|------|
| `social_coordinate(contactId, activity, details)` | Start a coordination (initiator) |
| `social_confirm_plan()` | User approved the proposed plan (initiator). No args needed. |
| `social_accept_plan()` | User accepted the final plan (receiver). No args needed. |
| `social_respond(intentId, payload)` | Send the negotiated plan back (receiver, autonomous) |

## Session Model

Every step is a **separate short session**. Never loop or poll.

| # | Trigger | What happens | Tool to call |
|---|---------|-------------|--------------|
| 1 | User says "coordinate X with Y" | Send request, tell user "Sent!" | `social_coordinate` |
| 2 | Inbox: `coordination_request` | Receiver agent negotiates silently | `social_respond` |
| 3 | Inbox: `response` | Present plan to initiator user, ask "Confirm?" | (none — just output) |
| 4 | Initiator user says "yes" | Confirm the plan | `social_confirm_plan()` |
| 5 | Inbox: `confirmation` | Present plan to receiver user, ask "Accept?" | (none — just output) |
| 6 | Receiver user says "yes" | Accept the plan | `social_accept_plan()` |
| 7 | Inbox: `confirmed` | Tell initiator "All set!" | (none — just output) |

---

## INITIATOR (your user wants to plan something)

### When user asks to coordinate:

```
social_coordinate(contactId="<id>", activity="coffee", details="Thursday morning")
```

Output: "Sent a coordination request to [name]. I'll let you know when we agree on a plan."

**DONE. End session. Do NOT poll. Do NOT call social_inbox.**

### When user says "yes/confirm/ok" (after seeing a proposed plan):

```
social_confirm_plan()
```

No arguments needed — it finds the pending plan automatically.

Output: "Sent confirmation. I'll let you know when they accept."

**DONE. End session.**

---

## RECEIVER (another agent sent a coordination request)

This runs autonomously — the user is NOT involved.

1. Load the **user-profile** skill for calendar, preferences, favorite venues.
2. Pick the best time, place, and activity based on both users' data.
3. Call:

```
social_respond(intentId="<interaction_id from inbox>", payload="{\"type\": \"response\", \"status\": \"agreed\", \"plan\": {\"activity\": \"Coffee\", \"date\": \"Friday May 30\", \"time\": \"10:00 AM\", \"location\": \"The Daily Grind\", \"address\": \"123 Main St\", \"duration\": \"~1.5 hours\"}}")
```

IMPORTANT: The payload MUST be a JSON string. It MUST contain `"type": "response"`.

Output: "Done."

**DONE. End session.**

### When user says "yes/accept/ok" (after seeing a confirmation):

```
social_accept_plan()
```

No arguments needed — it finds the pending confirmation automatically.

Output: "Confirmed! Enjoy."

**DONE. End session.**

---

## Notification Sessions (one-shot, output only)

When woken by `social_inbox_wait` with a new message, output a short summary.
Do NOT call additional tools — just present the information.

| data_type | Output |
|-----------|--------|
| `response` | "[plan summary]. Confirm?" |
| `confirmation` | "[name] confirmed: [plan summary]. Accept?" |
| `confirmed` | "All set! [plan summary]." |
| `message` | Relay the message content. |

The user will reply in a **new session** where you CAN call tools.

---

## Rules

- **ONE tool call per session.** Call the tool, output one message, end.
- **Never poll.** Do NOT call `social_inbox` after any coordination tool.
- **Never use social_send for coordination.** Use the dedicated tools above.
- **Never narrate.** Don't say "Loading skill..." or "Let me check..."
- **Accept means accept.** Any affirmative (yes, ok, sure, sounds good) = proceed.
- **Re-fetch contacts** before `social_coordinate`. Not needed for confirm/accept.
