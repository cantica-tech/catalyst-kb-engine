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
uv tool install "catalyst-kb-engine[vectors,openai]"   # vectors: pyarrow; openai: Ollama and OpenAI-compatible models

catalyst-kb-engine onboard "Support KB" --project app --other-module software-engineering   # you decide each step
catalyst-kb-engine onboard "Support KB" … --record --serves <rule IDs> --classification Internal
catalyst-kb-engine plan KB-000001-…                                                     # read it back
catalyst-kb-engine build-folders <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal --record
catalyst-kb-engine build-vectors <kb repo> builds/1.0.0 --kb KB-… --version 1.0.0 --floor Internal \
    --local-model ollama:nomic-embed-text [--hosted-model openai:text-embedding-3-small --hosted-up-to Internal]
```

Records go through catalyst's CLI (`CATALYST_CLI`, else `catalyst`), in the project (`--project-root`). A vector
build uses one embedding model: the hosted one only when everything in it is within the knowledge base's
`Hosted embedding up to`, else the local one; with neither allowed, nothing is built. Builds follow the knowledge
base module's `kbm-build/1` format, readable by any model without catalyst.

## Development

```sh
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest -q
```
