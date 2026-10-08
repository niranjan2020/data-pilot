"""Opt-in PostgreSQL lifecycle test for reviewed relationship verification.

Set DATAPILOT_TEST_METADATA_DATABASE_URL to a disposable PostgreSQL database.
Never run against a production or shared metadata catalog.
"""

import os
import uuid

import pytest

from datapilot.application.relationship_evidence import review_fingerprint
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    not os.getenv("DATAPILOT_TEST_METADATA_DATABASE_URL"),
    reason="Requires disposable DATAPILOT_TEST_METADATA_DATABASE_URL",
)
async def test_review_verify_retrieve_change_invalidate():
    url = os.environ["DATAPILOT_TEST_METADATA_DATABASE_URL"]
    provider = PostgreSQLMetadataProvider(url)
    source_id = None
    try:
        await provider.initialize()
        pool = await provider._get_pool()
        # A dedicated test database is mandatory: this test mutates catalog rows.
        # Never infer safety from a localhost host name or an existing dev database.
        from urllib.parse import urlparse
        db_name = urlparse(url).path.lstrip("/").lower()
        if not (db_name.endswith("_test") or db_name.startswith("test_")):
            pytest.skip("Use a dedicated database named *_test or test_* for integration tests.")
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO datapilot_catalog.data_sources
                    (name, provider, host, port, database_name, username)
                    VALUES (%s, 'postgresql', 'localhost', 5432, 'test', 'test')
                    RETURNING id""",
                    (f"verification_test_{uuid.uuid4().hex}",),
                )
                source_id = (await cur.fetchone())[0]

        review = {
            "from_schema": "demo", "from_table": "children",
            "from_column": "parent_id", "to_schema": "demo",
            "to_table": "parents", "to_column": "id",
            "cardinality": "many_to_one", "review_status": "approved",
            "join_policy": "matched_only", "description": "",
        }
        await provider.save_reviewed_relationship(source_id, review)
        record = {"structurally_valid": True, "live_cardinality_verified": True,
                  "cardinality_holds": True, "referential_integrity_checked": True,
                  "unmatched_references": False, "nullable_references": False,
                  "publishable": False}
        assert await provider.save_relationship_verification(source_id, review, record)
        stored = await provider.get_relationship_verification(source_id, review)
        assert stored is not None
        assert stored["review_fingerprint"] == review_fingerprint(review)
        assert stored["verified_at"]
        assert stored["publishable"] is False

        changed = {**review, "join_policy": "preserve_source"}
        assert not await provider.save_relationship_verification(source_id, changed, record)
        await provider.save_reviewed_relationship(source_id, changed)
        assert await provider.get_relationship_verification(source_id, changed) is None
        assert await provider.get_relationship_verification(source_id, review) is None

        assert await provider.save_relationship_verification(source_id, changed, record)
        assert await provider.get_relationship_verification(source_id, changed) is not None
        # Saving an identical review must also require fresh verification.
        await provider.save_reviewed_relationship(source_id, changed)
        assert await provider.get_relationship_verification(source_id, changed) is None
    finally:
        if source_id is not None:
            pool = await provider._get_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM datapilot_catalog.data_sources WHERE id=%s",
                        (source_id,),
                    )
        await provider.close()
