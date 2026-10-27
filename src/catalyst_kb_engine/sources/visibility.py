"""A source's visibility (`eng-SOURCE-000002`): resolved from its `KSOURCE-` record and its host before anything is
read; when the two disagree, nothing is."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from catalyst_kb_engine.models import Source, Visibility

_SCP = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!//)(.+)$")
"""A git URL in scp form: `[user@]host:path`."""
_SCHEMES = {"https", "http", "ssh", "git", "git+ssh", "ssh+git"}
_GITHUB_HOSTS = {"github.com", "www.github.com", "ssh.github.com"}

GITHUB, AZURE_DEVOPS, GIT = "github", "azure-devops", "git"

Host = Callable[[str], Visibility | None]
"""A repository's path (GitHub `owner/name`, Azure DevOps `org/project/name`, any other host `<host>/<path>`) to its
visibility, or None when it cannot be told."""


class SourceError(Exception):
    """A source cannot be read as recorded; nothing was read from it."""


@dataclass(frozen=True)
class Repository:
    """A hosted git repository: GitHub's `owner/name`, Azure DevOps' `org/project/name`, or any other host's
    `<host>/<path>` (URL-encoded as given). `suffix` is the `.git` its URL ended with, for cloning; not its identity."""

    host: str
    path: str
    suffix: str = field(default="", compare=False)

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[1]

    @property
    def web_url(self) -> str:
        if self.host == AZURE_DEVOPS:
            org, project, name = self.path.split("/")
            return f"https://dev.azure.com/{org}/{project}/_git/{name}"
        if self.host == GIT:
            return f"https://{self.path}"
        return f"https://github.com/{self.path}"

    @property
    def clone_url(self) -> str:
        if self.host == AZURE_DEVOPS:
            return self.web_url
        return self.web_url + (self.suffix if self.host == GIT else ".git")

    def file_url(self, path: str) -> str:
        if self.host == AZURE_DEVOPS:
            return f"{self.web_url}?path=/{urllib.parse.quote(path)}"
        if self.host == GIT:
            return self.web_url  # no file address any host shares
        return f"{self.web_url}/blob/HEAD/{path}"

    @property
    def commits_url(self) -> str:
        if self.host == AZURE_DEVOPS:
            return f"{self.web_url}/commits"
        return self.web_url if self.host == GIT else f"{self.web_url}/commits/HEAD"


def _split(url: str) -> tuple[str, str, str] | None:
    """A git URL's host, path and `.git` suffix: `https://`, `http://`, `ssh://` (a user, a port) or `[user@]host:path`."""
    url = url.strip()
    if "://" in url:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() not in _SCHEMES or not parts.hostname:
            return None
        host, path = parts.hostname.lower(), parts.path
    elif match := _SCP.match(url):
        host, path = match.group(1).lower(), match.group(2)
    else:
        return None
    path = path.strip("/")
    suffix = ".git" if path.endswith(".git") else ""
    path = path.removesuffix(".git").strip("/")
    return (host, path, suffix) if path else None


def _azure(host: str, parts: list[str]) -> str | None:
    """`org/project/name` of an Azure DevOps address, else None."""
    if host in ("ssh.dev.azure.com", "vs-ssh.visualstudio.com"):
        return "/".join(parts[1:]) if len(parts) == 4 and parts[0] == "v3" else None
    if host == "dev.azure.com":
        org, rest = (parts[0], parts[1:]) if parts else ("", [])
    elif host.endswith(".visualstudio.com"):
        org, rest = host.split(".", 1)[0], [p for p in parts if p != "DefaultCollection"]
    else:
        return None
    return f"{org}/{rest[0]}/{rest[2]}" if len(rest) == 3 and rest[1] == "_git" and org else None


def repository(url: str) -> Repository | None:
    """The repository a git URL names: GitHub's, Azure DevOps', or, on any other host, a plain git repository."""
    split = _split(url)
    if split is None:
        return None
    host, path, suffix = split
    parts = path.split("/")
    if host in _GITHUB_HOSTS:
        return Repository(GITHUB, "/".join(parts[:2])) if len(parts) >= 2 else None
    if host == "dev.azure.com" or host.endswith(".visualstudio.com") or host == "ssh.dev.azure.com":
        found = _azure(host, parts)
        return Repository(AZURE_DEVOPS, found) if found else None
    return Repository(GIT, f"{host}/{path}", suffix) if len(parts) >= 1 and "." in host else None


def github_repository(url: str) -> str | None:
    """`owner/name` of a GitHub URL (https or ssh), else None."""
    found = repository(url)
    return found.path if found and found.host == GITHUB else None


def repository_of(path: str) -> Repository:
    """A repository from its path: a host first (it has a dot) is any git host's, three segments Azure DevOps',
    two GitHub's."""
    if "." in path.split("/", 1)[0]:
        return Repository(GIT, path)
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


def anonymous_visibility(*urls: str) -> Visibility | None:
    """`Public` when git reads one of `urls` with no credential of this machine: no credential helper, no `.netrc`,
    no git configuration (a `url.insteadOf` could add one), no prompt; else None, since a refusal does not tell
    private from missing."""
    with tempfile.TemporaryDirectory() as home:
        env = {
            **os.environ, "HOME": home, "XDG_CONFIG_HOME": home, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
        }  # fmt: skip
        for url in urls:
            try:
                done = subprocess.run(
                    ["git", "-c", "credential.helper=", "ls-remote", "--exit-code", url, "HEAD"],
                    capture_output=True, env=env, timeout=60, check=False,
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                continue
            if done.returncode == 0:
                return Visibility.PUBLIC
    return None


def hosted_visibility(path: str) -> Visibility | None:
    """A repository's visibility on its own host: GitHub's or Azure DevOps' answer, else (any other host, or theirs
    unknown) `Public` only when git reads it anonymously."""
    found = repository_of(path)
    if found.host == AZURE_DEVOPS:
        told = azure_visibility(found.path)
    elif found.host == GITHUB:
        told = github_visibility(found.path)
    else:
        told = None
    if told is not None:
        return told
    return anonymous_visibility(found.web_url + ".git", found.web_url)


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
