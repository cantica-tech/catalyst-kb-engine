"""The folders build: readable by any model, without catalyst (`eng-OUTPUT-000001`; KBM `rr-KB-009`)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from catalyst_kb_engine.build.folders import FORMAT, BuildError, BuildInfo, build_folders
from catalyst_kb_engine.models import Classification

INFO = BuildInfo(
    knowledge_base="KB-000001-Ab3xR9pQ",
    version="1.0.0",
    floor=Classification.INTERNAL,
    ceiling=Classification.INTERNAL,
    built=datetime(2026, 10, 24, tzinfo=UTC),
)


def _doc(path: Path, title: str, classification: str | None, body: str, **more: str) -> None:
    meta = {"title": title, **({"classification": classification} if classification else {}), **more}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(meta) + "---\n\n" + body, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    _doc(kb / "docs/billing/invoices.md", "Invoices", "Public", "# Invoices\n\nHow invoices are approved.\n")
    _doc(kb / "docs/billing/salaries.md", "Salaries", "Confidential", "Who earns what.\n")
    _doc(kb / "pointers/billing/matrix.md", "Approval matrix", "Internal", "Who approves.\n", url="https://x.example")
    _doc(kb / "pointers/billing/gone.md", "Gone", "Internal", "Moved away.\n", url="https://y.example", status="broken")
    (kb / "docs/README.md").write_text("# What this level holds\n", encoding="utf-8")
    return kb


def test_it_keeps_what_the_ceiling_allows_at_its_effective_classification(repo, tmp_path):
    result = build_folders(repo, tmp_path / "out", INFO)
    out = tmp_path / "out"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md")) == [
        "README.md",
        "docs/billing/invoices.md",
        "docs/billing/matrix.md",
        "index.md",
    ]
    invoices = (out / "docs/billing/invoices.md").read_text(encoding="utf-8")
    assert "classification: Internal" in invoices  # Public under an Internal floor is Internal
    assert (result.documents, result.pointers, result.left_out) == (1, 1, 2)  # the confidential one, the broken one
    assert "salaries" not in (out / "index.md").read_text(encoding="utf-8")  # a left-out name is not revealed


def test_its_manifest_says_what_it_is_and_hashes_every_file(repo, tmp_path):
    build_folders(repo, tmp_path / "out", INFO)
    out = tmp_path / "out"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == FORMAT and manifest["target"] == "folders"
    assert manifest["classification"] == "Internal" and manifest["ceiling"] == "Internal"
    for name, digest in manifest["files"].items():
        assert digest == "sha256:" + hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert set(manifest["files"]) == {"README.md", "index.md", "docs/billing/invoices.md", "docs/billing/matrix.md"}


def test_the_same_repository_builds_the_same_files(repo, tmp_path):
    build_folders(repo, tmp_path / "a", INFO)
    build_folders(repo, tmp_path / "b", INFO)
    a, b = (json.loads((tmp_path / d / "manifest.json").read_text())["files"] for d in "ab")
    assert a == b


def test_an_unmarked_document_stops_the_build_and_nothing_is_written(repo, tmp_path):
    _doc(repo / "docs/billing/draft.md", "Draft", None, "Not yet marked.\n")
    with pytest.raises(BuildError, match="unmarked"):
        build_folders(repo, tmp_path / "out", INFO)
    assert not (tmp_path / "out").exists()


def test_a_build_is_written_once(repo, tmp_path):
    build_folders(repo, tmp_path / "out", INFO)
    with pytest.raises(BuildError, match="not empty"):
        build_folders(repo, tmp_path / "out", INFO)


def test_a_higher_ceiling_takes_more(repo, tmp_path):
    info = BuildInfo(**{**INFO.__dict__, "ceiling": Classification.CONFIDENTIAL})
    result = build_folders(repo, tmp_path / "out", info)
    assert result.classification is Classification.CONFIDENTIAL and result.left_out == 1  # the broken pointer
