"""Searching a vector database build (`eng-SEARCH-000001`; design 01 §7): keywords (SQLite FTS5) and vectors (the
question embedded with the build's own model, compared by cosine), merged by reciprocal rank. Every passage cites its
source, document, heading and classification, and a criterion's entity. A search reads the build and writes nothing."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from catalyst_kb_engine.build.folders import BuildError, _split

RRF_K = 60
"""Reciprocal rank fusion's constant: a passage scores the sum of 1 / (60 + its rank) in each ranking."""
CANDIDATES = 50
"""How many passages each ranking contributes to the fusion."""
KEYWORD_WEIGHTS = (5.0, 3.0, 1.0)
"""`bm25`'s weight for a match in a chunk's title, its heading and its text: measured on catalyst-docs' realm against
1/1/1, 3/2/1 and 10/5/1, the best hybrid recall (REQ-000011-7TE7wuaB)."""
_WORD = re.compile(r"[\w-]{2,}", re.UNICODE)

Embed = Callable[[str], Awaitable[list[float]]]
"""A question to its vector, with the build's embedding model."""


class Mode(StrEnum):
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class Passage:
    rank: int
    score: float
    text: str
    path: str
    title: str
    heading: str
    classification: str
    source: str | None
    entity: str | None
    """For a criterion document, its entity's or rule's ID."""
    criterion: str | None

    def record(self) -> dict[str, Any]:
        return asdict(self)


def fts_query(question: str) -> str:
    """The question's words, each quoted, joined by OR: FTS5's syntax never sees the question's punctuation."""
    words = dict.fromkeys(w.lower() for w in _WORD.findall(question))
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words)


