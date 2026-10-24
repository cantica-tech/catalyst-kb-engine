"""Chunks of a build's documents, by heading (KBM `GUIDE.md` "A build": `chunking.by` `heading`)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

CHARS_PER_TOKEN = 4
"""A token is taken as about four characters: chunk sizes need no tokenizer, so no model is assumed."""
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Chunk:
    id: str
    path: str
    title: str
    heading: str
    text: str
    classification: str
    source: str | None
    url: str | None

    def record(self) -> dict:
        return asdict(self)


def _sections(body: str) -> list[tuple[str, str]]:
    """(heading path, text) for each part of the body between headings."""
    trail: list[str] = []
    sections, lines = [], []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append((" > ".join(trail), text))
        lines.clear()

    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            trail[:] = [*trail[: level - 1], match.group(2)]
        else:
            lines.append(line)
    flush()
    return sections


def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Pieces of at most `size` characters, cut at paragraph or word boundaries, each starting `overlap` before."""
    if len(text) <= size:
        return [text]
    pieces, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n\n", start, end), text.rfind(" ", start, end))
            end = cut if cut > start + size // 2 else end
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in pieces if p]


def chunk(
    path: str, title: str, body: str, classification: str, *, max_tokens: int, overlap: int, **meta: str | None
) -> list[Chunk]:
    size, back = max_tokens * CHARS_PER_TOKEN, overlap * CHARS_PER_TOKEN
    out: list[Chunk] = []
    for heading, text in _sections(body):
        for piece in _windows(text, size, back):
            out.append(
                Chunk(
                    id=f"{path}#{len(out) + 1}",
                    path=path,
                    title=title,
                    heading=heading,
                    text=piece,
                    classification=classification,
                    source=meta.get("source"),
                    url=meta.get("url"),
                )
            )
    return out
