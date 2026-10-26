"""Publishing a public build (`eng-PUBLISH-000001`, `eng-PUBLISH-000002`), offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalyst_kb_engine.build.folders import BuildError, BuildInfo, build_folders
from catalyst_kb_engine.models import Classification, Source, SourceKind, Visibility
from catalyst_kb_engine.publish import export_sources, load_sources, publish_check
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.site import make_site
from catalyst_kb_engine.sources.visibility import Projects

PUBLIC = Source(title="app", location="https://github.com/acme/app", kind=SourceKind.REPOSITORY,
                visibility=Visibility.PUBLIC, classification=Classification.PUBLIC)  # fmt: skip
PRIVATE = Source(title="secrets", location="https://github.com/acme/secrets", kind=SourceKind.REPOSITORY,
                 visibility=Visibility.PRIVATE)  # fmt: skip
HOSTS = {"acme/app": Visibility.PUBLIC, "acme/secrets": Visibility.PRIVATE}.get
KB = KnowledgeBase("KB-000001-Ab3xR9pQ", Classification.PUBLIC, Classification.INTERNAL,
                   [("KSOURCE-1", PUBLIC), ("KSOURCE-2", PRIVATE)])  # fmt: skip


def test_the_export_names_public_sources_only(tmp_path: Path):
    listing = export_sources(KB, Projects(tmp_path), HOSTS)
    assert [s["id"] for s in listing["sources"]] == ["KSOURCE-1"]
    assert "secrets" not in json.dumps(listing)
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(listing))
    kb = load_sources(path)
    assert kb.id == KB.id and [(sid, s.visibility) for sid, s in kb.sources] == [("KSOURCE-1", Visibility.PUBLIC)]


def test_a_list_naming_a_private_source_is_refused(tmp_path: Path):
    listing = export_sources(KB, Projects(tmp_path), HOSTS)
    listing["sources"].append({"id": "KSOURCE-2", "title": "secrets", "location": "x", "visibility": "Private"})
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(listing))
    with pytest.raises(BuildError, match="public sources only"):
        load_sources(path)


def _doc(repo: Path, rel: str, meta: str, body: str = "Text.") -> None:
    path = repo / "docs" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{meta}---\n\n{body}\n")


def _build(tmp_path: Path, *docs: tuple[str, str], ceiling: Classification = Classification.PUBLIC) -> Path:
    repo = tmp_path / "staging"
    for rel, meta in docs:
        _doc(repo, rel, meta)
    info = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.PUBLIC, ceiling)
    build_folders(repo, tmp_path / "build", info)
    return tmp_path / "build"


GUIDE = ("guide/01-intro.md", "title: Intro\nclassification: Public\n")
REFERENCE = ("repositories/app/docs/rules.md",
             "title: Rules\nclassification: Public\nsource: KSOURCE-1\nrepository: acme/app\npath: docs/rules.md\n")  # fmt: skip
LISTING = KnowledgeBase(KB.id, KB.classification, KB.default_classification, [("KSOURCE-1", PUBLIC)])


def test_a_public_build_of_listed_sources_and_own_pages_is_publishable(tmp_path: Path):
    assert publish_check(_build(tmp_path, GUIDE, REFERENCE), LISTING) == 2


@pytest.mark.parametrize(
    ("doc", "why"),
    [
        (("repositories/secrets/a.md", "title: A\nclassification: Public\nsource: KSOURCE-2\n"), "does not name"),
        (("repositories/app/b.md", "title: B\nclassification: Public\n"), "cites no source"),
        (("criteria/app/req/REQ-1.md", "title: R\nclassification: Public\nsource: KSOURCE-9\n"), "does not name"),
    ],
)
def test_a_document_from_an_unlisted_source_refuses_the_publication(tmp_path: Path, doc, why):
    with pytest.raises(BuildError, match=why):
        publish_check(_build(tmp_path, GUIDE, doc), LISTING)


def test_a_build_above_public_is_refused(tmp_path: Path):
    internal = ("guide/02-internal.md", "title: Internal\nclassification: Internal\n")
    with pytest.raises(BuildError, match="not Public"):
        publish_check(_build(tmp_path, GUIDE, internal, ceiling=Classification.INTERNAL), LISTING)


def test_the_site_holds_the_guide_as_written_and_a_cited_page_per_document(tmp_path: Path):
    site = make_site(_build(tmp_path, GUIDE, REFERENCE), tmp_path / "site", title="Docs", intro="Hello.")
    assert (site.guide, site.reference) == (1, 1)
    out = tmp_path / "site"
    assert "title: Intro" in (out / "guide" / "01-intro.md").read_text()
    page = (out / "reference" / "app" / "docs" / "rules.md").read_text()
    assert "[`acme/app`: `docs/rules.md`](https://github.com/acme/app/blob/HEAD/docs/rules.md)" in page
    assert "- [Rules](app/docs/rules.md)" in (out / "reference" / "app.md").read_text()
    assert "- [app](app.md): 1 pages" in (out / "reference" / "index.md").read_text()
    home = (out / "index.md").read_text()
    assert "Hello." in home and "1. [Intro](guide/01-intro.md)" in home
