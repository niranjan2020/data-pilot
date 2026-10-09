"""Diagnostic comparison of golden SQL structure; not semantic accuracy."""
from dataclasses import dataclass
from enum import Enum
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_sql_observation import AnalyticalSQLObservation

class StructuralDisposition(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNVERIFIED = "unverified"

@dataclass(frozen=True)
class StructuralComparison:
    case_id: str
    disposition: StructuralDisposition
    reasons: tuple[str, ...]
    semantic_verified: bool = False

def compare_golden_sql_structure(
    expectation: AnalyticalEvaluationCase,
    observation: AnalyticalSQLObservation,
) -> StructuralComparison:
    if not isinstance(expectation, AnalyticalEvaluationCase):
        raise ValueError("Typed golden expectation required")
    if not isinstance(observation, AnalyticalSQLObservation):
        raise ValueError("Typed SQL observation required")
    if expectation.case_id != observation.case_id:
        raise ValueError("Observation case id mismatch")
    if observation.semantic_verified:
        raise ValueError("Unexpected semantic verification claim")
    if not observation.supported:
        return StructuralComparison(expectation.case_id, StructuralDisposition.UNVERIFIED,
                                    observation.reasons or ("unsupported_sql_observation",))
    failures = []
    if observation.operations != expectation.expected_operations:
        failures.append("operation_mismatch")
    if expectation.expected_source is None:
        return StructuralComparison(expectation.case_id, StructuralDisposition.UNVERIFIED,
                                    tuple(failures) + ("expected_physical_source_missing",))
    expected_source = ".".join(expectation.expected_source).casefold()
    if len(observation.sources) != 1 or "." not in observation.sources[0]:
        return StructuralComparison(expectation.case_id, StructuralDisposition.UNVERIFIED,
                                    tuple(failures) + ("physical_source_not_fully_qualified",))
    if observation.sources[0].casefold() != expected_source:
        failures.append("physical_source_mismatch")
    return StructuralComparison(
        expectation.case_id,
        StructuralDisposition.MISMATCH if failures else StructuralDisposition.MATCH,
        tuple(failures) if failures else ("semantic_binding_not_verified",),
    )
