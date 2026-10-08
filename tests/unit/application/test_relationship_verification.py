from datapilot.application.relationship_verification import preflight_relationship


def fixtures():
    review = dict(from_schema="demo", from_table="events", from_column="asset_id",
                  to_schema="demo", to_table="assets", to_column="id",
                  cardinality="many_to_one", review_status="approved")
    catalog = [
        dict(schema_name="demo", table_name="events", columns=[dict(name="asset_id", data_type="integer", is_primary_key=False)]),
        dict(schema_name="demo", table_name="assets", columns=[dict(name="id", data_type="integer", is_primary_key=True)]),
    ]
    fk = [dict(schema_name="demo", table_name="events", from_column="asset_id", referenced_table="assets", to_column="id")]
    return review, catalog, fk


def test_valid_structure_still_not_publishable_without_live_verification():
    result = preflight_relationship(*fixtures())
    assert result.structurally_valid
    assert not result.live_cardinality_verified
    assert not result.publishable


def test_missing_unique_target_blocks_structure():
    review, catalog, fk = fixtures()
    catalog[1]["columns"][0]["is_primary_key"] = False
    result = preflight_relationship(review, catalog, fk)
    assert not result.structurally_valid
    assert not result.publishable


def test_missing_fk_blocks_structure():
    review, catalog, _ = fixtures()
    assert not preflight_relationship(review, catalog, []).structurally_valid


def test_unapproved_relationship_blocks_structure():
    review, catalog, fk = fixtures()
    review["review_status"] = "rejected"
    assert not preflight_relationship(review, catalog, fk).structurally_valid


def test_incompatible_types_block_structure():
    review, catalog, fk = fixtures()
    catalog[1]["columns"][0]["data_type"] = "uuid"
    assert not preflight_relationship(review, catalog, fk).structurally_valid
