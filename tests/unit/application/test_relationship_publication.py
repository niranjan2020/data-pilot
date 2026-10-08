from datapilot.application.relationship_publication import assess_relationship_publication


def eligible(**overrides):
    args = dict(
        review=dict(review_status="approved", cardinality="many_to_one", join_policy="preserve_source"),
        structural_valid=True, live_cardinality_verified=True, cardinality_holds=True,
        referential_integrity_checked=True, unmatched_references=False,
        nullable_references=True, policy_enforced_by_sql_governance=True,
    )
    args.update(overrides)
    return assess_relationship_publication(**args)


def test_complete_evidence_can_be_eligible():
    assert eligible().eligible


def test_sql_governance_must_enforce_join_policy():
    result = eligible(policy_enforced_by_sql_governance=False)
    assert not result.eligible
    assert any("SQL governance" in reason for reason in result.reasons)


def test_missing_join_policy_blocks_publication():
    assert not eligible(review=dict(review_status="approved", cardinality="many_to_one", join_policy="unconfigured")).eligible


def test_stale_live_evidence_blocks_publication():
    assert not eligible(live_cardinality_verified=False).eligible


def test_missing_integrity_evidence_blocks_publication():
    assert not eligible(referential_integrity_checked=False, unmatched_references=None).eligible


def test_unmatched_references_block_publication():
    assert not eligible(unmatched_references=True).eligible


def test_many_to_many_is_not_fanout_safe():
    assert not eligible(review=dict(review_status="approved", cardinality="many_to_many", join_policy="preserve_source")).eligible


def test_unapproved_relationship_blocks_publication():
    assert not eligible(review=dict(review_status="rejected", cardinality="many_to_one", join_policy="preserve_source")).eligible
