"""A source's visibility (`eng-SOURCE-000002`): resolved from its `KSOURCE-` record and its host before anything is
read; when the two disagree, nothing is."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from catalyst_kb_engine.models import Source, Visibility

_GITHUB = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?$"
)
_AZURE = (
    re.compile(r"^https://(?:[^@/]+@)?dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/?#]+?)(?:\.git)?/?$"),
    re.compile(r"^https://(?:[^@/]+@)?([\w-]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/?#]+?)/?$"),
    re.compile(r"^(?:ssh://)?git@ssh\.dev\.azure\.com[:/]v3/([^/]+)/([^/]+)/([^/]+?)/?$"),
)

GITHUB, AZURE_DEVOPS = "github", "azure-devops"

Host = Callable[[str], Visibility | None]
"""A repository's path (GitHub `owner/name`, Azure DevOps `org/project/name`) to its visibility, or None when it
cannot be told."""


class SourceError(Exception):
    """A source cannot be read as recorded; nothing was read from it."""


@dataclass(frozen=True)
class Repository:
    """A hosted git repository: GitHub's `owner/name`, or Azure DevOps' `org/project/name` (URL-encoded as given)."""

    host: str
    path: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[1]

    @property
    def web_url(self) -> str:
        if self.host == AZURE_DEVOPS:
            org, project, name = self.path.split("/")
            return f"https://dev.azure.com/{org}/{project}/_git/{name}"
        return f"https://github.com/{self.path}"

    @property
    def clone_url(self) -> str:
        return self.web_url if self.host == AZURE_DEVOPS else f"{self.web_url}.git"

    def file_url(self, path: str) -> str:
        if self.host == AZURE_DEVOPS:
            return f"{self.web_url}?path=/{urllib.parse.quote(path)}"
        return f"{self.web_url}/blob/HEAD/{path}"

    @property
    def commits_url(self) -> str:
        return f"{self.web_url}/commits" if self.host == AZURE_DEVOPS else f"{self.web_url}/commits/HEAD"


def repository(url: str) -> Repository | None:
    """The GitHub or Azure DevOps repository a URL (https or ssh) names, else None."""
    url = url.strip()
    if match := _GITHUB.match(url):
        return Repository(GITHUB, match.group(1))
    for pattern in _AZURE:
        if match := pattern.match(url):
            return Repository(AZURE_DEVOPS, "/".join(match.groups()))
    return None


def github_repository(url: str) -> str | None:
    """`owner/name` of a GitHub URL (https or ssh), else None."""
    match = _GITHUB.match(url.strip())
    return match.group(1) if match else None


def repository_of(path: str) -> Repository:
    """A repository from its path: three segments are Azure DevOps', two GitHub's."""
    return Repository(AZURE_DEVOPS if path.count("/") == 2 else GITHUB, path)


def github_visibility(repository: str) -> Visibility | None:
    """`gh repo view`: GitHub's `PUBLIC` is public, anything else (private, internal) private; None if unknown."""
    done = subprocess.run(
        ["gh", "repo", "view", repository, "--json", "visibility", "-q", ".visibility"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return Visibility.PUBLIC if done.stdout.strip() == "PUBLIC" else Visibility.PRIVATE


def _azure_get(url: str) -> object | None:
    """Azure DevOps' answer to a REST GET, with `AZURE_DEVOPS_EXT_PAT` when set; None unless it answers JSON (a
    private project, asked anonymously, redirects to its sign-in page)."""
    if not url.startswith("https://dev.azure.com/"):
        raise ValueError(f"not an Azure DevOps API URL: {url}")
    headers = {"Accept": "application/json"}
    if token := os.environ.get("AZURE_DEVOPS_EXT_PAT"):
        headers["Authorization"] = "Basic " + base64.b64encode(f":{token}".encode()).decode()
    try:
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https://dev.azure.com/ only, above
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310 - the same
            if "json" not in answer.headers.get("Content-Type", ""):
                return None
            return json.load(answer)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def azure_visibility(path: str, get: Callable[[str], object | None] | None = None) -> Visibility | None:
    """An Azure DevOps repository's visibility, which is its project's: `public` is public, anything else private;
    None when Azure DevOps does not say (a private project without a token, a missing repository)."""
    org, project, name = path.split("/")
    answer = (get or _azure_get)(f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{name}?api-version=7.1")
    project_info = answer.get("project") if isinstance(answer, dict) else None
    visibility = project_info.get("visibility") if isinstance(project_info, dict) else None
    if not isinstance(visibility, str):
        return None
    return Visibility.PUBLIC if visibility.lower() == "public" else Visibility.PRIVATE


def hosted_visibility(path: str) -> Visibility | None:
    """A repository's visibility on its own host, GitHub or Azure DevOps."""
    found = repository_of(path)
    return azure_visibility(found.path) if found.host == AZURE_DEVOPS else github_visibility(found.path)


@dataclass
class Projects:
    """Where the sources' checkouts are: `<directory>/<name>`, unless an override names another directory."""

    directory: Path | None = None
    overrides: dict[str, Path] = field(default_factory=dict)

    def find(self, name: str, *, catalyst: bool = False) -> Path:
        path = self.overrides.get(name) or (self.directory / name if self.directory else None)
        if path is None or not path.is_dir():
            raise SourceError(f"no checkout of {name!r}: give --projects-dir or --project {name}=<dir>")
        if catalyst and not (path / "catalyst.toml").is_file():
            raise SourceError(f"{path} has no catalyst.toml, so it is not the catalyst project {name!r}")
        return path


def criterion_repository(project: Path) -> str | None:
    """A catalyst project's criterion repository (`catalyst.toml` `catalyst_repo_url`): its path on its host."""
    toml = tomllib.loads((project / "catalyst.toml").read_text(encoding="utf-8"))
    found = repository(str(toml.get("catalyst_repo_url") or ""))
    return found.path if found else None


def host_repository(source: Source, projects: Projects) -> str | None:
    """The repository whose visibility is the source's: a criterion's own repository, else its location."""
    if source.is_criterion:
        return criterion_repository(projects.find(source.project or "", catalyst=True))
    found = repository(source.location)
    return found.path if found else None


def resolve(source_id: str, source: Source, projects: Projects, host: Host = hosted_visibility) -> Visibility:
    """The source's visibility: its record and its host must agree; a recorded `Public` must be confirmed; a source
    whose visibility is neither recorded nor known is `Private`."""
    repository = host_repository(source, projects)
    hosted = host(repository) if repository else None
    recorded = source.visibility
    if recorded and hosted and recorded is not hosted:
        raise SourceError(
            f"{source_id}: recorded {recorded.value}, but {repository} is {hosted.value}; nothing is read until they agree"
        )
    if recorded is Visibility.PUBLIC and hosted is None:
        what = repository or source.location
        raise SourceError(f"{source_id}: recorded Public, but {what}'s visibility cannot be confirmed; nothing is read")
    return recorded or hosted or Visibility.PRIVATE
