# 01 — catalyst-docs: catalyst's central documentation, public in depth, searchable in depth by the realm

> **Status: decided (owner, 2026-10-25)**, §10's four questions as proposed. The owner's request: a central documentation of catalyst, started in depth and
> public, with an in-depth search of what it covers, built by KBM over the whole fleet of criteria describing
> catalyst. The owner's four answers are in §2, §10's in §10. Builds on KBM's
> `docs/engine-and-onboarding.md` and on catalyst's designs `30` (visibility) and `32` (project membership).

## 1. The request

- **One central documentation of catalyst**, in depth, for the public.
- **An in-depth search** of everything it covers, drawing on all of catalyst's criteria, private ones included.
- Built by the knowledge-base module (KBM) and this engine: catalyst's own documentation is KBM's proof of maturity.

## 2. The owner's answers (2026-10-25)

1. **A project of its own: `catalyst-docs`**, its criterion running KBM alone (KB-L2: alone, or beside any module).
2. **The search is for the realm only**, for now.
3. **Private criteria feed it but are never made public.** Their data is used to build and search, never published.
   What is private may change, and every build follows the current classification.
4. **GitHub Pages** hosts the public site, for now.

## 3. Today: what is ready, what is missing

Ready:

- onboarding records a knowledge base's four decisions (`KB-`);
- a folders build and a vector build, readable by any model (`kbm-build/1`), checked with `nomic-embed-text`;
- a classification ceiling per build: a document above it is never written;
- one knowledge base, many sources (`KSOURCE-`).

Missing, each one a phase (§9):

