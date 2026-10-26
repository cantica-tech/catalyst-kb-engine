"""Reading sources (`eng-SOURCE-000001`, `eng-SOURCE-000002`), against a fake catalyst and a fake GitHub."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.models import Classification, Source, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase, read_knowledge_base
from catalyst_kb_engine.sources.criterion import read_criterion, render
from catalyst_kb_engine.sources.stage import stage, summary
from catalyst_kb_engine.sources.visibility import Projects, SourceError, github_repository, resolve

REQ = {
    "id": "REQ-000001-Ab3xR9pQ",
    "type": "REQ",
    "title": "Invoices are approved twice",
    "file": "requirements/REQ-000001-invoices.md",
    "Name": "`invoices`",
    "Status": "Active",
    "Targets": "`app-PAY-000001-Ab3xR9pQ`",
    "Assignee": "*(none yet)*",
    "links": {"Targets": ["app-PAY-000001-Ab3xR9pQ"], "Steps": []},
    "sections": [{"heading": "Summary", "text": "Two people approve an invoice."}],
    "next": [],
    "linked_from": [{"id": "STEP-000001-Ab3xR9pQ", "field": "Parent"}],
    "journal": [
        {"timestamp": "2026-10-20T10:00:00Z", "actor": "ada", "command": "/create-req", "action": "create",
         "intent": ["the approval rule needs a requirement"]},
        {"timestamp": "2026-10-22T09:00:00Z", "actor": "ada", "command": "/status", "action": "status-change",
         "intent": ["work starts"]},
    ],
}  # fmt: skip
RULE = {
    "id": "app-PAY-000001-Ab3xR9pQ",
    "type": "rule",
    "title": "An invoice is approved by two people",
    "status": "✅ working — `approve()`",
    "text": "### `app-PAY-000001-Ab3xR9pQ` An invoice is approved by two people\n\n- **Strength**: must\n\nTwo.",
    "file": "rules/app-rules.md",
    "retired": False,
    "links": {},
    "linked_from": [{"id": "REQ-000001-Ab3xR9pQ", "field": "Targets"}],
    "journal": [],
}
META = {"id": "rr-META-000001-Ab3xR9pQ", "type": "rule", "file": "rules/Rules-of-Rules.md"}
ROADMAP_ROW = {"id": "RM-000001-Ab3xR9pQ", "type": "RM"}


class FakeCriterion(CatalystCLI):
    """catalyst's CLI in a project, as far as the reader uses it: `where`, `list all`, `view`."""

    def __init__(
        self, project: Path, name: str = "app", views: tuple[dict, ...] = (REQ, RULE), journal: tuple[dict, ...] = ()
    ) -> None:
        super().__init__(project=project, command=["catalyst"])
        self.name = name
        self.views = {v["id"]: v for v in views}
        self.journal = list(journal)
        self.calls: list[list[str]] = []

    def run(self, *args: str) -> str:
        self.calls.append(list(args))
        if args[0] == "where":
            return json.dumps({"name": self.name})
        if args[:2] == ("list", "all"):
            listed = [{"id": i, "type": v["type"], "file": v["file"]} for i, v in self.views.items()]
            return json.dumps([*listed, META, ROADMAP_ROW])
        if args[0] == "view":
            return json.dumps(self.views[args[1]])
        if args[:2] == ("journal", "show"):
            return json.dumps(self.journal)
        raise AssertionError(args)

    @property
    def viewed(self) -> list[str]:
        return sorted(c[1] for c in self.calls if c[0] == "view")


def _hosts(**known: Visibility):
    return known.get


def test_github_repository_reads_https_and_ssh_urls():
    assert github_repository("https://github.com/acme/app") == "acme/app"
    assert github_repository("git@github.com:acme/app-criterion.git") == "acme/app-criterion"
    assert github_repository("https://wiki.example.com/space") is None


def test_a_criterion_source_has_a_criterion_location():
    with pytest.raises(ValueError):
        Source(title="x", location="https://github.com/acme/app", kind=SourceKind.CRITERION)
    assert Source(title="x", location="criterion:app").project == "app"


