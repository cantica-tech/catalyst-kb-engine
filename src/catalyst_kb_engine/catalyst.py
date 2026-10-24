"""catalyst's CLI, run from the project (`eng-WORKFLOW-000003`): every record the engine writes goes through it, so
it is journaled and signed as catalyst signs (the logged-in person, else the machine's system account)."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class CatalystError(Exception):
    """catalyst refused or failed; its own message says why."""


@dataclass
class CatalystCLI:
    project: Path
    """The project's root (where `catalyst.toml` is)."""
    command: list[str] = field(default_factory=lambda: shlex.split(os.environ.get("CATALYST_CLI") or "catalyst"))
    """How catalyst is run: `CATALYST_CLI` (e.g. `python3 ~/.catalyst/bin/catalyst`), else `catalyst`."""
    as_user: str | None = None
    """The signer, when not the logged-in person or the system account."""
    command_name: str = "/kb-setup"
    """The slash command the records are journaled for."""

    def run(self, *args: str) -> str:
        argv = [*self.command, *args]
        done = subprocess.run(argv, cwd=self.project, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise CatalystError(done.stderr.strip() or done.stdout.strip() or f"catalyst exited {done.returncode}")
        return done.stdout

    def json(self, *args: str) -> Any:
        return json.loads(self.run(*args, "--json"))

    def _signed(self, intent: str, tier: str) -> list[str]:
        out = ["--intent", intent, "--command", self.command_name, "--tier", tier]
        return [*out, "--as", self.as_user] if self.as_user else out

    def new(self, type_: str, title: str, fields: dict[str, str], *, intent: str, tier: str) -> dict[str, Any]:
        args = ["new", type_, "--title", title]
        for name, value in fields.items():
            args += ["--field", f"{name}={value}"]
        return self.json(*args, *self._signed(intent, tier))

    def criterion(self) -> Path:
        """The project's criterion (`catalyst where`): entity files are relative to it."""
        return Path(self.json("where")["criterion"])

    def view(self, entity: str) -> dict[str, Any]:
        return self.json("view", entity)

    def status(self, entity: str, status: str, *, intent: str, tier: str) -> None:
        self.run("status", "set", entity, status, *self._signed(intent, tier))

    def write_section(self, entity: str, heading: str, text: str, *, intent: str, tier: str) -> None:
        """Replace one section of an entity's file, then journal it (L1): the way a person writes a section."""
        path = self.criterion() / self.view(entity)["file"]
        body = path.read_text(encoding="utf-8")
        match = re.search(rf"^## {re.escape(heading)}\n", body, re.M)
        if not match:
            raise CatalystError(f"{entity} has no section {heading!r}")
        end = body.find("\n## ", match.end())
        rest = body[end:] if end >= 0 else "\n"
        path.write_text(body[: match.start()] + f"## {heading}\n\n{text.strip()}\n" + rest, encoding="utf-8")
        self.run(
            "journal", "append", "--action", "update", "--artifact", entity, "--file", str(path),
            *self._signed(intent, tier),
        )  # fmt: skip
