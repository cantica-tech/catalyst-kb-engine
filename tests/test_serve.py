"""The realm's search over HTTP (`eng-SEARCH-000003`), offline: catalyst-users' own `OIDCClient.accepts` decides,
with only the provider's introspection replaced."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from catalyst_users.config import Settings
from catalyst_users.errors import ProviderUnavailableError
from catalyst_users.fastapi_auth import KeycloakAuth
from catalyst_users.oidc import OIDCClient
from fastapi.testclient import TestClient

from catalyst_kb_engine.serve import app
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
