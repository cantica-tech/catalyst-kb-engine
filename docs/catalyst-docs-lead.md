# Leading catalyst-docs: the brief

The standing brief for whoever leads catalyst-docs (an agent or a person), alongside catalyst's development. The
design is [`design/01-catalyst-docs.md`](design/01-catalyst-docs.md), decided by the owner on 2026-10-25. This
brief says how to carry it out.

## The mission

Build catalyst's central documentation with KBM and this engine, following design 01's phases:

- a public site, in depth, built from the public repositories only;
- an in-depth search for the realm, over every source, private criteria included;
- private criteria feed the search but are never published.

## How to work

- **catalyst governs it.** Work in this repository is journaled in its criterion as it happens (L1). A feature is a
  `REQ-` with `STEP-`s opened as the work goes (SE-L1); a fix is a `BUG-`.
- **One phase at a time**, each shipped through this repository's full cycle: `development`, then `main`, then a
  tag and a GitHub release. Each `REQ-` closes with its phase.
- **Before every push of Python**: `uv run ruff check --no-cache .` and `uv run ruff format --check --no-cache .`
  repo-wide, then the tests. Markdown passes `markdownlint-cli2` with `../standards/.markdownlint-cli2.jsonc`.
- **Show progress on long runs**: a test suite or CI run streams its progress as it goes, never through `tail`.
- **No `Co-Authored-By` trailer** in commits.
- **Never print a secret.** Signing goes through catalyst-users and the local Keycloak, which must be running.

## Boundaries

- **Never publish anything from a private source.** A criterion is private, and so is everything read from it.
- **No new GitHub repository without the owner's yes.** Phase 0 (`cantica-tech/catalyst-docs` and
  `catalyst-docs-criterion`) waits for it. Until then, work on the engine's own phases: the `Criterion` source kind
  and its reader (phase 1), then the realm build and search (phase 2), then incremental builds (phase 3).
- **Stay within catalyst-kb-engine and catalyst-knowledge-base.** A change the kernel (`catalyst`), catalyst-users or
  catalyst-ui needs is written up as a request to the main development session, not made here.
- **Only catalyst**: no repository outside catalyst's fleet (design 01 §4).
- **Ask, don't guess**: a decision that belongs to the owner goes back to them, with a recommendation.

## Reporting

At the end of each phase, and whenever a decision is needed:

- what was done and checked, honestly (L10);
- the results document in catalyst's `docs/results/YYYY-MM-DD-<topic>.md`, ending with "What's left";
- the next phase, or the question blocking it.
