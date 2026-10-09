"""Golden analytical questions: domain fixtures, not production mappings.

Physical sources here are illustrative evaluation fixtures. Production metadata
and category mappings must be approved independently before live execution.
"""
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion as Gold, GoldenCaseStatus as Status,
)

def _case(id, question, ops, dims, metrics, params, source, *, domain, pending=()):
    return Gold(
        expectation=AnalyticalEvaluationCase(
            case_id=id, question=question, expected_operations=ops,
            expected_dimensions=dims, expected_metrics=metrics,
            expected_parameters=params, expected_source=source,
        ),
        domain=domain,
        status=Status.PENDING if pending else Status.SUPPORTED,
        required_capabilities=pending,
    )

_BASE=(Op.GROUP,Op.AGGREGATE,Op.SORT,Op.LIMIT)
_FILTER=(Op.FILTER,)+_BASE
_THRESHOLD=(Op.GROUP,Op.AGGREGATE,Op.THRESHOLD,Op.SORT,Op.LIMIT)
_FILTER_THRESHOLD=(Op.FILTER,)+_THRESHOLD

GOLDEN_QUESTIONS=(
    _case("sales-01","Top 10 product groups by units sold",_BASE,
          ("OrderDetail.Product",),("Units", "Units"),(),("Sales","OrderDetail"),domain="adventureworks"),
    _case("sales-02","Top 5 regions by order count",_BASE,
          ("OrderDetail.Region",),("Orders","Orders"),(),("Sales","OrderDetail"),domain="adventureworks"),
    _case("sales-03","Units sold by product for red items",_FILTER,
          ("OrderDetail.Color","OrderDetail.Product"),("Units","Units"),("Red",),
          ("Sales","OrderDetail"),domain="adventureworks"),
    _case("sales-04","Top products by revenue over 1000",_THRESHOLD,
          ("OrderDetail.Product",),("Revenue",)*3,(1000,),("Sales","OrderDetail"),domain="adventureworks"),
    _case("sales-05","Top 10 red products with revenue above 1000",_FILTER_THRESHOLD,
          ("OrderDetail.Color","OrderDetail.Product"),("Revenue",)*3,("Red",1000),
          ("Sales","OrderDetail"),domain="adventureworks"),
    _case("sales-06","Compare this month revenue with last month",(
          Op.TIME_WINDOW,Op.COMPARE),(),("Revenue",),(),("Sales","OrderDetail"),
          domain="adventureworks",pending=("time_window","comparison")),
    _case("sales-07","Average order value by customer",(
          Op.JOIN,Op.GROUP,Op.AGGREGATE),("Customer.Customer",),("AverageOrderValue",),(),
          ("Sales","OrderDetail"),domain="adventureworks",pending=("join","grain_validation")),
    _case("sales-08","Share of revenue by product",(
          Op.GROUP,Op.AGGREGATE,Op.CONTRIBUTION),("OrderDetail.Product",),("Revenue",),(),
          ("Sales","OrderDetail"),domain="adventureworks",pending=("contribution",)),
    _case("vessel-01","Top 10 operators by vessel count",_BASE,
          ("Vessel.Operator",),("VesselCount",)*2,(),("astra","vessel"),
          domain="astra"),
    _case("vessel-02","Vessel count by ownership status",_BASE,
          ("Vessel.Ownership",),("VesselCount",)*2,(),("astra","vessel"),
          domain="astra"),
    _case("vessel-03","Top operators for owned vessels",_FILTER,
          ("Vessel.Ownership","Vessel.Operator"),("VesselCount",)*2,("O",),
          ("astra","vessel"),domain="astra"),
    _case("vessel-04","Operators with more than 50 vessels",_THRESHOLD,
          ("Vessel.Operator",),("VesselCount",)*3,(50,),("astra","vessel"),
          domain="astra"),
    _case("vessel-05","Top operators with more than 50 owned vessels",_FILTER_THRESHOLD,
          ("Vessel.Ownership","Vessel.Operator"),("VesselCount",)*3,("O",50),
          ("astra","vessel"),domain="astra"),
    _case("vessel-06","How many owned or chartered vessels does MSC operate?",_FILTER,
          ("Vessel.Ownership","Vessel.Operator"),("VesselCount",)*2,("O","T","MSC"),
          ("astra","vessel"),domain="astra",pending=("categorical_resolution","multi_filter_binding")),
    _case("vessel-07","Compare vessel fleet size month over month",(
          Op.TIME_WINDOW,Op.COMPARE),(),("VesselCount",),(),("astra","vessel"),
          domain="astra",pending=("snapshot_grain","time_window","comparison")),
    _case("vessel-08","Average vessel age by segment for MSC",(
          Op.FILTER,Op.GROUP,Op.AGGREGATE),("Vessel.Operator","Vessel.Segment"),
          ("AverageAge",),("MSC",),("astra","vessel"),
          domain="astra",pending=("derived_metric","time_grain")),
)
