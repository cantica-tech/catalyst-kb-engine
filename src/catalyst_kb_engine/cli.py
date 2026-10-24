"""`catalyst-kb-engine`: `onboard` runs the onboarding workflow with a person at the terminal; `build-folders` writes a
folders build. Exit codes: 0 done, 1 refused or failed, 2 usage."""

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
from catalyst_kb_engine.models import Classification
from catalyst_kb_engine.onboarding import AgentProposer, OnboardingContext, onboard

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
    b = sub.add_parser("build-folders", help="write a folders build of a knowledge base repository")
    b.add_argument("repository", help="the knowledge base repository (docs/, pointers/)")
    b.add_argument("out", help="the build's directory, new or empty")
    b.add_argument("--kb", required=True, help="the KB- ID")
    b.add_argument("--version", required=True)
    b.add_argument("--floor", required=True, choices=levels, help="the knowledge base's Classification")
    b.add_argument("--ceiling", choices=levels, help="the highest classification it may contain (default: --floor)")
    b.add_argument("--build", help="the KBUILD- ID, once recorded")
    b.add_argument("--content-commit", help="the repository's commit it is built from")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        return {"onboard": _onboard, "build-folders": _build_folders}[args.command](args)
    except (BuildError, ValidationError, ValueError) as err:
        print(f"catalyst-kb-engine: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
