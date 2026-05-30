"""v0.2 protocol runtime: receiver pipeline, DB-backed adapters, resolution.

Replaces the v0.1 DID/SNS/VP machinery. Holds the singletons the FastAPI app
and MCP tools call into. SDK wire calls are synchronous; callers on the event
loop MUST wrap them with run_in_threadpool.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from shadownet.addressing import DirectAddress, ShadownameAddress, parse_shadow_address
from shadownet.agentcard import (
    fetch_and_verify_agent_card,
    fetch_and_verify_direct_agent_card,
)
from shadownet.identifiers import is_public_key_identifier
from shadownet.provider import lookup_provider_record
from shadownet.receiver import (
    InMemoryCredentialCache,
    ReceiverConfig,
    ReceiverPipeline,
)
from shadownet.tls import InMemoryTLSPinStore, make_pinned_httpx_client
from shadownet.trust import AcceptancePolicy, TrustEntry, TrustStore
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.identity import get_subject
from app.models import AccessGrant, Contact, GrantType, OutboundContext, ReplayEntry

logger = logging.getLogger(__name__)

_pipeline: ReceiverPipeline | None = None
_credential_cache: InMemoryCredentialCache | None = None
_own_creds: tuple[str, ...] = ()
# Process-wide TOFU store so direct-mode pins persist across resolves (§5.3).
_tofu_store = InMemoryTLSPinStore()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DbReplayCache:
    """RFC 0001 §8.9 replay cache backed by the messages DB."""

    def seen(self, sender: str, message_id: str) -> bool:
        now = _utcnow()
        with Session(engine) as s:
            for stale in s.exec(select(ReplayEntry).where(ReplayEntry.expires_at <= now)).all():
                s.delete(stale)
            s.commit()
            row = s.exec(
                select(ReplayEntry)
                .where(ReplayEntry.sender == sender)
                .where(ReplayEntry.message_id == message_id)
            ).first()
            return row is not None

    def remember(self, sender: str, message_id: str, *, retention_seconds: int) -> None:
        with Session(engine) as s:
            s.add(
                ReplayEntry(
                    sender=sender,
                    message_id=message_id,
                    expires_at=_utcnow() + timedelta(seconds=retention_seconds),
                )
            )
            s.commit()


class DbContactGraph:
    """RFC 0001 §9 contact graph + outbound-context log backed by the DB."""

    def is_contact(self, identifier: str) -> bool:
        from app.grants import is_allowed_contact

        with Session(engine) as s:
            return is_allowed_contact(s, identifier)

    def has_recent_outbound(self, *, context_id: str, peer: str, lookback_seconds: int) -> bool:
        cutoff = _utcnow() - timedelta(seconds=lookback_seconds)
        with Session(engine) as s:
            row = s.exec(
                select(OutboundContext)
                .where(OutboundContext.context_id == context_id)
                .where(OutboundContext.peer == peer)
                .where(OutboundContext.created_at >= cutoff)
            ).first()
            return row is not None

    def add_contact(self, identifier: str) -> None:
        with Session(engine) as s:
            existing = s.exec(select(Contact).where(Contact.identifier == identifier)).first()
            if existing is None:
                contact = Contact(
                    identifier=identifier,
                    name=identifier,
                    public_key=identifier if is_public_key_identifier(identifier) else "",
                )
                s.add(contact)
                s.flush()
                s.add(AccessGrant(contact_id=contact.id, grant_type=GrantType.messaging))
            s.commit()


def record_outbound_context(context_id: str, peer: str) -> None:
    """Log an outbound (contextId, peer) for the §9 auto-add rule."""
    if not context_id:
        return
    with Session(engine) as s:
        s.add(OutboundContext(context_id=context_id, peer=peer))
        s.commit()


def _build_trust_store() -> TrustStore:
    entries = tuple(TrustEntry.model_validate(e) for e in settings.trust_store_entries())
    return TrustStore(entries=entries)


def _build_policy() -> AcceptancePolicy:
    raw = settings.acceptance_policy_dict()
    return AcceptancePolicy.model_validate(raw) if raw else AcceptancePolicy()


def _load_own_credentials() -> tuple[str, ...]:
    path = settings.credentials_path
    if not path:
        return ()
    p = Path(path)
    if not p.exists():
        logger.warning("credentials_path %s does not exist; no credentials will be presented", path)
        return ()
    files = sorted(p.glob("*.jwt")) if p.is_dir() else [p]
    creds = tuple(f.read_text().strip() for f in files if f.read_text().strip())
    logger.info("Loaded %d own credential(s)", len(creds))
    return creds


def init() -> None:
    global _pipeline, _credential_cache, _own_creds
    _credential_cache = InMemoryCredentialCache()
    _own_creds = _load_own_credentials()
    config = ReceiverConfig(
        subject=get_subject(),
        trust_store=_build_trust_store(),
        policy=_build_policy(),
        same_provider_org=settings.same_provider_org,
    )
    _pipeline = ReceiverPipeline(
        config,
        replay_cache=DbReplayCache(),
        contact_graph=DbContactGraph(),
        credential_cache=_credential_cache,
    )
    logger.info("Receiver pipeline ready (subject=%s)", config.subject)


def get_pipeline() -> ReceiverPipeline:
    if _pipeline is None:
        raise RuntimeError("Protocol not initialized — call protocol.init() first")
    return _pipeline


def get_credential_cache() -> InMemoryCredentialCache:
    if _credential_cache is None:
        raise RuntimeError("Protocol not initialized — call protocol.init() first")
    return _credential_cache


def own_credentials() -> tuple[str, ...]:
    return _own_creds


def _direct_origin_and_client(addr: DirectAddress) -> tuple[str, httpx.Client]:
    if addr.host in ("localhost", "127.0.0.1", "::1"):
        # RFC 0001 §4.1 permits http://localhost for local development.
        return f"http://{addr.host}:{addr.port}", httpx.Client(timeout=10.0)
    # RFC 0001 §5.3: enforce the #sha256 pin when supplied, otherwise TOFU.
    return addr.endpoint, make_pinned_httpx_client(addr, tofu_store=_tofu_store, timeout=10.0)


def resolve_recipient(to: str) -> tuple[str, str, str]:
    """Resolve `to` to (wire identifier, A2A endpoint URL, public key). Sync."""
    addr = parse_shadow_address(to)
    if isinstance(addr, ShadownameAddress):
        _, provider = addr.shadowname.split("@", 1)
        record = lookup_provider_record(provider)
        card = fetch_and_verify_agent_card(addr.shadowname, record)
        return addr.shadowname, card.endpoint_url, card.shadow_public_key
    origin, client = _direct_origin_and_client(addr)
    try:
        card = fetch_and_verify_direct_agent_card(origin, addr.public_key, client=client)
    finally:
        client.close()
    return addr.public_key, card.endpoint_url, card.shadow_public_key
