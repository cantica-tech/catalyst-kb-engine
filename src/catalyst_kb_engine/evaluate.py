"""A search measured against an evaluation set (`eng-SEARCH-000002`; design 01 §7): each question with the documents
or entity IDs a good answer cites; recall at k and mean reciprocal rank, per mode. Only scores, counts and question
IDs are reported: the questions themselves may be drawn from private sources."""

from __future__ import annotations

from typing import Any

from catalyst_kb_engine.search import BuildIndex, Embed, Mode, Passage, query_embedder


def _normal(path: str) -> str:
    return path.removeprefix("docs/")


def first_hit(passages: list[Passage], expect: list[str]) -> int | None:
    """The rank of the first passage citing an expected entity or document, if any."""
    wanted = {_normal(e) for e in expect}
    for p in passages:
        if (p.entity and p.entity in wanted) or _normal(p.path) in wanted:
            return p.rank
    return None


async def evaluate(
    index: BuildIndex,
    questions: list[dict[str, Any]],
    *,
    k: int = 10,
    modes: tuple[Mode, ...] = (Mode.KEYWORD, Mode.VECTOR, Mode.HYBRID),
    embed: Embed | None = None,
) -> dict[str, Any]:
    """Every question in every mode; each question is embedded once, by the build's model unless `embed` is given."""
    embedder = embed
    cache: dict[str, list[float]] = {}

    async def cached(question: str) -> list[float]:
        nonlocal embedder
        if question not in cache:
            embedder = embedder or query_embedder(index.model)
            cache[question] = await embedder(question)
        return cache[question]

    result: dict[str, Any] = {"k": k, "questions": len(questions), "modes": {}}
    for mode in modes:
        ranks: list[int | None] = []
        misses = []
        for q in questions:
            passages = await index.search(q["question"], k=k, mode=mode, embed=cached)
            rank = first_hit(passages, [str(e) for e in q["expect"]])
            ranks.append(rank)
            if rank is None:
                misses.append(q["id"])
        n = len(questions) or 1
        result["modes"][mode.value] = {
            "recall_at_k": round(sum(r is not None for r in ranks) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
            "misses": misses,
        }
    return result


def verification(score: dict[str, Any], questions_file: str) -> str:
    """The score as a `KBUILD-`'s Verification text (KBM: "a sample of queries and what they returned")."""
    lines = [
        f"Evaluated against {score['questions']} questions (`{questions_file}`), top {score['k']} passages:",
        "",
        "| Mode | Recall at k | MRR | Missed |",
        "| --- | --- | --- | --- |",
    ]
    for mode, s in score["modes"].items():
        lines.append(f"| {mode} | {s['recall_at_k']} | {s['mrr']} | {len(s['misses'])} |")
    return "\n".join(lines)
