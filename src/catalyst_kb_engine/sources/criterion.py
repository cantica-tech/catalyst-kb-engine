"""A catalyst criterion as a source (`eng-SOURCE-000001`; design 01 §5.2): read only through catalyst's CLI in its
project, `list all --json` then `view <ID> --json`, one markdown document per entity and rule, citing its ID, its
criterion, its type and its status, with its fields, sections, links and its own history."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
        intent = "; ".join(entry.get("intent") or [])
        lines.append(
            f"- {entry.get('timestamp', '')} {entry.get('actor', '')}, `{entry.get('command', '')}` "
            f"{entry.get('action', '')}{': ' + intent if intent else ''}"
        )
    return lines


def _links(view: dict[str, Any]) -> list[str]:
    lines = [f"- {name}: {', '.join(f'`{i}`' for i in ids)}" for name, ids in (view.get("links") or {}).items() if ids]
    back = [f"`{link['id']}` ({link['field']})" for link in view.get("linked_from") or []]
    return lines + ([f"- Cited by: {', '.join(back)}"] if back else [])


def _rule_status(view: dict[str, Any]) -> str:
    if view.get("retired"):
        return "retired"
    return str(view.get("status") or "").split(" — ")[0].strip() or "unknown"


def render(view: dict[str, Any], project: str) -> EntityDocument:
    """A `view --json` record as a document: the rule's own text, or the entity's fields and sections; then its links
    and its history (its own journal entries, never another entity's content)."""
    id_, type_, title = view["id"], view["type"], str(view.get("title") or view["id"])
    parts = [f"# `{id_}` {title}", f"In the criterion of `{project}`."]
    if type_ == "rule":
        status = _rule_status(view)
        text = str(view.get("text") or "")
        parts.append(text.split("\n", 1)[1].strip() if text.startswith("#") and "\n" in text else text.strip())
    else:
        status = str(view.get("Status") or "unknown")
        fields = [(k, str(v)) for k, v in view.items() if k not in _NOT_FIELDS and v not in (None, "", UNSET)]
        if fields:
            parts.append(
                "| Field | Value |\n| --- | --- |\n" + "\n".join(f"| {k} | {v.replace('|', '/')} |" for k, v in fields)
            )
        for section in view.get("sections") or []:
            parts.append(f"## {section['heading']}\n\n{str(section.get('text') or '').strip()}")
    if links := _links(view):
        parts.append("## Links\n\n" + "\n".join(links))
    history = _history(view)
    if history:
        parts.append("## History\n\n" + "\n".join(history))
    updated = max((e.get("timestamp", "") for e in view.get("journal") or []), default="")[:10] or None
    return EntityDocument(id_, type_, title, status, updated, "\n\n".join(p for p in parts if p) + "\n")


@dataclass(frozen=True)
class CriterionRead:
    documents: list[EntityDocument]
    unviewable: list[str]
    """IDs `list all` gives without a file, which `view` cannot show (a roadmap's rows): left out, and counted."""


def read_criterion(cli: CatalystCLI, project: str, *, workers: int = 8) -> CriterionRead:
    """Every entity and rule of the criterion of `project`, whose checkout `cli` runs in; its name is checked first
    (`catalyst where`). The composed meta-rules are left out (`COMPOSED`)."""
    named = cli.json("where").get("name")
    if named != project:
        raise SourceError(f"{cli.project} is the catalyst project {named!r}, not {project!r}")
    listed = cli.json("list", "all")
    items = [i for i in listed if i.get("file") and i["file"] not in COMPOSED]
    unviewable = sorted(i["id"] for i in listed if not i.get("file"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        views = list(pool.map(lambda item: cli.view(item["id"]), items))
    return CriterionRead(sorted((render(view, project) for view in views), key=lambda d: d.path), unviewable)
