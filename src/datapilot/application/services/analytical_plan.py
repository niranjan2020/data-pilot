"""Provider-independent analytical plan contracts.

This module describes *what* an analytical query must do, not how SQL is
generated. The existing NL-to-SQL path is unchanged until explicit integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AnalyticalOperation(str, Enum):
    FILTER = "filter"
    AGGREGATE = "aggregate"
    GROUP = "group"
    SORT = "sort"
    LIMIT = "limit"
    RANK = "rank"
    COMPARE = "compare"
    THRESHOLD = "threshold"
    CONTRIBUTION = "contribution"
    TIME_WINDOW = "time_window"
    JOIN = "join"
    PROJECT = "project"


@dataclass(frozen=True)
class PlanStep:
    id: str
    operation: AnalyticalOperation
    inputs: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Plan step requires a nonempty id")
        if not isinstance(self.operation, AnalyticalOperation):
            raise ValueError("Plan step requires a known analytical operation")
        if not isinstance(self.inputs, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.inputs
        ):
            raise ValueError("Plan step inputs must be nonempty identifiers")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError("Plan step inputs must not repeat")
        if not isinstance(self.parameters, dict):
            raise ValueError("Plan step parameters must be a mapping")


@dataclass(frozen=True)
class AnalyticalPlan:
    """Ordered operation graph with an explicit output step.

    Step inputs refer to other steps, or to declared source identifiers.
    Requiring earlier definitions keeps the plan acyclic and deterministic.
    """

    sources: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    output: str

    def __post_init__(self) -> None:
        if not isinstance(self.sources, tuple) or not self.sources or any(
            not isinstance(source, str) or not source.strip() for source in self.sources
        ):
            raise ValueError("Analytical plan requires declared sources")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Analytical plan sources must be unique")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("Analytical plan requires steps")
        known = set(self.sources)
        for step in self.steps:
            if not isinstance(step, PlanStep):
                raise ValueError("Analytical plan contains an invalid step")
            if step.id in known:
                raise ValueError(f"Duplicate plan identifier: {step.id}")
            if not step.inputs or any(item not in known for item in step.inputs):
                raise ValueError(f"Unresolved or forward plan input: {step.id}")
            known.add(step.id)
        if self.output not in {step.id for step in self.steps}:
            raise ValueError("Analytical plan output must reference a step")

    @property
    def operations(self) -> tuple[AnalyticalOperation, ...]:
        return tuple(step.operation for step in self.steps)
