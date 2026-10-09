"""Domain-neutral golden-question catalog and capability-aware coverage reporting.

Gold cases are specifications, not examples to send to the LLM. An unsupported
case must not be counted as a successful prediction or executed automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase


class GoldenCaseStatus(str, Enum):
    SUPPORTED = "supported"
    PENDING = "pending"


@dataclass(frozen=True)
class GoldenAnalyticalQuestion:
    expectation: AnalyticalEvaluationCase
    domain: str
    status: GoldenCaseStatus
    required_capabilities: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.expectation, AnalyticalEvaluationCase):
            raise ValueError("Golden question requires an evaluation expectation")
        if not isinstance(self.domain, str) or not self.domain.strip():
            raise ValueError("Golden question requires a domain")
        if not isinstance(self.status, GoldenCaseStatus):
            raise ValueError("Golden question requires a known status")
        if not isinstance(self.required_capabilities, tuple) or any(
            not isinstance(cap, str) or not cap.strip() for cap in self.required_capabilities
        ):
            raise ValueError("Required capabilities must be named")
        if self.status is GoldenCaseStatus.PENDING and not self.required_capabilities:
            raise ValueError("Pending question requires an explicit capability gap")
        if self.status is GoldenCaseStatus.SUPPORTED and self.required_capabilities:
            raise ValueError("Supported question cannot have pending capabilities")


@dataclass(frozen=True)
class GoldenCoverage:
    total: int
    supported: int
    pending: int
    supported_case_ids: tuple[str, ...]
    pending_case_ids: tuple[str, ...]


def summarize_golden_coverage(
    cases: tuple[GoldenAnalyticalQuestion, ...],
) -> GoldenCoverage:
    if not isinstance(cases, tuple) or any(
        not isinstance(case, GoldenAnalyticalQuestion) for case in cases
    ):
        raise ValueError("Golden catalog must contain typed questions")
    ids = [case.expectation.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate golden question id")
    supported = tuple(
        case.expectation.case_id for case in cases
        if case.status is GoldenCaseStatus.SUPPORTED
    )
    pending = tuple(
        case.expectation.case_id for case in cases
        if case.status is GoldenCaseStatus.PENDING
    )
    return GoldenCoverage(len(cases), len(supported), len(pending), supported, pending)
