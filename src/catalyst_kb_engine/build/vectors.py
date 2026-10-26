"""The vector database build (`eng-OUTPUT-000001`, `eng-OUTPUT-000002`; KBM `rr-KB-009`, KB-L1): the documents, their
chunks, and one unit-length vector per chunk from one embedding model, chosen within the knowledge base's allowance.

```
<version>/
├── manifest.json     format kbm-build/1, target vector-database, embedding, chunking, every file's SHA-256
├── README.md         what it is and how to load it
├── index.md, docs/   the documents, as the folders build
├── chunks.jsonl      id, path, title, heading, text, classification, source, url
└── vectors.parquet   id, vector (float32, the manifest's dimensions), in chunks.jsonl's order
```
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from catalyst_kb_engine.build.chunks import Chunk, chunk
from catalyst_kb_engine.build.folders import (
    BuildError,
    BuildInfo,
    FoldersBuild,
    refuse_written,
    select,
    stage_documents,
    write_build,
)
from catalyst_kb_engine.models import Classification

BATCH = 64
EmbedInput = Literal["text", "context"]
"""What a chunk's embedding input is: its text alone, or `context`, its document's title and heading before it."""


def embed_input(c: Chunk, mode: EmbedInput) -> str:
    """The text embedded for a chunk (`eng-OUTPUT-000003`): with `context`, a short document keeps its subject."""
    if mode == "text":
        return c.text
    return "\n".join(x for x in (c.title, c.heading) if x) + "\n\n" + c.text


@dataclass(frozen=True)
class EmbeddingModel:
    """An embedding model the build may use: a Pydantic AI `Embedder` (or its model name) and where it runs."""

    model: Any
    """e.g. `sentence-transformers:all-MiniLM-L6-v2` (local), `ollama:nomic-embed-text` (local), `openai:…` (hosted)."""
    name: str
    where: str
    """`local`, or the hosted service's name."""


@dataclass(frozen=True)
class EmbeddingPolicy:
    hosted_up_to: Classification | Literal["Local only"]
    """The knowledge base's `Hosted embedding up to`."""
    hosted: EmbeddingModel | None = None
    local: EmbeddingModel | None = None

    def choose(self, chunks: list[Chunk]) -> EmbeddingModel:
        """One model for the whole build: hosted only when every chunk is within the allowance, else local."""
        allowed = self.hosted_up_to != "Local only" and all(
            Classification(c.classification).rank <= Classification(self.hosted_up_to).rank for c in chunks
        )
        if allowed and self.hosted:
            return self.hosted
        if self.local:
            return self.local
        why = "nothing may go to a hosted service" if self.hosted_up_to == "Local only" else (
            f"a chunk is above the hosted allowance ({self.hosted_up_to})" if self.hosted else "no model is configured"
        )  # fmt: skip
        raise BuildError(f"no embedding model allowed: {why}, and no local model is configured")


@dataclass
class VectorsBuild(FoldersBuild):
    chunks: int = 0
    embedding: dict[str, Any] | None = None
    incremental: dict[str, Any] | None = None
    """With a previous build: which one, and how many chunks were reused and embedded."""


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


async def _embed(model: EmbeddingModel, texts: list[str]) -> list[list[float]]:
    from pydantic_ai import Embedder
    from pydantic_ai.exceptions import AgentRunError, ModelAPIError, UserError

    vectors: list[list[float]] = []
    try:
        embedder = model.model if isinstance(model.model, Embedder) else Embedder(model.model)
        for start in range(0, len(texts), BATCH):
            result = await embedder.embed_documents(texts[start : start + BATCH])
            vectors += [_unit([float(x) for x in v]) for v in result.embeddings]
    except (AgentRunError, ModelAPIError, UserError, ImportError, ValueError) as err:  # ValueError: unknown provider
        raise BuildError(f"embedding with {model.name} failed, so nothing is built: {err}") from err
    return vectors


def _parquet(ids: list[str], vectors: list[list[float]], dimensions: int) -> bytes:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as err:  # pragma: no cover - the `vectors` extra
        raise BuildError("the vector build needs pyarrow: install catalyst-kb-engine[vectors]") from err
    table = pa.table(
        {"id": pa.array(ids, pa.string()), "vector": pa.array(vectors, pa.list_(pa.float32(), dimensions))}
    )
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


