"""The search as an MCP tool (`eng-SEARCH-000001`; design 01 §7): a stdio server over one vector database build, its
`search` tool answering as `catalyst-kb-engine search` does. Read locally, by the realm only: the build may hold
private documents, so the server is never exposed beyond the machine that keeps it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from catalyst_kb_engine.search import BuildIndex, Mode, render


def server(build: Path) -> Any:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as err:  # pragma: no cover - the `mcp` extra
        raise ImportError("the MCP server needs the mcp package: install catalyst-kb-engine[mcp]") from err
    index = BuildIndex(build)
    kb, version = index.manifest.get("knowledge_base"), index.manifest.get("version")
    app = MCPServer("catalyst-kb-engine", instructions=f"Search {kb} {version}: passages citing their sources.")

    @app.tool()
    async def search(question: str, k: int = 8, mode: str = "hybrid") -> str:
        """Search the knowledge base for passages answering a question. Each passage cites its document, its source
        and, from a catalyst criterion, its entity ID. `mode`: hybrid (default), keyword or vector."""
        return render(await index.search(question, k=max(1, min(k, 50)), mode=Mode(mode)))

    return app


def serve(build: Path) -> None:
    server(build).run()
