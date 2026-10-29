"""`catalyst-kb-engine`: `onboard` runs the onboarding workflow with a person at the terminal (`--record` writes it to
the criterion); `read-sources` reads a knowledge base's sources into a private staging directory a build can read;
`build-folders` writes a folders build (`--record` records it); `search` searches a vector build, `mcp` serves that
search as an MCP tool, `evaluate` scores it against an evaluation set (`--record` keeps the score with the build);
`export-sources`, `publish-check` and `site` publish a public build; `repository` tells a git repository URL's host
(GitHub, Azure DevOps, any other), name and visibility; `serve` serves the search to the realm, behind
catalyst-users; `plan` reads a recorded knowledge base back. Records go through catalyst's CLI (`CATALYST_CLI`, else
`catalyst`). Exit codes: 0 done, 1 refused or failed, 2 usage."""

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


def _projects(args: argparse.Namespace) -> Projects:
    overrides = {}
    for given in args.project or []:
        name, sep, directory = given.partition("=")
        if not sep or not name or not directory:
            raise ValueError(f"--project takes <name>=<dir>, not {given!r}")
        overrides[name] = Path(directory).expanduser()
    return Projects(Path(args.projects_dir).expanduser() if args.projects_dir else None, overrides)


def _export_sources(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.publish import export_sources

    listing = export_sources(read_knowledge_base(CatalystCLI(Path(args.project_root)), args.kb), _projects(args))
    Path(args.out).write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": args.out, "public_sources": len(listing["sources"])}, indent=2))
    return 0


def _repository(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.sources.visibility import hosted_visibility, repository

    found = repository(args.url)
    if found is None:
        raise ValueError(f"{args.url} is not a git repository URL (https://, ssh:// or user@host:path)")
    visibility = hosted_visibility(found.path)
    print(json.dumps({
        "host": found.host, "repository": found.path, "name": found.name, "clone_url": found.clone_url,
        "web_url": found.web_url, "visibility": visibility.value if visibility else None,
    }, indent=2))  # fmt: skip
    return 0


def _publish_check(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.publish import load_sources, publish_check

    checked = publish_check(Path(args.build), load_sources(Path(args.sources)))
    print(json.dumps({"build": args.build, "documents": checked, "publishable": True}, indent=2))
    return 0


def _site(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.site import make_site

    site = make_site(Path(args.build), Path(args.out), title=args.title, intro=args.intro)
    print(json.dumps({"out": str(site.out), "guide": site.guide, "reference": site.reference}, indent=2))
    return 0


def _record_site(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.published import record_site

    done = record_site(CatalystCLI(Path(args.project_root)), args.site)
    print(json.dumps({"recorded": done.recorded, "known": done.known, "superseded": done.superseded}, indent=2))
    return 0


def _read_sources(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.sources.stage import stage, summary

    cli = CatalystCLI(Path(args.project_root))
    projects = _projects(args)
    if args.sources:
        from catalyst_kb_engine.publish import load_sources

        kb = load_sources(Path(args.sources), public_only=args.public_only)
        if kb.id != args.kb:
            raise ValueError(f"{args.sources} is the public sources list of {kb.id}, not {args.kb}")
    else:
        kb = read_knowledge_base(cli, args.kb)
    staged = stage(
        kb,
        Path(args.out),
        projects,
        public_only=args.public_only,
        catalyst=lambda project: CatalystCLI(project, command=cli.command),
        workers=args.workers,
        previous=Path(args.previous) if args.previous else None,
        history=args.history,
    )
    print(json.dumps(summary(staged), indent=2))
    return 0


def _search(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.search import BuildIndex, Mode, render

    index = BuildIndex(Path(args.build))
    passages = asyncio.run(index.search(args.question, k=args.k, mode=Mode(args.mode), per_document=args.per_document))
    print(json.dumps([p.record() for p in passages], indent=2) if args.json else render(passages))
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.mcp_server import serve

    serve(Path(args.build))
    return 0


def _serve(args: argparse.Namespace) -> int:
    from catalyst_kb_engine.serve import serve

    serve(Path(args.build), args.host, args.port)
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
                      overlap=args.overlap, embedding_input=args.embed_input, document_prefix=args.document_prefix,
                      query_prefix=args.query_prefix, previous=Path(args.previous) if args.previous else None)
    )  # fmt: skip
    summary = {
        "out": str(result.out),
        "classification": result.classification.value,
        "documents": result.documents,
        "pointers": result.pointers,
        "chunks": result.chunks,
        "left_out": result.left_out,
        "embedding": result.embedding,
        **({"incremental": result.incremental} if result.incremental is not None else {}),
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
    r.add_argument("--previous", help="an earlier staging directory: re-view only what the journal says moved")
    r.add_argument(
        "--sources",
        help="read the sources a sources list names (export-sources' public one, or one naming private sources "
        "without --public-only), not the KB-'s",
    )
    r.add_argument("--history", type=int, default=0, metavar="N",
                   help="also read each repository's last N commits: per document, and its log (needs full clones)")  # fmt: skip
    x = sub.add_parser(
        "export-sources", help="write a knowledge base's public sources list, each confirmed on its host"
    )
    x.add_argument("kb", help="the KB- ID")
    x.add_argument("out", help="the list's file (JSON); it names public sources only")
    x.add_argument("--projects-dir", help="the directory holding the sources' checkouts, each under its own name")
    x.add_argument("--project", action="append", help="<name>=<dir>: a checkout elsewhere (repeatable)")
    rp = sub.add_parser("repository", help="a git repository URL (https, ssh): its host, name and visibility")
    rp.add_argument("url", help="https or ssh; Azure DevOps reads AZURE_DEVOPS_EXT_PAT for a private project")
    pc = sub.add_parser("publish-check", help="refuse to publish a build holding anything not public")
    pc.add_argument("build", help="the public folders build")
    pc.add_argument("--sources", required=True, help="the public sources list it was read from")
    st = sub.add_parser("site", help="a public folders build as a site's pages (home, guide, reference)")
    st.add_argument("build", help="the public folders build, checked by publish-check")
    st.add_argument("out", help="the pages' directory, new or empty")
    st.add_argument("--title", default="Documentation", help="the home page's title")
    st.add_argument("--intro", default="", help="the home page's opening paragraph")
    rs = sub.add_parser("record-site", help="record the builds a site publishes, from its manifests, as KBUILD-s")
    rs.add_argument("site", help="the site's https URL, e.g. https://<owner>.github.io/<repository>/")
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
    v.add_argument("--embed-input", choices=["context", "text"], default="context",
                   help="what each chunk is embedded as: its title and heading before its text (default), or its text")  # fmt: skip
    v.add_argument("--document-prefix", default="", help="before each chunk, e.g. 'search_document: ' for nomic")
    v.add_argument("--query-prefix", default="", help="recorded for searches, e.g. 'search_query: ' for nomic")
    v.add_argument("--previous", help="a previous vector build: reuse every vector whose exact input is unchanged")
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
    s.add_argument(
        "--per-document", type=int, default=1, help="at most this many passages of one document (default 1; 0: any)"
    )
    s.add_argument("--mode", choices=modes, default="hybrid")
    s.add_argument("--json", action="store_true", help="the passages as JSON")
    m = sub.add_parser("mcp", help="serve a vector build's search as an MCP tool, over stdio")
    m.add_argument("--build", required=True, help="the vector database build's directory")
    sv = sub.add_parser(
        "serve",
        help="serve a vector build's search over HTTP, to the realm only (catalyst-users)",
        epilog="Settings: catalyst-users' environment (CATALYST_USERS_SERVER, CATALYST_USERS_API_CLIENT_SECRET, ...); "
        "for a build embedded with an ollama: model, OLLAMA_BASE_URL (default http://localhost:11434/v1).",
    )
    sv.add_argument("--build", required=True, help="the vector database build's directory")
    sv.add_argument("--host", default="127.0.0.1", help="the address to listen on (default: this machine only)")
    sv.add_argument("--port", type=int, default=8765)
    e = sub.add_parser("evaluate", help="score a vector build's search against an evaluation set")
    e.add_argument("questions", help="the evaluation set (YAML: questions, each id, question, expect)")
    e.add_argument("--build", required=True, help="the vector database build's directory")
    e.add_argument("-k", type=int, default=10, help="how many passages count (default 10)")
    e.add_argument("--record", metavar="KBUILD", help="write the score into this KBUILD-'s Verification")
    pl = sub.add_parser("plan", help="read a recorded knowledge base back into its onboarding plan")
    pl.add_argument("kb", help="the KB- ID")
    for p in (o, r, x, b, v, e, pl, rs):
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
            "export-sources": _export_sources,
            "repository": _repository,
            "publish-check": _publish_check,
            "site": _site,
            "record-site": _record_site,
            "build-folders": _build_folders,
            "build-vectors": _build_vectors,
            "search": _search,
            "mcp": _mcp,
            "serve": _serve,
            "evaluate": _evaluate,
            "plan": _plan,
        }[args.command](args)
    except (BuildError, CatalystError, SourceError, ValidationError, ValueError) as err:
        print(f"catalyst-kb-engine: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