async def build_vectors(
    repo: Path,
    out: Path,
    info: BuildInfo,
    policy: EmbeddingPolicy,
    *,
    max_tokens: int = 512,
    overlap: int = 64,
    embedding_input: EmbedInput = "context",
    document_prefix: str = "",
    query_prefix: str = "",
    previous: Path | None = None,
) -> VectorsBuild:
    """Write the vector database build of `repo` into `out` (new or empty); nothing is written if it is refused."""
    refuse_written(out)
    selection = select(repo, info)
    chunks: list[Chunk] = []
    for entry in selection.kept:
        title = str(entry.meta.get("title") or Path(entry.path).stem)
        chunks += chunk(
            f"docs/{entry.path}", title, entry.body, entry.effective.value, max_tokens=max_tokens, overlap=overlap,
            source=entry.meta.get("source"), url=entry.meta.get("url"),
        )  # fmt: skip
    model = policy.choose(chunks)
    texts = [document_prefix + embed_input(c, embedding_input) for c in chunks]
    known, incremental = _previous(previous, model, embedding_input, document_prefix)
    missing = [t for t in dict.fromkeys(texts) if _key(t) not in known]
    embedded = dict(zip(missing, await _embed(model, missing), strict=True)) if missing else {}
    vectors = [embedded[t] if t in embedded else known[_key(t)] for t in texts]
    dimensions = len(vectors[0]) if vectors else 0
    if any(len(v) != dimensions for v in vectors):
        raise BuildError("the previous build's vectors and this build's differ in dimensions, so nothing is built")
    if incremental is not None:
        incremental |= {"reused": len(texts) - sum(t in embedded for t in texts), "embedded": len(missing)}
    embedding = {
        "model": model.name, "dimensions": dimensions, "where": model.where, "normalized": True, "distance": "cosine",
        "input": embedding_input, "document_prefix": document_prefix, "query_prefix": query_prefix,
    }  # fmt: skip
    result = VectorsBuild(
        out=out,
        classification=selection.classification,
        documents=selection.documents,
        pointers=selection.pointers,
        left_out=selection.left_out,
        chunks=len(chunks),
        embedding=embedding,
        incremental=incremental,
    )
    staged = stage_documents(selection, info)
    staged["chunks.jsonl"] = "".join(json.dumps(c.record(), ensure_ascii=False) + "\n" for c in chunks).encode()
    staged["vectors.parquet"] = _parquet([c.id for c in chunks], vectors, dimensions)
    staged["README.md"] = _readme(info, result, max_tokens, overlap).encode("utf-8")
    manifest = write_build(
        out, staged, info, selection,
        target="vector-database",
        embedding=embedding,
        chunking={"max_tokens": max_tokens, "overlap": overlap, "by": "heading"},
        **({"incremental": incremental} if incremental is not None else {}),
        counts={"documents": result.documents, "pointers": result.pointers, "chunks": len(chunks),
                "left_out": result.left_out},
    )  # fmt: skip
    result.files = manifest["files"]
    return result


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _previous(
    previous: Path | None, model: EmbeddingModel, embedding_input: EmbedInput, document_prefix: str
) -> tuple[dict[str, list[float]], dict[str, Any] | None]:
    """The previous build's vectors by the hash of their exact embedding input (`eng-OUTPUT-000004`), and the
    manifest's `incremental` record; none reused when the previous build embedded otherwise."""
    if previous is None:
        return {}, None
    manifest = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    embedding = manifest.get("embedding") or {}
    record: dict[str, Any] = {"previous": manifest.get("version"), "reused": 0, "embedded": 0}
    then = (embedding.get("model"), embedding.get("input") or "text", embedding.get("document_prefix") or "")
    if manifest.get("target") != "vector-database" or then != (model.name, embedding_input, document_prefix):
        record["not_reused"] = "the previous build embedded with another model, input or prefix"
        return {}, record
    import pyarrow.parquet as pq

    rows = [json.loads(line) for line in (previous / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    table = pq.read_table(previous / "vectors.parquet")
    by_id = dict(zip(table.column("id").to_pylist(), table.column("vector").to_pylist(), strict=True))
    known = {}
    for row in rows:
        text = document_prefix + embed_input(Chunk(**row), embedding_input)
        known[_key(text)] = [float(x) for x in by_id[row["id"]]]
    return known, record


def _readme(info: BuildInfo, result: VectorsBuild, max_tokens: int, overlap: int) -> str:
    e = result.embedding or {}
    return f"""# {info.knowledge_base} {info.version}: a vector database

A build of a knowledge base in the `kbm-build/1` format, target `vector-database`. It needs no particular tool,
account, network or model: UTF-8 markdown, JSON Lines and Apache Parquet.

- **Classification**: {result.classification.value} (ceiling {info.ceiling.value}). Store and share it only where
  that classification allows. Each document's and chunk's own classification is given.
- **Contents**: {result.documents} documents and {result.pointers} pointers in {result.chunks} chunks;
  {result.left_out} left out by the ceiling or as broken pointers.
- **Embedding**: `{e.get("model")}` ({e.get("where")}), {e.get("dimensions")} dimensions, unit length, compared by
  cosine. Chunks: by heading, at most {max_tokens} tokens (about {max_tokens * 4} characters), {overlap} overlapping.

## Loading it

- `chunks.jsonl`: one chunk a line (`id`, `path`, `title`, `heading`, `text`, `classification`, `source`, `url`).
- `vectors.parquet`: `id` and `vector`, in the same order. Any vector store loads it (FAISS, LanceDB, pgvector,
  Chroma); with pyarrow: `pyarrow.parquet.read_table("vectors.parquet")`.
- Query with the same embedding model, normalized, each question prefixed with the manifest's
  `embedding.query_prefix`; or re-embed `chunks.jsonl` (or `docs/`) with your own model. Each chunk was embedded as
  `embedding.document_prefix` followed by {_input_said(e)}.
- `index.md` and `docs/` hold the documents themselves; `manifest.json` gives every file's SHA-256.
"""


def _input_said(embedding: dict[str, Any]) -> str:
    if embedding.get("input") == "text":
        return "its `text` alone"
    return "its `title`, a newline, its `heading` (when it has one), a blank line and its `text`"
