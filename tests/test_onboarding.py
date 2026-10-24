"""The onboarding workflow: proposed, then decided by a person (`eng-WORKFLOW-000001`, `eng-WORKFLOW-000002`)."""

from __future__ import annotations

import asyncio
from typing import TypeVar, cast

from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from catalyst_kb_engine.models import Basis, DocumentBase, Target
from catalyst_kb_engine.onboarding import (
    AgentProposer,
    OnboardingContext,
    TargetChoice,
    onboard,
)

P = TypeVar("P", bound=BaseModel)

BESIDE = OnboardingContext(title="Support KB", project="app", other_modules=["software-engineering"])
ALONE = OnboardingContext(title="Handbook")


class Person:
    """Accepts every proposal, except the answers given (by question number)."""

    def __init__(self, **answers: BaseModel) -> None:
        self.answers = answers
        self.seen: list[tuple[str, BaseModel]] = []

    async def decide(self, question: str, proposal: P) -> P:
        self.seen.append((question, proposal))
        answer = self.answers.get(f"q{question[0]}")
        return proposal if answer is None else cast(P, answer)


def test_beside_another_module_it_proposes_the_criterion_dynamic_and_asks_four_times():
    person = Person()
    plan, state = asyncio.run(onboard(BESIDE, person))
    assert plan.basis is Basis.CRITERION and plan.sources[0].location == "criterion:app"
    assert plan.document_base is DocumentBase.DYNAMIC and plan.layout.folders[0].path == "criterion"
    assert [q for q, _ in person.seen] == state.asked and len(state.asked) == 4


def test_alone_it_proposes_gathered_documents():
    plan, _ = asyncio.run(onboard(ALONE, Person()))
    assert plan.basis is Basis.DOCUMENTS and not any(s.is_criterion for s in plan.sources)
    assert plan.document_base is DocumentBase.STATIC


def test_the_person_decides_not_the_proposal():
    plan, _ = asyncio.run(onboard(BESIDE, Person(q3=TargetChoice(target=Target.VECTOR_DATABASE))))
    assert plan.target is Target.VECTOR_DATABASE  # the default proposes Folders


ANSWERS = {
    "basis": {"basis": "Criterion", "sources": [{"title": "App criterion", "location": "criterion:app"}]},
    "repository": {"repository": "../support-kb", "folders": [{"path": "criterion", "holds": "records"}]},
    "target": {"target": "Vector database"},
    "static": {"document_base": "Dynamic"},
}


def _model(messages, info: AgentInfo) -> ModelResponse:
    """A model that answers each question with typed output, as a real one would, offline."""
    question = next(p.content for m in messages for p in m.parts if p.part_kind == "user-prompt").splitlines()[0]
    key = next(k for k in ANSWERS if k in question)
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, ANSWERS[key])])


def test_an_agent_proposes_with_typed_output_and_the_person_still_decides():
    person = Person()
    plan, _ = asyncio.run(onboard(BESIDE, person, AgentProposer(FunctionModel(_model))))
    assert plan.target is Target.VECTOR_DATABASE and plan.layout.repository == "../support-kb"
    assert len(person.seen) == 4  # every agent proposal went to the person