@pytest.fixture
def projects(tmp_path: Path) -> Projects:
    app = tmp_path / "app"
    app.mkdir()
    (app / "catalyst.toml").write_text(
        'project_name = "app"\ncatalyst_repo_url = "git@github.com:acme/app-criterion.git"\n'
    )
    return Projects(tmp_path)


def test_visibility_agrees_with_the_host(projects: Projects):
    public = Source(title="app", location="https://github.com/acme/app", visibility=Visibility.PUBLIC)
    assert resolve("KSOURCE-1", public, projects, _hosts(**{"acme/app": Visibility.PUBLIC})) is Visibility.PUBLIC
    criterion = Source(title="c", location="criterion:app", visibility=Visibility.PRIVATE)
    hosts = _hosts(**{"acme/app-criterion": Visibility.PRIVATE})
    assert resolve("KSOURCE-2", criterion, projects, hosts) is Visibility.PRIVATE


def test_a_disagreement_or_an_unconfirmed_public_source_is_refused(projects: Projects):
    public = Source(title="app", location="https://github.com/acme/app", visibility=Visibility.PUBLIC)
    with pytest.raises(SourceError, match="recorded Public, but acme/app is Private"):
        resolve("KSOURCE-1", public, projects, _hosts(**{"acme/app": Visibility.PRIVATE}))
    with pytest.raises(SourceError, match="cannot be confirmed"):
        resolve("KSOURCE-1", public, projects, _hosts())


def test_an_unknown_visibility_is_private(projects: Projects):
    site = Source(title="wiki", location="https://wiki.example.com")
    assert resolve("KSOURCE-3", site, projects, _hosts()) is Visibility.PRIVATE


def test_an_entity_becomes_a_document_citing_it_with_its_own_history():
    doc = render(REQ, "app")
    assert (doc.id, doc.type, doc.status, doc.updated, doc.path) == (
        "REQ-000001-Ab3xR9pQ", "REQ", "Active", "2026-10-22", "req/REQ-000001-Ab3xR9pQ.md",
    )  # fmt: skip
    assert doc.body.startswith("# `REQ-000001-Ab3xR9pQ` Invoices are approved twice")
    assert "| Targets | `app-PAY-000001-Ab3xR9pQ` |" in doc.body
    assert "Assignee" not in doc.body  # unset fields are left out
    assert "## Summary\n\nTwo people approve an invoice." in doc.body
    assert "- Cited by: `STEP-000001-Ab3xR9pQ` (Parent)" in doc.body
    assert "- 2026-10-20T10:00:00Z ada, `/create-req` create: the approval rule needs a requirement" in doc.body


def test_a_rule_becomes_a_document_of_its_own_text():
    doc = render(RULE, "app")
    assert doc.status == "✅ working"
    assert doc.body.count("app-PAY-000001-Ab3xR9pQ") == 1 + 0  # its heading only, not repeated from the text
    assert "Two." in doc.body and "- Cited by: `REQ-000001-Ab3xR9pQ` (Targets)" in doc.body


def test_the_reader_checks_the_project_leaves_out_meta_rules_and_counts_unviewable_rows(tmp_path: Path):
    read = read_criterion(FakeCriterion(tmp_path), "app")
    assert [d.id for d in read.documents] == ["REQ-000001-Ab3xR9pQ", "app-PAY-000001-Ab3xR9pQ"]
    assert read.unviewable == ["RM-000001-Ab3xR9pQ"]
    with pytest.raises(SourceError, match="not 'other'"):
        read_criterion(FakeCriterion(tmp_path), "other")


def _repository(path: Path) -> Path:
    path.mkdir()
    (path / "README.md").write_text("# The app\n\nWhat it is.\n")
    (path / "docs").mkdir()
    (path / "docs" / "secret.md").write_text("---\nclassification: Confidential\n---\n\n# Keys\n\nKept close.\n")
    (path / "untracked.md").write_text("# Not committed\n")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "README.md", "docs"], check=True)
    return path


def _kb(*sources: tuple[str, Source]) -> KnowledgeBase:
    return KnowledgeBase("KB-000001-Ab3xR9pQ", Classification.PUBLIC, Classification.INTERNAL, list(sources))


