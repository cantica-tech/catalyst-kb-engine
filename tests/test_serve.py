"""The realm's search over HTTP (`eng-SEARCH-000003`), offline: catalyst-users' own `OIDCClient.accepts` decides,
with only the provider's introspection replaced."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from catalyst_users.config import Settings
from catalyst_users.errors import ProviderUnavailableError
from catalyst_users.fastapi_auth import KeycloakAuth
from catalyst_users.http import Http, Request, Response
from catalyst_users.oidc import OIDCClient
from fastapi.testclient import TestClient

from catalyst_kb_engine.serve import app
from catalyst_kb_engine.serve_auth import LoopbackOIDCClient, claimed_issuer, loopback_twin
from tests.test_search import axis_embed, build  # noqa: F401 - the hand-made vector build, a fixture

SETTINGS = Settings(server_url="http://kc.test", realm="catalyst", api_client_secret="test-only")
REALM = SETTINGS.issuer


class Introspected(OIDCClient):
    """catalyst-users' client, the provider's answer for each token given by the test."""

    def __init__(self, answers: dict[str, dict]) -> None:
        super().__init__(SETTINGS)
        self.answers = answers

    def introspect(self, token: str) -> dict:
        answer = self.answers.get(token)
        if answer is None:
            raise ProviderUnavailableError("the provider is out of reach")
        return answer


def claims(**over) -> dict:
    return {"active": True, "iss": REALM, "aud": "catalyst-api", "exp": time.time() + 300, "sub": "s-ada",
            "preferred_username": "ada", "groups": ["/cantica-tech/catalyst/developers"],
            "realm_access": {"roles": ["developer"]}, **over}  # fmt: skip


ANSWERS = {
    "realm": claims(),
    "inactive": {"active": False},
    "other-realm": claims(iss="http://kc.test/realms/master"),
    "elsewhere": claims(iss="https://id.example.com/realms/catalyst"),
    "other-audience": claims(aud="another-service"),
    "expired": claims(exp=time.time() - 1),
}


@pytest.fixture
def client(build: Path) -> TestClient:  # noqa: F811 - the fixture from test_search
    auth = KeycloakAuth(oidc=Introspected(ANSWERS))
    return TestClient(app(build, auth=auth, embed=axis_embed))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_realm_token_gets_passages_citing_their_sources(client: TestClient):
    answer = client.get("/search", params={"q": "who approves an invoice", "k": 2}, headers=bearer("realm"))
    assert answer.status_code == 200
    body = answer.json()
    assert body["knowledge_base"] == "KB-000001-Ab3xR9pQ" and body["passages"][0]["entity"] == "REQ-000001-Ab3xR9pQ"
    assert client.get("/me", headers=bearer("realm")).json()["signer"]


@pytest.mark.parametrize("token", ["other-realm", "elsewhere", "inactive", "other-audience", "expired"])
def test_a_token_the_realm_does_not_vouch_for_is_refused(client: TestClient, token: str):
    for path in ("/search?q=invoice", "/me"):
        answer = client.get(path, headers=bearer(token))
        assert answer.status_code == 401 and answer.headers["www-authenticate"] == "Bearer"
        assert "passages" not in answer.text


def test_no_token_is_refused(client: TestClient):
    assert client.get("/search", params={"q": "invoice"}).status_code == 401
    assert (
        client.get("/search", params={"q": "invoice"}, headers={"Authorization": "Basic YWRhOng="}).status_code == 401
    )


def test_a_provider_out_of_reach_refuses_rather_than_lets_through(client: TestClient):
    assert client.get("/search", params={"q": "invoice"}, headers=bearer("unknown-to-the-fake")).status_code == 503


def test_a_question_out_of_bounds_is_refused_after_the_realm_check(client: TestClient):
    assert client.get("/search", params={"q": "invoice", "k": 500}, headers=bearer("realm")).status_code == 422
    assert client.get("/search", params={"q": "invoice", "k": 500}, headers=bearer("other-realm")).status_code == 401


def test_no_api_description_is_served(client: TestClient):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# BUG-000047: Keycloak builds a token's issuer from the host it is asked at, and introspection verifies a token against
# the host it is asked at. A fake of that, on both loopback names of one port.


def jwt(issuer: str) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'iss': issuer})}.sig"


def keycloak(asked: list[str]) -> Http:
    def transport(request: Request, timeout: float) -> Response:
        parts = urlsplit(request.url)
        issuer = f"{parts.scheme}://{parts.netloc}/realms/catalyst"
        asked.append(parts.hostname or "")
        if request.url.endswith("/.well-known/openid-configuration"):
            endpoints = {name: f"{issuer}/protocol/openid-connect/{name}" for name in ("token", "auth/device")}
            meta = {"issuer": issuer, "token_endpoint": endpoints["token"],
                    "device_authorization_endpoint": endpoints["auth/device"],
                    "introspection_endpoint": f"{issuer}/protocol/openid-connect/token/introspect",
                    "userinfo_endpoint": f"{issuer}/protocol/openid-connect/userinfo",
                    "revocation_endpoint": f"{issuer}/protocol/openid-connect/revoke"}  # fmt: skip
            return Response(200, {}, json.dumps(meta).encode())
        token = parse_qs((request.body or b"").decode())["token"][0]
        if claimed_issuer(token) != issuer:  # Keycloak: a token of another host is not active here
            return Response(200, {}, json.dumps({"active": False}).encode())
        return Response(200, {}, json.dumps(claims(iss=issuer)).encode())

    return Http(transport)


@pytest.fixture
def loopback(build: Path) -> tuple[TestClient, list[str]]:  # noqa: F811 - the fixture from test_search
    asked: list[str] = []
    settings = replace(SETTINGS, server_url="http://localhost:8080")
    auth = KeycloakAuth(settings, oidc=LoopbackOIDCClient(settings, http=keycloak(asked)))
    return TestClient(app(build, auth=auth, embed=axis_embed)), asked


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_a_token_got_at_either_loopback_name_is_accepted_by_a_service_on_loopback(loopback, host: str):
    client, asked = loopback
    answer = client.get("/search", params={"q": "invoice"}, headers=bearer(jwt(f"http://{host}:8080/realms/catalyst")))
    assert answer.status_code == 200 and answer.json()["passages"]
    assert asked and set(asked) == {host}  # introspected where the token was got, where Keycloak accepts it


@pytest.mark.parametrize(
    "issuer",
    [
        "http://localhost:8081/realms/catalyst",  # another port: another provider
        "http://127.0.0.1:8080/realms/master",  # another realm
        "https://localhost:8080/realms/catalyst",  # another scheme
        "http://kc.test/realms/catalyst",  # not loopback
    ],
)
def test_a_token_of_another_port_realm_scheme_or_host_is_still_refused(loopback, issuer: str):
    client, asked = loopback
    assert client.get("/me", headers=bearer(jwt(issuer))).status_code == 401
    assert set(asked) == {"localhost"}  # asked at the service's own host only, which refuses it


def test_a_token_that_is_no_jwt_is_introspected_at_the_service_s_own_host(loopback):
    client, asked = loopback
    assert client.get("/me", headers=bearer("opaque")).status_code == 401
    assert set(asked) == {"localhost"}


def test_the_loopback_twin_is_only_for_a_loopback_provider():
    assert loopback_twin("http://localhost:8080") == "http://127.0.0.1:8080"
    assert loopback_twin("http://127.0.0.1") == "http://localhost"
    assert loopback_twin("https://id.example.com") is None
    assert LoopbackOIDCClient(SETTINGS).twin is None  # kc.test: only the realm's own host
