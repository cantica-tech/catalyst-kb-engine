"""What onboarding decided and what a build produced, as the criterion's records (`eng-WORKFLOW-000003`): a `KB-` and
its `KSOURCE-`s, a `KBUILD-`, written through catalyst's CLI and read back to resume. The engine keeps nothing else."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from catalyst_kb_engine.build.folders import BuildInfo, FoldersBuild
from catalyst_kb_engine.catalyst import CatalystCLI
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

UNSET = "*(none yet)*"
"""What catalyst writes in an optional field it was not given."""
_IDS = re.compile(r"`?([A-Z]+-\d{6}-[A-Za-z0-9]{8})`?")
_FOLDER = re.compile(r"^- `docs/(?P<path>[^`]+?)/` — (?P<holds>.+)$", re.M)


class KbPolicy(BaseModel):
    """What `/kb-setup` asks besides onboarding: what it serves, and its classification policy."""

    title: str = Field(min_length=1)
    serves: list[str] = Field(min_length=1, description="the rule IDs it exists for")
    kind: Literal["Project", "Reflective"] = "Project"
    classification: Classification
    default_classification: Classification
    hosted_embedding_up_to: Classification | Literal["Local only"] = "Local only"
    freshness: str = "30 days"
    curator: str | None = None


@dataclass(frozen=True)
class Recorded:
    kb: str
    sources: list[str]


def structure(layout: Layout) -> str:
    """The KB's Structure section: its repository and folder plan, one line per folder (read back by `read_plan`)."""
    lines = [f"- `docs/{f.path}/` — {f.holds}" for f in layout.folders]
    return (
        f"Repository: `{layout.repository}`. Documents live under `docs/`, organized as below; pointers mirror it "
        "under `pointers/`.\n\n" + "\n".join(lines)
    )


def record_onboarding(cli: CatalystCLI, policy: KbPolicy, plan: OnboardingPlan) -> Recorded:
    """`catalyst new KB` with what onboarding decided, one `KSOURCE-` per source (the criterion first), and the folder
    plan in the KB's Structure. Only a decided plan is recorded (`eng-WORKFLOW-000002`)."""
    intent = f"onboarding decided: {plan.basis.value}-based, {plan.document_base.value}, target {plan.target.value}"
    fields = {
        "Serves": ",".join(policy.serves),
        "Kind": policy.kind,
        "Classification": policy.classification.value,
        "Default classification": policy.default_classification.value,
        "Hosted embedding up to": str(policy.hosted_embedding_up_to),
        "Repository": plan.layout.repository,
        "Freshness": policy.freshness,
        "Basis": plan.basis.value,
        "Document base": plan.document_base.value,
        "Target": plan.target.value,
    }
    if policy.curator:
        fields["Curator"] = policy.curator
    kb = cli.new("KB", policy.title, fields, intent=intent, tier="kb")["id"]
    sources = []
    for source in plan.sources:
        fields = {"Knowledge base": kb, "Location": source.location}
        if source.classification:
            fields["Classification"] = source.classification.value
        if source.access:
            fields["Access"] = source.access
        what = "the criterion it is built on" if source.is_criterion else "a source onboarding selected"
        sources.append(cli.new("KSOURCE", source.title, fields, intent=what, tier="kb")["id"])
    cli.write_section(kb, "Structure", structure(plan.layout), intent="the folder plan onboarding decided", tier="kb")
    return Recorded(kb=kb, sources=sources)


def _value(record: dict[str, Any], name: str) -> str | None:
    value = record.get(name)
    return None if value in (None, "", UNSET) else str(value).strip()


def read_plan(cli: CatalystCLI, kb: str) -> OnboardingPlan:
    """A recorded knowledge base, read back into its onboarding plan: how a workflow resumes."""
    record = cli.view(kb)
    sources = []
    for source_id in _IDS.findall(record.get("Sources") or ""):
        s = cli.view(source_id)
        mark = _value(s, "Classification")
        sources.append(
            Source(
                title=s["title"],
                location=_value(s, "Location") or "",
                classification=Classification(mark) if mark and mark != "Unmarked" else None,
                access=_value(s, "Access"),
            )
        )
    sources.sort(key=lambda s: not s.is_criterion)  # the criterion first, as onboarding records it
    text = next((x["text"] for x in record.get("sections", []) if x["heading"] == "Structure"), "")
    folders = [Folder(path=m["path"], holds=m["holds"].strip()) for m in _FOLDER.finditer(text)]
    basis, base, target = (_value(record, n) for n in ("Basis", "Document base", "Target"))
    if not (basis and base and target):
        raise ValueError(f"{kb} was not onboarded: its Basis, Document base or Target is unset")
    return OnboardingPlan(
        basis=Basis(basis),
        sources=sources,
        layout=Layout(repository=_value(record, "Repository") or "", folders=folders),
        target=Target(target),
        document_base=DocumentBase(base),
    )


def record_build(cli: CatalystCLI, info: BuildInfo, result: FoldersBuild, location: str, title: str) -> str:
    """`catalyst new KBUILD` for a folders build, its Contents written, set `Built` (publishing is a person's)."""
    fields = {
        "Knowledge base": info.knowledge_base,
        "Version": info.version,
        "Target": Target.FOLDERS.value,
        "Ceiling": info.ceiling.value,
        "Classification": result.classification.value,
        "Location": location,
    }
    if info.content_commit:
        fields["Content commit"] = info.content_commit
    cli.command_name = "/kb-build"
    build = cli.new("KBUILD", title, fields, intent=f"the folders build {info.version}", tier="build")["id"]
    contents = (
        f"{result.documents} documents and {result.pointers} pointers, format `kbm-build/1`, target folders; "
        f"{result.left_out} left out by the ceiling ({info.ceiling.value}) or as broken pointers."
    )
    cli.write_section(build, "Contents", contents, intent="what the build contains", tier="build")
    cli.status(build, "Built", intent="the build is written", tier="build")
    return build
