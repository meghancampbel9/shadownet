---
name: shadownet-confirm
description: One-tap confirm a proposed ShadowNet plan.
version: 1.0.0
metadata:
  hermes:
    tags: [social, coordination]
    category: social
---

# Confirm Plan

The user wants to confirm a proposed plan from a ShadowNet coordination.

## Instructions

1. Call `social_confirm_plan()` — no arguments needed, it auto-finds the pending plan.
2. Output: "Confirmed! I'll let you know when they accept."
3. **DONE. End session.**

## Rules

- ONE tool call. No polling. No `social_inbox`.
- If the tool returns an error saying no pending plan exists, tell the user: "No pending plan to confirm right now. You'll get a notification when one arrives."
