"""A public build as a site's pages (design 01 §5.3; `eng-PUBLISH-000002`): the knowledge base's own written pages
(the guide) as they are, and the reference, one page per source document, grouped by repository, each citing its
file on its host. The site's look and navigation are its generator's configuration (MkDocs, `mkdocs.yml`), not this.

```
<out>/
├── index.md                     the home page
├── guide/…                      the knowledge base's own pages, as written
└── reference/
    ├── index.md                 every repository, with its count of pages
    ├── <repository>.md          its pages, by title
    └── <repository>/<path>.md   one page per document, citing its file
```
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from catalyst_kb_engine.build.folders import BuildError, _split, refuse_written
from catalyst_kb_engine.sources.visibility import repository_of

OWN = "guide"
"""Where the knowledge base's own written pages are, under a build's `docs/`."""


@dataclass
class Site:
    out: Path
    guide: int = 0
    reference: int = 0


def _front(meta: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _title(meta: dict[str, Any], path: Path) -> str:
    return str(meta.get("title") or path.stem)


def make_site(build: Path, out: Path, *, title: str, intro: str) -> Site:
    """Write the site's pages for the public build `build` into `out` (new or empty)."""
    refuse_written(out)
    docs = build / "docs"
    if not docs.is_dir():
        raise BuildError(f"{build} has no docs/: it is not a folders build")
    site = Site(out)
    guide: list[tuple[str, str]] = []
    repositories: dict[str, list[tuple[str, str]]] = {}
    for document in sorted(docs.rglob("*.md")):
        rel = document.relative_to(docs)
        meta, body = _split(document.read_text(encoding="utf-8"), document)
        if rel.parts[0] == OWN:
            _write(out / rel, _front(meta, body))
            guide.append((rel.as_posix(), _title(meta, rel)))
            site.guide += 1
        elif rel.parts[0] == "repositories" and meta.get("repository") and meta.get("path"):
            name = rel.parts[1]
            page = Path("reference", name, *rel.parts[2:])
            url = meta.get("url") or repository_of(str(meta["repository"])).file_url(str(meta["path"]))
            cite = f"> From [`{meta['repository']}`: `{meta['path']}`]({url}).\n\n"
            _write(out / page, _front({"title": _title(meta, rel)}, cite + body))
            repositories.setdefault(name, []).append((Path(*rel.parts[2:]).as_posix(), _title(meta, rel)))
            site.reference += 1
        else:
            raise BuildError(f"docs/{rel.as_posix()} is neither the knowledge base's own page nor a repository's")
    for name, pages in repositories.items():
        lines = [f"- [{t}]({name}/{p})" for p, t in sorted(pages, key=lambda x: x[1].lower())]
        _write(out / "reference" / f"{name}.md", _front({"title": name}, "\n".join(lines) + "\n"))
    listing = [f"- [{name}]({name}.md): {len(pages)} pages" for name, pages in sorted(repositories.items())]
    reference = "The documents of catalyst's public repositories, one page each, as their repositories hold them.\n\n"
    _write(out / "reference" / "index.md", _front({"title": "Reference"}, reference + "\n".join(listing) + "\n"))
    contents = "\n".join(f"{i}. [{t}]({p})" for i, (p, t) in enumerate(guide, start=1))
    home = f"{intro.strip()}\n\n## The guide\n\n{contents}\n\n## The reference\n\n[Every public document](reference/index.md).\n"
    _write(out / "index.md", _front({"title": title}, home))
    return site
