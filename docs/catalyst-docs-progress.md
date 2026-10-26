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
| 6     | **built** (engine 0.9.0); the live check waits for the owner     | `REQ-000010-7TE7wuaB` (Active), `STEP-000015-7TE7wuaB`        |

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
- **What still misses**: 11 of 52 questions in hybrid mode (0.788 at k 10, MRR 0.536), since 0.10.0 weights keyword
  matches in a chunk's title 5 and heading 3 against 1 in its text. Measure any further change the same way.
- **Extras**: `search` (numpy, pyarrow) and `mcp` (mcp 2.x, where `FastMCP` is now `MCPServer`).
- **Local models**: Ollama runs `nomic-embed-text`, `llama3.2:3b` and `codestral`.

## The exact next step

Phase 6's live check, the last step of design 01, with the owner. catalyst-kb-engine 0.9.0's `serve` is built and
tested offline (`tests/test_serve.py`, with catalyst-users' own token checks). The live check needs the local realm's
`catalyst-api` secret, which only the owner supplies:

```sh
export CATALYST_USERS_SERVER=http://localhost:8080 CATALYST_USERS_API_CLIENT_SECRET=…   # the owner's
catalyst-kb-engine serve --build ~/.catalyst/projects/catalyst-docs/realm/builds/0.2.1 &
curl -s -H "Authorization: Bearer $(catalyst-users token --system)" localhost:8765/me      # the realm: 200
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <a token from another realm>" localhost:8765/me  # 401
```

Use the same host (`localhost` or `127.0.0.1`) for the token and the service: Keycloak builds its issuer from it. Then
`REQ-000010-7TE7wuaB` completes, and design 01 is done.

## Open for the owner

- **The reference includes test fixtures** (for example the UI repository's sample criterion under
  `src/test/fixtures/`): a repository source takes all its committed markdown. A source's import could name what it
  draws on, or the repositories could opt fixtures out with `.catalystignore`.
- **The public build is not recorded as a `KBUILD-`**: Actions cannot reach the private criterion. Its manifest is
  published with the site (`manifest.json`).
- catalyst-docs' `development` has another session's commit (a project map; `KB.md` updated), not yet merged to
  `main`.
