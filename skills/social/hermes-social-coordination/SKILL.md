---
name: hermes-social-coordination
description: Coordinate meetups between agents via Hermes Social. Fully autonomous negotiation — agents use calendar and preference data to agree on a plan, then present it to users for one-tap confirmation.
version: 6.0.0
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

### Step 1 — Gather context and send a rich request

Load the **user-profile** skill to get your user's calendar, preferences,
interests, and favorite venues. Then send a RICH request:

```
social_send(contact_id, content=JSON.stringify({
  "activity": "coffee",
  "proposed_dates": ["Friday May 1", "Friday May 8"],
  "proposed_times": ["9:00-12:00"],
  "location_area": "Berlin Mitte",
  "initiator_preferences": {
    "interests": ["specialty coffee", "brunch", "walks"],
    "dietary": "none",
    "vibe": "casual, relaxed morning"
  },
  "initiator_availability": {
    "Friday May 1": "free 9am-1pm",
    "Friday May 8": "free 9am-11am"
  },
  "flexibility": "open to other suggestions"
}), data_type="coordination_request")
```

### Step 2 — Tell the user and END the session

Output ONE message:

> Sent a coordination request to [contact]. I'll notify you when we've agreed on a plan.

DONE. Do NOT poll. A webhook will start a new session when the response arrives.

### Step 3 — Present the agreed plan (webhook: data_type=response)

The receiver's agent sent back an agreed plan. Present it to the user:

> Agreed with Test Friend: Coffee at Zazza (Lehrter Str 24e),
> Friday May 1 at 10am. Confirm?

Wait for the user to confirm, then:

```
social_send(contact_id, content=JSON.stringify({
  "status": "confirmed",
  "plan": { ... the agreed plan ... }
}), data_type="confirmation")
```

Output: "Sent! You'll be notified when they accept." DONE.

### Step 4 — Final confirmation (webhook: data_type=confirmed)

Output ONE message:

> All set! Coffee with Test Friend — Friday May 1 at 10am, Zazza.

DONE. The coordination is complete.

---

## RECEIVER FLOW (another agent sent a coordination request)

### Step 1 — Read the request and YOUR user's data

The inbound message contains the initiator's availability, preferences,
and proposed dates/times. Load the **user-profile** skill to get YOUR
user's calendar, preferences, interests, and favorite venues.

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

Wait for user response. If they accept:

```
social_respond(interaction_id, content='{"status": "confirmed"}', data_type="confirmed")
```

Output: "Confirmed! Enjoy." DONE — this is the final step, nothing else happens.

---

## Message Types

| data_type | Sent by | Meaning |
|---|---|---|
| `coordination_request` | Initiator | Rich request with availability + preferences |
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

- **DO NOT ask the receiver's user during negotiation.** You have their preferences and calendar — use them.
- **DO NOT poll.** Webhooks handle all notifications.
- **STOP on confirmed.** Never respond to a confirmed message.
- **No old tools.** `social_coordinate`, `social_check_proposals`, `social_respond_proposal` do not exist.
