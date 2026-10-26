"""Publishing a knowledge base's public build (`eng-PUBLISH-000001`; design 01 §6).

- **The public sources list** (`kbm-sources/1`): a knowledge base's public sources, each confirmed on its host when
  exported, so a public build can be read where the criterion is not (a publishing service). It names no private
  source, and so holds nothing private.
- **The publication check**: every document of the build cites a listed public source or is the knowledge base's own
  document, and is `Public`; the build's ceiling and classification are `Public`. One failure refuses it all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from catalyst_kb_engine.build.folders import BuildError, _split
from catalyst_kb_engine.models import Classification, Source, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.sources.visibility import Host, Projects, github_visibility, resolve

FORMAT = "kbm-sources/1"
STAGED = ("repositories", "criteria")
"""Where a staged source's documents are, under a build's `docs/`; anything else is the knowledge base's own."""


def export_sources(kb: KnowledgeBase, projects: Projects, host: Host = github_visibility) -> dict[str, Any]:
    """The knowledge base's public sources, each one's visibility resolved on its host first; a private one is left
    out, never written."""
    sources = []
    for sid, source in kb.sources:
        if resolve(sid, source, projects, host) is not Visibility.PUBLIC:
            continue
        sources.append({
            "id": sid,
            "title": source.title,
            "location": source.location,
            "kind": source.kind.value if source.kind else None,
            "visibility": Visibility.PUBLIC.value,
            "classification": source.classification.value if source.classification else None,
        })  # fmt: skip
    return {
        "format": FORMAT,
        "knowledge_base": kb.id,
        "classification": kb.classification.value,
        "default_classification": kb.default_classification.value,
        "sources": sources,
    }


def load_sources(path: Path) -> KnowledgeBase:
    """A public sources list as the knowledge base `read-sources` reads; refused if it names a source not public."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise BuildError(f"{path} is not a public sources list ({FORMAT})")
    sources = []
    for entry in data.get("sources") or []:
        if entry.get("visibility") != Visibility.PUBLIC.value:
            raise BuildError(
                f"{path} names {entry.get('id')} as {entry.get('visibility')}: a list holds public sources only"
            )
        mark = entry.get("classification")
        sources.append((
            entry["id"],
            Source(
                title=entry["title"], location=entry["location"],
                kind=SourceKind(entry["kind"]) if entry.get("kind") else None, visibility=Visibility.PUBLIC,
                classification=Classification(mark) if mark else None,
            ),
        ))  # fmt: skip
    return KnowledgeBase(
        data["knowledge_base"],
        Classification(data["classification"]),
        Classification(data["default_classification"]),
        sources,
    )


def publish_check(build: Path, listing: KnowledgeBase) -> int:
    """Refuse the publication of `build` unless everything in it may be public; returns the documents checked."""
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for name in ("ceiling", "classification"):
        if manifest.get(name) != Classification.PUBLIC.value:
            problems.append(f"the build's {name} is {manifest.get(name)}, not Public")
    public = {sid for sid, _ in listing.sources}
    documents = sorted((build / "docs").rglob("*.md")) if (build / "docs").is_dir() else []
    for document in documents:
        rel = document.relative_to(build / "docs").as_posix()
        meta, _ = _split(document.read_text(encoding="utf-8"), document)
        if meta.get("classification") != Classification.PUBLIC.value:
            problems.append(f"docs/{rel} is {meta.get('classification')}, not Public")
        source = meta.get("source")
        if source and source not in public:
            problems.append(f"docs/{rel} comes from {source}, which the public sources list does not name")
        if not source and rel.split("/", 1)[0] in STAGED:
            problems.append(f"docs/{rel} is a staged document that cites no source")
    if problems:
        raise BuildError("not published: " + "; ".join(problems))
    return len(documents)
