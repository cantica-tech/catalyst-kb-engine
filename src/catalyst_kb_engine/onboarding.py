"""The onboarding workflow (`eng-WORKFLOW-000001`, `eng-WORKFLOW-000002`): four decisions, each proposed (by default
rules or by a Pydantic AI agent, any model) and decided by a person, as a `pydantic-graph` graph.

1. its basis and sources: the project's criterion enriched by other sources, or gathered documents;
2. its location and storage strategy: the repository and its folder organization;
3. its target: organized folders, or a vector database;
4. its document base: static, or dynamic (dynamic by default for a criterion-based one).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field
from pydantic_graph import GraphBuilder, StepContext

from catalyst_kb_engine.models import (
    CRITERION_SCHEME,
    Basis,
    DocumentBase,
    Folder,
    Layout,
    OnboardingPlan,
    Source,
    Target,
    default_document_base,
)

P = TypeVar("P", bound=BaseModel)


class OnboardingContext(BaseModel):
    """What the workflow knows before it asks anything."""

    title: str = Field(min_length=1, description="the knowledge base's title")
    purpose: str = Field(default="", description="what it must make known, and for whom")
    project: str | None = Field(default=None, description="the catalyst project it belongs to, if any")
    other_modules: list[str] = Field(default_factory=list, description="the modules governing the project beside KBM")
    candidate_sources: list[Source] = Field(default_factory=list, description="sources already known")


class SourcesChoice(BaseModel):
    basis: Basis
    sources: list[Source] = Field(min_length=1)


class TargetChoice(BaseModel):
    target: Target


class DocumentBaseChoice(BaseModel):
    document_base: DocumentBase


class Proposer(Protocol):
    async def sources(self, context: OnboardingContext) -> SourcesChoice: ...
    async def layout(self, context: OnboardingContext, sources: SourcesChoice) -> Layout: ...
    async def target(self, context: OnboardingContext, sources: SourcesChoice) -> TargetChoice: ...
    async def document_base(self, context: OnboardingContext, sources: SourcesChoice) -> DocumentBaseChoice: ...


class Decider(Protocol):
    async def decide(self, question: str, proposal: P) -> P:
        """A person's decision on a proposal: the proposal itself, or what they put in its place (same type)."""
        ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "knowledge-base"


class DefaultProposer:
    """Proposals from the module's rules alone, no model: criterion-based when other modules govern the project."""

    async def sources(self, context: OnboardingContext) -> SourcesChoice:
        known = [s for s in context.candidate_sources if not s.is_criterion]
        if context.other_modules and context.project:
            criterion = Source(title=f"The {context.project} criterion", location=CRITERION_SCHEME + context.project)
            return SourcesChoice(basis=Basis.CRITERION, sources=[criterion, *known])
        if not known:
            known = [Source(title="To be gathered", location="TODO: where the documents live")]
        return SourcesChoice(basis=Basis.DOCUMENTS, sources=known)

    async def layout(self, context: OnboardingContext, sources: SourcesChoice) -> Layout:
        folders = [
            Folder(path="criterion" if s.is_criterion else _slug(s.title), holds=f"what {s.title} contributes")
            for s in sources.sources
        ]
        return Layout(repository=f"../{_slug(context.title)}", folders=folders)

    async def target(self, context: OnboardingContext, sources: SourcesChoice) -> TargetChoice:
        return TargetChoice(target=Target.FOLDERS)

    async def document_base(self, context: OnboardingContext, sources: SourcesChoice) -> DocumentBaseChoice:
        return DocumentBaseChoice(document_base=default_document_base(sources.basis))


INSTRUCTIONS = """You help a curator onboard a knowledge base for catalyst's knowledge base module (KBM).
You propose; the curator decides. Rules you must respect:
- A criterion-based knowledge base (KBM beside other modules) has the project's criterion as its first source, with
  the location `criterion:<project>`, and only other sources that enrich it.
- A documents-based knowledge base (KBM alone) draws on gathered documents only, never on a criterion.
- Folders are lowercase, hyphenated paths under docs/, one topic each.
- A criterion-based knowledge base's document base is Dynamic unless the curator says otherwise.
Propose only what the context supports; never invent a source's location."""


