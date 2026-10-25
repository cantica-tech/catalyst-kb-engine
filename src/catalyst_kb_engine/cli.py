"""`catalyst-kb-engine`: `onboard` runs the onboarding workflow with a person at the terminal (`--record` writes it to
the criterion); `read-sources` reads a knowledge base's sources into a private staging directory a build can read;
`build-folders` writes a folders build (`--record` records it); `search` searches a vector build, `mcp` serves that
search as an MCP tool, `evaluate` scores it against an evaluation set (`--record` keeps the score with the build);
`plan` reads a recorded knowledge base back. Records go through catalyst's CLI (`CATALYST_CLI`, else `catalyst`). Exit codes: 0 done, 1 refused or failed,
2 usage."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
from catalyst_kb_engine.record import KbPolicy, read_knowledge_base, read_plan, record_build, record_onboarding
from catalyst_kb_engine.sources.visibility import Projects, SourceError

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


def _read_sources(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.sources.stage import stage, summary

    cli = CatalystCLI(Path(args.project_root))
    overrides = {}
    for given in args.project or []:
        name, sep, directory = given.partition("=")
        if not sep or not name or not directory:
            raise ValueError(f"--project takes <name>=<dir>, not {given!r}")
        overrides[name] = Path(directory).expanduser()
    projects = Projects(Path(args.projects_dir).expanduser() if args.projects_dir else None, overrides)
    staged = stage(
        read_knowledge_base(cli, args.kb),
        Path(args.out),
        projects,
        public_only=args.public_only,
        catalyst=lambda project: CatalystCLI(project, command=cli.command),
        workers=args.workers,
    )
    print(json.dumps(summary(staged), indent=2))
    return 0


def _search(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.search import BuildIndex, Mode, render

    passages = asyncio.run(BuildIndex(Path(args.build)).search(args.question, k=args.k, mode=Mode(args.mode)))
    print(json.dumps([p.record() for p in passages], indent=2) if args.json else render(passages))
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.mcp_server import serve

    serve(Path(args.build))
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.evaluate import evaluate, verification
    from catalyst_kb_engine.search import BuildIndex, load_questions

    score = asyncio.run(evaluate(BuildIndex(Path(args.build)), load_questions(Path(args.questions)), k=args.k))
    if args.record:
        cli = CatalystCLI(Path(args.project_root), command_name="/kb-build")
        text = verification(score, Path(args.questions).name)
        cli.write_section(args.record, "Verification", text, intent="the build's search, scored", tier="build")
    print(json.dumps(score, indent=2))
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


def _build_vectors(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.build.vectors import EmbeddingModel, EmbeddingPolicy, build_vectors

    info = BuildInfo(
        knowledge_base=args.kb,
        build=args.build,
        version=args.version,
        floor=Classification(args.floor),
        ceiling=Classification(args.ceiling or args.floor),
        content_commit=args.content_commit,
    )
    up_to = args.hosted_up_to if args.hosted_up_to == "Local only" else Classification(args.hosted_up_to)
    hosted = args.hosted_model and EmbeddingModel(args.hosted_model, args.hosted_model, args.hosted_model.split(":")[0])
    local = args.local_model and EmbeddingModel(args.local_model, args.local_model, "local")
    policy = EmbeddingPolicy(hosted_up_to=up_to, hosted=hosted or None, local=local or None)
    result = asyncio.run(
        build_vectors(Path(args.repository), Path(args.out), info, policy, max_tokens=args.max_tokens,
                      overlap=args.overlap)
    )  # fmt: skip
    summary = {
        "out": str(result.out),
        "classification": result.classification.value,
        "documents": result.documents,
        "pointers": result.pointers,
        "chunks": result.chunks,
        "left_out": result.left_out,
        "embedding": result.embedding,
    }
    if args.record:
        location = args.location or str(Path(args.out).resolve())
        summary["build"] = record_build(
            CatalystCLI(Path(args.project_root)), info, result, location, f"{args.kb} {args.version}"
        )
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
    r = sub.add_parser("read-sources", help="read a knowledge base's sources into a staging directory (private data)")
    r.add_argument("kb", help="the KB- ID")
    r.add_argument("out", help="the staging directory, new or empty; private whenever a private source is read")
    r.add_argument("--projects-dir", help="the directory holding the sources' checkouts, each under its own name")
    r.add_argument("--project", action="append", help="<name>=<dir>: a checkout elsewhere (repeatable)")
    r.add_argument("--public-only", action="store_true", help="open public sources only (for a public build)")
    r.add_argument("--workers", type=int, default=8, help="parallel catalyst calls per criterion")
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
    v = sub.add_parser("build-vectors", help="write a vector database build of a knowledge base repository")
    v.add_argument("repository", help="the knowledge base repository (docs/, pointers/)")
    v.add_argument("out", help="the build's directory, new or empty")
    v.add_argument("--kb", required=True, help="the KB- ID")
    v.add_argument("--version", required=True)
    v.add_argument("--floor", required=True, choices=levels, help="the knowledge base's Classification")
    v.add_argument("--ceiling", choices=levels, help="the highest classification it may contain (default: --floor)")
    v.add_argument("--hosted-up-to", choices=["Local only", *levels], default="Local only",
                   help="the knowledge base's Hosted embedding up to")  # fmt: skip
    v.add_argument(
        "--local-model", help="a local Pydantic AI embedding model, e.g. sentence-transformers:all-MiniLM-L6-v2"
    )
    v.add_argument(
        "--hosted-model", help="a hosted one, used only within --hosted-up-to, e.g. openai:text-embedding-3-small"
    )
    v.add_argument("--max-tokens", type=int, default=512)
    v.add_argument("--overlap", type=int, default=64)
    v.add_argument("--build", help="the KBUILD- ID, once recorded")
    v.add_argument("--content-commit", help="the repository's commit it is built from")
    v.add_argument("--record", action="store_true", help="record it as a KBUILD- in the criterion, Built")
    v.add_argument("--location", help="with --record: where the build is kept (default: the output directory)")
    modes = ["hybrid", "keyword", "vector"]
    s = sub.add_parser("search", help="search a vector database build: passages citing their sources")
    s.add_argument("question")
    s.add_argument("--build", required=True, help="the vector database build's directory")
    s.add_argument("-k", type=int, default=8, help="how many passages (default 8)")
    s.add_argument("--mode", choices=modes, default="hybrid")
    s.add_argument("--json", action="store_true", help="the passages as JSON")
    m = sub.add_parser("mcp", help="serve a vector build's search as an MCP tool, over stdio")
    m.add_argument("--build", required=True, help="the vector database build's directory")
    e = sub.add_parser("evaluate", help="score a vector build's search against an evaluation set")
    e.add_argument("questions", help="the evaluation set (YAML: questions, each id, question, expect)")
    e.add_argument("--build", required=True, help="the vector database build's directory")
    e.add_argument("-k", type=int, default=10, help="how many passages count (default 10)")
    e.add_argument("--record", metavar="KBUILD", help="write the score into this KBUILD-'s Verification")
    pl = sub.add_parser("plan", help="read a recorded knowledge base back into its onboarding plan")
    pl.add_argument("kb", help="the KB- ID")
    for p in (o, r, b, v, e, pl):
        p.add_argument("--project-root", default=".", help="the catalyst project (default: here)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    logging.basicConfig(level=logging.WARNING, format="catalyst-kb-engine: %(message)s")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        return {
            "onboard": _onboard,
            "read-sources": _read_sources,
            "build-folders": _build_folders,
            "build-vectors": _build_vectors,
            "search": _search,
            "mcp": _mcp,
            "evaluate": _evaluate,
            "plan": _plan,
        }[args.command](args)
    except (BuildError, CatalystError, SourceError, ValidationError, ValueError) as err:
        print(f"catalyst-kb-engine: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
