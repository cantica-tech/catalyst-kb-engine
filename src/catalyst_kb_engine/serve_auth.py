"""The realm's token check for `serve` (`eng-SEARCH-000003`), with the two loopback names of one provider taken as one
host. Keycloak builds a token's issuer from the host it was asked at, and verifies a token at introspection against
the host it is asked at: a token got at `localhost` was refused by a service checking at `127.0.0.1`, and the other
way (BUG-000047). When the service's provider is on loopback, a token whose issuer names the other loopback name of
the same port and realm is introspected there and checked against that issuer; any other token is checked as before.
The provider still decides: the token's own claim only picks which of the two names to ask. Needs the `serve` extra.
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from catalyst_users import config
from catalyst_users.config import Settings
from catalyst_users.fastapi_auth import KeycloakAuth
from catalyst_users.oidc import OIDCClient

LOOPBACK = ("localhost", "127.0.0.1")


def loopback_twin(url: str) -> str | None:
    """`url` on the other loopback name (same scheme, port and path), or None when its host is not loopback."""
    parts = urlsplit(url)
    if parts.hostname not in LOOPBACK or parts.username or parts.password:
        return None
    other = LOOPBACK[1 - LOOPBACK.index(parts.hostname)]
    return urlunsplit(parts._replace(netloc=f"{other}:{parts.port}" if parts.port else other))


def claimed_issuer(token: str) -> str | None:
    """The issuer a JWT names, unverified (it only picks where to introspect), or None for anything else."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    issuer = claims.get("iss") if isinstance(claims, dict) else None
    return issuer if isinstance(issuer, str) else None


class LoopbackOIDCClient(OIDCClient):
    """catalyst-users' client for the realm, beside a twin on the other loopback name when the provider is on one."""

    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        super().__init__(settings, **kwargs)
        server = loopback_twin(settings.server_url)
        self.twin = OIDCClient(replace(settings, server_url=server), **kwargs) if server else None

    def _twin_for(self, issuer: object) -> OIDCClient | None:
        twin = self.twin
        return twin if twin is not None and issuer == twin.settings.issuer else None

    def introspect(self, token: str) -> dict:
        twin = self._twin_for(claimed_issuer(token))
        return twin.introspect(token) if twin else super().introspect(token)

    def accepts(self, claims: dict[str, Any]) -> bool:
        twin = self._twin_for(claims.get("iss"))
        return twin.accepts(claims) if twin else super().accepts(claims)


def realm_auth(settings: Settings | None = None) -> KeycloakAuth:
    """catalyst-users' FastAPI dependency for the realm, settings from the environment unless given."""
    settings = settings or config.load()
    return KeycloakAuth(settings, oidc=LoopbackOIDCClient(settings))
