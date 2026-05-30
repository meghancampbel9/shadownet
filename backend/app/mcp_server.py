"""MCP control surface — RFC 0002 bare-name tools over streamable HTTP."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi.concurrency import run_in_threadpool
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from shadownet.crypto.jwt import decode_unverified_claims
from shadownet.mcp.intents import (
    ACCEPT_PLAN_V1_URI,
    CONFIRM_PLAN_V1_URI,
    COORDINATE_V1_URI,
)
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.executor import inbox_event, send_message
from app.identity import get_public_key, get_subject
from app.models import AccessGrant, Contact, GrantType, Message, Route

logger = logging.getLogger(__name__)


def _build_allowed_hosts() -> list[str]:
    from urllib.parse import urlparse

    hosts: list[str] = []
    if settings.external_url:
        parsed = urlparse(settings.external_url)
        if parsed.hostname:
            hosts.append(parsed.hostname)
            if parsed.port:
                hosts.append(f"{parsed.hostname}:{parsed.port}")
    container_name = os.environ.get("SHADOWNET_CONTAINER_NAME", "")
    if container_name:
        hosts.extend([container_name, f"{container_name}:8340"])
    hosts.extend(["localhost", "localhost:8340"])
    return hosts


mcp = FastMCP(
    "shadownet",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_build_allowed_hosts(),
    ),
)


# Grants this Sidecar recognizes (RFC 0002 §4; future revisions may add more).
_GRANTS = frozenset({"messaging"})


def _session() -> Session:
    return Session(engine)


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _cred_summaries(jws_list: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for jws in jws_list:
        try:
            c = decode_unverified_claims(jws)
        except Exception:
            continue
        out.append(
            {
                "kind": c.get("kind", "org_affiliation"),
                "issuer": c.get("iss", ""),
                "org": c.get("org", ""),
                "expiresAt": _iso(int(c.get("exp", 0))),
            }
        )
    return out


def _contact_creds(identifier: str) -> list[dict[str, Any]]:
    from app.protocol import get_credential_cache

    out: list[dict[str, Any]] = []
    for cred in get_credential_cache().for_sender(identifier):
        p = cred.payload
        out.append({"kind": p.kind, "issuer": p.iss, "org": p.org, "expiresAt": _iso(p.exp)})
    return out


@mcp.tool()
def identity() -> dict[str, Any]:
    """Return this Sidecar's identity (RFC 0002 §4)."""
    from app.protocol import own_credentials

    return {
        "shadowname": get_subject(),
        "pk": get_public_key(),
        "credentials": _cred_summaries(own_credentials()),
    }


@mcp.tool()
async def resolve(name: str) -> dict[str, Any]:
    """Resolve a Shadowname or shadow:// URI without adding to contacts."""
    from app.protocol import resolve_recipient

    try:
        identifier, endpoint, pk = await run_in_threadpool(resolve_recipient, name)
    except Exception as exc:
        return {"error": "resolve_failed", "detail": str(exc)}
    return {"shadowname": identifier, "pk": pk, "endpoint": endpoint}


@mcp.tool()
def contacts(query: str | None = None) -> dict[str, Any]:
    """List known contacts."""
    with _session() as s:
        rows = s.exec(select(Contact)).all()
        out = []
        for c in rows:
            if query:
                q = query.lower()
                if q not in c.identifier.lower() and q not in c.name.lower():
                    continue
            grant = s.exec(
                select(AccessGrant)
                .where(AccessGrant.contact_id == c.id)
                .where(AccessGrant.grant_type == GrantType.messaging)
            ).first()
            grants = ["messaging"] if (grant and grant.allowed) else []
            out.append(
                {
                    "shadowname": c.identifier,
                    "displayName": c.name or None,
                    "grants": grants,
                    "lastSeen": c.last_seen.isoformat() if c.last_seen else None,
                }
            )
        return {"contacts": out}


@mcp.tool()
def contact_detail(name: str) -> dict[str, Any]:
    """Full record for one contact."""
    import json

    with _session() as s:
        c = s.exec(select(Contact).where(Contact.identifier == name)).first()
        if c is None:
            return {"error": "not_contact"}
        grant = s.exec(
            select(AccessGrant)
            .where(AccessGrant.contact_id == c.id)
            .where(AccessGrant.grant_type == GrantType.messaging)
        ).first()
        grants = ["messaging"] if (grant and grant.allowed) else []
        profile = json.loads(c.profile_json) or None
        return {
            "shadowname": c.identifier,
            "displayName": c.name or None,
            "pk": c.public_key,
            "endpoint": c.agent_endpoint,
            "grants": grants,
            "credentials": _contact_creds(c.identifier),
            "profile": profile,
            "addedAt": c.added_at.isoformat(),
            "lastSeen": c.last_seen.isoformat() if c.last_seen else None,
        }


