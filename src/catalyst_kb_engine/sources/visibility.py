"""A source's visibility (`eng-SOURCE-000002`): resolved from its `KSOURCE-` record and its host before anything is
read; when the two disagree, nothing is."""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from catalyst_kb_engine.models import Source, Visibility

_GITHUB = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?$"
)

Host = Callable[[str], Visibility | None]
"""A GitHub repository (`owner/name`) to its visibility, or None when it cannot be told."""


class SourceError(Exception):
    """A source cannot be read as recorded; nothing was read from it."""


def github_repository(url: str) -> str | None:
    """`owner/name` of a GitHub URL (https or ssh), else None."""
    match = _GITHUB.match(url.strip())
    return match.group(1) if match else None


def github_visibility(repository: str) -> Visibility | None:
    """`gh repo view`: GitHub's `PUBLIC` is public, anything else (private, internal) private; None if unknown."""
    done = subprocess.run(
        ["gh", "repo", "view", repository, "--json", "visibility", "-q", ".visibility"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return Visibility.PUBLIC if done.stdout.strip() == "PUBLIC" else Visibility.PRIVATE


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
    """A catalyst project's criterion repository (`catalyst.toml` `catalyst_repo_url`) as `owner/name`."""
    toml = tomllib.loads((project / "catalyst.toml").read_text(encoding="utf-8"))
    return github_repository(str(toml.get("catalyst_repo_url") or ""))


def host_repository(source: Source, projects: Projects) -> str | None:
    """The GitHub repository whose visibility is the source's: a criterion's own repository, else its location."""
    if source.is_criterion:
        return criterion_repository(projects.find(source.project or "", catalyst=True))
    return github_repository(source.location)


def resolve(source_id: str, source: Source, projects: Projects, host: Host = github_visibility) -> Visibility:
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
