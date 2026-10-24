"""Recording in the criterion through catalyst's CLI (`eng-WORKFLOW-000003`), against a fake catalyst."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalyst_kb_engine.build.folders import BuildInfo, FoldersBuild
from catalyst_kb_engine.catalyst import CatalystCLI, CatalystError
from catalyst_kb_engine.models import (
    Basis,
    Classification,
    DocumentBase,
    Folder,
    Layout,
    OnboardingPlan,
    Source,
    Target,
)
from catalyst_kb_engine.record import KbPolicy, read_plan, record_build, record_onboarding, structure

PLAN = OnboardingPlan(
    basis=Basis.CRITERION,
    sources=[
        Source(title="The app criterion", location="criterion:app"),
        Source(title="The wiki", location="https://wiki.example.com", classification=Classification.INTERNAL),
    ],
    layout=Layout(repository="../app-kb", folders=[Folder(path="criterion", holds="the project's records")]),
    target=Target.FOLDERS,
    document_base=DocumentBase.DYNAMIC,
)
POLICY = KbPolicy(
    title="App KB", serves=["kr-KNOW-000001-Ab3xR9pQ"], classification=Classification.INTERNAL,
    default_classification=Classification.INTERNAL,
)  # fmt: skip


class FakeCatalyst(CatalystCLI):
    """catalyst's CLI as far as the recorder uses it: `new`, `view`, `where`, `status`, `journal append`."""

    def __init__(self, criterion: Path) -> None:
        super().__init__(project=criterion, command=["catalyst"])
        self.root = criterion
        self.records: dict[str, dict] = {}
        self.calls: list[list[str]] = []

    def run(self, *args: str) -> str:
        self.calls.append(list(args))
        verb = args[0]
        if verb == "where":
            return json.dumps({"criterion": str(self.root)})
        if verb == "new":
            type_, title = args[1], args[3]
            n = sum(r["type"] == type_ for r in self.records.values()) + 1
            entity = f"{type_}-{n:06d}-Ab3xR9pQ"
            fields = dict(a.split("=", 1) for a in args[4:] if "=" in a and not a.startswith("--"))
            path = self.root / f"{entity}.md"
            path.write_text(
                f"# {title}\n\n## Structure\n\nplaceholder\n\n## Contents\n\nplaceholder\n", encoding="utf-8"
            )
            self.records[entity] = {"id": entity, "type": type_, "title": title, "file": path.name, **fields}
            if type_ == "KSOURCE":
                kb = self.records[fields["Knowledge base"]]
                kb["Sources"] = ", ".join(filter(None, [kb.get("Sources"), f"`{entity}`"]))
            return json.dumps({"id": entity})
        if verb == "view":
            record = dict(self.records[args[1]])
            text = (self.root / record["file"]).read_text(encoding="utf-8")
            heads = text.split("\n## ")[1:]
            record["sections"] = [{"heading": h.split("\n", 1)[0], "text": h.split("\n", 1)[1].strip()} for h in heads]
            return json.dumps(record)
        if verb in ("status", "journal"):
            return ""
        raise CatalystError(f"unexpected {args}")


def test_onboarding_becomes_a_kb_its_sources_and_its_structure(tmp_path):
    cli = FakeCatalyst(tmp_path)
    recorded = record_onboarding(cli, POLICY, PLAN)
    kb = cli.records[recorded.kb]
    assert (kb["Basis"], kb["Document base"], kb["Target"]) == ("Criterion", "Dynamic", "Folders")
    assert kb["Hosted embedding up to"] == "Local only"  # never `None`, which catalyst reads as empty
    assert [cli.records[s]["Location"] for s in recorded.sources] == ["criterion:app", "https://wiki.example.com"]
    assert "- `docs/criterion/` — the project's records" in (tmp_path / kb["file"]).read_text(encoding="utf-8")
    assert cli.calls[-1][:2] == ["journal", "append"]  # the Structure, journaled


def test_a_recorded_kb_reads_back_into_the_same_plan(tmp_path):
    cli = FakeCatalyst(tmp_path)
    recorded = record_onboarding(cli, POLICY, PLAN)
    assert read_plan(cli, recorded.kb) == PLAN


def test_a_kb_never_onboarded_is_refused(tmp_path):
    cli = FakeCatalyst(tmp_path)
    recorded = record_onboarding(cli, POLICY, PLAN)
    cli.records[recorded.kb]["Basis"] = "*(none yet)*"
    with pytest.raises(ValueError, match="not onboarded"):
        read_plan(cli, recorded.kb)


def test_a_build_is_recorded_built_with_its_contents(tmp_path):
    cli = FakeCatalyst(tmp_path)
    info = BuildInfo("KB-000001-Ab3xR9pQ", "1.0.0", Classification.INTERNAL, Classification.INTERNAL)
    result = FoldersBuild(out=tmp_path, classification=Classification.INTERNAL, documents=3, pointers=1, left_out=2)
    build = record_build(cli, info, result, "../builds/1.0.0", "App KB 1.0.0")
    assert cli.records[build]["Target"] == "Folders" and cli.records[build]["Location"] == "../builds/1.0.0"
    assert ["status", "set", build, "Built"] == cli.calls[-1][:4]
    assert "3 documents and 1 pointers" in (tmp_path / cli.records[build]["file"]).read_text(encoding="utf-8")


def test_structure_lists_every_folder():
    assert structure(PLAN.layout).count("- `docs/") == 1