@mcp.tool()
async def add_contact(
    name: str,
    displayName: str | None = None,
    grants: list[str] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a Shadowname/URI and add it to the contact graph (RFC 0002 §4)."""
    import json

    from app.protocol import get_credential_cache, resolve_recipient

    try:
        identifier, endpoint, pk = await run_in_threadpool(resolve_recipient, name)
    except Exception:
        return {"error": "resolve_failed"}

    with _session() as s:
        if s.exec(select(Contact).where(Contact.identifier == identifier)).first():
            return {"error": "already_contact"}
        contact = Contact(
            identifier=identifier,
            name=displayName or identifier,
            public_key=pk,
            agent_endpoint=endpoint,
            profile_json=json.dumps(profile or {}),
        )
        s.add(contact)
        s.flush()
        for g in grants or ["messaging"]:
            s.add(AccessGrant(contact_id=contact.id, grant_type=g, allowed=True))
        s.commit()

    untrusted = _untrusted_issuers(get_credential_cache().for_sender(identifier))
    result: dict[str, Any] = {"shadowname": identifier}
    if untrusted:
        result["trustWarning"] = {"untrustedIssuers": untrusted}
    return result


def _untrusted_issuers(creds) -> list[str]:
    from app.protocol import get_pipeline

    store = get_pipeline().config.trust_store
    return sorted(
        {c.payload.iss for c in creds if not store.accepts(c.payload.iss, c.payload.kind)}
    )


@mcp.tool()
def grant(name: str, grant: str, allowed: bool) -> dict[str, Any]:
    """Set or clear a per-contact permission (RFC 0002 §4)."""
    if grant not in _GRANTS:
        return {"error": "unknown_grant"}
    with _session() as s:
        c = s.exec(select(Contact).where(Contact.identifier == name)).first()
        if c is None:
            return {"error": "not_contact"}
        existing = s.exec(
            select(AccessGrant)
            .where(AccessGrant.contact_id == c.id)
            .where(AccessGrant.grant_type == grant)
        ).first()
        if existing:
            existing.allowed = allowed
            s.add(existing)
        else:
            s.add(AccessGrant(contact_id=c.id, grant_type=grant, allowed=allowed))
        s.commit()
        return {"ok": True}


@mcp.tool()
def set_contact_profile(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Update the local-only profile on a contact (RFC 0002 §6)."""
    import json

    with _session() as s:
        c = s.exec(select(Contact).where(Contact.identifier == name)).first()
        if c is None:
            return {"error": "not_contact"}
        c.profile_json = json.dumps(profile)
        s.add(c)
        s.commit()
        return {"ok": True}


@mcp.tool()
async def send(to: str, body: dict[str, Any], contextId: str | None = None) -> dict[str, Any]:
    """Send a Shadownet envelope. End your turn after calling this."""
    result = await send_message(
        to,
        text=body.get("text"),
        intent=body.get("intent"),
        data=body.get("data"),
        context_id=contextId,
    )
    return {
        "messageId": result.message_id,
        "contextId": result.context_id,
        "status": result.status,
        "error": result.error,
    }


def _peer_for_context(context_id: str) -> str | None:
    with _session() as s:
        m = s.exec(
            select(Message)
            .where(Message.context_id == context_id)
            .where(Message.direction == "inbound")
            .order_by(Message.created_at.desc())
        ).first()
        return m.sender if m else None


@mcp.tool()
async def respond(contextId: str, body: dict[str, Any]) -> dict[str, Any]:
    """Respond within an existing thread (same contextId)."""
    peer = _peer_for_context(contextId)
    if peer is None:
        return {"messageId": "", "status": "rejected", "error": "unknown_context"}
    result = await send_message(
        peer,
        text=body.get("text"),
        intent=body.get("intent"),
        data=body.get("data"),
        context_id=contextId,
    )
    return {"messageId": result.message_id, "status": result.status, "error": result.error}


@mcp.tool()
async def coordinate(name: str, activity: str, details: str | None = None) -> dict[str, Any]:
    """Start a coordination flow with a contact (RFC 0002 §5.1). End your turn after."""
    data = {"activity": activity}
    if details:
        data["details"] = details
    text = f"Let's coordinate {activity}" + (f" — {details}" if details else "")
    result = await send_message(name, text=text, intent=COORDINATE_V1_URI, data=data)
    return {"messageId": result.message_id, "contextId": result.context_id}


@mcp.tool()
async def confirm_plan(name: str, contextId: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Confirm an agreed plan (RFC 0002 §5.2)."""
    result = await send_message(
        name,
        text=f"Confirming: {plan.get('activity', 'plan')} at {plan.get('when', '')}",
        intent=CONFIRM_PLAN_V1_URI,
        data=plan,
        context_id=contextId,
    )
    return {"messageId": result.message_id}


@mcp.tool()
async def accept_plan(name: str, contextId: str, acceptsMessageId: str) -> dict[str, Any]:
    """Accept a peer's confirmed plan (RFC 0002 §5.3)."""
    result = await send_message(
        name,
        text="Accepted.",
        intent=ACCEPT_PLAN_V1_URI,
        data={"acceptsMessageId": acceptsMessageId},
        context_id=contextId,
    )
    return {"messageId": result.message_id}


def _message_to_item(m: Message) -> dict[str, Any]:
    import json

    return {
        "messageId": m.message_id,
        "contextId": m.context_id,
        "from": m.sender,
        "receivedAt": m.created_at.isoformat(),
        "status": m.route,
        "body": json.loads(m.body_json),
    }


@mcp.tool()
def inbox(
    since: str | None = None,
    contact: str | None = None,
    intent: str | None = None,
    includeReview: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List pending inbound messages with full body content (RFC 0002 §4)."""
    routes = [Route.inbox, Route.stranger_review] if includeReview else [Route.inbox]
    with _session() as s:
        stmt = (
            select(Message)
            .where(Message.direction == "inbound")
            .where(Message.route.in_(routes))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        if contact:
            stmt = stmt.where(Message.sender == contact)
        if intent:
            stmt = stmt.where(Message.intent == intent)
        if since:
            cutoff = datetime.fromisoformat(since)
            stmt = stmt.where(Message.created_at > cutoff)
        rows = s.exec(stmt).all()
        items = [_message_to_item(m) for m in rows]
        next_since = rows[0].created_at.isoformat() if rows else since
        return {"items": items, "nextSince": next_since}


@mcp.tool()
async def inbox_wait(
    timeout_seconds: int | None = None, last_event_id: str | None = None
) -> dict[str, Any]:
    """Long-poll for inbox events (RFC 0002 §4, §7). RECOMMENDED inbound path."""
    timeout = min(timeout_seconds or 30, 90)
    deadline = time.time() + timeout
    cutoff = _parse_cursor(last_event_id)

    while time.time() < deadline:
        events, high_water = _drain_events(cutoff)
        if events:
            return {"events": events, "next_event_id": high_water}
        inbox_event.clear()
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(inbox_event.wait(), timeout=min(remaining, 2.0))
        except asyncio.TimeoutError:
            pass

    _, high_water = _drain_events(cutoff)
    return {"events": [], "next_event_id": high_water or last_event_id}


def _parse_cursor(cursor: str | None) -> datetime:
    # eventId is "<iso>|<messageRowId>"; the timestamp prefix drives the cursor.
    if cursor:
        try:
            return datetime.fromisoformat(cursor.split("|", 1)[0])
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _drain_events(cutoff: datetime) -> tuple[list[dict[str, Any]], str | None]:
    with _session() as s:
        rows = s.exec(
            select(Message)
            .where(Message.direction == "inbound")
            .where(Message.created_at > cutoff)
            .order_by(Message.created_at.asc())
            .limit(50)
        ).all()
    events = []
    high_water: str | None = None
    for m in rows:
        event_id = f"{m.created_at.isoformat()}|{m.id}"
        events.append(
            {
                "eventId": event_id,
                "event": "inbox.message",
                "occurredAt": int(m.created_at.timestamp()),
                "data": {
                    "messageId": m.message_id,
                    "contextId": m.context_id,
                    "from": m.sender,
                    "intent": m.intent or None,
                    "status": m.route,
                },
            }
        )
        high_water = event_id
    return events, high_water
