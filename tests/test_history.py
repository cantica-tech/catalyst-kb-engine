"""A repository's history, on request (`eng-SOURCE-000005`), offline against a repository the test makes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from catalyst_kb_engine.models import Classification, Source, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.sources.stage import stage
from catalyst_kb_engine.sources.visibility import Projects, SourceError

APP = Source(title="app", location="https://github.com/acme/app", kind=SourceKind.REPOSITORY,
             visibility=Visibility.PUBLIC, classification=Classification.PUBLIC)  # fmt: skip
KB = KnowledgeBase("KB-000001-Ab3xR9pQ", Classification.PUBLIC, Classification.INTERNAL, [("KSOURCE-1", APP)])
HOSTS = {"acme/app": Visibility.PUBLIC}.get


def _commit(repo: Path, author: str, message: str, **files: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    env = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author.split(maxsplit=1)[0].lower()}@example.com",
           "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "c@example.com"}  # fmt: skip
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True, env=env)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = tmp_path / "src" / "app"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _commit(repo, "Ada Lovelace", "Add the guide", **{"guide.md": "# Guide\n\nFirst.\n"})
    _commit(repo, "Grace Hopper", "Explain the reset links", **{"guide.md": "# Guide\n\nSecond.\n"})
    _commit(repo, "Grace Hopper", "Fix the reset code", **{"src/reset.py": "EXPIRY = 30\n"})
    return repo


def _read(tmp_path: Path, app: Path, history: int):
    return stage(KB, tmp_path / "out", Projects(app.parent), host=HOSTS, history=history)


def test_each_document_gains_the_commits_that_touched_its_file(tmp_path: Path, app: Path):
    _read(tmp_path, app, history=10)
    guide = (tmp_path / "out" / "docs" / "repositories" / "app" / "guide.md").read_text()
    section = guide.split("## History", 1)[1]
    assert "Grace Hopper: Explain the reset links" in section and "Ada Lovelace: Add the guide" in section
    assert "Fix the reset code" not in section  # another file's commit
    assert section.index("Explain") < section.index("Add the guide")  # newest first


def test_the_repository_log_covers_every_file_and_names_no_address(tmp_path: Path, app: Path):
    staged = _read(tmp_path, app, history=10)
    log = (tmp_path / "out" / "docs" / "repositories" / "app" / "git-history.md").read_text()
    assert "Fix the reset code (`src/reset.py`)" in log and "Explain the reset links (`guide.md`)" in log
    assert "url: https://github.com/acme/app/commits/HEAD" in log and "classification: Public" in log
    assert "@" not in log.split("---", 2)[2] and "example.com" not in log
    assert staged.documents == 2  # the guide and the repository's log


def test_a_limit_keeps_the_newest_commits(tmp_path: Path, app: Path):
    _read(tmp_path, app, history=1)
    log = (tmp_path / "out" / "docs" / "repositories" / "app" / "git-history.md").read_text()
    assert "Fix the reset code" in log and "Add the guide" not in log


def test_without_the_option_no_history_is_read(tmp_path: Path, app: Path):
    staged = _read(tmp_path, app, history=0)
    guide = (tmp_path / "out" / "docs" / "repositories" / "app" / "guide.md").read_text()
    assert "## History" not in guide and staged.documents == 1
    assert not (tmp_path / "out" / "docs" / "repositories" / "app" / "git-history.md").exists()


def test_a_shallow_clone_is_refused(tmp_path: Path, app: Path):
    shallow = tmp_path / "shallow" / "app"
    shallow.parent.mkdir()
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{app}", str(shallow)], check=True)
    with pytest.raises(SourceError, match="shallow clone"):
        stage(KB, tmp_path / "out", Projects(shallow.parent), host=HOSTS, history=5)
    assert not (tmp_path / "out" / "docs").exists()
