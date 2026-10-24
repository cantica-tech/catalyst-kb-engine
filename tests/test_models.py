"""The onboarding plan's validation (`kbm-ONBOARDING-000001`, `kbm-MODEL-000001`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from catalyst_kb_engine.models import (
    Basis,
    Classification,
    DocumentBase,
    Folder,
    Layout,
    OnboardingPlan,
    Source,
    Target,
    default_document_base,
)

LAYOUT = Layout(repository="../kb", folders=[Folder(path="criterion", holds="the project's records")])
CRITERION = Source(title="The app criterion", location="criterion:app")
WIKI = Source(title="The wiki", location="https://wiki.example.com", classification=Classification.INTERNAL)


def _plan(basis: Basis, sources: list[Source]) -> OnboardingPlan:
    return OnboardingPlan(
        basis=basis, sources=sources, layout=LAYOUT, target=Target.FOLDERS, document_base=DocumentBase.DYNAMIC
    )


def test_a_criterion_based_plan_starts_with_the_criterion_and_may_be_enriched():
    assert _plan(Basis.CRITERION, [CRITERION, WIKI]).sources[0].is_criterion


@pytest.mark.parametrize("sources", [[WIKI], [WIKI, CRITERION], [CRITERION, CRITERION]])
def test_a_criterion_based_plan_without_the_criterion_first_and_once_is_refused(sources):
    with pytest.raises(ValidationError, match="first and only criterion source"):
        _plan(Basis.CRITERION, sources)


def test_a_documents_based_plan_draws_on_no_criterion():
    assert _plan(Basis.DOCUMENTS, [WIKI]).basis is Basis.DOCUMENTS
    with pytest.raises(ValidationError, match="draws on no criterion"):
        _plan(Basis.DOCUMENTS, [WIKI, CRITERION])


def test_folders_are_lowercase_hyphenated_and_distinct():
    with pytest.raises(ValidationError):
        Folder(path="Not OK", holds="x")
    with pytest.raises(ValidationError, match="once"):
        Layout(repository="r", folders=[Folder(path="a", holds="x"), Folder(path="a", holds="y")])


def test_a_criterion_based_document_base_is_dynamic_by_default():
    assert default_document_base(Basis.CRITERION) is DocumentBase.DYNAMIC
    assert default_document_base(Basis.DOCUMENTS) is DocumentBase.STATIC


def test_classifications_are_ordered():
    assert Classification.highest(Classification.PUBLIC, Classification.CONFIDENTIAL) is Classification.CONFIDENTIAL
