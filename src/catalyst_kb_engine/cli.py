"""`catalyst-kb-engine`: `onboard` runs the onboarding workflow with a person at the terminal (`--record` writes it to
the criterion); `build-folders` writes a folders build (`--record` records it); `plan` reads a recorded knowledge base
back. Records go through catalyst's CLI (`CATALYST_CLI`, else `catalyst`). Exit codes: 0 done, 1 refused or failed,
2 usage."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from catalyst_kb_engine.build.folders import BuildError, BuildInfo, build_folders
from catalyst_kb_engine.catalyst import CatalystCLI, CatalystError
from catalyst_kb_engine.models import Classification
from catalyst_kb_engine.onboarding import AgentProposer, OnboardingContext, onboard
from catalyst_kb_engine.record import KbPolicy, read_plan, record_build, record_onboarding

P = TypeVar("P", bound=BaseModel)


class ConsoleDecider:
    """A person at the terminal: Enter accepts the proposal; a JSON document replaces it (validated, asked again)."""

    async def decide(self, question: str, proposal: P) -> P:
        print(f"\n{question}\nProposed:\n{proposal.model_dump_json(indent=2)}")
        while True:
            answer = input("Enter to accept, or JSON to replace it: ").strip()
            if not answer:
                return proposal
            try:
                return type(proposal).model_validate_json(answer)
            except ValidationError as err:
                print(f"Not valid: {err.errors()[0]['msg']}", file=sys.stderr)


def _onboard(args: argparse.Namespace) -> int:
    context = OnboardingContext(
        title=args.title,
        purpose=args.purpose or "",
        project=args.project,
        other_modules=args.other_module or [],
    )
    proposer = AgentProposer(args.model) if args.model else None
    plan, _ = asyncio.run(onboard(context, ConsoleDecider(), proposer))
    print(plan.model_dump_json(indent=2))
    if args.record:
        if not args.serves or not args.classification:
            raise ValueError("--record needs --serves and --classification")
        policy = KbPolicy(
            title=args.title,
            serves=args.serves.split(","),
            kind=args.kind,
            classification=Classification(args.classification),
            default_classification=Classification(args.default_classification or args.classification),
            hosted_embedding_up_to=args.hosted_up_to,
            freshness=args.freshness,
            curator=args.curator,
        )
        recorded = record_onboarding(CatalystCLI(Path(args.project_root)), policy, plan)
        print(json.dumps({"kb": recorded.kb, "sources": recorded.sources}, indent=2))
    return 0


def _plan(args: argparse.Namespace) -> int:
    print(read_plan(CatalystCLI(Path(args.project_root)), args.kb).model_dump_json(indent=2))
    return 0


def _build_folders(args: argparse.Namespace) -> int:
    info = BuildInfo(
        knowledge_base=args.kb,
        build=args.build,
        version=args.version,
        floor=Classification(args.floor),
        ceiling=Classification(args.ceiling or args.floor),
        content_commit=args.content_commit,
    )
    result = build_folders(Path(args.repository), Path(args.out), info)
    summary = {
        "out": str(result.out),
        "classification": result.classification.value,
        "documents": result.documents,
        "pointers": result.pointers,
        "left_out": result.left_out,
    }
    if args.record:
        location = args.location or str(Path(args.out).resolve())
        title = f"{args.kb} {args.version}"
        summary["build"] = record_build(CatalystCLI(Path(args.project_root)), info, result, location, title)
    print(json.dumps(summary, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    levels = [c.value for c in Classification]
    parser = argparse.ArgumentParser(prog="catalyst-kb-engine", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    o = sub.add_parser("onboard", help="onboard a knowledge base: four decisions, proposed, decided by you")
    o.add_argument("title")
    o.add_argument("--purpose", help="what it must make known, and for whom")
    o.add_argument("--project", help="the catalyst project it belongs to")
    o.add_argument("--other-module", action="append", help="a module governing the project beside KBM (repeatable)")
    o.add_argument("--model", help="a Pydantic AI model to propose with, e.g. ollama:llama3.2 (default: rules only)")
    o.add_argument("--record", action="store_true", help="record the decided plan in the criterion (KB-, KSOURCE-s)")
    o.add_argument("--serves", help="with --record: the rule IDs it exists for, comma-separated")
    o.add_argument("--kind", choices=["Project", "Reflective"], default="Project")
    o.add_argument("--classification", choices=levels, help="with --record: its classification (its floor)")
    o.add_argument("--default-classification", choices=levels, help="the policy's mark (default: --classification)")
    o.add_argument("--hosted-up-to", choices=["Local only", *levels], default="Local only")
    o.add_argument("--freshness", default="30 days")
    o.add_argument("--curator")
    b = sub.add_parser("build-folders", help="write a folders build of a knowledge base repository")
    b.add_argument("repository", help="the knowledge base repository (docs/, pointers/)")
    b.add_argument("out", help="the build's directory, new or empty")
    b.add_argument("--kb", required=True, help="the KB- ID")
    b.add_argument("--version", required=True)
    b.add_argument("--floor", required=True, choices=levels, help="the knowledge base's Classification")
    b.add_argument("--ceiling", choices=levels, help="the highest classification it may contain (default: --floor)")
    b.add_argument("--build", help="the KBUILD- ID, once recorded")
    b.add_argument("--content-commit", help="the repository's commit it is built from")
    b.add_argument("--record", action="store_true", help="record it as a KBUILD- in the criterion, Built")
    b.add_argument("--location", help="with --record: where the build is kept (default: the output directory)")
    pl = sub.add_parser("plan", help="read a recorded knowledge base back into its onboarding plan")
    pl.add_argument("kb", help="the KB- ID")
    for p in (o, b, pl):
        p.add_argument("--project-root", default=".", help="the catalyst project (default: here)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        return {"onboard": _onboard, "build-folders": _build_folders, "plan": _plan}[args.command](args)
    except (BuildError, CatalystError, ValidationError, ValueError) as err:
        print(f"catalyst-kb-engine: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