class BuildIndex:
    """A vector database build, loaded for searching: its chunks, its vectors, and each document's front matter."""

    def __init__(self, build: Path) -> None:
        manifest_file = build / "manifest.json"
        if not manifest_file.is_file():
            raise BuildError(f"{build} is not a build: it has no manifest.json")
        self.manifest: dict[str, Any] = json.loads(manifest_file.read_text(encoding="utf-8"))
        if self.manifest.get("target") != "vector-database":
            raise BuildError(f"{build} is a {self.manifest.get('target')} build; search needs a vector database")
        self.build = build
        self.chunks = [json.loads(line) for line in (build / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.meta = {c["path"]: self._front(build / c["path"]) for c in self.chunks}
        self.vectors = self._vectors(build / "vectors.parquet")
        self.fts = sqlite3.connect(":memory:", check_same_thread=False)
        self.fts.execute("CREATE VIRTUAL TABLE chunks USING fts5(title, heading, text, tokenize='porter unicode61')")
        self.fts.executemany(
            "INSERT INTO chunks(rowid, title, heading, text) VALUES (?, ?, ?, ?)",
            ((i, c["title"], c["heading"], c["text"]) for i, c in enumerate(self.chunks)),
        )

    @staticmethod
    def _front(document: Path) -> dict[str, Any]:
        return _split(document.read_text(encoding="utf-8"), document)[0] if document.is_file() else {}

    def _vectors(self, parquet: Path) -> Any:
        try:
            import numpy as np
            import pyarrow.parquet as pq
        except ImportError as err:  # pragma: no cover - the `search` extra
            raise BuildError("search needs numpy and pyarrow: install catalyst-kb-engine[search]") from err
        table = pq.read_table(parquet)
        if table.column("id").to_pylist() != [c["id"] for c in self.chunks]:
            raise BuildError(f"{parquet} is not in chunks.jsonl's order")
        dimensions = int(self.manifest.get("embedding", {}).get("dimensions") or 0)
        flat = table.column("vector").combine_chunks().flatten().to_numpy(zero_copy_only=False)
        return np.asarray(flat, dtype=np.float32).reshape(len(self.chunks), dimensions)

    @property
    def model(self) -> str:
        return str(self.manifest.get("embedding", {}).get("model") or "")

    @property
    def query_prefix(self) -> str:
        """What the build's model expects before a question (`eng-OUTPUT-000003`); none for an older build."""
        return str(self.manifest.get("embedding", {}).get("query_prefix") or "")

    def keyword(self, question: str, n: int = CANDIDATES) -> list[tuple[int, float]]:
        query = fts_query(question)
        if not query:
            return []
        bm25 = "bm25(chunks, {}, {}, {})".format(*KEYWORD_WEIGHTS)
        rows = self.fts.execute(
            f"SELECT rowid, {bm25} FROM chunks WHERE chunks MATCH ? ORDER BY {bm25} LIMIT ?",  # noqa: S608 - constants
            (query, n),
        ).fetchall()
        return [(int(rowid), -float(score)) for rowid, score in rows]

    async def vector(self, question: str, embed: Embed, n: int = CANDIDATES) -> list[tuple[int, float]]:
        import numpy as np

        query = np.asarray(await embed(self.query_prefix + question), dtype=np.float32)
        if query.shape != (self.vectors.shape[1],):
            raise BuildError(
                f"the question's vector has {query.shape[0]} dimensions, the build's {self.vectors.shape[1]}"
            )
        norm = float(np.linalg.norm(query))
        scores = self.vectors @ (query / norm if norm else query)
        top = np.argsort(-scores)[:n]
        return [(int(i), float(scores[i])) for i in top]

    def passage(self, index: int, rank: int, score: float) -> Passage:
        chunk, meta = self.chunks[index], self.meta.get(self.chunks[index]["path"], {})
        return Passage(
            rank=rank,
            score=round(score, 6),
            text=chunk["text"],
            path=chunk["path"],
            title=chunk["title"],
            heading=chunk["heading"],
            classification=chunk["classification"],
            source=chunk.get("source"),
            entity=meta.get("entity"),
            criterion=meta.get("criterion"),
        )

    async def search(
        self, question: str, *, k: int = 8, mode: Mode = Mode.HYBRID, embed: Embed | None = None
    ) -> list[Passage]:
        if mode is Mode.KEYWORD:
            ranked = self.keyword(question)
        else:
            if embed is None:
                embed = query_embedder(self.model)
            vectors = await self.vector(question, embed)
            ranked = vectors if mode is Mode.VECTOR else fuse(self.keyword(question), vectors)
        return [self.passage(i, rank, score) for rank, (i, score) in enumerate(ranked[:k], start=1)]


def fuse(*rankings: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: each ranking adds 1 / (RRF_K + rank) to a passage's score."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, (index, _) in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def query_embedder(model: str) -> Embed:
    """The build's own embedding model (its manifest's `embedding.model`), as a Pydantic AI `Embedder` for queries."""
    from catalyst_kb_engine.build.vectors import embedder as make_embedder

    embedder = make_embedder(model)

    async def embed(question: str) -> list[float]:
        result = await embedder.embed_query(question)
        return [float(x) for x in result.embeddings[0]]

    return embed


def render(passages: list[Passage]) -> str:
    """Passages as plain text for a person or a model: each with what it cites."""
    out = []
    for p in passages:
        cites = ", ".join(x for x in (p.entity, p.criterion and f"criterion {p.criterion}", p.source) if x)
        where = f"{p.path}{' > ' + p.heading if p.heading else ''}"
        out.append(f"[{p.rank}] {p.title} ({p.classification}; {cites})\n    {where}\n\n{p.text.strip()}\n")
    return "\n".join(out) if out else "(no passage)"


def load_questions(path: Path) -> list[dict[str, Any]]:
    """An evaluation set: `questions`, each an `id`, a `question` and `expect` (entity IDs or document paths)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    for q in questions:
        if not (q.get("id") and q.get("question") and q.get("expect")):
            raise BuildError(f"{path}: each question has an id, a question and what it expects: {q!r}")
    return questions
