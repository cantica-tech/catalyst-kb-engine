"""The realm's search over HTTP (`eng-SEARCH-000003`; design 01 §7): a vector build's search, answered only to a
bearer token the realm's provider vouches for, through catalyst-users' FastAPI integration (active introspection,
the realm's issuer, the service's audience). A refused token is 401, a provider out of reach 503: no request passes
unchecked. Every person of the realm may search everything, for now (design 01 §10.1).

Settings come from the environment, as catalyst-users reads them (`CATALYST_USERS_SERVER`, `…_REALM`,
`…_API_CLIENT_ID`, `…_API_CLIENT_SECRET`); the service never logs or returns a token or a secret. Needs the `serve`
extra.
"""

from pathlib import Path
from typing import Annotated, Any

from catalyst_kb_engine.search import BuildIndex, Embed, Mode


def app(build: Path, *, auth: Any = None, embed: Embed | None = None) -> Any:
    """The service for the vector build `build`. `auth` is catalyst-users' `KeycloakAuth` (made from the environment
    when not given); `embed` replaces the build's embedding model (tests)."""
    try:
        from catalyst_users.fastapi_auth import KeycloakAuth
        from catalyst_users.identity import Identity
        from fastapi import Depends, FastAPI, Query
    except ImportError as err:  # pragma: no cover - the `serve` extra
        raise ImportError(
            "the realm's search needs catalyst-users and FastAPI: install catalyst-kb-engine[serve]"
        ) from err

    index = BuildIndex(build)
    realm = auth or KeycloakAuth()
    kb, version = index.manifest.get("knowledge_base"), index.manifest.get("version")
    service = FastAPI(title=f"{kb} {version}: the realm's search", docs_url=None, redoc_url=None, openapi_url=None)

    # annotations are evaluated here, where Identity and realm exist (FastAPI reads them): no deferred annotations
    @service.get("/me")
    def me(who: Annotated[Identity, Depends(realm)]) -> dict[str, Any]:
        """Who the service sees: the caller's verified identity, so a caller can check their token."""
        return {"signer": who.signer()}

    @service.get("/search")
    async def search(
        q: Annotated[str, Query(min_length=1, max_length=2000)],
        who: Annotated[Identity, Depends(realm)],
        k: Annotated[int, Query(ge=1, le=50)] = 8,
        mode: Mode = Mode.HYBRID,
    ) -> dict[str, Any]:
        """Passages answering `q`, each citing its source, document and, from a criterion, its entity."""
        passages = await index.search(q, k=k, mode=mode, embed=embed)
        return {"knowledge_base": kb, "build": version, "passages": [p.record() for p in passages]}

    return service


def serve(build: Path, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app(build), host=host, port=port, log_level="info", access_log=False)
