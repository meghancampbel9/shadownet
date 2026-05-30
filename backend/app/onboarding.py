"""RFC 0003 onboarding — shadow://connect minting + handoff + refresh (server side).

The SDK's shadownet.onboarding is the client half; this is the Sidecar half:
the account portal mints connect URIs, hosts handoff redemption, and rotates
refresh tokens. Access tokens are opaque (RFC 0003 §6.2).
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.deps import CurrentUser
from app.models import OnboardToken

logger = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"])

HANDOFF_TTL = timedelta(minutes=10)
ACCESS_TTL = timedelta(minutes=settings.jwt_expire_minutes)
REFRESH_TTL = timedelta(days=30)

# RFC 0003 §3.1 handoff grammar.
_HANDOFF_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$")

# RFC 0003 §8 — in-memory per-IP rate limiting for the onboard endpoints.
_RATE: dict[str, list[float]] = {}


def _rate_limited(key: str, *, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    bucket = [t for t in _RATE.get(key, []) if t > now - window]
    bucket.append(now)
    _RATE[key] = bucket
    return len(bucket) > limit


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mcp_endpoint() -> str:
    return f"{settings.external_url.rstrip('/')}/u/{settings.mcp_label}/mcp"


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _mint(
    session: Session, subject: str, kind: str, ttl: timedelta, family_id: str | None
) -> OnboardToken:
    tok = OnboardToken(
        subject=subject,
        kind=kind,
        token=_new_token(),
        expires_at=_utcnow() + ttl,
    )
    if family_id:
        tok.family_id = family_id
    session.add(tok)
    return tok


def _expired(tok: OnboardToken) -> bool:
    if tok.expires_at is None:
        return False
    exp = tok.expires_at
    if exp.tzinfo is None:  # SQLite round-trips datetimes as naive UTC
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < _utcnow()


def validate_access_token(token: str) -> str | None:
    """Return the Subject for a live access token, else None. Used by MCP auth."""
    with Session(get_engine()) as s:
        row = s.exec(select(OnboardToken).where(OnboardToken.token == token)).first()
        if row is None or row.kind != "access" or row.revoked or _expired(row):
            return None
        return row.subject


def get_engine():
    from app.database import engine

    return engine


@router.post("/api/onboard/connect")
def mint_connect_uri(
    user: CurrentUser, form: str = "handoff", session: Session = Depends(get_session)
):
    """Portal: mint a shadow://connect URI for a host LLM (RFC 0003 §3)."""
    mcp = quote(_mcp_endpoint(), safe="")
    if form == "inline":
        access = _mint(session, user.id, "access", ACCESS_TTL, None)
        session.commit()
        uri = f"shadow://connect?mcp={mcp}&token={quote(access.token, safe='')}"
        return {"connectUri": uri, "expiresAt": access.expires_at.isoformat()}
    handoff = _mint(session, user.id, "handoff", HANDOFF_TTL, None)
    session.commit()
    uri = f"shadow://connect?mcp={mcp}&handoff={handoff.token}"
    return {
        "connectUri": uri,
        "handoff": handoff.token,
        "expiresAt": handoff.expires_at.isoformat(),
    }


@router.post("/.well-known/shadownet/onboard/handoff/{code}")
def redeem_handoff(code: str, request: Request, session: Session = Depends(get_session)):
    """RFC 0003 §4 — redeem a single-use handoff code for tokens."""
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(f"handoff:{ip}", limit=20) or _rate_limited(f"handoff:{code[:6]}", limit=10):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    if not _HANDOFF_RE.match(code):
        return JSONResponse({"error": "handoff_unknown"}, status_code=404)
    row = session.exec(
        select(OnboardToken).where(OnboardToken.token == code).where(OnboardToken.kind == "handoff")
    ).first()
    if row is None or row.revoked:
        return JSONResponse({"error": "handoff_unknown"}, status_code=404)
    if _expired(row):
        return JSONResponse({"error": "handoff_expired"}, status_code=410)

    row.revoked = True  # single-use
    session.add(row)
    access = _mint(session, row.subject, "access", ACCESS_TTL, None)
    refresh = _mint(session, row.subject, "refresh", REFRESH_TTL, access.family_id)
    session.commit()
    return JSONResponse(
        {
            "accessToken": access.token,
            "expiresAt": access.expires_at.isoformat(),
            "refreshToken": refresh.token,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/.well-known/shadownet/onboard/refresh")
def refresh_token(
    request: Request,
    session: Session = Depends(get_session),
    authorization: str = Header(default=""),
):
    """RFC 0003 §7 — rotate a refresh token; reuse revokes the family."""
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(f"refresh:{ip}", limit=30):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    if not authorization.lower().startswith("bearer "):
        return JSONResponse({"error": "refresh_invalid"}, status_code=401)
    presented = authorization[7:].strip()
    row = session.exec(
        select(OnboardToken)
        .where(OnboardToken.token == presented)
        .where(OnboardToken.kind == "refresh")
    ).first()
    if row is None or _expired(row):
        return JSONResponse({"error": "refresh_invalid"}, status_code=401)
    if row.revoked:
        _revoke_family(session, row.family_id)  # §7.3 reuse detection
        session.commit()
        return JSONResponse({"error": "refresh_invalid"}, status_code=401)

    row.revoked = True
    session.add(row)
    access = _mint(session, row.subject, "access", ACCESS_TTL, row.family_id)
    refresh = _mint(session, row.subject, "refresh", REFRESH_TTL, row.family_id)
    session.commit()
    return JSONResponse(
        {
            "accessToken": access.token,
            "expiresAt": access.expires_at.isoformat(),
            "refreshToken": refresh.token,
        },
        headers={"Cache-Control": "no-store"},
    )


def _revoke_family(session: Session, family_id: str) -> None:
    for tok in session.exec(select(OnboardToken).where(OnboardToken.family_id == family_id)).all():
        tok.revoked = True
        session.add(tok)
