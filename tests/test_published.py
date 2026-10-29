"""A published build's record (`eng-PUBLISH-000003`), from a site's manifests, against a fake catalyst."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from catalyst_kb_engine.build.folders import BuildError
from catalyst_kb_engine.catalyst import CatalystError
from catalyst_kb_engine.published import record_site
from tests.test_record import FakeCatalyst

SITE = "https://example.github.io/docs/"
KB = "KB-000001-Ab3xR9pQ"


class SiteCatalyst(FakeCatalyst):
    """The fake catalyst, also listing builds and keeping their status."""

    def __init__(self, criterion: Path) -> None:
        super().__init__(criterion)
        self.records[KB] = {"id": KB, "type": "KB", "title": "Docs", "file": "kb.md"}
        (criterion / "kb.md").write_text("# Docs\n", encoding="utf-8")

    def run(self, *args: str) -> str:
        if args[:2] == ("list", "KBUILD"):
            self.calls.append(list(args))
            builds = [r for r in self.records.values() if r["type"] == "KBUILD"]
            return json.dumps([{**b, "Knowledge base": f"`{b['Knowledge base']}`"} for b in builds])
        if args[:2] == ("status", "set"):
            self.records[args[2]]["Status"] = args[3]
        out = super().run(*args)
        if args[0] == "new" and args[1] == "KBUILD":
            entity = json.loads(out)["id"]
            path = self.root / self.records[entity]["file"]
            path.write_text(
                path.read_text(encoding="utf-8") + "\n## Verification\n\nx\n\n## Related\n\nx\n", encoding="utf-8"
            )
        return out


def manifest(target: str, version: str = "abc123", **extra) -> bytes:
    data = {"format": "kbm-build/1", "target": target, "knowledge_base": KB, "version": version,
            "classification": "Public", "ceiling": "Public", "content_commit": "abc123def",
            "counts": {"documents": 3, "pointers": 0, "left_out": 0}, **extra}  # fmt: skip
    return json.dumps(data).encode()


def serving(pages: bytes | None, vectors: bytes | None = None):
    return lambda url: {SITE + "manifest.json": pages, SITE + "vectors/manifest.json": vectors}[url]


def test_each_served_build_is_recorded_published_with_its_verification(tmp_path):
    cli = SiteCatalyst(tmp_path)
    vectors = manifest("vector-database", embedding={"model": "ollama:nomic-embed-text", "dimensions": 768,
                                                      "where": "local", "input": "context"})  # fmt: skip
    done = record_site(cli, SITE, serving(manifest("folders"), vectors))
    pages, vecs = (cli.records[b] for b in done.recorded)
    assert (pages["Target"], pages["Location"], pages["Status"]) == ("Folders", SITE, "Published")
    assert (vecs["Target"], vecs["Location"]) == ("Vector database", SITE + "vectors/catalyst-vectors.tar.gz")
    assert vecs["Embedding model"].startswith("ollama:nomic-embed-text (768 dimensions), local")
    digest = hashlib.sha256(manifest("folders")).hexdigest()
    assert pages["Version"] == f"abc123+{digest[:8]}" and pages["Content commit"] == "abc123def"
    text = (tmp_path / pages["file"]).read_text(encoding="utf-8")
    assert digest in text and "publish-check" in text and "The first build served here." in text
    assert pages["title"] == "Docs public site " + pages["Version"]


def test_recording_again_records_nothing(tmp_path):
    cli = SiteCatalyst(tmp_path)
    first = record_site(cli, SITE, serving(manifest("folders")))
    again = record_site(cli, SITE, serving(manifest("folders")))
    assert again.recorded == [] and again.known == first.recorded


def test_a_new_build_supersedes_the_one_the_site_served_before(tmp_path):
    cli = SiteCatalyst(tmp_path)
    first = record_site(cli, SITE, serving(manifest("folders")))
    second = record_site(cli, SITE, serving(manifest("folders", counts={"documents": 4})))  # same commit, rebuilt
    assert second.superseded == first.recorded and cli.records[first.recorded[0]]["Status"] == "Superseded"
    related = (tmp_path / cli.records[second.recorded[0]]["file"]).read_text(encoding="utf-8")
    assert f"Supersedes `{first.recorded[0]}`." in related


@pytest.mark.parametrize("change", [{"classification": "Internal"}, {"ceiling": "Restricted"}, {"format": "x"}])
def test_a_manifest_not_public_or_not_a_build_is_refused(tmp_path, change):
    cli = SiteCatalyst(tmp_path)
    with pytest.raises(BuildError):
        record_site(cli, SITE, serving(manifest("folders", **change)))
    assert not [r for r in cli.records.values() if r["type"] == "KBUILD"]


def test_a_site_without_a_build_or_of_an_unknown_kb_is_refused(tmp_path):
    cli = SiteCatalyst(tmp_path)
    with pytest.raises(BuildError, match="serves no build"):
        record_site(cli, SITE, serving(None))
    with pytest.raises((CatalystError, KeyError)):
        record_site(cli, SITE, serving(manifest("folders", knowledge_base="KB-000009-Ab3xR9pQ")))
