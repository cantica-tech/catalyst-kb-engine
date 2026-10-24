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

## Development

```sh
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest -q
```
