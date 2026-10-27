"""A knowledge base's sources, read and staged (design 01 §5.1, §6): each document written under
`<out>/docs/<criteria|repositories>/<name>/` with its front matter, in the layout the builds read, so a build of
`<out>` is a build of the sources. A private source's documents are at least `Internal`; with `public_only`, a
private source is never opened. `<out>` holds private data whenever a private source was read: keep it out of any
public repository. `<out>/read.json` says when and how each source was read, so the next read can be incremental
(`eng-SOURCE-000003`): given it as `previous`, a criterion whose source is unchanged re-views only what moved."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from catalyst_kb_engine.build.folders import _split, refuse_written
from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.ignore import Ignored
from catalyst_kb_engine.models import PRIVATE_FLOOR, Classification, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.sources.criterion import read_criterion
from catalyst_kb_engine.sources.visibility import (
    Host,
    Projects,
    SourceError,
    hosted_visibility,
    repository,
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
    carried: int = 0
    """Documents an incremental read carried over from the previous read, unviewed."""

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


_FIELDS = "%h%x1f%ad%x1f%an%x1f%s"
"""A commit as its short hash, date, author's name and subject: never an author's e-mail (`eng-SOURCE-000005`)."""
HISTORY_DOCUMENT = "git-history.md"


def _git(checkout: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SourceError(f"git {args[0]} failed in {checkout}: {done.stderr.strip()}")
    return done.stdout


def _commit_line(fields: list[str]) -> str:
    sha, date, author, subject = [*fields, "", "", "", ""][:4]
    return f"- {date} `{sha}` {author}: {subject}"


def _file_history(checkout: Path, rel: str, n: int) -> str:
    """The last `n` commits that touched `rel`, as a History section; empty when none did."""
    out = _git(checkout, "log", f"-n{n}", "--date=short", f"--format={_FIELDS}", "--", rel)
    lines = [_commit_line(line.split("\x1f")) for line in out.splitlines() if line]
    return "## History\n\n" + "\n".join(lines) if lines else ""


def _repository_history(checkout: Path, repo: str, n: int) -> str:
    """The repository's last `n` commits across all its files, each with the files it changed."""
    out = _git(checkout, "log", f"-n{n}", "--date=short", f"--format=%x1e{_FIELDS}", "--name-only")
    lines = []
    for record in out.split("\x1e"):
        head, _, rest = record.strip("\n").partition("\n")
        if not head:
            continue
        files = [f for f in rest.splitlines() if f]
        shown = ", ".join(f"`{f}`" for f in files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
        lines.append(_commit_line(head.split("\x1f")) + (f" ({shown})" if files else ""))
    return f"# {repo}: recent history\n\nThe last {len(lines)} commits of `{repo}`, newest first.\n\n" + "\n".join(
        lines
    )


def _require_full_history(checkout: Path) -> None:
    if _git(checkout, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise SourceError(
            f"{checkout} is a shallow clone, so its history is incomplete: run `git -C {checkout} fetch --unshallow`, "
            "or read without --history"
        )


def _repository_files(checkout: Path) -> list[str]:
    done = subprocess.run(["git", "-C", str(checkout), "ls-files", "*.md"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SourceError(f"{checkout} is not a git checkout: {done.stderr.strip()}")
    ignored = Ignored(checkout)  # what catalyst ignores, a knowledge base leaves out (`eng-SOURCE-000004`)
    return sorted(line for line in done.stdout.splitlines() if line and not ignored(line))


def stage(
    kb: KnowledgeBase,
    out: Path,
    projects: Projects,
    *,
    public_only: bool = False,
    catalyst: Callable[[Path], CatalystCLI] = CatalystCLI,
    host: Host = hosted_visibility,
    workers: int = 8,
    previous: Path | None = None,
    history: int = 0,
) -> Staged:
    """Read every source of `kb` into `out` (new or empty). Every source's visibility is resolved before any is read,
    so a disagreement stops the whole read (`eng-SOURCE-000002`). With `previous` (an earlier staging directory of
    the same knowledge base), each unchanged criterion source is read incrementally (`eng-SOURCE-000003`). With
    `history`, each repository's last `history` commits are read too: each document's, and the repository's own log
    (`eng-SOURCE-000005`)."""
    refuse_written(out)
    read_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    before = _previous_read(previous, kb.id)
    visibilities = {sid: resolve_visibility(sid, source, projects, host) for sid, source in kb.sources}
    report = []
    reads: dict[str, dict[str, Any]] = {}
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
        how = {"kind": kind.value if kind else None, "location": source.location, "visibility": visibilities[sid].value,
               "classification": base.value, "floor": floor.value}  # fmt: skip
        reads[sid] = {**how, "read_at": read_at}
        if kind is SourceKind.CRITERION:
            name = source.project or ""
            cli = catalyst(projects.find(name, catalyst=True))
            then = (before or {}).get(sid) or {}
            since = then.get("read_at") if {k: then.get(k) for k in how} == how else None
            old = (previous or out) / "docs" / "criteria" / name  # nothing is carried without a previous read
            have = frozenset(f.relative_to(old).as_posix() for f in old.rglob("*.md")) if since else frozenset()
            criterion = read_criterion(cli, name, workers=workers, since=since, have=have)
            read.unviewable = len(criterion.unviewable)
            for path in criterion.carried:
                text = (old / path).read_text(encoding="utf-8")
                meta, body = _split(text, old / path)
                read.mark(Classification(meta["classification"]), base, floor)
                read.carried += 1
                _write(out, f"criteria/{name}/{path}", meta, body)
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
        elif kind in (SourceKind.REPOSITORY, None) and (hosted := repository(source.location)):
            repo, name = hosted.path, hosted.name
            checkout = projects.find(name)
            if history:
                _require_full_history(checkout)
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
                if history and (section := _file_history(checkout, rel, history)):
                    body = body.rstrip("\n") + "\n\n" + section + "\n"
                _write(out, f"repositories/{name}/{_staged_path(rel)}", meta, body)
            if history:
                meta = {
                    "title": f"{repo}: recent history",
                    "classification": read.mark(None, base, floor),
                    "source": sid,
                    "repository": repo,
                    "path": HISTORY_DOCUMENT,
                    "url": hosted.commits_url,
                }
                _write(
                    out,
                    f"repositories/{name}/{HISTORY_DOCUMENT}",
                    meta,
                    _repository_history(checkout, repo, history) + "\n",
                )
        else:
            read.skipped = f"not read: a {kind.value if kind else 'source'} at {source.location} is not supported yet"
            del reads[sid]
    record = {"knowledge_base": kb.id, "read_at": read_at, "sources": reads}
    out.mkdir(parents=True, exist_ok=True)
    (out / "read.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return Staged(out, report)


def _previous_read(previous: Path | None, kb: str) -> dict[str, dict[str, Any]] | None:
    """The sources an earlier staging directory read, and how; refused if it was another knowledge base's."""
    if previous is None:
        return None
    record = json.loads((previous / "read.json").read_text(encoding="utf-8"))
    if record.get("knowledge_base") != kb:
        raise SourceError(f"{previous} was read for {record.get('knowledge_base')}, not {kb}")
    return record.get("sources") or {}


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
                **({"carried": s.carried} if s.carried else {}),
            }
            for s in staged.sources
        ],
    }