PUBLIC_REPO = Source(
    title="app", location="https://github.com/acme/app", kind=SourceKind.REPOSITORY,
    classification=Classification.PUBLIC, visibility=Visibility.PUBLIC,
)  # fmt: skip
CRITERION = Source(title="app's criterion", location="criterion:app", visibility=Visibility.PRIVATE)
HOSTS = _hosts(**{"acme/app": Visibility.PUBLIC, "acme/app-criterion": Visibility.PRIVATE})


def _front(path: Path) -> dict:
    text = path.read_text()
    return yaml.safe_load(text[4 : text.index("\n---", 4)])


def test_staging_floors_a_private_source_and_keeps_a_documents_own_higher_mark(tmp_path: Path, projects: Projects):
    _repository(tmp_path / "app-repo")
    projects.overrides["app"] = tmp_path / "app"
    projects.overrides["app-repo"] = tmp_path / "app-repo"
    repo = PUBLIC_REPO.model_copy(update={"location": "https://github.com/acme/app-repo"})
    hosts = _hosts(**{"acme/app-repo": Visibility.PUBLIC, "acme/app-criterion": Visibility.PRIVATE})
    out = tmp_path / "out"
    staged = stage(_kb(("KSOURCE-1", repo), ("KSOURCE-2", CRITERION)), out, projects,
                   catalyst=FakeCriterion, host=hosts)  # fmt: skip
    docs = out / "docs"
    assert _front(docs / "repositories/app-repo/readme.md")["classification"] == "Public"
    assert _front(docs / "repositories/app-repo/docs/secret.md")["classification"] == "Confidential"
    assert not (docs / "repositories/app-repo/untracked.md").exists()  # only what is committed
    req = _front(docs / "criteria/app/req/REQ-000001-Ab3xR9pQ.md")
    assert req["classification"] == "Internal"  # the private floor, over the knowledge base's Public
    assert (req["entity"], req["criterion"], req["source"], req["status"]) == (
        "REQ-000001-Ab3xR9pQ", "app", "KSOURCE-2", "Active",
    )  # fmt: skip
    report = summary(staged)
    assert report["documents"] == 4
    assert report["sources"][1] == {
        "source": "KSOURCE-2", "title": "app's criterion", "visibility": "Private", "documents": 2,
        "classification": {"Internal": 2}, "unviewable": 1,
    }  # fmt: skip


def test_a_public_read_never_opens_a_private_source(tmp_path: Path, projects: Projects):
    opened: list[Path] = []

    def catalyst(project: Path) -> CatalystCLI:
        opened.append(project)
        return FakeCriterion(project)

    staged = stage(_kb(("KSOURCE-2", CRITERION)), tmp_path / "out", projects, public_only=True,
                   catalyst=catalyst, host=HOSTS)  # fmt: skip
    assert opened == [] and staged.documents == 0
    assert staged.sources[0].skipped == "private: a public read never opens it"


def test_one_disagreement_stops_the_whole_read(tmp_path: Path, projects: Projects):
    lying = CRITERION.model_copy(update={"visibility": Visibility.PUBLIC})
    with pytest.raises(SourceError, match="KSOURCE-2"):
        stage(_kb(("KSOURCE-1", PUBLIC_REPO), ("KSOURCE-2", lying)), tmp_path / "out", projects,
              catalyst=FakeCriterion, host=HOSTS)  # fmt: skip
    assert not (tmp_path / "out").exists()


class FakeRecords(CatalystCLI):
    def __init__(self, records: dict[str, dict]) -> None:
        super().__init__(project=Path(), command=["catalyst"])
        self.records = records

    def run(self, *args: str) -> str:
        assert args[0] == "view"
        return json.dumps(self.records[args[1]])


def test_a_knowledge_base_is_read_with_its_live_sources():
    records = {
        "KB-1": {"Classification": "Public", "Default classification": "Internal", "Sources": "`KSOURCE-000001-Ab3xR9pQ`, `KSOURCE-000002-Ab3xR9pQ`"},
        "KSOURCE-000001-Ab3xR9pQ": {"title": "app's criterion", "Location": "criterion:app", "Kind": "Criterion",
                                    "Visibility": "Private", "Classification": "Unmarked", "Status": "Active"},
        "KSOURCE-000002-Ab3xR9pQ": {"title": "gone", "Location": "https://github.com/acme/gone", "Status": "Retired"},
    }  # fmt: skip
    kb = read_knowledge_base(FakeRecords(records), "KB-1")
    assert (kb.classification, kb.default_classification) == (Classification.PUBLIC, Classification.INTERNAL)
    assert [(sid, s.kind, s.visibility, s.classification) for sid, s in kb.sources] == [
        ("KSOURCE-000001-Ab3xR9pQ", SourceKind.CRITERION, Visibility.PRIVATE, None)
    ]


