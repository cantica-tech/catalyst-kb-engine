"""Incremental vector builds (`eng-OUTPUT-000004`): only what is provably unchanged is reused."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pydantic_ai.embeddings import TestEmbeddingModel

from catalyst_kb_engine.build import vectors
from catalyst_kb_engine.build.folders import BuildInfo
from catalyst_kb_engine.build.vectors import EmbeddingModel, EmbeddingPolicy, build_vectors
from catalyst_kb_engine.models import Classification

INFO = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.PUBLIC, Classification.PUBLIC)


@pytest.fixture
def embedded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the build sent to the model; each text's vector is its length and its first letter's code."""
    sent: list[str] = []

    async def fake(model, texts):
        sent.extend(texts)
        return [[float(len(t)), float(ord(t[0]))] for t in texts]

    monkeypatch.setattr(vectors, "_embed", fake)
    return sent


def _doc(repo: Path, name: str, text: str) -> None:
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / f"{name}.md").write_text(f"---\ntitle: {name}\nclassification: Public\n---\n\n{text}\n")


def _build(repo: Path, out: Path, previous: Path | None = None, name: str = "local-test"):
    policy = EmbeddingPolicy("Local only", local=EmbeddingModel(TestEmbeddingModel(dimensions=2), name, "local"))
    return asyncio.run(build_vectors(repo, out, INFO, policy, previous=previous))


def _vectors(build: Path) -> dict[str, list[float]]:
    rows = [json.loads(line) for line in (build / "chunks.jsonl").read_text().splitlines()]
    table = pq.read_table(build / "vectors.parquet")
    return {r["path"]: v for r, v in zip(rows, table.column("vector").to_pylist(), strict=True)}


def test_a_rebuild_after_one_change_embeds_only_that_change(tmp_path: Path, embedded: list[str]):
    repo = tmp_path / "kb"
    _doc(repo, "kept", "Unchanged.")
    _doc(repo, "edited", "Before.")
    _doc(repo, "removed", "Going away.")
    first = _build(repo, tmp_path / "1")
    assert first.incremental is None and len(embedded) == 3
    embedded.clear()

    _doc(repo, "edited", "After the change.")
    _doc(repo, "added", "New.")
    (repo / "docs" / "removed.md").unlink()
    second = _build(repo, tmp_path / "2", previous=tmp_path / "1")

    assert embedded == ["added\n\nNew.", "edited\n\nAfter the change."]
    assert second.incremental == {"previous": "1.0.0", "reused": 1, "embedded": 2}
    old, new = _vectors(tmp_path / "1"), _vectors(tmp_path / "2")
    assert new["docs/kept.md"] == old["docs/kept.md"]
    assert "docs/removed.md" not in new
    manifest = json.loads((tmp_path / "2" / "manifest.json").read_text())
    assert manifest["incremental"] == second.incremental and manifest["counts"]["chunks"] == 3


def test_a_previous_build_from_another_model_is_not_reused(tmp_path: Path, embedded: list[str]):
    repo = tmp_path / "kb"
    _doc(repo, "kept", "Unchanged.")
    _build(repo, tmp_path / "1", name="old-model")
    embedded.clear()
    second = _build(repo, tmp_path / "2", previous=tmp_path / "1", name="new-model")
    assert embedded == ["kept\n\nUnchanged."]
    assert (
        second.incremental and second.incremental["reused"] == 0 and "another model" in second.incremental["not_reused"]
    )
