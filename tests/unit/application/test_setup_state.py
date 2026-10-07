from datapilot.application.setup_state import SetupStep, SetupStepState, derive_setup_status


def test_fresh_install_starts_with_ai_provider():
    status = derive_setup_status(ai_provider_ready=False, data_source_ready=False, data_selection_ready=False, semantic_model_ready=False)
    assert status.first_run is True
    assert status.current_step == SetupStep.AI_PROVIDER
    assert status.steps[0].state == SetupStepState.IN_PROGRESS
    assert status.steps[1].state == SetupStepState.BLOCKED


def test_setup_resumes_at_first_incomplete_step():
    status = derive_setup_status(ai_provider_ready=True, data_source_ready=True, data_selection_ready=False, semantic_model_ready=False)
    assert status.current_step == SetupStep.DATA_SELECTION
    assert status.steps[0].state == SetupStepState.COMPLETE
    assert status.steps[1].state == SetupStepState.COMPLETE
    assert status.steps[2].state == SetupStepState.IN_PROGRESS


def test_completed_setup_is_ready_and_not_first_run():
    status = derive_setup_status(ai_provider_ready=True, data_source_ready=True, data_selection_ready=True, semantic_model_ready=True)
    assert status.first_run is False
    assert status.ready is True
    assert status.current_step == SetupStep.READY
    assert all(step.state == SetupStepState.COMPLETE for step in status.steps)
