"""What catalyst ignores, a knowledge base leaves out (`eng-SOURCE-000004`)."""

from __future__ import annotations

from pathlib import Path

from catalyst_kb_engine.build.folders import BuildInfo, build_folders
from catalyst_kb_engine.ignore import Ignored
from catalyst_kb_engine.models import Classification


def test_an_empty_file_opts_out_its_directory_and_a_listed_path_its_subtree(tmp_path: Path):
    (tmp_path / "docs" / "scratch").mkdir(parents=True)
    (tmp_path / "docs" / "scratch" / ".catalystignore").write_text("# all of it\n\n")
    (tmp_path / ".catalystignore").write_text("# not the project's\n./docs/user-generated\n/notes.md\n")
    ignored = Ignored(tmp_path)
    assert ignored("docs/scratch/a.md") and ignored("docs/user-generated/map.md") and ignored("notes.md")
    assert not ignored("docs/guide/01.md") and not ignored("docs/user-generated-not.md")


def test_a_build_never_reads_what_is_opted_out(tmp_path: Path):
    repo = tmp_path / "kb"
    (repo / "docs" / "guide").mkdir(parents=True)
    (repo / "docs" / "user-generated").mkdir(parents=True)
    (repo / "docs" / "guide" / "page.md").write_text("---\ntitle: Page\nclassification: Public\n---\n\nKept.\n")
    (repo / "docs" / "user-generated" / "map.md").write_text("# Unmarked, and not the project's\n")
    (repo / ".catalystignore").write_text("docs/user-generated\n")
    info = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.PUBLIC, Classification.PUBLIC)
    result = build_folders(repo, tmp_path / "out", info)  # an unmarked document would refuse the build
    assert result.documents == 1 and not (tmp_path / "out" / "docs" / "user-generated").exists()
