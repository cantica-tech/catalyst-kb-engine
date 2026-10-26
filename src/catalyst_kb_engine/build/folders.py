"""The folders build (`eng-OUTPUT-000001`; KBM `rr-KB-009`, `GUIDE.md` "A build"): the knowledge base's documents
at or below the ceiling, organized as its folders, with an index, a README and a manifest, readable by any model
without catalyst.

```
<version>/
├── manifest.json   format kbm-build/1, target folders, every file's SHA-256
├── README.md       what it is and how to read it
├── index.md        every document: path, title, classification, one-line summary
└── docs/<topic>/<document>.md
```
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from catalyst_kb_engine.ignore import Ignored
from catalyst_kb_engine.models import Classification

FORMAT = "kbm-build/1"


class BuildError(Exception):
    """The build cannot be written as asked; nothing was written."""


@dataclass(frozen=True)
class BuildInfo:
    knowledge_base: str
    """The `KB-` ID."""
    version: str
    floor: Classification
    """The knowledge base's own `Classification`: the floor of everything in it."""
    ceiling: Classification
    build: str | None = None
    """The `KBUILD-` ID, once recorded."""
    content_commit: str | None = None
    built: datetime | None = None


@dataclass
class _Entry:
    path: str  # under docs/
    meta: dict[str, Any]
    body: str
    effective: Classification
    pointer: bool


@dataclass
class FoldersBuild:
    out: Path
    classification: Classification
    documents: int = 0
    pointers: int = 0
    left_out: int = 0
    files: dict[str, str] = field(default_factory=dict)


def _split(text: str, where: Path) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        raise BuildError(f"{where}: front matter is not closed")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise BuildError(f"{where}: front matter is not a mapping")
    return meta, text[end + 4 :].lstrip("\n")


def _classification(value: Any, where: Path) -> Classification | None:
    if value in (None, "", "Unmarked"):
        return None
    try:
        return Classification(value)
    except ValueError:
        raise BuildError(f"{where}: unknown classification {value!r}") from None


def _read(
    repo: Path, folder: str, info: BuildInfo, pointer: bool, ignored: Ignored
) -> tuple[list[_Entry], list[Path], int]:
    entries, unmarked, broken = [], [], 0
    root = repo / folder
    for file in sorted(root.rglob("*.md")) if root.is_dir() else ():
        if file.name == "README.md":
            continue  # a level's description; the build's index replaces them
        if ignored(file.relative_to(repo).as_posix()):
            continue  # opted out of catalyst, so not part of the knowledge base (`eng-SOURCE-000004`)
        meta, body = _split(file.read_text(encoding="utf-8"), file)
        own = _classification(meta.get("classification"), file)
        if own is None:
            unmarked.append(file.relative_to(repo))
            continue
        if pointer and meta.get("status") == "broken":
            broken += 1  # never built: its target is gone (KBM `/kb-refresh`)
            continue
        rel = file.relative_to(root).as_posix()
        entries.append(_Entry(rel, meta, body, Classification.highest(own, info.floor), pointer))
    return entries, unmarked, broken