| # | Gap                                                                                                       |
| - | --------------------------------------------------------------------------------------------------------- |
| 1 | Nothing reads a criterion: builds read a repository of markdown documents only                            |
| 2 | No search: a vector build is files, with no command, API or MCP tool to query it                          |
| 3 | No incremental build: `Dynamic` should reprocess only what changed; every build starts over               |
| 4 | No publishing: a folders build is not a site                                                              |
| 5 | No classification on a criterion's entities (design `30` is not built): a source's level is all there is  |
| 6 | No default embedding model (KBM's `docs/engine-and-onboarding.md` §6, question 3)                          |
| 7 | Never run at this scale: the one real build was catalyst-users-kb's (since deleted)                                       |

## 4. The fleet

As of 2026-10-25, under `cantica-tech`. **Every criterion repository is private**, so by §2.3 nothing read from a
criterion is ever public: the public site is built from the public repositories alone.

| Source                                   | Kind       | Visibility | Public site | Realm search |
| ---------------------------------------- | ---------- | ---------- | ----------- | ------------ |
| `catalyst` (kernel, framework, designs)  | repository | public     | yes         | yes          |
| `catalyst-software-engineering`          | repository | public     | yes         | yes          |
| `catalyst-knowledge-base`                | repository | public     | yes         | yes          |
| `catalyst-kb-engine`                     | repository | public     | yes         | yes          |
| `catalyst-users`                         | repository | public     | yes         | yes          |
| `catalyst-ui`                            | repository | public     | yes         | yes          |
| `standards`                              | repository | public     | yes         | yes          |
| `criterion` (catalyst's own)             | criterion  | private    | **never**   | yes          |
| `catalyst-users-criterion`               | criterion  | private    | **never**   | yes          |
| `catalyst-ui-criterion`                  | criterion  | private    | **never**   | yes          |
| `catalyst-knowledge-base-criterion`      | criterion  | private    | **never**   | yes          |
| `catalyst-kb-engine-criterion`           | criterion  | private    | **never**   | yes          |

About 1,370 markdown files in the five criteria, plus the repositories' documentation. Volume is not the difficulty.
`catalyst-users-kb` and `catalyst-risk-management` (both deleted 2026-10-25) and every repository outside catalyst stay out.

## 5. The model

### 5.1 The project

- A repository `cantica-tech/catalyst-docs` (public: it holds what is published, and the site's sources), its
  criterion `cantica-tech/catalyst-docs-criterion` (private, like every criterion), KBM alone in it.
- **One knowledge base**, `KB-000001` "catalyst", with one `KSOURCE-` per source of §4, each with its visibility.
- **Two builds** of it, never one build filtered afterwards:

| Build      | Reads                      | Ceiling     | Target                       | For                    |
| ---------- | -------------------------- | ----------- | ---------------------------- | ---------------------- |
| **public** | the public sources only    | `Public`    | folders, then the site       | everyone (Pages)       |
| **realm**  | every source               | the highest | folders and vector database  | the realm's search     |

The public build never reads a private source, so no private text can reach it, not even through a summary or a
generated page.

### 5.2 A criterion as a source

A new `KSOURCE-` kind, `Criterion`: another project's criterion, read through catalyst's CLI (`catalyst list`, `view
--json`, the spec's schemas), never by reading its files. The reader turns:

- each entity (rule, requirement, design decision, bug, workflow…) into a document citing its ID, its criterion and
  its status;
- the journal into a history per entity (who changed it, when, why), never the content of other entities.

Each document carries its source's classification as a floor (§6).

### 5.3 Two layers of documentation

- **The reference**: generated from the sources, one page per entity, rule or document, always current.
- **The guide**: written pages (concepts, getting started, the kernel, the modules, people and IAM, knowledge bases,
  the UI), drafted with the realm search and reviewed by a person before they land (L4: humans decide). A guide page
  cites the reference pages it rests on; a public guide page may cite only public ones.

## 6. Private stays private, as it changes

- **A source's visibility is a floor.** Every document read from a private source is at least `Internal`, whatever its
  own front matter says, until design `30` gives entities a classification of their own; then the higher of the two.
- **A change of visibility is followed by the next build.** A source made private: its documents leave the next
  public build. A source made public: they join it. Each build re-reads the sources' visibility (`KSOURCE-` and
  GitHub's), and refuses to run when the two disagree.
- **The site keeps no history of its own.** It is published by GitHub Actions' Pages deployment, not a `gh-pages`
  branch, so a page withdrawn from the site leaves no copy in a public branch.
- **A check before each publication**: the public build's manifest lists each document's source; publication refuses
  any whose source is not public.

## 7. The realm's search

- **A command and an MCP tool**: `catalyst-kb-engine search "<question>"` and the same as a tool, answering with
  passages, each citing its source, document and, for a criterion, the entity ID.
- **Hybrid**: keyword search (SQLite FTS5, in the standard library) and vector search over the realm build, merged.
- **Realm only**: served behind catalyst-users' FastAPI integration, which accepts only the realm's tokens. Read
  locally, the realm build stays in its own private storage, never in the public repository.
- **Measured**: a set of questions with the answers expected (for example 50, across the fleet), run after each
  build, its score kept with the build.

## 8. Incremental builds

`Dynamic` means each build reprocesses only what changed: a document whose source content hash is unchanged keeps
its chunks and vectors; a removed one leaves; the manifest says which were reused. A full rebuild remains available.

## 9. Phases

| Phase | Delivers                                                                                                   | Done when                                                       |
| ----- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 0     | `catalyst-docs` and its criterion, KBM alone; `KB-000001` onboarded; one `KSOURCE-` per source of §4         | `catalyst check` passes in the new criterion                    |
| 1     | The `Criterion` source kind and its reader; visibility floors (§6)                                         | the five criteria read, every document citing its entity         |
| 2     | The realm build; `search` and its MCP tool; the question set                                               | the question set answered, its score recorded                   |
| 3     | Incremental builds                                                                                         | a rebuild after one change reprocesses only that change          |
| 4     | The guide's outline and first pages, drafted and reviewed                                                   | the outline approved by the owner                               |
| 5     | The public build; the site; Pages through Actions; the publication check                                   | the site live, holding nothing from a private source             |
| 6     | The search served to the realm, behind catalyst-users                                                      | a token from outside the realm refused                          |

Gaps 5 and 7 close with phases 1 and 2 (source floors, then the fleet's real build); gap 6 is closed by §10.3.

## 10. Decided (owner, 2026-10-25)

1. **Whose search results**: every person of the realm sees results from every criterion for now; only from the
   criteria they are members of once designs `30` and `32` are built.
2. **The site's generator**: MkDocs with Material (Python, markdown-native, search built in).
3. **The default embedding model**: `nomic-embed-text`, local: it stays within every allowance, and the realm build
   holds private data. A hosted model only when one is configured, up to a knowledge base's allowance.
4. **The site's address**: `cantica-tech.github.io/catalyst-docs`, for now.
