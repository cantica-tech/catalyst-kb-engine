"""The vector database build: one model within the allowance, Parquet vectors any model can read
(`eng-OUTPUT-000001`, `eng-OUTPUT-000002`; KBM `rr-KB-009`, KB-L1)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math

import pyarrow.parquet as pq
import pytest
from pydantic_ai.embeddings import TestEmbeddingModel

from catalyst_kb_engine.build.chunks import chunk
from catalyst_kb_engine.build.folders import BuildError
from catalyst_kb_engine.build.vectors import EmbeddingModel, EmbeddingPolicy, build_vectors
from catalyst_kb_engine.models import Classification
from catalyst_kb_engine.record import record_build
from tests.test_folders import INFO, repo  # noqa: F401 - the fixture
from tests.test_record import FakeCatalyst

LOCAL = EmbeddingModel(TestEmbeddingModel(dimensions=8), "local-test", "local")
HOSTED = EmbeddingModel(TestEmbeddingModel(dimensions=8), "hosted-test", "hosted-co")


def test_chunks_follow_headings_and_stay_within_size():
    body = "# A\n\nintro\n\n## B\n\n" + "word " * 400 + "\n\n## C\n\nend\n"
    chunks = chunk("docs/x.md", "X", body, "Internal", max_tokens=100, overlap=10)
    assert chunks[0].heading == "A" and chunks[-1].heading == "A > C"
    assert all(len(c.text) <= 400 for c in chunks) and len({c.id for c in chunks}) == len(chunks)
    assert sum(c.heading == "A > B" for c in chunks) > 1  # a long section is split


@pytest.mark.parametrize(
    ("up_to", "hosted", "local", "chosen"),
    [
        (Classification.CONFIDENTIAL, HOSTED, LOCAL, "hosted-test"),  # every chunk within the allowance
        (Classification.PUBLIC, HOSTED, LOCAL, "local-test"),  # an Internal chunk is above it
        ("Local only", HOSTED, LOCAL, "local-test"),
    ],
)
def test_one_model_is_chosen_within_the_allowance(repo, tmp_path, up_to, hosted, local, chosen):  # noqa: F811
    policy = EmbeddingPolicy(hosted_up_to=up_to, hosted=hosted, local=local)
    result = asyncio.run(build_vectors(repo, tmp_path / "out", INFO, policy))
    assert result.embedding and result.embedding["model"] == chosen


def test_without_an_allowed_model_nothing_is_built(repo, tmp_path):  # noqa: F811
    policy = EmbeddingPolicy(hosted_up_to=Classification.PUBLIC, hosted=HOSTED)
    with pytest.raises(BuildError, match="no embedding model allowed"):
        asyncio.run(build_vectors(repo, tmp_path / "out", INFO, policy))
    assert not (tmp_path / "out").exists()


def test_the_build_is_readable_without_catalyst(repo, tmp_path):  # noqa: F811
    out = tmp_path / "out"
    result = asyncio.run(build_vectors(repo, out, INFO, EmbeddingPolicy("Local only", local=LOCAL), max_tokens=50))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["target"] == "vector-database" and manifest["embedding"]["dimensions"] == 8
    assert manifest["embedding"]["normalized"] and manifest["chunking"]["by"] == "heading"
    for name, digest in manifest["files"].items():
        assert digest == "sha256:" + hashlib.sha256((out / name).read_bytes()).hexdigest()
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    table = pq.read_table(out / "vectors.parquet")
    assert table.column("id").to_pylist() == [c["id"] for c in chunks] and len(chunks) == result.chunks
    assert all(math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-5) for v in table.column("vector").to_pylist())
    assert {c["classification"] for c in chunks} == {"Internal"} and (out / "docs").is_dir()


def test_a_vector_build_is_recorded_with_its_model(repo, tmp_path):  # noqa: F811
    result = asyncio.run(build_vectors(repo, tmp_path / "out", INFO, EmbeddingPolicy("Local only", local=LOCAL)))
    cli = FakeCatalyst(tmp_path)
    build = record_build(cli, INFO, result, "here", "KB 1.0.0")
    assert cli.records[build]["Target"] == "Vector database"
    assert cli.records[build]["Embedding model"] == "local-test, local"


def test_a_failing_embedding_model_is_a_refusal_and_nothing_is_written(repo, tmp_path):  # noqa: F811
    broken = EmbeddingModel("no-such-provider:model", "broken", "local")
    with pytest.raises(BuildError, match="embedding with broken failed"):
        asyncio.run(build_vectors(repo, tmp_path / "out", INFO, EmbeddingPolicy("Local only", local=broken)))
    assert not (tmp_path / "out").exists()
