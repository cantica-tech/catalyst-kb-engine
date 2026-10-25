"""What onboarding decides (KBM `kbm-ONBOARDING-000001`, `kbm-MODEL-000001`), as typed, validated data.

The values are the knowledge base module's own field values, so a plan maps one to one onto a `KB-` record's
`Basis`, `Document base` and `Target`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

CRITERION_SCHEME = "criterion:"
"""A source whose location starts with this is a catalyst criterion, read through catalyst's CLI."""


class Basis(StrEnum):
    CRITERION = "Criterion"
    DOCUMENTS = "Documents"


class DocumentBase(StrEnum):
    STATIC = "Static"
    DYNAMIC = "Dynamic"


class Target(StrEnum):
    FOLDERS = "Folders"
    VECTOR_DATABASE = "Vector database"


class Classification(StrEnum):
    PUBLIC = "Public"
    INTERNAL = "Internal"
    CONFIDENTIAL = "Confidential"
    RESTRICTED = "Restricted"

    @property
    def rank(self) -> int:
        return list(Classification).index(self)

    @classmethod
    def highest(cls, *levels: Classification) -> Classification:
        return max(levels, key=lambda level: level.rank)


class SourceKind(StrEnum):
    """KBM's `KSOURCE` `Kind` (`kbm-MODEL-000002`)."""

    REPOSITORY = "Repository"
    FOLDER = "Folder"
    SITE = "Site"
    CRITERION = "Criterion"


class Visibility(StrEnum):
    """KBM's `KSOURCE` `Visibility`: a `Private` source's documents are at least `Internal` (`rr-KB-002`)."""

    PUBLIC = "Public"
    PRIVATE = "Private"


PRIVATE_FLOOR = Classification.INTERNAL
"""The least classification of a document read from a private source."""


class Source(BaseModel):
    """A place the knowledge base draws on: a `KSOURCE-` once recorded."""

    title: str = Field(min_length=1)
    location: str = Field(min_length=1, description="a URL, a path, or `criterion:<project name>`")
    classification: Classification | None = Field(default=None, description="its mark; else the policy's")
    access: str | None = Field(default=None, description="how it is reached, if not plainly")
    kind: SourceKind | None = Field(default=None, description="what it is; a `criterion:` location is a criterion")
    visibility: Visibility | None = Field(default=None, description="as its host shows it; unknown is private")

    @model_validator(mode="after")
    def _criterion_kind(self) -> Source:
        if self.kind is None and self.is_criterion:
            self.kind = SourceKind.CRITERION
        if self.kind is not None and (self.kind is SourceKind.CRITERION) != self.is_criterion:
            raise ValueError(f"a Criterion source, and only one, has a location `{CRITERION_SCHEME}<project name>`")
        return self

    @property
    def is_criterion(self) -> bool:
        return self.location.startswith(CRITERION_SCHEME)

    @property
    def project(self) -> str | None:
        """A criterion source's project name."""
        return self.location.removeprefix(CRITERION_SCHEME) if self.is_criterion else None


class Folder(BaseModel):
    """One folder of the knowledge base's organization: a path under `docs/`, and what it holds."""

    path: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*$")
    holds: str = Field(min_length=1)


class Layout(BaseModel):
    """The location and storage strategy: where the repository lives, and how its documents are organized."""

    repository: str = Field(min_length=1, description="a git URL, or a path on this machine")
    folders: list[Folder] = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct_folders(self) -> Layout:
        paths = [f.path for f in self.folders]
        if len(paths) != len(set(paths)):
            raise ValueError("each folder appears once")
        return self


class OnboardingPlan(BaseModel):
    """Everything onboarding decided: what `/kb-setup` records as the `KB-` and its `KSOURCE-`s."""

    basis: Basis
    sources: list[Source] = Field(min_length=1)
    layout: Layout
    target: Target
    document_base: DocumentBase

    @model_validator(mode="after")
    def _sources_fit_the_basis(self) -> OnboardingPlan:
        criteria = [s for s in self.sources if s.is_criterion]
        if self.basis is Basis.CRITERION and (len(criteria) != 1 or not self.sources[0].is_criterion):
            raise ValueError(
                "a criterion-based knowledge base has the criterion as its first and only criterion source"
            )
        if self.basis is Basis.DOCUMENTS and criteria:
            raise ValueError("a documents-based knowledge base draws on no criterion")
        return self


def default_document_base(basis: Basis) -> DocumentBase:
    """Dynamic for a criterion-based knowledge base, a criterion always being in flux; static otherwise."""
    return DocumentBase.DYNAMIC if basis is Basis.CRITERION else DocumentBase.STATIC
