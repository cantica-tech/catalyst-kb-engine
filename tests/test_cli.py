"""The command line: exit codes and a build from it."""

from __future__ import annotations

import json

from catalyst_kb_engine import cli
from tests.test_folders import repo  # noqa: F401 - the fixture


def test_build_folders_from_the_command_line(repo, tmp_path, capsys):  # noqa: F811
    code = cli.main(["build-folders", str(repo), str(tmp_path / "out"), "--kb", "KB-1", "--version", "1.0.0",
                     "--floor", "Internal"])  # fmt: skip
    assert code == 0 and json.loads(capsys.readouterr().out)["documents"] == 1


def test_a_refused_build_exits_1_and_says_why(repo, tmp_path, capsys):  # noqa: F811
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x").write_text("x")
    code = cli.main(["build-folders", str(repo), str(tmp_path / "out"), "--kb", "KB-1", "--version", "1",
                     "--floor", "Internal"])  # fmt: skip
    assert code == 1 and "not empty" in capsys.readouterr().err


def test_usage_errors_exit_2(capsys):
    assert cli.main(["build-folders"]) == 2
