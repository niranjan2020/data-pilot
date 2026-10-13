import asyncio

from datapilot.application.published_join_authorization import authorize_published_joins


class Metadata:
    async def list_current_relationship_publications(self, source_id):
        assert source_id == 27
        return [{
            "from_schema": "astra", "from_table": "fixtures", "from_column": "vessel_id",
            "to_schema": "astra", "to_table": "vessels", "to_column": "id",
            "cardinality": "many_to_one", "join_policy": "preserve_source",
            "review_status": "approved",
        }]


SQL = ("SELECT v.operator, COUNT(DISTINCT f.id) FROM astra.fixtures f "
       "LEFT JOIN astra.vessels v ON f.vessel_id = v.id GROUP BY v.operator")


def required(to_column="id"):
    return [{
        "from_schema": "astra", "from_table": "astra.fixtures", "from_column": "vessel_id",
        "to_schema": "astra", "to_table": "astra.vessels", "to_column": to_column,
        "cardinality": "many-to-one", "join_policy": "unconfigured",
    }]


def test_qualified_semantic_identity_matches_verified_grant():
    result = asyncio.run(authorize_published_joins(Metadata(), 27, SQL, required()))
    assert result.allowed, result.reasons
    assert result.verified_grants[0]["join_policy"] == "preserve_source"


def test_wrong_join_key_remains_denied():
    result = asyncio.run(authorize_published_joins(Metadata(), 27, SQL, required("imo")))
    assert not result.allowed


def test_join_type_must_obey_published_policy():
    sql = SQL.replace("LEFT JOIN", "INNER JOIN")
    result = asyncio.run(authorize_published_joins(Metadata(), 27, sql, required()))
    assert not result.allowed
