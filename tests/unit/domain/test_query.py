from datapilot.domain.query import QueryTrace


def test_query_trace_starts_with_no_correction_attempts():
    trace = QueryTrace()
    assert trace.correction_attempts == []