BUG = {
    "id": "BUG-000001-Ab3xR9pQ", "type": "BUG", "title": "Totals round wrongly", "file": "bugs/BUG-000001-totals.md",
    "Status": "Open", "links": {}, "sections": [], "linked_from": [], "journal": [],
}  # fmt: skip


def test_an_incremental_read_re_views_only_what_moved_and_what_it_cites(tmp_path: Path, projects: Projects):
    hosts, kb = HOSTS, _kb(("KSOURCE-2", CRITERION))
    first = FakeCriterion(tmp_path, views=(REQ, RULE, BUG))
    stage(kb, tmp_path / "1", projects, catalyst=lambda _: first, host=hosts)
    assert first.viewed == sorted([REQ["id"], RULE["id"], BUG["id"]])

    added = {**BUG, "id": "BUG-000002-Ab3xR9pQ", "file": "bugs/BUG-000002-new.md", "title": "New"}
    moved = {
        "artifact": REQ["id"],
        "targets": [],
        "files": [{"path": ".criterion/requirements/REQ-000001-invoices.md"}],
    }
    second = FakeCriterion(tmp_path, views=(REQ, RULE, BUG, added), journal=(moved,))
    staged = stage(kb, tmp_path / "2", projects, catalyst=lambda _: second, host=hosts, previous=tmp_path / "1")
    # the moved requirement, the rule it cites (its back-references changed) and the new bug; the old bug carried
    assert second.viewed == sorted([REQ["id"], RULE["id"], added["id"]])
    assert [
        "journal",
        "show",
        "--since",
        json.loads((tmp_path / "1" / "read.json").read_text())["read_at"],
        "--json",
    ] in second.calls
    assert staged.sources[0].carried == 1 and staged.documents == 4
    carried = tmp_path / "2" / "docs/criteria/app/bug/BUG-000001-Ab3xR9pQ.md"
    assert carried.read_text() == (tmp_path / "1" / "docs/criteria/app/bug/BUG-000001-Ab3xR9pQ.md").read_text()

    third = FakeCriterion(tmp_path, views=(REQ, RULE))  # the bugs are gone from the criterion
    stage(kb, tmp_path / "3", projects, catalyst=lambda _: third, host=hosts, previous=tmp_path / "2")
    assert not list((tmp_path / "3" / "docs/criteria/app").glob("bug/*.md"))


def test_a_source_whose_visibility_changed_is_read_in_full(tmp_path: Path, projects: Projects):
    first = FakeCriterion(tmp_path, views=(REQ, RULE, BUG))
    stage(_kb(("KSOURCE-2", CRITERION)), tmp_path / "1", projects, catalyst=lambda _: first, host=HOSTS)
    public = CRITERION.model_copy(update={"visibility": Visibility.PUBLIC})
    second = FakeCriterion(tmp_path, views=(REQ, RULE, BUG))
    hosts = _hosts(**{"acme/app-criterion": Visibility.PUBLIC})
    stage(_kb(("KSOURCE-2", public)), tmp_path / "2", projects, catalyst=lambda _: second, host=hosts,
          previous=tmp_path / "1")  # fmt: skip
    assert second.viewed == first.viewed and not any(c[0] == "journal" for c in second.calls)


def test_a_previous_read_of_another_knowledge_base_is_refused(tmp_path: Path, projects: Projects):
    stage(_kb(), tmp_path / "1", projects, host=HOSTS)
    other = KnowledgeBase("KB-000009-Ab3xR9pQ", Classification.PUBLIC, Classification.INTERNAL, [])
    with pytest.raises(SourceError, match="not KB-000009"):
        stage(other, tmp_path / "2", projects, host=HOSTS, previous=tmp_path / "1")
