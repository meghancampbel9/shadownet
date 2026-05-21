---
name: hermes-social-coordination
description: Coordinate meetups between agents via Hermes Social. Fully autonomous negotiation — agents use calendar and preference data to agree on a plan, then present it to users for one-tap confirmation.
version: 4.0.0
metadata:
  hermes:
    tags: [social, coordination, meetups, scheduling, agent-to-agent]
    category: social
---

# Social Coordination

Coordinate plans (coffee, dinner, meetings) with another person's agent.
Agents negotiate **fully autonomously** using each user's calendar,
preferences, and local knowledge. Users only see the final agreed plan.

## Roles

Every coordination has an **initiator** and a **receiver**.

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

### Step 2 — End the session

> Sent a coordination request to Test Friend with your availability and preferences. I'll notify you when we've agreed on a plan.

DONE. Do NOT poll. Webhook handles the rest.

### Step 3 — Handle the response (webhook session)

When the receiver's agent responds, it will contain an **agreed plan**
(the receiver's agent already matched calendars and preferences autonomously).

Present ONE clean message:

> ☕ Agreed with Test Friend: Coffee at Zazza (Lehrter Str 24e),
> Friday May 1 at 10am. Confirm?

### Step 4 — Send confirmation after user approves

```
social_send(contact_id, content=JSON.stringify({
  "status": "confirmed",
  "plan": { ... the agreed plan ... }
}), data_type="confirmation")
```

### Step 5 — Final notification (webhook)

When `confirmed` comes back → "All set! Coffee Friday 10am at Zazza."

---

## RECEIVER FLOW (another agent sent you a coordination request)

**THIS IS THE CRITICAL PART. You must negotiate AUTONOMOUSLY.**

### Step 1 — Read the request and YOUR user's data

The inbound message contains the initiator's availability, preferences,
and proposed dates/times. Load the **user-profile** skill to get YOUR
user's calendar, preferences, interests, and favorite venues.

### Step 2 — Find the best match AUTONOMOUSLY

Compare both users' data and pick the best option:
- Overlapping free time slots
- Shared interests or activities both enjoy
- A specific venue that fits (use your local knowledge)
- A concrete date, time, and place

DO NOT ask your user for input. YOU decide based on what you know.

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
  "reasoning": "Both free Friday May 1 morning. Zazza is in Mitte, has great reviews, matches the specialty coffee preference."
}), data_type="response")
```

**CRITICAL: Do NOT write ANY text to the user during this phase.**
Your only output is the social_respond tool call. Say nothing.
Do not explain your reasoning. Do not narrate. The user will be
notified later when the initiator's user confirms.

End the session immediately after the tool call.

### Step 4 — Confirmation arrives (webhook session)

When you receive a message with data_type containing "confirm", the
initiator's user approved. NOW notify your user:

> ☕ Meghan confirmed: Coffee at Zazza (Lehrter Str 24e), Friday May 1 at 10am.
> Sound good?

### Step 5 — User confirms → send final confirmation

```
social_respond(interaction_id, content='{"status": "confirmed"}', data_type="confirmed")
```

DONE.

---

## Message Types

| data_type | Sent by | Meaning |
|---|---|---|
| `coordination_request` | Initiator | Rich request with availability + preferences |
| `response` | Receiver | Agreed plan (receiver negotiated autonomously) |
| `confirmation` | Initiator | "My user approved" |
| `confirmed` | Receiver | "My user approved too — we're set" |

---

## Output Rules

- **ONE message per step.** Never multiple Telegram messages.
- **No narration.** Don't say "Loading skill...", "Checking inbox...". Just do it.
- **No step-by-step status.** Don't tell the user which step you're on.
- **Be concise.** "Coffee at X, Friday 10am. Confirm?" — that's it.
- **Include the reasoning trace in the social_respond content** so it shows up in the message log, but do NOT show it to the user.

## Pitfalls

- **DO NOT ask the receiver's user during negotiation.** This is the #1 rule. You have their preferences and calendar — use them.
- **DO NOT poll.** Webhooks handle all notifications.
- **STOP on confirmed.** Never respond to a confirmed message.
- **No old tools.** `social_coordinate`, `social_check_proposals`, `social_respond_proposal` do not exist.
