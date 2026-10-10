# Real-question acceptance: product-first development

This is a manual product acceptance suite, **not** a set of unit tests. Run a
small representative set through Query Playground after a feature batch is
green in CI. Substitute published terms from the connected dataset; the
engine must not contain these example schema or business values as constants.

## How to assess a run

For each question, inspect **resolved semantic entities/attributes**, **selected
metric**, **generated SQL**, **correctness checks**, **execution result**, and
**follow-up context**. Compare result counts against a trusted SQL query where
possible. A syntactically valid query is not sufficient.

Record each outcome as PASS, WRONG SQL, WRONG RESULT, NEEDS CLARIFICATION,
UNSUPPORTED, or PROVIDER FAILURE. Keep SQL/result failures distinct from
provider connectivity problems.

## Scenario A: categorical resolution and comparison

1. Show the count of records by ownership category.
   - Must group by the published category, not silently return a total.
2. Compare owned and time-chartered records by operator.
   - Must retain both published canonical values and each operator's comparison
     grain. A single combined count is incorrect.
3. Show only records in the owned-but-chartered category.
   - Must resolve the *composite* published phrase, not its constituent labels.
4. Compare owned versus time-chartered records for the last available snapshot.
   - Must preserve both cohorts while applying the correct snapshot filter.
5. Show owned and time-chartered records, then follow up with "only for operator X".
   - Must preserve the comparison and add the new filter.
6. Show category TO between 2015 and 2025.
   - The range connector "to" must not be interpreted as categorical code TO.
7. Compare two synonyms mapped to different attributes without naming the
   attribute.
   - Must ask for clarification rather than guess.

## Scenario B: aggregation and grain

8. Count distinct records by operator and segment.
   - Count the governed identifier at the requested grain.
9. Show average age by segment for operator X.
   - Average must use the governed age definition and preserve segment grouping.
10. Show the top 10 operators by record count.
    - Ranking must use the aggregate, not arbitrary rows.
11. Compare two categories using separate conditional aggregate columns.
    - Each cohort must have an independent output measure.
12. Count records by a published array-valued attribute.
    - Expand array values correctly; avoid invalid GROUP BY UNNEST expressions.
13. Show counts by operator after joining a one-to-many detail table.
    - Avoid fan-out inflation by counting at the correct physical key grain.

## Scenario C: time and follow-up

14. Show monthly revenue for the last 12 complete months.
    - Respect the governed time dimension, month grain and complete-month rule.
15. Compare revenue this month versus last month.
    - Preserve two time cohorts and use the published revenue expression.
16. Show revenue by product; follow up with "only red ones".
    - Reuse the metric and grouping; resolve red using published attributes.
17. Show the top 10 customers by order count.
    - Count distinct governed orders, not line items.
18. Show average order value by customer.
    - Aggregate at order grain before averaging across orders.
19. Show records for a period where the connected dataset has no data.
    - Return an honest empty result, not invented values.
20. Ask for a metric that is not published or cannot be safely derived.
    - Clarify or report unsupported intent; do not fabricate a formula.

## Release gate

- GitHub Actions unit suite is green.
- At least five representative real questions from the changed capability
  have been inspected in Playground.
- No wrong-result or unsafe-SQL outcome is marked as a pass.
- Failures are classified as semantic resolution, generation, validation,
  execution, presentation, or provider/infrastructure.
- A reproduced bug receives a focused regression test **after** its product
  behavior has been understood.

This checklist intentionally prioritizes answer correctness over test-count growth.
