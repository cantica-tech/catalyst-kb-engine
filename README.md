# catalyst-kb-engine

The engine of catalyst's knowledge base module (KBM): it carries a knowledge base's **onboarding** and its **builds**
out as workflows, and produces what a model reads, **organized markdown folders** or a **vector database**, in open
formats any model can consume without catalyst (KBM's `rr-KB-009`).

- **Workflows** are typed graphs (`pydantic-graph`); the steps that need judgment (which sources, which folders,
  which classification) are proposed by an agent (Pydantic AI, any model, local or hosted) and **decided by a person**.
- **State** is the catalyst criterion's records (`KB-`, `KSOURCE-`, `KBUILD-`, `WORKFLOW-`), journaled; the engine
  keeps none of its own.

Status: in development. The design and the technology research behind it are in the knowledge base module's
`docs/engine-and-onboarding.md`.

## Using it

```sh
uv tool install "catalyst-kb-engine[vectors,openai,search,mcp,serve]"   # search: numpy; mcp, serve: the servers

catalyst-kb-engine onboard "Support KB" --project app --other-module software-engineering   # you decide each step
catalyst-kb-engine onboard "Support KB" … --record --serves <rule IDs> --classification Internal
catalyst-kb-engine plan KB-000001-…                                                     # read it back
catalyst-kb-engine read-sources KB-… <staging dir> --projects-dir ~/sources [--public-only] [--previous <staging>]
catalyst-kb-engine build-folders <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal --record
catalyst-kb-engine build-vectors <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal \
    --local-model ollama:nomic-embed-text [--hosted-model openai:text-embedding-3-small --hosted-up-to Internal] \
    [--embed-input context|text] [--document-prefix "search_document: " --query-prefix "search_query: "] \
    [--previous builds/0.9.0]
catalyst-kb-engine search "who approves an invoice?" --build builds/1.0.0 [-k 8] [--mode hybrid|keyword|vector]
catalyst-kb-engine mcp --build builds/1.0.0                                             # the same, as an MCP tool
catalyst-kb-engine serve --build builds/1.0.0 [--port 8765]                            # over HTTP, to the realm only
catalyst-kb-engine evaluate questions.yaml --build builds/1.0.0 [--record KBUILD-…]     # score it
catalyst-kb-engine export-sources KB-… site/sources.json --projects-dir ~/sources         # its public sources only
catalyst-kb-engine publish-check builds/public --sources site/sources.json               # nothing private in it
catalyst-kb-engine site builds/public _pages --title "…" --intro "…"                      # the site's pages
```

Records go through catalyst's CLI (`CATALYST_CLI`, else `catalyst`), in the project (`--project-root`). A vector
build uses one embedding model: the hosted one only when everything in it is within the knowledge base's
`Hosted embedding up to`, else the local one; with neither allowed, nothing is built. Builds follow the knowledge
base module's `kbm-build/1` format, readable by any model without catalyst.

`read-sources` reads every live source of a knowledge base into a staging directory, in the layout the builds read:
a catalyst criterion (`Kind` `Criterion`) through catalyst's CLI in its project, one document per entity and rule
citing its ID, criterion and status with its own history; a git repository (GitHub, Azure DevOps, or any other host,
given as an `https://`, `ssh://` or `user@host:path` URL) from its checkout, its committed markdown. Each source's
visibility is checked against its host first (on Azure DevOps, its project's; on any other host, it is public only
when git reads it anonymously, with no credential of this machine), and any disagreement stops the read. Every
document from a private source is at least `Internal`, and `--public-only` never opens a private source. The staging
directory holds private data whenever a private source was read: keep it out of any public repository. Checkouts are
found as `<--projects-dir>/<name>`, or given with `--project <name>=<dir>`. GitHub is asked through `gh`, which must
be logged in; Azure DevOps through its REST API, anonymously (a public project answers) or with a personal access token
in `AZURE_DEVOPS_EXT_PAT` (a private project's visibility, read scope). When GitHub or Azure DevOps cannot answer, the same anonymous read
may confirm a public repository. `repository <url>` says a repository URL's host, name, clone URL and visibility, as
JSON, for a script deciding what to read.

What a `.catalystignore` opts out of catalyst (catalyst's `FORMAT.md` §11) is never part of a knowledge base: the
builds skip it in the knowledge base repository, and `read-sources` skips it in a repository source.

`read-sources --history N` also reads each repository source's last N commits, which needs full clones (a shallow
clone is refused). Each document gains a `## History` section with the commits that touched its file, and each
repository a `git-history.md` of its recent commits across all files, each with the files it changed. A commit gives
its date, short hash, author's name and subject, never an e-mail address. History is classified like its repository.

Builds can be incremental. `read-sources --previous <staging>` re-views, in each criterion whose source is unchanged,
only the entities a journal entry since the previous read names or touched, the new ones, and what they cite. Every
other document is carried over; repositories are always re-read. `build-vectors --previous <build>` reuses a chunk's
vector when its exact embedding input was embedded by that build with the same model, input and prefix, and embeds
the rest. Its manifest's `incremental` counts both. By default a chunk is embedded with its document's title and
heading before its text (`--embed-input context`). The manifest records that, and any prefixes; `search` applies the
build's query prefix to each question.

`search` reads a vector build and writes nothing. It merges keywords (SQLite FTS5) and vectors (the question embedded
with the build's own model, from its manifest) by reciprocal rank. Each passage cites its document, heading,
classification and source, and for a criterion document its entity's ID. `mcp` serves the same search over stdio,
for an agent on the machine that keeps the build. `evaluate` runs an evaluation set (YAML: `questions`, each with an
`id`, a `question` and `expect`, the entity IDs or document paths a good answer cites) in every mode. It reports
recall at k and mean reciprocal rank, and names only the missed questions' IDs. `--record` writes the score into the
build's `KBUILD-` `Verification`. An evaluation set drawn from private sources is private: keep it in the knowledge
base's criterion.

A public site is published from a public build. `export-sources` writes a knowledge base's public sources list:
each source's visibility is confirmed on its host, and a private one is never written. `read-sources --sources <list>`
reads from that list where the criterion is not available, such as a publishing service's runner. A list read without
`--public-only` may also name private sources (recorded `Private`, or with no visibility, which their host then tells):
their documents are at least `Internal`, and `publish-check` refuses such a list. `publish-check`
refuses a build holding any document whose source the list does not name, or that is not `Public`. `site` makes the
pages: the knowledge base's own pages (`docs/guide/`) as written, and one reference page per document citing its file.
catalyst-docs builds its site this way in GitHub Actions and deploys it to Pages, with no branch keeping it.

`serve` answers `GET /search?q=&k=&mode=` (and `GET /me`) only to a bearer token the realm's provider vouches for,
through catalyst-users' FastAPI integration: active introspection, the realm's issuer, the `catalyst-api` audience. Any
other token is refused (401), and a provider out of reach refuses too (503). Its settings are catalyst-users'
environment (`CATALYST_USERS_SERVER`, `CATALYST_USERS_REALM`, `CATALYST_USERS_API_CLIENT_SECRET`, …); it never logs or
returns a token or a secret, serves no API description, and listens on this machine only unless `--host` says
otherwise.

## Development

```sh
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest -q
```
