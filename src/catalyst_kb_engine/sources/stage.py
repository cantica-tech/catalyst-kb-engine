"""A knowledge base's sources, read and staged (design 01 §5.1, §6): each document written under
`<out>/docs/<criteria|repositories>/<name>/` with its front matter, in the layout the builds read, so a build of
`<out>` is a build of the sources. A private source's documents are at least `Internal`; with `public_only`, a
private source is never opened. `<out>` holds private data whenever a private source was read: keep it out of any
public repository."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from catalyst_kb_engine.build.folders import _split, refuse_written
from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.models import PRIVATE_FLOOR, Classification, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.sources.criterion import read_criterion
from catalyst_kb_engine.sources.visibility import (
    Host,
    Projects,
    SourceError,
    github_repository,
    github_visibility,
    resolve as resolve_visibility,
)


@dataclass
class SourceRead:
    source: str
    """The `KSOURCE-` ID."""
    title: str
    visibility: Visibility | None = None
    documents: int = 0
    by_classification: dict[str, int] = field(default_factory=dict)
    skipped: str | None = None
    """Why nothing was read from it, when nothing was."""
    unviewable: int = 0
    """Items its criterion lists but cannot show (`CriterionRead.unviewable`): left out."""

    def mark(self, own: Classification | None, base: Classification, floor: Classification) -> str:
        """A document's classification, counted: its own mark or its source's, never below the floor."""
        level = Classification.highest(own or base, base, floor)
        self.by_classification[level.value] = self.by_classification.get(level.value, 0) + 1
        self.documents += 1
        return level.value


@dataclass
class Staged:
    out: Path
    sources: list[SourceRead]

    @property
    def documents(self) -> int:
        return sum(s.documents for s in self.sources)


def _write(out: Path, path: str, meta: dict[str, Any], body: str) -> None:
    target = out / "docs" / path
    if target.exists():
        raise SourceError(f"two documents would be staged at docs/{path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body, "utf-8")


def _title(body: str, path: str) -> str:
    heading = next((line for line in body.splitlines() if line.startswith("# ")), None)
    return heading[2:].strip() if heading else Path(path).stem


def _staged_path(rel: str) -> str:
    """A repository's `README.md` is a document: staged as `readme.md`, since a build skips `README.md` (a knowledge
    base repository's folder description)."""
    path = Path(rel)
    return (path.parent / "readme.md").as_posix() if path.name == "README.md" else rel


def _repository_files(checkout: Path) -> list[str]:
    done = subprocess.run(["git", "-C", str(checkout), "ls-files", "*.md"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SourceError(f"{checkout} is not a git checkout: {done.stderr.strip()}")
    return sorted(line for line in done.stdout.splitlines() if line)


def stage(
    kb: KnowledgeBase,
    out: Path,
    projects: Projects,
    *,
    public_only: bool = False,
    catalyst: Callable[[Path], CatalystCLI] = CatalystCLI,
    host: Host = github_visibility,
    workers: int = 8,
) -> Staged:
    """Read every source of `kb` into `out` (new or empty). Every source's visibility is resolved before any is read,
    so a disagreement stops the whole read (`eng-SOURCE-000002`)."""
    refuse_written(out)
    visibilities = {sid: resolve_visibility(sid, source, projects, host) for sid, source in kb.sources}
    report = []
    for sid, source in kb.sources:
        read = SourceRead(sid, source.title, visibilities[sid])
        report.append(read)
        if public_only and read.visibility is not Visibility.PUBLIC:
            read.skipped = "private: a public read never opens it"
            continue
        base = source.classification or kb.default_classification
        floor = kb.classification
        if read.visibility is Visibility.PRIVATE:
            floor = Classification.highest(floor, PRIVATE_FLOOR)

        kind = source.kind
        if kind is SourceKind.CRITERION:
            name = source.project or ""
            cli = catalyst(projects.find(name, catalyst=True))
            criterion = read_criterion(cli, name, workers=workers)
            read.unviewable = len(criterion.unviewable)
            for doc in criterion.documents:
                meta = {
                    "title": f"{doc.id} {doc.title}",
                    "classification": read.mark(None, base, floor),
                    "source": sid,
                    "entity": doc.id,
                    "type": doc.type,
                    "status": doc.status,
                    "criterion": name,
                }
                if doc.updated:
                    meta["updated"] = doc.updated
                _write(out, f"criteria/{name}/{doc.path}", meta, doc.body)
        elif kind in (SourceKind.REPOSITORY, None) and (repo := github_repository(source.location)):
            name = repo.split("/")[1]
            checkout = projects.find(name)
            for rel in _repository_files(checkout):
                own_meta, body = _split((checkout / rel).read_text(encoding="utf-8"), checkout / rel)
                own = own_meta.get("classification")
                level = Classification(own) if own in {c.value for c in Classification} else None
                meta = {
                    "title": str(own_meta.get("title") or _title(body, rel)),
                    "classification": read.mark(level, base, floor),
                    "source": sid,
                    "repository": repo,
                    "path": rel,
                }
                _write(out, f"repositories/{name}/{_staged_path(rel)}", meta, body)
        else:
            read.skipped = f"not read: a {kind.value if kind else 'source'} at {source.location} is not supported yet"
    return Staged(out, report)


def summary(staged: Staged) -> dict[str, Any]:
    """Counts only: what was read from each source, never its content."""
    return {
        "out": str(staged.out),
        "documents": staged.documents,
        "sources": [
            {
                "source": s.source,
                "title": s.title,
                "visibility": s.visibility.value if s.visibility else None,
                "documents": s.documents,
                "classification": s.by_classification,
                **({"skipped": s.skipped} if s.skipped else {}),
                **({"unviewable": s.unviewable} if s.unviewable else {}),
            }
            for s in staged.sources
        ],
    }
