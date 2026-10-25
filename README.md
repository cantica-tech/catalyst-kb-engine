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
uv tool install "catalyst-kb-engine[vectors,openai,search,mcp]"   # search: numpy; mcp: the MCP server

catalyst-kb-engine onboard "Support KB" --project app --other-module software-engineering   # you decide each step
catalyst-kb-engine onboard "Support KB" … --record --serves <rule IDs> --classification Internal
catalyst-kb-engine plan KB-000001-…                                                     # read it back
catalyst-kb-engine read-sources KB-… <staging dir> --projects-dir ~/sources [--public-only]   # its sources, staged
catalyst-kb-engine build-folders <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal --record
catalyst-kb-engine build-vectors <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal \
    --local-model ollama:nomic-embed-text [--hosted-model openai:text-embedding-3-small --hosted-up-to Internal]
catalyst-kb-engine search "who approves an invoice?" --build builds/1.0.0 [-k 8] [--mode hybrid|keyword|vector]
catalyst-kb-engine mcp --build builds/1.0.0                                             # the same, as an MCP tool
catalyst-kb-engine evaluate questions.yaml --build builds/1.0.0 [--record KBUILD-…]     # score it
```

Records go through catalyst's CLI (`CATALYST_CLI`, else `catalyst`), in the project (`--project-root`). A vector
build uses one embedding model: the hosted one only when everything in it is within the knowledge base's
`Hosted embedding up to`, else the local one; with neither allowed, nothing is built. Builds follow the knowledge
base module's `kbm-build/1` format, readable by any model without catalyst.

`read-sources` reads every live source of a knowledge base into a staging directory, in the layout the builds read:
a catalyst criterion (`Kind` `Criterion`) through catalyst's CLI in its project, one document per entity and rule
citing its ID, criterion and status with its own history; a GitHub repository from its checkout, its committed
markdown. Each source's visibility is checked against GitHub first, and any disagreement stops the read. Every
document from a private source is at least `Internal`, and `--public-only` never opens a private source. The staging
directory holds private data whenever a private source was read: keep it out of any public repository. Checkouts are
found as `<--projects-dir>/<name>`, or given with `--project <name>=<dir>`; `gh` must be logged in.

`search` reads a vector build and writes nothing. It merges keywords (SQLite FTS5) and vectors (the question embedded
with the build's own model, from its manifest) by reciprocal rank. Each passage cites its document, heading,
classification and source, and for a criterion document its entity's ID. `mcp` serves the same search over stdio,
for an agent on the machine that keeps the build. `evaluate` runs an evaluation set (YAML: `questions`, each with an
`id`, a `question` and `expect`, the entity IDs or document paths a good answer cites) in every mode. It reports
recall at k and mean reciprocal rank, and names only the missed questions' IDs. `--record` writes the score into the
build's `KBUILD-` `Verification`. An evaluation set drawn from private sources is private: keep it in the knowledge
base's criterion.

## Development

```sh
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest -q
```