def _summary(body: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return line if len(line) <= 160 else line[:157] + "..."
    return ""


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _front(meta: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body


@dataclass
class Selection:
    """What a build takes from the repository: what is at or below the ceiling, and what was left out."""

    kept: list[_Entry]
    classification: Classification
    documents: int
    pointers: int
    left_out: int


def select(repo: Path, info: BuildInfo) -> Selection:
    """The documents and pointers a build takes; refuses unmarked ones (KBM INV-KB-4) and a floor above the ceiling."""
    ignored = Ignored(repo)
    documents, unmarked, _ = _read(repo, "docs", info, pointer=False, ignored=ignored)
    pointers, unmarked_pointers, broken = _read(repo, "pointers", info, pointer=True, ignored=ignored)
    if unmarked or unmarked_pointers:
        listed = ", ".join(str(p) for p in [*unmarked, *unmarked_pointers])
        raise BuildError(f"unmarked, so nothing is built: {listed}")
    kept = sorted((e for e in [*documents, *pointers] if e.effective.rank <= info.ceiling.rank), key=lambda e: e.path)
    paths = [e.path for e in kept]
    if len(paths) != len(set(paths)):
        raise BuildError("a pointer and a document share a path; rename one")
    classification = Classification.highest(info.floor, *(e.effective for e in kept))
    if classification.rank > info.ceiling.rank:
        raise BuildError(f"the knowledge base's floor {info.floor.value} is above the ceiling {info.ceiling.value}")
    return Selection(
        kept=kept,
        classification=classification,
        documents=sum(not e.pointer for e in kept),
        pointers=sum(e.pointer for e in kept),
        left_out=len(documents) + len(pointers) - len(kept) + broken,
    )


def stage_documents(selection: Selection, info: BuildInfo) -> dict[str, bytes]:
    """`docs/` (each document with its effective classification and content hash) and `index.md`."""
    staged: dict[str, bytes] = {}
    lines = []
    for entry in selection.kept:
        meta = dict(entry.meta)
        meta["classification"] = entry.effective.value
        meta.pop("hash", None)
        meta["hash"] = _sha(entry.body.encode("utf-8"))
        staged[f"docs/{entry.path}"] = _front(meta, entry.body).encode("utf-8")
        title = str(meta.get("title") or Path(entry.path).stem)
        summary = _summary(entry.body)
        lines.append(f"- [{title}](docs/{entry.path}) ({entry.effective.value}){' — ' + summary if summary else ''}")
    staged["index.md"] = (
        f"# Index of {info.knowledge_base} {info.version}\n\n"
        + ("\n".join(lines) if lines else "*(no document at or below the ceiling)*")
        + "\n"
    ).encode("utf-8")
    return staged


def refuse_written(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise BuildError(f"{out} is not empty: a build is written once, into its own version")


def write_build(out: Path, staged: dict[str, bytes], info: BuildInfo, selection: Selection, **more: Any) -> dict:
    """Every staged file, then `manifest.json` with each one's SHA-256 (`kbm-build/1`); returns the manifest."""
    built = (info.built or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = {
        "format": FORMAT,
        **{k: v for k, v in more.items() if k == "target"},
        "knowledge_base": info.knowledge_base,
        "build": info.build,
        "version": info.version,
        "classification": selection.classification.value,
        "ceiling": info.ceiling.value,
        "content_commit": info.content_commit,
        **{k: v for k, v in more.items() if k not in ("target", "counts")},
        "counts": more.get("counts")
        or {"documents": selection.documents, "pointers": selection.pointers, "left_out": selection.left_out},
        "files": {name: _sha(data) for name, data in sorted(staged.items())},
        "built": built,
    }
    for name, data in {
        **staged,
        "manifest.json": (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(),
    }.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest


def build_folders(repo: Path, out: Path, info: BuildInfo) -> FoldersBuild:
    """Write the folders build of the knowledge base repository `repo` into `out` (new or empty)."""
    refuse_written(out)
    selection = select(repo, info)
    result = FoldersBuild(
        out=out,
        classification=selection.classification,
        documents=selection.documents,
        pointers=selection.pointers,
        left_out=selection.left_out,
    )
    staged = stage_documents(selection, info)
    staged["README.md"] = _readme(info, result).encode("utf-8")
    result.files = write_build(out, staged, info, selection, target="folders")["files"]
    return result


def _readme(info: BuildInfo, result: FoldersBuild) -> str:
    return f"""# {info.knowledge_base} {info.version}: organized documents

A build of a knowledge base in the `{FORMAT}` format, target `folders`. It needs no particular tool, account,
network or model: every file is UTF-8 markdown or JSON.

- **Classification**: {result.classification.value} (ceiling {info.ceiling.value}). Store and share it only where
  that classification allows. Each document's own classification is in its front matter.
- **Contents**: {result.documents} documents and {result.pointers} pointers; {result.left_out} left out by the
  ceiling or as broken pointers.

## Reading it

- `index.md` lists every document with its title, classification and a one-line summary: give it to a model first.
- `docs/` holds the documents, organized by topic. Each starts with YAML front matter (`title`, `classification`,
  `source`, `updated`, `hash`); a pointer also has its `url`.
- `manifest.json` says what this is and gives every file's SHA-256 (`files`), to check it is complete and unchanged.
"""
