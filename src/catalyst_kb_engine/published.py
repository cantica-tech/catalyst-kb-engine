"""A published build's record (`eng-PUBLISH-000003`): a site publishes its builds' manifests where a publishing
service, which cannot reach the private criterion, put them; `record-site` reads them back on the curator's machine
and keeps a `KBUILD-` for each, `Published`, superseding the one it replaces. A manifest is recognized by its SHA-256,
so recording again records nothing, and a rebuild of the same commit (the same version, other contents) is a new
build.

```
<site>/manifest.json           the pages' build (target folders)
<site>/vectors/manifest.json   the vector database's, served beside it as vectors/catalyst-vectors.tar.gz
```
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from catalyst_kb_engine.build.folders import BuildError
from catalyst_kb_engine.catalyst import CatalystCLI
from catalyst_kb_engine.models import Classification, Target

FORMAT = "kbm-build/1"
SERVED = (
    ("manifest.json", Target.FOLDERS, ""),
    ("vectors/manifest.json", Target.VECTOR_DATABASE, "vectors/catalyst-vectors.tar.gz"),
)
"""Each manifest a site serves: its path, its build's target, and where that build is (the site itself for pages)."""
_TARGETS = {"folders": Target.FOLDERS, "vector-database": Target.VECTOR_DATABASE}

Fetch = Callable[[str], bytes | None]
"""A URL's body, or None when it is not there."""


def fetch(url: str) -> bytes | None:
    if not url.startswith("https://"):
        raise ValueError(f"a site is read over https only: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as answer:  # noqa: S310 - https only, above
            return answer.read()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


@dataclass
class SiteRecord:
    recorded: list[str] = field(default_factory=list)
    """The `KBUILD-`s recorded now."""
    known: list[str] = field(default_factory=list)
    """The ones already recorded for a manifest the site still serves."""
    superseded: list[str] = field(default_factory=list)


def _check(manifest: dict[str, Any], url: str, target: Target) -> None:
    if manifest.get("format") != FORMAT:
        raise BuildError(f"{url} is not a {FORMAT} manifest")
    if _TARGETS.get(str(manifest.get("target"))) is not target:
        raise BuildError(f"{url} is a {manifest.get('target')} build, not {target.value}")
    for name in ("classification", "ceiling"):
        if manifest.get(name) != Classification.PUBLIC.value:
            raise BuildError(f"{url}: the build's {name} is {manifest.get(name)}, not Public: not a published build")


def _contents(manifest: dict[str, Any], url: str, digest: str) -> str:
    counts = manifest.get("counts") or {}
    chunks = f" in {counts['chunks']} chunks" if "chunks" in counts else ""
    return (
        f"{counts.get('documents', 0)} documents and {counts.get('pointers', 0)} pointers{chunks}, format "
        f"`{FORMAT}`, classification Public (ceiling Public); {counts.get('left_out', 0)} left out. Recorded from the "
        f"manifest the site serves, {url} (SHA-256 `{digest}`)."
    )


def _embedding(manifest: dict[str, Any]) -> str | None:
    e = manifest.get("embedding") or {}
    if not e.get("model"):
        return None
    prefixes = f"; prefixes {e['document_prefix']}/ {e['query_prefix']}" if e.get("document_prefix") else ""
    return f"{e['model']} ({e.get('dimensions')} dimensions), {e.get('where')}; input {e.get('input')}{prefixes}"


def record_site(cli: CatalystCLI, site: str, get: Fetch = fetch) -> SiteRecord:
    """Record each build `site` serves that no `KBUILD-` records yet, `Published`; the knowledge base's earlier
    `Published` build of the same target at the same location is `Superseded`."""
    site = site.rstrip("/") + "/"
    builds = cli.json("list", "KBUILD")
    result = SiteRecord()
    cli.command_name = "/kb-build"
    for path, target, where in SERVED:
        url = site + path
        raw = get(url)
        if raw is None:
            if target is Target.FOLDERS:
                raise BuildError(f"{url} is not there: {site} serves no build")
            continue
        manifest = json.loads(raw)
        _check(manifest, url, target)
        kb, digest = str(manifest.get("knowledge_base") or ""), hashlib.sha256(raw).hexdigest()
        version = f"{manifest.get('version')}+{digest[:8]}"
        location = site + where
        same = [b for b in builds if str(b.get("Version")) == version and b.get("Knowledge base") == f"`{kb}`"]
        if same:
            result.known.append(same[0]["id"])
            continue
        name = str(cli.view(kb).get("title") or kb)  # the knowledge base is recorded here, or catalyst refuses
        fields = {
            "Knowledge base": kb, "Version": version, "Target": target.value, "Ceiling": Classification.PUBLIC.value,
            "Classification": Classification.PUBLIC.value, "Location": location,
        }  # fmt: skip
        if manifest.get("content_commit"):
            fields["Content commit"] = str(manifest["content_commit"])
        if embedding := _embedding(manifest):
            fields["Embedding model"] = embedding
        kind = "vectors" if target is Target.VECTOR_DATABASE else "site"
        build = cli.new(
            "KBUILD", f"{name} public {kind} {version}", fields, intent=f"the published {target.value} build {version}",
            tier="build",
        )["id"]  # fmt: skip
        cli.write_section(build, "Contents", _contents(manifest, url, digest), intent="what it holds", tier="build")
        cli.status(build, "Built", intent="the build the site serves", tier="build")
        verification = (
            f"Served at {location}: the site is deployed only after the publication check (`publish-check`, "
            f"`eng-PUBLISH-000001`) passes against its public sources list, and its manifest says classification "
            f"Public, ceiling Public."
        )
        cli.write_section(build, "Verification", verification, intent="why it may be public", tier="build")
        cli.status(build, "Published", intent="the site serves it", tier="build")
        result.recorded.append(build)
        replaced = [
            earlier["id"]
            for earlier in builds
            if earlier.get("Status") == "Published"
            and earlier.get("Target") == target.value
            and earlier.get("Location") == location
            and earlier.get("Knowledge base") == f"`{kb}`"
        ]
        for earlier in replaced:
            cli.status(earlier, "Superseded", intent=f"the site now serves {build}", tier="build")
        result.superseded += replaced
        related = f"Supersedes {', '.join(f'`{r}`' for r in replaced)}." if replaced else "The first build served here."
        cli.write_section(build, "Related", related, intent="the build it replaces", tier="build")
    return result
