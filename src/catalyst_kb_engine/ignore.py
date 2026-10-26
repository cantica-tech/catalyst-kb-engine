"""What catalyst ignores, a knowledge base leaves out (`eng-SOURCE-000004`): the paths `.catalystignore` files opt out
of catalyst, as catalyst's `FORMAT.md` §11 defines them. An empty file (blank lines and `#` comments aside) opts out
its directory and everything below it; otherwise each line is a path relative to the file's directory, a file or a
directory and everything below it, `/`-separated, without wildcards, a leading `/` or `./` ignored."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

NAME = ".catalystignore"


class Ignored:
    """The opted-out paths under `root`, relative to it."""

    def __init__(self, root: Path) -> None:
        self.paths: set[PurePosixPath] = set()
        for file in root.rglob(NAME):
            here = PurePosixPath(file.parent.relative_to(root).as_posix())
            lines = [line.strip() for line in file.read_text(encoding="utf-8").splitlines()]
            entries = [line for line in lines if line and not line.startswith("#")]
            if not entries:
                self.paths.add(here)
            for entry in entries:
                self.paths.add(here / entry.removeprefix("./").lstrip("/"))

    def __call__(self, path: str | PurePosixPath) -> bool:
        """Whether `path` (relative to the root, `/`-separated) is opted out, itself or through a directory above it."""
        candidate = PurePosixPath(path)
        return any(candidate == p or p in candidate.parents for p in self.paths)
