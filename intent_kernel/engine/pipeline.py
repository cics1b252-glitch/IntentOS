"""Pipeline — DAG executor for the processing pipeline."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from intent_kernel.types import Mode, ParsedIntent, PipelineContext, PipelineResult


# Pipeline node function type
NodeFn = Callable[[PipelineContext], Awaitable[PipelineContext]]


class PipelineDAG:
    """Directed Acyclic Graph executor for the processing pipeline.

    Each mode maps to a different path through the DAG.
    Nodes are registered with names and edges define the flow.
    """

    def __init__(self):
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, list[str]] = {}

        # Define paths for each mode
        self._mode_paths: dict[Mode, list[str]] = {
            Mode.QUICK: ["intake", "classify", "build", "deliver"],
            Mode.BASIC: ["intake", "classify", "diagnose", "build", "review", "deliver"],
            Mode.DETAIL: ["intake", "classify", "diagnose", "plan", "build", "review", "deliver"],
            Mode.EXPERT: ["intake", "classify", "diagnose", "plan", "build", "stress_test", "review", "deliver"],
            Mode.ARCHITECT: ["intake", "classify", "diagnose", "plan", "build", "stress_test", "review", "knowledge_check", "deliver"],
        }

    def register(self, name: str, fn: NodeFn) -> None:
        """Register a pipeline node."""
        self._nodes[name] = fn

    async def execute(
        self,
        intent: ParsedIntent,
        mode: Mode,
        extra_context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Execute the pipeline for the given mode.

        Traverses the DAG path for the mode, running each node in sequence.
        """
        path = self._mode_paths.get(mode, self._mode_paths[Mode.BASIC])

        ctx = PipelineContext(
            intent=intent,
            mode=mode,
            data=extra_context or {},
        )

        for node_name in path:
            if node_name in self._nodes:
                ctx = await self._nodes[node_name](ctx)

        return PipelineResult(
            context=ctx,
            output_text=ctx.output_text,
            mode=mode,
            domain=intent.domain,
            confidence=ctx.confidence,
            epistemic_status=ctx.epistemic_status,
            events=ctx.events,
        )
