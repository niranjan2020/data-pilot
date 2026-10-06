from datapilot.domain.query import QueryTrace


def test_query_trace_starts_with_no_correction_attempts():
    trace = QueryTrace()
    assert trace.correction_attempts == []


def test_query_trace_starts_with_no_execution_recovery_attempts():
    trace = QueryTrace()
    assert trace.execution_recovery_attempts == []


def test_query_trace_preserves_structured_execution_recovery_diagnostics():
    trace = QueryTrace(
        execution_recovery_attempts=[{
            "attempt": 1,
            "failed_sql": "SELECT missing FROM orders",
            "database_error": {
                "provider": "postgresql",
                "sqlstate": "42703",
                "column_name": "missing",
            },
            "classification": {
                "recoverable": True,
                "category": "sql_execution",
            },
            "corrected_sql": "SELECT id FROM orders",
        }]
    )

    attempt = trace.execution_recovery_attempts[0]
    assert attempt["attempt"] == 1
    assert attempt["database_error"]["sqlstate"] == "42703"
    assert attempt["classification"]["recoverable"] is True
    assert attempt["corrected_sql"] == "SELECT id FROM orders"
