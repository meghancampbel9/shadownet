---
name: shadownet-coordination
description: Coordinate meetups between agents via ShadowNet. Fully autonomous negotiation — agents use calendar and preference data to agree on a plan, then present it to users for one-tap confirmation.
version: 7.0.0
metadata:
  hermes:
    tags: [social, coordination, meetups, scheduling, agent-to-agent]
    category: social
---

# Social Coordination

Coordinate plans (coffee, dinner, meetings) with another person's agent.
Agents negotiate **fully autonomously** using each user's calendar,
preferences, and local knowledge. Users are only involved at the end to
confirm.

## Roles

Every coordination has an **initiator** and a **receiver**.

---

## Tools

| Tool | When to use |
|------|-------------|
| `social_coordinate(contact_id, activity, details)` | Initiator Step 1: start a coordination |
| `social_confirm_plan(contact_id)` | Initiator Step 3: user approved the plan |
| `social_accept_plan(interaction_id)` | Receiver Step 4: user accepted the plan |

These tools handle all data formatting, routing, and state management
automatically. Do NOT use `social_send` or `social_respond` for
coordination flows.

---

## WEBHOOK SESSION ROUTING

When woken by a webhook, identify which step you're in by `data_type`:

| data_type | You are | What to do |
|---|---|---|
| `coordination_request` | Receiver | Go to RECEIVER FLOW Step 1 |
| `response` | Initiator | Go to INITIATOR FLOW Step 3 |
| `confirmation` | Receiver | Go to RECEIVER FLOW Step 4 |
| `confirmed` | Initiator | Go to INITIATOR FLOW Step 4 |

**Rules for ALL webhook sessions:**
- Do NOT narrate your reasoning or explain what you are doing.
- ONE short message to the user per step. Nothing else.
- Do NOT quote skill instructions or routing logic.
- Be concise: "Coffee at X, Friday 10am. Confirm?" — that's it.

---

## INITIATOR FLOW (your user asked to plan something)

### Step 1 — Send the coordination request

```
social_coordinate(contact_id, activity="coffee", details="Thursday morning before work")
```

### Step 2 — Tell the user and END the session

Output ONE message:

> Sent a coordination request to [contact]. I'll notify you when we've agreed on a plan.

DONE. Do NOT poll. Do NOT call social_inbox. A webhook will start a new
session when the response arrives.

### Step 3 — Present the agreed plan (webhook: data_type=response)

The receiver's agent sent back an agreed plan. Present it to the user
concisely and ask them to confirm:

> Coffee at Zazza (Lehrter Str 24e), Friday May 1 at 10am. Confirm?

Output ONLY that question. **STOP. Do NOT call any tool yet.** Wait for
the user to reply.

When the user confirms (yes, ok, confirm, sure, sounds good), call:

```
social_confirm_plan(contact_id)
```

Output EXACTLY: **"Sent confirmation. I'll let you know when they accept."**

**WARNING**: The plan is NOT finalized yet. Do NOT say "confirmed" or
"all set" at this stage.

### Step 4 — Final confirmation (webhook: data_type=confirmed)

Output ONE message:

> All set! Coffee with Test Friend — Friday May 1 at 10am, Zazza.

DONE. The coordination is complete.

---

## RECEIVER FLOW (another agent sent a coordination request)

### Step 1 — Read the request and YOUR user's data

The inbound message contains the initiator's activity and details.
Load the **user-profile** skill to get YOUR user's calendar, preferences,
interests, and favorite venues.

### Step 2 — Find the best match AUTONOMOUSLY

Compare both users' data and pick the best option:
- Overlapping free time slots
- Shared interests or activities both enjoy
- A specific venue that fits (use your local knowledge or web search)
- A concrete date, time, and place

DO NOT ask your user. YOU decide based on what you know.

### Step 3 — Respond with the agreed plan

```
social_respond(interaction_id, content=JSON.stringify({
  "status": "agreed",
  "plan": {
    "activity": "Coffee",
    "date": "Friday May 1",
    "time": "10:00 AM",
    "location": "Zazza",
    "address": "Lehrter Str 24e, Berlin Mitte",
    "duration": "~1.5 hours",
    "notes": "Great specialty coffee, opens 7:30am"
  },
  "reasoning": "Both free Friday morning. Zazza matches specialty coffee interest."
}), data_type="response")
```

Output exactly: "Done."

DONE. End the session. The user is NOT notified at this stage.

### Step 4 — Ask user to accept (webhook: data_type=confirmation)

The initiator's user approved the plan. NOW notify your user:

> [Name] wants to meet: Coffee at Zazza (Lehrter Str 24e),
> Friday May 1 at 10am. Accept?

Output ONLY that message. **STOP. Do NOT call any tool yet.** Wait for
the user to reply.

When the user accepts (yes, accept, ok, sure, sounds good), call:

```
social_accept_plan(interaction_id="<from webhook>")
```

Output: "Confirmed! Enjoy." DONE.

---

## Message Types

| data_type | Sent by | Meaning |
|---|---|---|
| `coordination_request` | Initiator | Request with activity + details |
| `response` | Receiver | Agreed plan (receiver negotiated autonomously) |
| `confirmation` | Initiator | "My user approved this plan" |
| `confirmed` | Receiver | "My user approved too — we're set" |

---

## Output Rules

- **ONE message per step.** Never multiple messages.
- **No narration.** Don't say "Loading skill...", "Checking inbox...". Just do it.
- **Be concise.** "Coffee at X, Friday 10am. Confirm?" — that's it.
- **Receiver negotiation is SILENT.** Steps 1-3 of the receiver flow run without user-visible output. Output "Done." after the tool call to satisfy the framework.

## Pitfalls

- **Use the purpose-built tools.** `social_coordinate` to start, `social_confirm_plan` to confirm, `social_accept_plan` to accept. Do NOT use `social_send` for coordination.
- **DO NOT ask the receiver's user during negotiation.** You have their preferences and calendar — use them.
- **DO NOT poll.** Do NOT call `social_inbox` after sending. Webhooks handle all notifications.
- **DO NOT say "confirmed" prematurely.** After confirming (Step 3), the plan is NOT final. Say "Sent confirmation. I'll let you know when they accept."
- **Accept means accept.** When you ask a user to confirm/accept and they reply with ANY affirmative (yes, ok, accept, sure, sounds good), act on it. Do not ask for clarification.
- **STOP on confirmed.** Never respond to a confirmed message.
- **No old tools.** `social_coordinate_old`, `social_check_proposals`, `social_respond_proposal` do not exist.
