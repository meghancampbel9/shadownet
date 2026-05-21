"""A2A authentication helpers — shadownet-local protocol.

Outbound: DID-bound session token + Verifiable Presentation handshake.
Inbound: verify_handshake validates session JWT + optional VP.
Also initializes shared protocol dependencies (Resolver, TrustStore, SNSClient).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx
from shadownet.a2a.client import build_handshake_headers
from shadownet.a2a.server import verify_handshake
from shadownet.did.resolver import Resolver
from shadownet.sns.client import SNSClient
from shadownet.trust import TrustStore
from shadownet.vc.presentation import mint_presentation

from app.config import settings
from app.identity import get_did, get_keypair

if TYPE_CHECKING:
    from collections.abc import Mapping

    from shadownet.a2a.server import HandshakeContext

logger = logging.getLogger(__name__)

_resolver: Resolver | None = None
_trust_store: TrustStore | None = None
_sns_client: SNSClient | None = None
_http_client: httpx.AsyncClient | None = None


def init_protocol() -> None:
    """Initialize protocol-level dependencies at app startup."""
    global _resolver, _trust_store, _sns_client, _http_client

    from shadownet.did.web import WebDIDResolver

    _http_client = httpx.AsyncClient()
    web_resolver = WebDIDResolver(_http_client)
    _resolver = Resolver(web=web_resolver)

    pairs = json.loads(settings.trust_store_pairs)
    if pairs:
        _trust_store = TrustStore.from_pairs(pairs)
    else:
        _trust_store = TrustStore(entries=())

    if settings.sns_provider_host:
        _sns_client = SNSClient(_http_client, resolver=_resolver)


def get_resolver() -> Resolver:
    if _resolver is None:
        raise RuntimeError("Protocol not initialized — call init_protocol() first")
    return _resolver


def get_trust_store() -> TrustStore:
    if _trust_store is None:
        raise RuntimeError("Protocol not initialized — call init_protocol() first")
    return _trust_store


def get_sns_client() -> SNSClient | None:
    return _sns_client


def build_outbound_headers(
    audience_did: str, credential_jwts: list[str] | None = None
) -> dict[str, str]:
    """Build A2A handshake headers for an outbound request."""
    keypair = get_keypair()
    my_did = get_did()

    presentation_jwt: str | None = None
    if credential_jwts:
        presentation_jwt = mint_presentation(
            holder_key=keypair,
            holder_did=my_did,
            audience_did=audience_did,
            credentials=credential_jwts,
        )

    return build_handshake_headers(
        holder_key=keypair,
        holder_did=my_did,
        audience_did=audience_did,
        presentation_jwt=presentation_jwt,
    )


async def verify_inbound(headers: Mapping[str, str]) -> HandshakeContext:
    """Verify inbound A2A request using RFC-0006 handshake.

    Known contacts (by DID) are treated as pre-authorized — VP is not
    required since we have no SCA infrastructure yet. Unknown DIDs will
    still get PresentationRequiredError per the spec.
    """
    from sqlmodel import Session, select

    from app.database import engine
    from app.models import Contact

    with Session(engine) as session:
        contacts = session.exec(select(Contact).where(Contact.did != "")).all()
        trusted_dids = {c.did for c in contacts}

    class _TrustedCache:
        """Dict-like that answers 'in' for known contact DIDs."""

        def __contains__(self, did: str) -> bool:
            return did in trusted_dids

        def __getitem__(self, did: str):
            return None

    return await verify_handshake(
        headers,
        expected_audience=get_did(),
        resolver=get_resolver(),
        trust_store=get_trust_store(),
        required_predicate=None,
        cached_presentations=_TrustedCache(),  # type: ignore[arg-type]
    )
