"""Persisted publication integration: no allow-all, no implicit attributes."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.analytical_golden_loader import evaluate_published_golden_readiness
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op


class Provider:
    def __init__(self):
        self.calls = []
    async def get_data_source_id(self, name):
        self.calls.append(("datasource", name))
        return {"sales": 7, "vessels": 8}.get(name)
    async def list_semantic_entities(self, source_id):
        self.calls.append(("entities", source_id))
        schema, table = ("Sales", "OrderDetail") if source_id == 7 else ("astra", "vessel")
        return [{"id": 1, "name": table, "schema_name": schema,
                 "table_name": table, "attributes": [
                     {"name": "Group", "column_name": "group_code"},
                     {"name": "Category", "column_name": "category_code"},
                 ]}]
    async def list_semantic_metrics(self, source_id):
        self.calls.append(("metrics", source_id))
        return [{"id": 2, "name": "Measure"}, {"id": 3, "name": "Draft"}]
    async def list_time_dimensions(self, source_id):
        self.calls.append(("times", source_id))
        return []


class Store:
    def __init__(self, grants, *, error=False):
        self.grants = grants
        self.calls = []
        self.error = error
    async def is_published(self, *args):
        self.calls.append(args)
        if self.error:
            raise RuntimeError("Publication store unavailable")
        return args in self.grants


def case(domain="sales", *, dimension="Group", metric="Measure", pending=False):
    schema, table = ("Sales", "OrderDetail") if domain == "sales" else ("astra", "vessel")
    return GoldenAnalyticalQuestion(
        expectation=AnalyticalEvaluationCase(
            case_id=f"{domain}-{dimension}-{metric}",
            question="Count records by group",
            expected_operations=(Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT),
            expected_dimensions=(f"{table}.{dimension}",),
            expected_metrics=(metric, metric),
            expected_source=(schema, table),
        ),
        domain="adventureworks" if domain == "sales" else "astra",
        status=GoldenCaseStatus.PENDING if pending else GoldenCaseStatus.SUPPORTED,
        required_capabilities=("join",) if pending else (),
    )


def inputs(domain="sales", *, metric=True, attribute=True, error=False):
    source_id = 7 if domain == "sales" else 8
    return {
        "datasource": domain,
        "provider": Provider(),
        "publication_store": Store({(source_id, "metric", 2)} if metric else set(), error=error),
        "attribute_publication_store": Store({(source_id, 1, "Group")} if attribute else set()),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["sales", "vessels"])
@pytest.mark.parametrize("pending", [False, True])
async def test_persisted_publications_control_readiness(domain, pending):
    args = inputs(domain)
    question = case("sales" if domain == "sales" else "vessels", pending=pending)
    result, = await evaluate_published_golden_readiness(cases=(question,), **args)
    assert result.ready is (not pending)
    assert result.reasons == (("unsupported_capability",) if pending else ())
    assert (7 if domain == "sales" else 8, "metric", 3) in args["publication_store"].calls


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["sales", "vessels"])
@pytest.mark.parametrize("metric,attribute", [(False, True), (True, False), (False, False)])
async def test_unpublished_references_are_not_promoted(domain, metric, attribute):
    args = inputs(domain, metric=metric, attribute=attribute)
    result, = await evaluate_published_golden_readiness(
        cases=(case("sales" if domain == "sales" else "vessels"),), **args,
    )
    assert not result.ready
    assert ("unpublished_or_ambiguous_metric:Measure" in result.reasons) is (not metric)
    assert any("unpublished_or_ambiguous_dimension" in x for x in result.reasons) is (not attribute)


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["sales", "vessels"])
async def test_multiple_cases_share_one_published_snapshot(domain):
    args = inputs(domain)
    name = "sales" if domain == "sales" else "vessels"
    cases = (case(name), replace(case(name), expectation=replace(
        case(name).expectation, case_id="second", expected_dimensions=(),
    )))
    results = await evaluate_published_golden_readiness(cases=cases, **args)
    assert all(result.ready for result in results)
    assert args["provider"].calls.count(("metrics", 7 if domain == "sales" else 8)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["sales", "vessels"])
async def test_publication_store_failure_propagates(domain):
    args = inputs(domain, error=True)
    with pytest.raises(RuntimeError, match="unavailable"):
        await evaluate_published_golden_readiness(
            cases=(case("sales" if domain == "sales" else "vessels"),), **args,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["publication_store", "attribute_publication_store", "provider"])
async def test_missing_trust_dependencies_rejected(field):
    args = inputs()
    args[field] = None
    with pytest.raises(ValueError):
        await evaluate_published_golden_readiness(cases=(case(),), **args)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, [], ("not-a-case",)])
async def test_untrusted_case_collection_rejected(bad):
    with pytest.raises(ValueError):
        await evaluate_published_golden_readiness(cases=bad, **inputs())


@pytest.mark.asyncio
async def test_duplicate_case_ids_rejected_before_metadata_access():
    args = inputs()
    with pytest.raises(ValueError, match="Duplicate"):
        await evaluate_published_golden_readiness(cases=(case(), case()), **args)
    assert args["provider"].calls == []


@pytest.mark.asyncio
async def test_empty_case_set_does_not_load_metadata():
    args = inputs()
    assert await evaluate_published_golden_readiness(cases=(), **args) == ()
    assert args["provider"].calls == []


@pytest.mark.asyncio
async def test_unknown_datasource_rejected():
    args = inputs()
    args["datasource"] = "unknown"
    with pytest.raises(ValueError, match="Unknown datasource"):
        await evaluate_published_golden_readiness(cases=(case(),), **args)
