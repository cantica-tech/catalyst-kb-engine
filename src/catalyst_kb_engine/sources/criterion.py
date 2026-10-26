"""A catalyst criterion as a source (`eng-SOURCE-000001`; design 01 §5.2): read only through catalyst's CLI in its
project, `list all --json` then `view <ID> --json`, one markdown document per entity and rule, citing its ID, its
criterion, its type and its status, with its fields, sections, links and its own history."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.sources.visibility import SourceError

COMPOSED = {"rules/Rules-of-Rules.md"}
"""Composed from the kernel's and modules' meta-rules, public in their own repositories: left out."""
_NOT_FIELDS = {"id", "type", "title", "file", "line", "Name", "Filename", "links", "sections", "next", "linked_from"}
_NOT_FIELDS |= {"journal", "text", "status", "domain", "retired", "strength"}
UNSET = "*(none yet)*"


@dataclass(frozen=True)
class EntityDocument:
    """One entity or rule of a criterion, as a document."""

    id: str
    type: str
    title: str
    status: str
    updated: str | None
    body: str

    @property
    def path(self) -> str:
        """Its path under the criterion's folder: `<type>/<ID>.md`, the type in lower case (`rule`, `req`, …)."""
        return f"{self.type.lower()}/{self.id}.md"


def _history(view: dict[str, Any]) -> list[str]:
    lines = []
    for entry in view.get("journal") or []:
        given = entry.get("intent") or []
        intent = "; ".join([given] if isinstance(given, str) else given)  # a string, a list or nothing
        lines.append(
            f"- {entry.get('timestamp') or ''} {entry.get('actor') or ''}, `{entry.get('command') or ''}` "
            f"{entry.get('action') or ''}{': ' + intent if intent else ''}"
        )
    return lines


def _links(view: dict[str, Any]) -> list[str]:
    lines = [f"- {name}: {', '.join(f'`{i}`' for i in ids)}" for name, ids in (view.get("links") or {}).items() if ids]
    back = [f"`{link['id']}` ({link['field']})" for link in view.get("linked_from") or []]
    return lines + ([f"- Cited by: {', '.join(back)}"] if back else [])


def _cells(fields: list[tuple[str, str]]) -> str:
    return "| Field | Value |\n| --- | --- |\n" + "\n".join(f"| {k} | {v.replace('|', '/')} |" for k, v in fields)


def _rule_status(view: dict[str, Any]) -> str:
    if view.get("retired"):
        return "retired"
    return str(view.get("status") or "").split(" — ")[0].strip() or "unknown"


def render(view: dict[str, Any], project: str) -> EntityDocument:
    """A `view --json` record as a document: the rule's own text, a table row's cells, or the entity's fields and
    sections; then its links and its history (its own journal entries, never another entity's content)."""
    id_, type_, title = view["id"], view["type"], str(view.get("title") or view["id"])
    parts = [f"# `{id_}` {title}", f"In the criterion of `{project}`."]
    if type_ == "rule":
        status = _rule_status(view)
        text = str(view.get("text") or "")
        parts.append(text.split("\n", 1)[1].strip() if text.startswith("#") and "\n" in text else text.strip())
    elif view.get("row"):  # an entity kept as a row of a table (`spec/view.schema.json` `tableRow`, kernel 0.116.1)
        status = str(view.get("status") or "unknown")
        cells = [(k, str(v)) for k, v in (view.get("fields") or {}).items() if v not in (None, "", UNSET)]
        parts.append(f"A row of `{view.get('file')}`." + ("\n\n" + _cells(cells) if cells else ""))
    else:
        status = str(view.get("Status") or "unknown")
        fields = [(k, str(v)) for k, v in view.items() if k not in _NOT_FIELDS and v not in (None, "", UNSET)]
        if fields:
            parts.append(_cells(fields))
        for section in view.get("sections") or []:
            parts.append(f"## {section['heading']}\n\n{str(section.get('text') or '').strip()}")
    if links := _links(view):
        parts.append("## Links\n\n" + "\n".join(links))
    history = _history(view)
    if history:
        parts.append("## History\n\n" + "\n".join(history))
    updated = max((e.get("timestamp") or "" for e in view.get("journal") or []), default="")[:10] or None
    return EntityDocument(id_, type_, title, status, updated, "\n\n".join(p for p in parts if p) + "\n")


@dataclass(frozen=True)
class CriterionRead:
    documents: list[EntityDocument]
    """The entities and rules viewed in this read."""
    unviewable: list[str]
    """IDs `list all` gives without a file, which `view` cannot show (a roadmap's rows): left out, and counted."""
    carried: list[str] = field(default_factory=list)
    """Paths (`<type>/<ID>.md`) of the documents an incremental read carries over from the previous one, unviewed."""


def _path(item: dict[str, Any]) -> str:
    return f"{str(item['type']).lower()}/{item['id']}.md"


def moved_since(cli: CatalystCLI, since: str) -> tuple[set[str], set[str]]:
    """The IDs a journal entry since `since` names (its artifact, its targets) and the criterion files it touched
    (`eng-SOURCE-000003`)."""
    ids: set[str] = set()
    files: set[str] = set()
    for entry in cli.json("journal", "show", "--since", since):
        ids.add(str(entry.get("artifact") or ""))
        ids.update(str(t) for t in entry.get("targets") or [])
        files.update(str(f.get("path") or "").removeprefix(".criterion/") for f in entry.get("files") or [])
    return ids, files


def read_criterion(
    cli: CatalystCLI, project: str, *, workers: int = 8, since: str | None = None, have: frozenset[str] = frozenset()
) -> CriterionRead:
    """Every entity and rule of the criterion of `project`, whose checkout `cli` runs in; its name is checked first
    (`catalyst where`). The composed meta-rules are left out (`COMPOSED`). With `since` (the previous read's time) and
    `have` (the paths it staged), only what is new or what the journal says moved is viewed; the rest is carried."""
    named = cli.json("where").get("name")
    if named != project:
        raise SourceError(f"{cli.project} is the catalyst project {named!r}, not {project!r}")
    listed = cli.json("list", "all")
    items = [i for i in listed if i.get("file") and i["file"] not in COMPOSED]
    unviewable = sorted(i["id"] for i in listed if not i.get("file"))
    carried: set[str] = set()
    if since is not None:
        ids, files = moved_since(cli, since)
        carried = {_path(i) for i in items if _path(i) in have and i["id"] not in ids and i["file"] not in files}
        items = [i for i in items if _path(i) not in carried]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        views = list(pool.map(lambda item: cli.view(item["id"]), items))
        # what a moved entity cites now shows it among its back-references: view that too
        cited = {i for view in views for linked in (view.get("links") or {}).values() for i in linked}
        again = [i for i in listed if i.get("id") in cited and i.get("file") and _path(i) in carried]
        carried -= {_path(i) for i in again}
        views += list(pool.map(lambda item: cli.view(item["id"]), again))
    documents = sorted((render(view, project) for view in views), key=lambda d: d.path)
    return CriterionRead(documents, unviewable, sorted(carried))
