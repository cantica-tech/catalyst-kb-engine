"""Onboarding and a folders build recorded in a real catalyst deployment with KBM, read back, and checked.

Runs only when KB_ENGINE_IT=1. It needs a catalyst checkout (CATALYST_CHECKOUT, else ../catalyst), the knowledge base
module (KBM_MODULE, else ../catalyst-knowledge-base), and this machine's catalyst-users set up, whose system account
signs (KB_ENGINE_IT_USER: its name, else `git config user.name`). Everything else is in a temporary directory.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from catalyst_kb_engine.build.folders import BuildInfo, build_folders
from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.models import Classification, Source, Target
from catalyst_kb_engine.onboarding import OnboardingContext, onboard
from catalyst_kb_engine.record import KbPolicy, read_plan, record_build, record_onboarding

ROOT = Path(__file__).resolve().parents[2]
CHECKOUT = Path(os.environ.get("CATALYST_CHECKOUT") or ROOT.parent / "catalyst")
KBM = Path(os.environ.get("KBM_MODULE") or ROOT.parent / "catalyst-knowledge-base")

pytestmark = pytest.mark.skipif(os.environ.get("KB_ENGINE_IT") != "1", reason="integration: set KB_ENGINE_IT=1")


class Accept:
    async def decide(self, question, proposal):
        return proposal


def _user() -> str:
    found = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=False).stdout
    return os.environ.get("KB_ENGINE_IT_USER") or found.strip()


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("CATALYST_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONPATH", str(CHECKOUT / "scripts"))
    monkeypatch.setenv("CATALYST_CLI", f"{sys.executable} -m catalyst")
    app = tmp_path / "app"
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    cli = CatalystCLI(app)
    cli.run(
        "init", "--kernel", str(CHECKOUT / "framework/kernel"), "--name", "app", "--module", "knowledge-base",
        "--module-dir", str(KBM), "--user", _user(), "--rule-doc", "kb-rules.md:kr", "--no-runtime",
    )  # fmt: skip
    rules = cli.criterion() / "rules"
    with (rules / "domains" / "domains.md").open("a", encoding="utf-8") as f:
        f.write("| [`KNOW`](kr-KNOW-shared-knowledge.md) | rules/kb-rules.md | 2026-10-24 |\n")
    (rules / "domains" / "kr-KNOW-shared-knowledge.md").write_text("# `KNOW` — Shared knowledge\n", encoding="utf-8")
    cli.run(
        "journal", "append", "--command", "chore", "--action", "create", "--artifact", "domain KNOW", "--tier",
        "chore", "--intent", "the domain the test's first rule belongs to", "--file",
        str(rules / "domains" / "domains.md"), "--file", str(rules / "domains" / "kr-KNOW-shared-knowledge.md"),
    )  # fmt: skip
    rule = cli.run("id", "next-rule", "kr", "KNOW").strip().splitlines()[-1]
    doc, index = rules / "kb-rules.md", rules / "rules.md"
    doc.write_text(doc.read_text().replace("*(no rules yet)*", f"### `{rule}` Support answers\n\nAnswers.\n"))
    index.write_text(index.read_text().replace("*(none yet)*", f"- `{rule}` — Support answers"))
    cli.run(
        "journal", "append", "--command", "chore", "--action", "create", "--artifact", rule, "--tier", "chore",
        "--intent", "the rule the test's knowledge base serves", "--file", str(doc), "--file", str(index),
    )  # fmt: skip
    (app / ".rule").write_text(rule)
    return app


def test_onboarding_and_a_build_are_records_catalyst_checks(project, tmp_path):
    cli = CatalystCLI(project)
    rule = (project / ".rule").read_text()
    context = OnboardingContext(
        title="App KB",
        project="app",
        other_modules=["software-engineering"],
        candidate_sources=[Source(title="The wiki", location="https://wiki.example.com")],
    )
    plan, _ = asyncio.run(onboard(context, Accept()))
    policy = KbPolicy(
        title="App KB", serves=[rule], classification=Classification.INTERNAL,
        default_classification=Classification.INTERNAL,
    )  # fmt: skip
    recorded = record_onboarding(cli, policy, plan)
    assert read_plan(cli, recorded.kb) == plan
    assert cli.view(recorded.kb)["Hosted embedding up to"] == "Local only"

    repo = tmp_path / "kb"
    doc = repo / "docs" / "criterion" / "answers.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("---\n" + yaml.safe_dump({"title": "Answers", "classification": "Internal"}) + "---\n\nYes.\n")
    info = BuildInfo(recorded.kb, "1.0.0", Classification.INTERNAL, Classification.INTERNAL)
    result = build_folders(repo, tmp_path / "builds" / "1.0.0", info)
    build = record_build(cli, info, result, str(tmp_path / "builds" / "1.0.0"), "App KB 1.0.0")
    view = cli.view(build)
    assert (view["Status"], view["Target"]) == ("Built", Target.FOLDERS.value)

    report = cli.run("check")
    assert "0 error(s)" in report, report
