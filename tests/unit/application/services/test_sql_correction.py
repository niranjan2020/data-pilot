from datapilot.application.services.sql_correction import classify_sql_correction


def test_governed_violation_is_recoverable():
    decision = classify_sql_correction(
        correctness_checks=[{
            "code": "relationship_violation",
            "status": "failed",
            "message": "wrong join",
        }]
    )
    assert decision.recoverable is True
    assert decision.category == "governed_correctness"
    assert decision.feedback[0]["code"] == "relationship_violation"


def test_multiple_known_governed_violations_are_recoverable_together():
    decision = classify_sql_correction(
        correctness_checks=[
            {"code": "filter_violation", "status": "failed"},
            {"code": "time_grain_violation", "status": "failed"},
        ]
    )
    assert decision.recoverable is True
    assert [item["code"] for item in decision.feedback] == [
        "filter_violation",
        "time_grain_violation",
    ]


def test_unverifiable_governed_correctness_is_not_recoverable():
    decision = classify_sql_correction(
        correctness_checks=[{
            "code": "relationship_verification_unavailable",
            "status": "skipped",
        }]
    )
    assert decision.recoverable is False
    assert decision.category == "governed_correctness"


def test_unknown_governed_failure_is_not_recoverable():
    decision = classify_sql_correction(
        correctness_checks=[{
            "code": "future_unknown_violation",
            "status": "failed",
        }]
    )
    assert decision.recoverable is False


def test_ast_safety_validation_failure_is_not_recoverable():
    decision = classify_sql_correction(validation_errors=["write statement"])
    assert decision.recoverable is False
    assert decision.category == "validation"


def test_execution_policy_failure_is_not_recoverable():
    decision = classify_sql_correction(policy_errors=["query too complex"])
    assert decision.recoverable is False
    assert decision.category == "policy"


def test_no_failure_is_not_recoverable():
    decision = classify_sql_correction()
    assert decision.recoverable is False
    assert decision.category == "none"
