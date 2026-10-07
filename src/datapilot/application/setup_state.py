"""Provider-independent first-run setup state contract."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SetupStep(str, Enum):
    AI_PROVIDER = "ai_provider"
    DATA_SOURCE = "data_source"
    DATA_SELECTION = "data_selection"
    SEMANTIC_REVIEW = "semantic_review"
    READY = "ready"


class SetupStepState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class SetupStepStatus(BaseModel):
    step: SetupStep
    state: SetupStepState
    message: Optional[str] = None


class SetupStatus(BaseModel):
    first_run: bool
    current_step: SetupStep
    ready: bool
    steps: list[SetupStepStatus] = Field(default_factory=list)


def derive_setup_status(
    *,
    ai_provider_ready: bool,
    data_source_ready: bool,
    data_selection_ready: bool,
    semantic_model_ready: bool,
) -> SetupStatus:
    """Derive deterministic, resumable onboarding state from persisted readiness facts."""
    facts = [
        (SetupStep.AI_PROVIDER, ai_provider_ready),
        (SetupStep.DATA_SOURCE, data_source_ready),
        (SetupStep.DATA_SELECTION, data_selection_ready),
        (SetupStep.SEMANTIC_REVIEW, semantic_model_ready),
    ]
    first_incomplete = next((step for step, complete in facts if not complete), SetupStep.READY)
    steps: list[SetupStepStatus] = []
    blocked = False
    for step, complete in facts:
        if complete:
            state = SetupStepState.COMPLETE
        elif not blocked and step == first_incomplete:
            state = SetupStepState.IN_PROGRESS
            blocked = True
        else:
            state = SetupStepState.BLOCKED
        steps.append(SetupStepStatus(step=step, state=state))
    ready = all(complete for _, complete in facts)
    steps.append(SetupStepStatus(
        step=SetupStep.READY,
        state=SetupStepState.COMPLETE if ready else SetupStepState.BLOCKED,
    ))
    return SetupStatus(
        first_run=not ready,
        current_step=SetupStep.READY if ready else first_incomplete,
        ready=ready,
        steps=steps,
    )
