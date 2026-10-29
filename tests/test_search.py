"""Searching a vector build (`eng-SEARCH-000001`) and scoring it (`eng-SEARCH-000002`), offline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from catalyst_kb_engine.build.folders import BuildError, BuildInfo
from catalyst_kb_engine.build.vectors import EmbeddingModel, EmbeddingPolicy, build_vectors
from catalyst_kb_engine.evaluate import evaluate, first_hit, verification
from catalyst_kb_engine.models import Classification
from catalyst_kb_engine.search import BuildIndex, Mode, fts_query, fuse, load_questions, render

AXES = {"invoice": [1.0, 0.0, 0.0], "keycloak": [0.0, 1.0, 0.0], "release": [0.0, 0.0, 1.0]}
CHUNKS = [
    ("c1", "docs/criteria/app/req/REQ-000001-Ab3xR9pQ.md", "REQ-000001-Ab3xR9pQ Invoices are approved twice",
     "Summary", "Two people approve every invoice before it is paid.", "invoice"),
    ("c2", "docs/criteria/app/rule/app-IAM-000001-Ab3xR9pQ.md", "app-IAM-000001-Ab3xR9pQ Sign in through the realm",
     "", "People sign in through the realm's identity provider.", "keycloak"),
    ("c3", "docs/repositories/app/readme.md", "The app", "Releasing", "A release is tagged on main.", "release"),
]  # fmt: skip


async def axis_embed(question: str) -> list[float]:
    """A test embedder: the axis of the first topic word the question names."""
    for word, vector in AXES.items():
        if word in question.lower():
            return vector
    return [0.0, 0.0, 0.0]


@pytest.fixture
def build(tmp_path: Path) -> Path:
    out = tmp_path / "build"
    records = []
    for id_, path, title, heading, text, axis in CHUNKS:
        doc = out / path
        doc.parent.mkdir(parents=True, exist_ok=True)
        meta = f"title: {title}\nclassification: Internal\nsource: KSOURCE-000009-Ab3xR9pQ\n"
        if "/criteria/" in path:
            meta += f"entity: {Path(path).stem}\ncriterion: app\n"
        doc.write_text(f"---\n{meta}---\n\n{text}\n")
        records.append({"id": id_, "path": path, "title": title, "heading": heading, "text": text,
                        "classification": "Internal", "source": "KSOURCE-000009-Ab3xR9pQ", "url": None, "axis": axis})  # fmt: skip
    (out / "chunks.jsonl").write_text(
        "".join(json.dumps({k: v for k, v in r.items() if k != "axis"}) + "\n" for r in records)
    )
    table = pa.table({"id": [r["id"] for r in records],
                      "vector": pa.array([AXES[r["axis"]] for r in records], pa.list_(pa.float32(), 3))})  # fmt: skip
    pq.write_table(table, out / "vectors.parquet")
    manifest = {"format": "kbm-build/1", "target": "vector-database", "knowledge_base": "KB-000001-Ab3xR9pQ",
                "version": "0.1.0", "embedding": {"model": "test", "dimensions": 3, "where": "local"}}  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest))
    return out


def test_the_question_never_reaches_fts5_syntax():
    assert fts_query('Who "approves" invoices? (AND NOT)') == '"who" OR "approves" OR "invoices" OR "and" OR "not"'
    assert fts_query("?") == ""


def test_keyword_search_cites_the_entity_its_criterion_and_its_source(build: Path):
    passages = asyncio.run(BuildIndex(build).search("who approves an invoice", mode=Mode.KEYWORD, k=3))
    top = passages[0]
    assert (top.rank, top.entity, top.criterion, top.source, top.heading, top.classification) == (
        1, "REQ-000001-Ab3xR9pQ", "app", "KSOURCE-000009-Ab3xR9pQ", "Summary", "Internal",
    )  # fmt: skip


def test_vector_search_finds_what_shares_no_word_with_the_question(build: Path):
    index = BuildIndex(build)
    question = "keycloak login"  # the chunk says "identity provider", not "keycloak" or "login"
    assert asyncio.run(index.search(question, mode=Mode.KEYWORD)) == []
    passages = asyncio.run(index.search(question, mode=Mode.VECTOR, embed=axis_embed, k=1))
    assert passages[0].entity == "app-IAM-000001-Ab3xR9pQ"


def test_hybrid_merges_both_rankings_by_reciprocal_rank(build: Path):
    passages = asyncio.run(BuildIndex(build).search("release invoice", embed=axis_embed, k=3))
    assert {p.path for p in passages[:2]} == {CHUNKS[0][1], CHUNKS[2][1]}
    assert fuse([(1, 9.0), (2, 8.0)], [(2, 0.9), (3, 0.8)])[0][0] == 2  # in both rankings, so first


def test_a_repository_document_has_no_entity_and_render_says_where_it_is(build: Path):
    passages = asyncio.run(BuildIndex(build).search("tagged release", mode=Mode.KEYWORD, k=1))
    assert passages[0].entity is None
    assert "docs/repositories/app/readme.md > Releasing" in render(passages)


def test_a_question_embedded_with_another_model_is_refused(build: Path):
    async def wrong(question: str) -> list[float]:
        return [1.0, 0.0]

    with pytest.raises(BuildError, match="2 dimensions, the build's 3"):
        asyncio.run(BuildIndex(build).search("invoice", mode=Mode.VECTOR, embed=wrong))


def test_a_folders_build_is_not_searchable(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(json.dumps({"target": "folders"}))
    with pytest.raises(BuildError, match="needs a vector database"):
        BuildIndex(tmp_path)


def test_evaluation_scores_each_mode_and_names_only_the_missed_question_ids(build: Path, tmp_path: Path):
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(
        "questions:\n"
        "  - {id: q1, question: who approves an invoice, expect: [REQ-000001-Ab3xR9pQ]}\n"
        "  - {id: q2, question: keycloak login, expect: [app-IAM-000001-Ab3xR9pQ]}\n"
        "  - {id: q3, question: how is a release made, expect: [criteria/app/missing.md]}\n"
    )
    score = asyncio.run(evaluate(BuildIndex(build), load_questions(questions_file), k=2, embed=axis_embed))
    assert score["modes"]["keyword"] == {"recall_at_k": 0.333, "mrr": 0.333, "misses": ["q2", "q3"]}
    assert score["modes"]["vector"]["misses"] == ["q3"] and score["modes"]["hybrid"]["recall_at_k"] == 0.667
    text = verification(score, "questions.yaml")
    assert "| keyword | 0.333 | 0.333 | 2 |" in text and "who approves" not in text


def test_first_hit_matches_an_entity_or_a_document_path(build: Path):
    passages = asyncio.run(BuildIndex(build).search("tagged release", mode=Mode.KEYWORD, k=1))
    assert first_hit(passages, ["repositories/app/readme.md"]) == 1
    assert first_hit(passages, ["REQ-000001-Ab3xR9pQ"]) is None


def test_a_question_without_what_it_expects_is_refused(tmp_path: Path):
    bad = tmp_path / "q.yaml"
    bad.write_text("questions:\n  - {id: q1, question: anything}\n")
    with pytest.raises(BuildError, match="what it expects"):
        load_questions(bad)


def test_an_engine_build_loads_for_search(tmp_path: Path):
    from pydantic_ai.embeddings import TestEmbeddingModel

    repo = tmp_path / "kb"
    (repo / "docs" / "billing").mkdir(parents=True)
    (repo / "docs" / "billing" / "invoices.md").write_text(
        "---\ntitle: Invoices\nclassification: Internal\nsource: KSOURCE-000001-Ab3xR9pQ\n---\n\n# Approval\n\nTwice.\n"
    )
    info = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.PUBLIC, Classification.INTERNAL)
    local = EmbeddingModel(TestEmbeddingModel(dimensions=8), "local-test", "local")
    asyncio.run(build_vectors(repo, tmp_path / "out", info, EmbeddingPolicy("Local only", local=local)))
    passages = asyncio.run(BuildIndex(tmp_path / "out").search("approval", mode=Mode.KEYWORD))
    assert passages[0].path == "docs/billing/invoices.md" and passages[0].source == "KSOURCE-000001-Ab3xR9pQ"


def test_the_mcp_tool_answers_as_the_command_does(build: Path):
    from catalyst_kb_engine.mcp_server import server

    app = server(build)
    assert [t.name for t in asyncio.run(app.list_tools())] == ["search"]
    result = asyncio.run(app.call_tool("search", {"question": "who approves an invoice", "mode": "keyword", "k": 1}))
    text = "".join(getattr(c, "text", "") for c in getattr(result, "content", []))
    assert "REQ-000001-Ab3xR9pQ" in text and "criterion app" in text


def test_a_build_records_and_embeds_its_input_and_prefixes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pydantic_ai.embeddings import TestEmbeddingModel

    from catalyst_kb_engine.build import vectors

    embedded: list[str] = []

    async def capture(model, texts):
        embedded.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(vectors, "_embed", capture)
    repo = tmp_path / "kb"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "rule.md").write_text(
        "---\ntitle: Assent before push\nclassification: Public\n---\n\nAsk first.\n"
    )
    info = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.PUBLIC, Classification.PUBLIC)
    local = EmbeddingModel(TestEmbeddingModel(dimensions=2), "local-test", "local")
    policy = EmbeddingPolicy("Local only", local=local)
    asyncio.run(build_vectors(repo, tmp_path / "out", info, policy, document_prefix="doc: ", query_prefix="q: "))
    assert embedded == ["doc: Assent before push\n\nAsk first."]
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    recorded = {k: manifest["embedding"][k] for k in ("input", "document_prefix", "query_prefix")}
    assert recorded == {"input": "context", "document_prefix": "doc: ", "query_prefix": "q: "}
    embedded.clear()
    asyncio.run(build_vectors(repo, tmp_path / "plain", info, policy, embedding_input="text"))
    assert embedded == ["Ask first."]


def test_a_search_embeds_the_question_with_the_builds_query_prefix(build: Path):
    manifest = json.loads((build / "manifest.json").read_text())
    manifest["embedding"]["query_prefix"] = "search_query: "
    (build / "manifest.json").write_text(json.dumps(manifest))
    asked: list[str] = []

    async def record(question: str) -> list[float]:
        asked.append(question)
        return await axis_embed(question)

    asyncio.run(BuildIndex(build).search("invoice", mode=Mode.VECTOR, embed=record))
    assert asked == ["search_query: invoice"]


def test_a_title_match_outranks_a_match_in_the_text(tmp_path: Path):
    import json as _json

    out = tmp_path / "b"
    rows = [
        ("c1", "docs/a.md", "Release notes", "", "A note on invoices and other things in passing."),
        ("c2", "docs/b.md", "Invoices", "", "How the ledger is kept."),
    ]
    (out / "docs").mkdir(parents=True)
    for _, path, title, _, text in rows:
        (out / path).write_text(f"---\ntitle: {title}\nclassification: Public\n---\n\n{text}\n")
    (out / "chunks.jsonl").write_text("".join(_json.dumps({"id": i, "path": p, "title": t, "heading": h, "text": x,
        "classification": "Public", "source": None, "url": None}) + "\n" for i, p, t, h, x in rows))  # fmt: skip
    pq.write_table(pa.table({"id": ["c1", "c2"], "vector": pa.array([[1.0], [1.0]], pa.list_(pa.float32(), 1))}),
                   out / "vectors.parquet")  # fmt: skip
    (out / "manifest.json").write_text(_json.dumps({"target": "vector-database", "embedding": {"dimensions": 1}}))
    passages = asyncio.run(BuildIndex(out).search("invoices", mode=Mode.KEYWORD))
    assert passages[0].title == "Invoices"


def test_a_search_gives_each_documents_best_passage_only_unless_asked(tmp_path: Path):
    out = tmp_path / "b"
    rows = [
        ("c1", "docs/a.md", "Invoices", "Approval", "Invoices are approved twice."),
        ("c2", "docs/a.md", "Invoices", "Payment", "Invoices are paid once approved."),
        ("c3", "docs/b.md", "Ledger", "", "The ledger lists every invoice."),
    ]
    (out / "docs").mkdir(parents=True)
    for path, title in {(p, t) for _, p, t, _, _ in rows}:
        (out / path).write_text(f"---\ntitle: {title}\nclassification: Public\n---\n\ninvoices\n")
    (out / "chunks.jsonl").write_text("".join(json.dumps({"id": i, "path": p, "title": t, "heading": h, "text": x,
        "classification": "Public", "source": None, "url": None}) + "\n" for i, p, t, h, x in rows))  # fmt: skip
    vectors = pa.array([[1.0], [1.0], [1.0]], pa.list_(pa.float32(), 1))
    pq.write_table(pa.table({"id": ["c1", "c2", "c3"], "vector": vectors}), out / "vectors.parquet")
    (out / "manifest.json").write_text(json.dumps({"target": "vector-database", "embedding": {"dimensions": 1}}))
    index = BuildIndex(out)
    once = asyncio.run(index.search("invoices", mode=Mode.KEYWORD))
    assert [p.path for p in once] == ["docs/a.md", "docs/b.md"]
    every = asyncio.run(index.search("invoices", mode=Mode.KEYWORD, per_document=0))
    assert sorted(p.path for p in every) == ["docs/a.md", "docs/a.md", "docs/b.md"]