@dataclass
class AgentProposer:
    """Proposals from a Pydantic AI agent, typed and validated (`eng-ARCH-000001`: any model, local or hosted)."""

    model: Any
    """A Pydantic AI model or model name, e.g. `ollama:llama3.2`, `anthropic:claude-sonnet-5-5`, or a test model."""

    async def _ask(self, output_type: type[P], question: str, **known: Any) -> P:
        from pydantic_ai import Agent

        agent = Agent(self.model, output_type=output_type, instructions=INSTRUCTIONS)
        facts = {k: v.model_dump(mode="json") if isinstance(v, BaseModel) else v for k, v in known.items()}
        result = await agent.run(f"{question}\n\nWhat is known:\n{json.dumps(facts, indent=2)}")
        return result.output

    async def sources(self, context: OnboardingContext) -> SourcesChoice:
        return await self._ask(SourcesChoice, "Propose the basis and the sources.", context=context)

    async def layout(self, context: OnboardingContext, sources: SourcesChoice) -> Layout:
        return await self._ask(Layout, "Propose the repository and its folders.", context=context, sources=sources)

    async def target(self, context: OnboardingContext, sources: SourcesChoice) -> TargetChoice:
        return await self._ask(TargetChoice, "Propose the target.", context=context, sources=sources)

    async def document_base(self, context: OnboardingContext, sources: SourcesChoice) -> DocumentBaseChoice:
        return await self._ask(
            DocumentBaseChoice, "Propose whether its document base is static or dynamic.", context=context
        )


@dataclass
class OnboardingState:
    sources: SourcesChoice | None = None
    layout: Layout | None = None
    target: TargetChoice | None = None
    document_base: DocumentBaseChoice | None = None
    asked: list[str] = field(default_factory=list)


@dataclass
class OnboardingDeps:
    context: OnboardingContext
    proposer: Proposer
    decider: Decider


def _earlier(value: P | None, step: str) -> P:
    """What an earlier step decided; the graph's edges guarantee it, so its absence is a bug."""
    if value is None:
        raise RuntimeError(f"onboarding reached {step} before its earlier steps")
    return value


async def _decided(ctx: StepContext[OnboardingState, OnboardingDeps, Any], question: str, proposal: P) -> P:
    ctx.state.asked.append(question)
    decision = await ctx.deps.decider.decide(question, proposal)
    return type(proposal).model_validate(decision.model_dump())  # a person's answer is validated like a proposal


g = GraphBuilder(name="onboarding", state_type=OnboardingState, deps_type=OnboardingDeps, output_type=OnboardingPlan)


@g.step
async def basis_and_sources(ctx: StepContext[OnboardingState, OnboardingDeps, None]) -> None:
    proposal = await ctx.deps.proposer.sources(ctx.deps.context)
    ctx.state.sources = await _decided(ctx, "1. Its basis and sources", proposal)


@g.step
async def location_and_storage(ctx: StepContext[OnboardingState, OnboardingDeps, None]) -> None:
    sources = _earlier(ctx.state.sources, "its layout")
    proposal = await ctx.deps.proposer.layout(ctx.deps.context, sources)
    ctx.state.layout = await _decided(ctx, "2. Its location and storage strategy", proposal)


@g.step
async def target(ctx: StepContext[OnboardingState, OnboardingDeps, None]) -> None:
    sources = _earlier(ctx.state.sources, "its target")
    proposal = await ctx.deps.proposer.target(ctx.deps.context, sources)
    ctx.state.target = await _decided(ctx, "3. Its target", proposal)


@g.step
async def document_base(ctx: StepContext[OnboardingState, OnboardingDeps, None]) -> OnboardingPlan:
    sources = _earlier(ctx.state.sources, "its document base")
    layout, chosen = _earlier(ctx.state.layout, "its document base"), _earlier(ctx.state.target, "its document base")
    proposal = await ctx.deps.proposer.document_base(ctx.deps.context, sources)
    ctx.state.document_base = await _decided(ctx, "4. Its document base", proposal)
    return OnboardingPlan(
        basis=sources.basis,
        sources=sources.sources,
        layout=layout,
        target=chosen.target,
        document_base=ctx.state.document_base.document_base,
    )


g.add(
    g.edge_from(g.start_node).to(basis_and_sources),
    g.edge_from(basis_and_sources).to(location_and_storage),
    g.edge_from(location_and_storage).to(target),
    g.edge_from(target).to(document_base),
    g.edge_from(document_base).to(g.end_node),
)
ONBOARDING = g.build()


async def onboard(
    context: OnboardingContext, decider: Decider, proposer: Proposer | None = None
) -> tuple[OnboardingPlan, OnboardingState]:
    """Run the onboarding workflow; the plan is what the person decided, never a proposal taken as decided."""
    state = OnboardingState()
    deps = OnboardingDeps(context=context, proposer=proposer or DefaultProposer(), decider=decider)
    plan = await ONBOARDING.run(state=state, deps=deps)
    return plan, state
