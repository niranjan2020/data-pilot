# Repeatable NL-to-SQL evaluation

The evaluator accepts a JSON array or CSV with columns `id`, `question`, optional `reference_sql`, optional `duplicate_of`, and optional `expect` (JSON-encoded in CSV).

A case with a question but no approved `expect` is **executed and marked unreviewed**, not passed. An empty question is **not_configured**. Exit status is nonzero when cases are unreviewed, failed, unconfigured or encounter transport errors.

Example:

```cmd
python scripts/run_nl2sql_evaluation.py --cases evaluations/astra_questions.csv --source astra-dev --execute --output evaluation-results.json
```

Default is dry-run; `--execute` sends read-only queries to the existing `/api/query` API. Run only against an authorized configured source. The output includes each question, generated SQL, response body (including error details and trace), reference SQL, and assertion checks.

An approved case may contain:

```json
{
  "id": "example-1",
  "question": "Show non-empty labels",
  "reference_sql": "SELECT labels FROM items WHERE CARDINALITY(labels) > 0",
  "expect": {
    "status": "completed",
    "sql_contains": ["CARDINALITY("],
    "sql_excludes": ["IS NOT NULL"],
    "min_rows": 1
  }
}
```

These checks are structural/execution smoke checks, **not proof of result correctness**. The `reference_sql` column is provenance from the uploaded spreadsheet and must be reviewed before using it as a correctness oracle. A duplicate question remains visible for repeatability.

The original 38-question tracker is a separate historical diagnostic set. The uploaded October 10 workbook contains 49 rows and 48 unique questions; do not silently substitute it for the historical 38.
