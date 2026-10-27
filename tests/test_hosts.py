"""Azure DevOps beside GitHub (`eng-SOURCE-000002`, REQ-000013): a repository URL's host, its visibility there, and a
staged Azure DevOps repository cited on Azure DevOps; offline, the host's answer stubbed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from catalyst_kb_engine import cli
from catalyst_kb_engine.models import Classification, Source, SourceKind, Visibility
from catalyst_kb_engine.record import KnowledgeBase
from catalyst_kb_engine.sources import visibility
from catalyst_kb_engine.sources.stage import stage
from catalyst_kb_engine.sources.visibility import (
    AZURE_DEVOPS,
    GIT,
    GITHUB,
    Projects,
    Repository,
    anonymous_visibility,
    azure_visibility,
    repository,
    repository_of,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://dev.azure.com/acme/Payments/_git/app",
        "https://ada@dev.azure.com/acme/Payments/_git/app",
        "https://dev.azure.com/acme/Payments/_git/app.git",
        "https://acme.visualstudio.com/Payments/_git/app",
        "https://acme.visualstudio.com/Payments/_git/app.git",
        "https://acme.visualstudio.com/DefaultCollection/Payments/_git/app",
        "git@ssh.dev.azure.com:v3/acme/Payments/app",
        "ssh://git@ssh.dev.azure.com/v3/acme/Payments/app",
        "ssh://git@ssh.dev.azure.com:22/v3/acme/Payments/app",
        "git@vs-ssh.visualstudio.com:v3/acme/Payments/app",
        "acme@vs-ssh.visualstudio.com:v3/acme/Payments/app",
    ],
)
def test_azure_devops_urls_name_the_same_repository(url: str):
    assert repository(url) == Repository(AZURE_DEVOPS, "acme/Payments/app")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/app",
        "https://github.com/acme/app.git",
        "https://ada@github.com/acme/app.git",
        "http://github.com/acme/app",
        "https://www.github.com/acme/app/",
        "https://github.com/acme/app/tree/main",
        "git@github.com:acme/app.git",
        "ssh://git@github.com/acme/app.git",
        "ssh://git@github.com:22/acme/app.git",
    ],
)
def test_github_urls_name_the_same_repository(url: str):
    assert repository(url) == Repository(GITHUB, "acme/app")


@pytest.mark.parametrize(
    ("url", "path", "clone"),
    [
        ("https://gitlab.com/group/sub/app.git", "gitlab.com/group/sub/app", "https://gitlab.com/group/sub/app.git"),
        ("git@gitlab.com:group/app.git", "gitlab.com/group/app", "https://gitlab.com/group/app.git"),
        ("ssh://git@bitbucket.org:7999/team/app.git", "bitbucket.org/team/app", "https://bitbucket.org/team/app.git"),
        ("https://git.example.org/app", "git.example.org/app", "https://git.example.org/app"),
    ],
)
def test_any_other_host_is_a_git_repository(url: str, path: str, clone: str):
    found = repository(url)
    assert found is not None and (found.host, found.path, found.clone_url) == (GIT, path, clone)
    assert found.name == path.rsplit("/", 1)[1] and repository_of(path).host == GIT


def test_what_is_no_repository():
    for url in ("https://wiki.example.com", "/local/path", "file:///x/y", "not a url"):
        assert repository(url) is None
    assert repository_of("acme/Payments/app").host == AZURE_DEVOPS and repository_of("acme/app").host == GITHUB


def _bare(tmp_path: Path) -> Path:
    work, bare = tmp_path / "work", tmp_path / "app.git"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "-c", "user.name=Ada", "-c", "user.email=a@example.com",
                    "commit", "-q", "--allow-empty", "-m", "start"], check=True)  # fmt: skip
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


def test_a_repository_git_reads_anonymously_is_public_and_a_refusal_unknown(tmp_path: Path):
    bare = _bare(tmp_path)
    assert anonymous_visibility(str(tmp_path / "missing.git"), str(bare)) is Visibility.PUBLIC
    assert anonymous_visibility(str(tmp_path / "missing.git")) is None


def test_the_anonymous_read_ignores_this_machines_git_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bare = _bare(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(f'[url "{bare}"]\n\tinsteadOf = https://git.example.invalid/app.git\n')
    monkeypatch.setenv("HOME", str(home))
    reached = subprocess.run(["git", "ls-remote", "https://git.example.invalid/app.git", "HEAD"],
                             capture_output=True, check=False)  # fmt: skip
    assert reached.returncode == 0  # with this machine's configuration, the address reaches the repository
    assert anonymous_visibility("https://git.example.invalid/app.git") is None  # without it, nothing vouches


def test_links_follow_the_host():
    azure, github = Repository(AZURE_DEVOPS, "acme/Payments/app"), Repository(GITHUB, "acme/app")
    assert azure.clone_url == "https://dev.azure.com/acme/Payments/_git/app"
    assert azure.file_url("docs/a b.md") == "https://dev.azure.com/acme/Payments/_git/app?path=/docs/a%20b.md"
    assert azure.commits_url == "https://dev.azure.com/acme/Payments/_git/app/commits"
    assert github.file_url("guide.md") == "https://github.com/acme/app/blob/HEAD/guide.md"
    assert github.commits_url == "https://github.com/acme/app/commits/HEAD"


def test_azure_visibility_is_the_projects_and_unknown_when_azure_does_not_say():
    asked: list[str] = []

    def answer(project_visibility: object):
        def get(url: str):
            asked.append(url)
            return project_visibility

        return get

    assert azure_visibility("acme/Payments/app", answer({"project": {"visibility": "public"}})) is Visibility.PUBLIC
    assert azure_visibility("acme/Payments/app", answer({"project": {"visibility": "private"}})) is Visibility.PRIVATE
    assert azure_visibility("acme/Payments/app", answer(None)) is None  # a sign-in page, or a missing repository
    assert azure_visibility("acme/Payments/app", answer({"message": "not found"})) is None
    assert asked[0] == "https://dev.azure.com/acme/Payments/_apis/git/repositories/app?api-version=7.1"


def test_a_staged_azure_devops_repository_is_read_and_cited_there(tmp_path: Path):
    checkout = tmp_path / "repos" / "app"
    checkout.mkdir(parents=True)
    (checkout / "guide.md").write_text("# Guide\n\nText.\n")
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Ada", "-c", "user.email=a@example.com",
                    "commit", "-q", "-m", "Add the guide"], check=True)  # fmt: skip
    source = Source(title="app", location="https://dev.azure.com/acme/Payments/_git/app", kind=SourceKind.REPOSITORY,
                    visibility=Visibility.PUBLIC, classification=Classification.PUBLIC)  # fmt: skip
    kb = KnowledgeBase("KB-000001-Ab3xR9pQ", Classification.PUBLIC, Classification.INTERNAL, [("KSOURCE-1", source)])
    stage(kb, tmp_path / "out", Projects(tmp_path / "repos"), host={"acme/Payments/app": Visibility.PUBLIC}.get,
          history=5, public_only=True)  # fmt: skip
    staged = tmp_path / "out" / "docs" / "repositories" / "app"
    assert "repository: acme/Payments/app" in (staged / "guide.md").read_text()
    assert "url: https://dev.azure.com/acme/Payments/_git/app/commits" in (staged / "git-history.md").read_text()


def test_the_repository_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(visibility, "_azure_get", lambda url: {"project": {"visibility": "public"}})
    assert cli.main(["repository", "https://dev.azure.com/acme/Payments/_git/app"]) == 0
    told = json.loads(capsys.readouterr().out)
    assert told == {"host": "azure-devops", "repository": "acme/Payments/app", "name": "app",
                    "clone_url": "https://dev.azure.com/acme/Payments/_git/app",
                    "web_url": "https://dev.azure.com/acme/Payments/_git/app", "visibility": "Public"}  # fmt: skip
    assert cli.main(["repository", "not a url"]) == 1
