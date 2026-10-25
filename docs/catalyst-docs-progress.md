# catalyst-docs: progress and handoff

The handoff log of the catalyst-docs lead. Read it with [`catalyst-docs-lead.md`](catalyst-docs-lead.md) (the brief)
and [`design/01-catalyst-docs.md`](design/01-catalyst-docs.md) (the design). The second lead session (2026-10-25)
shipped KBM 0.6.0 and phases 0 to 2.

## State of each phase

| Phase | State                                                        | Records                                                    |
| ----- | ------------------------------------------------------------ | ---------------------------------------------------------- |
| KBM   | **done**: knowledge-base 0.6.0 released, in the distribution repo | `REQ-000002-I3JORbi9` (KBM's criterion, Completed)          |
| 0     | **done**: both repositories, `KB-000002-erFhHt6m` `Active`      | the catalyst-docs criterion                                |
| 1     | **done**: catalyst-kb-engine 0.4.0, `read-sources`             | `REQ-000004-7TE7wuaB` (the engine's criterion)              |
| 2     | **done**: catalyst-kb-engine 0.5.0, `search`, `mcp`, `evaluate` | `REQ-000005-7TE7wuaB`; catalyst-docs' `KBUILD-000001-erFhHt6m` |
| 3     | next                                                         | none yet                                                   |
| 4–6   | not started                                                  | none yet                                                   |

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
- **The realm build 0.1.0** (`KBUILD-000001-erFhHt6m`, `Built`): 913 documents, 6,791 chunks, `nomic-embed-text`
  local, in `~/.catalyst/projects/catalyst-docs/realm/builds/0.1.0`. `realm/run-0.1.0.sh` there rebuilds it.
- **The evaluation set**: 52 questions in the catalyst-docs criterion,
  `knowledge-bases/evaluations/KB-000002-erFhHt6m.yaml`. The first score at k 10: hybrid recall 0.712 (MRR 0.389),
  keyword 0.673, vector 0.635.

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
- **Raising the score**, two candidates, each needing a rebuild:
  - embed each chunk with its document's title and heading, not its text alone, since short rules lose their title;
  - use `nomic-embed-text`'s task prefixes (`search_document:`, `search_query:`), recorded in the manifest.

  Measure each against the evaluation set before keeping it.
- **A vector build of the realm takes about 25 minutes** on this machine's CPU. Incremental builds (phase 3) re-embed
  only changed documents.
- **Extras**: `search` (numpy, pyarrow) and `mcp` (mcp 2.x, where `FastMCP` is now `MCPServer`).
- **Local models**: Ollama runs `nomic-embed-text`, `llama3.2:3b` and `codestral`.

## The exact next step

Phase 3: incremental builds. A rebuild after one change reprocesses only that change. Reuse each unchanged
document's chunks and vectors by its content hash; re-view only the entities whose journal moved. The manifest says
which were reused. Open a `REQ-` in the engine's criterion first.

## Open for the owner

- **catalyst-docs' uncommitted files** (`KB.md`, `docs/user-generated/project-map.md`) are another session's, waiting
  on the owner's commit ask. The same goes for the catalyst-docs criterion's unshared entries (the two retirements and
  the Policy edit). The realm build's record and the evaluation set are unshared there too: a `share push` would
  publish all of them together, so it waits for the owner.
