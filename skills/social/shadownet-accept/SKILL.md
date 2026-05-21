---
name: shadownet-accept
description: One-tap accept a confirmed ShadowNet plan.
version: 1.0.0
metadata:
  hermes:
    tags: [social, coordination]
    category: social
---

# Accept Plan

The user wants to accept a confirmed plan from a ShadowNet coordination.

## Instructions

1. Call `social_accept_plan()` — no arguments needed, it auto-finds the pending confirmation.
2. Output: "Accepted! All set."
3. **DONE. End session.**

## Rules

- ONE tool call. No polling. No `social_inbox`.
- If the tool returns an error saying no pending confirmation exists, tell the user: "No pending plan to accept right now. You'll get a notification when one arrives."
