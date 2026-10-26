# catalyst-docs: progress and handoff

The handoff log of the catalyst-docs lead. Read it with [`catalyst-docs-lead.md`](catalyst-docs-lead.md) (the brief)
and [`design/01-catalyst-docs.md`](design/01-catalyst-docs.md) (the design). The second lead session (2026-10-25)
shipped KBM 0.6.0 and 0.6.1, and phases 0 to 5.

## State of each phase

| Phase | State                                                        | Records                                                    |
| ----- | ------------------------------------------------------------ | ---------------------------------------------------------- |
| KBM   | **done**: knowledge-base 0.6.0 released, in the distribution repo | `REQ-000002-I3JORbi9` (KBM's criterion, Completed)          |
| 0     | **done**: both repositories, `KB-000002-erFhHt6m` `Active`      | the catalyst-docs criterion                                |
| 1     | **done**: catalyst-kb-engine 0.4.0, `read-sources`             | `REQ-000004-7TE7wuaB` (the engine's criterion)              |
| 2     | **done**: catalyst-kb-engine 0.5.0, `search`, `mcp`, `evaluate` | `REQ-000005-7TE7wuaB`; catalyst-docs' `KBUILD-000001-erFhHt6m` |
| 3     | **done**: catalyst-kb-engine 0.6.0, `--previous` reads and builds | `REQ-000006-7TE7wuaB`, `REQ-000007-7TE7wuaB`; `KBUILD-000003-erFhHt6m` |
| 4     | **done**: the guide's twelve pages, each approved by the owner  | catalyst-docs' `GUIDE-OUTLINE.md`, `docs/guide/`            |
| 5     | **done**: the public site, live, built by Actions (engine 0.8.0) | `REQ-000009-7TE7wuaB`; catalyst-docs' `pages.yml`           |
| 6     | **in progress**: `serve` written, tests and live check to do   | `REQ-000010-7TE7wuaB`, `STEP-000015-7TE7wuaB`                |

## What exists

- **KBM 0.6.0**: `KSOURCE` has `Kind` (`Repository` / `Folder` / `Site` / `Criterion`) and `Visibility` (`Public` /
  `Private`); a private source's documents are at least `Internal` (`kbm-MODEL-000002-I3JORbi9`, 🟡 until the engine's
  phase 1 is released).
- **`cantica-tech/catalyst-docs`** (public), checked out next to the other repositories, branches `development` and
  `main`. Its criterion is `cantica-tech/catalyst-docs-criterion` (private), running KBM alone.
- **`KB-000002-erFhHt6m` "catalyst"**. It is number 2 because an earlier journal entry named `KB-000001` before it
  existed, and IDs are never reused. It serves `kn-DOCS-000001-erFhHt6m`. Its fields: classification `Public`, default
  `Internal`, `Local only`, 7 days, `Reflective`, `Documents`, `Dynamic`, `Vector database`, curator Olivier Steck.
- **Its sources**: 7 public repositories (`KSOURCE-000001` to `000007`) and the five criteria (`000009` to `000013`):
  catalyst, catalyst-users, catalyst-ui, catalyst-knowledge-base and catalyst-kb-engine. `000008` and `000014` are
  retired, since catalyst-users-kb was deleted at the owner's request.
- **The engine's `read-sources`** stages a knowledge base's live sources in the `docs/` layout the builds read.
- **The realm build 0.2.1** (`KBUILD-000003-erFhHt6m`, `Built`; 0.1.0 and 0.2.0 superseded): 931 documents, 6,925
  chunks, `nomic-embed-text` local, each chunk embedded with its title and heading and the model's prefixes. It is in
  `~/.catalyst/projects/catalyst-docs/realm/builds/0.2.1`, staged from `realm/sources/0.2.1` (with `read.json`).
- **The evaluation set**: 52 questions in the catalyst-docs criterion,
  `knowledge-bases/evaluations/KB-000002-erFhHt6m.yaml`. Scores at k 10 (hybrid recall, MRR): 0.1.0, 0.712, 0.389;
  with title and heading, 0.750, 0.507; with the prefixes too (0.2.1), 0.769, 0.500.

## Decided by the owner (2026-10-25)

- The repositories, and onboarding: the rule's text, default `Internal`, 7 days, and the other fields as proposed.
- **The evaluation set** (the realm search's questions and expected answers) lives in the catalyst-docs criterion.
- KBM releases go to the distribution repository as well.

## Findings for phase 3 and beyond

- **A full read takes about 2.5 minutes**, CPU-bound: each `catalyst view` is a new Python process, about 0.8 s of CPU.
  Phase 3's incremental builds are the remedy: re-view only the entities whose journal moved since the last read.
  `list all` is cheap; compare each entity's last journal timestamp with the previous manifest's.
- **The full read's size**: 906 documents, 636 of them from criteria, and a folders build of them holds all 906.
  Counts only, since the output is private.
- **Roadmap rows** (`RM-`): `list all` lists them, but `view` refuses them. That's 59 rows across catalyst's and the
  UI's criteria. They are left out and counted, and this is reported to the main session as a kernel item.
- **Repositories are read from their local checkout's tracked files.** A public build should read the commit on
  GitHub's default branch instead, so unpushed work never reaches the site (phase 5).
- **The realm build's home**: private local storage, outside any repository, for example
  `~/.catalyst/projects/catalyst-docs/realm/`. That is beside the criterion, never in it, since the criterion is
  shared through git.
- **Rebuilding the realm** is now cheap. Run `read-sources --previous <last staging>` (18 seconds), then
  `build-vectors --previous <last build>` with `--embed-input context --document-prefix "search_document: "
  --query-prefix "search_query: "` (seconds when little changed). A full vector build takes about 46 minutes.
- **What still misses**: 12 of 52 questions in hybrid mode. Keyword search is unchanged at 0.673, so better keyword
  ranking (for example weighting titles) is the next lever. Measure it the same way.
- **Extras**: `search` (numpy, pyarrow) and `mcp` (mcp 2.x, where `FastMCP` is now `MCPServer`).
- **Local models**: Ollama runs `nomic-embed-text`, `llama3.2:3b` and `codestral`.

## The exact next step

Phase 6, the last of design 01: the realm's search served behind catalyst-users, so a token from outside the realm is
refused (`eng-SEARCH-000003-7TE7wuaB`, `REQ-000010-7TE7wuaB`, `STEP-000015-7TE7wuaB`). On `development`, uncommitted
but journaled:

- `src/catalyst_kb_engine/serve.py`: a FastAPI app, `GET /search?q=&k=&mode=` and `GET /me`, both behind catalyst-users'
  `KeycloakAuth` (active introspection, the realm's issuer, the `catalyst-api` audience; 401, 403, 503). Settings come
  from `CATALYST_USERS_*` only. The module has no `from __future__ import annotations`, on purpose: FastAPI resolves
  the annotations, and `Identity` and `realm` exist only inside `app()`.
- `cli.py`: `catalyst-kb-engine serve --build <dir> [--host 127.0.0.1] [--port 8765]`.
- `pyproject.toml`: the `serve` extra (catalyst-users 0.7.0 from git, FastAPI, uvicorn); catalyst-users and httpx in the
  dev group. ruff and pyright are clean.

To do, in order:

1. **Offline tests** (`tests/test_serve.py`): build `KeycloakAuth(oidc=…)` from catalyst-users' real `OIDCClient`
   (`Settings(server_url=…, api_client_secret="test")`) with only `introspect` replaced, so its own `accepts` decides.
   Cover no token, an inactive token, another realm's issuer (`iss` of another realm: the done-when), another
   audience, an expired one (401); `introspect` raising `ProviderUnavailableError` (503); a realm token (200, passages,
   using the hand-made build of `tests/test_search.py` and its `axis_embed`). Use FastAPI's `TestClient`.
2. README, rule to ✅, step and requirement closed, version 0.9.0, release, share the criterion.
3. **The live check, with the owner**: the service needs the `catalyst-api` client's secret, which Keycloak generated
   for the local realm. Reading it was refused as credential exploration, rightly: the owner supplies it
   (`CATALYST_USERS_API_CLIENT_SECRET`) when running the service. Then a realm token (`catalyst-users token --system`)
   answers 200 on `/me`, and a token from outside the realm is refused 401.

## Open for the owner

- **The reference includes test fixtures** (for example the UI repository's sample criterion under
  `src/test/fixtures/`): a repository source takes all its committed markdown. A source's import could name what it
  draws on, or the repositories could opt fixtures out with `.catalystignore`.
- **The public build is not recorded as a `KBUILD-`**: Actions cannot reach the private criterion. Its manifest is
  published with the site (`manifest.json`).
- catalyst-docs' `development` has another session's commit (a project map; `KB.md` updated), not yet merged to
  `main`.
