"""Disposable PostgreSQL publication lifecycle: verified, expired, revoked.

Run with DATAPILOT_TEST_METADATA_DATABASE_URL pointing to *_test/test_*.
"""
import os
import uuid
from urllib.parse import urlparse

import pytest

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(not os.getenv("DATAPILOT_TEST_METADATA_DATABASE_URL"),
                    reason="Requires disposable PostgreSQL test database")
async def test_publish_reject_stale_and_revoke_on_review_change():
    url = os.environ["DATAPILOT_TEST_METADATA_DATABASE_URL"]
    db = urlparse(url).path.lstrip("/").lower()
    if not (db.endswith("_test") or db.startswith("test_")):
        pytest.skip("Requires dedicated *_test or test_* database.")
    metadata = PostgreSQLMetadataProvider(url)
    source_id = None
    keys = ("from_schema", "from_table", "from_column",
            "to_schema", "to_table", "to_column")
    review = {
        "from_schema": "demo", "from_table": "orders",
        "from_column": "customer_id", "to_schema": "demo",
        "to_table": "customers", "to_column": "id",
        "cardinality": "many_to_one", "review_status": "approved",
        "join_policy": "matched_only", "description": "",
    }
    proof = {
        "structurally_valid": True, "live_cardinality_verified": True,
        "cardinality_holds": True, "referential_integrity_checked": True,
        "unmatched_references": False, "nullable_references": False,
        "publishable": False,
    }
    try:
        await metadata.initialize()
        pool = await metadata._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO datapilot_catalog.data_sources
                    (name, provider, host, port, database_name, username)
                    VALUES (%s, 'postgresql', 'localhost', 5432, 'test', 'test')
                    RETURNING id
                """, (f"publication_test_{uuid.uuid4().hex}",))
                source_id = (await cur.fetchone())[0]

        await metadata.save_reviewed_relationship(source_id, review)
        assert not await metadata.publish_reviewed_relationship(source_id, review)
        assert await metadata.save_relationship_verification(source_id, review, proof)
        assert await metadata.publish_reviewed_relationship(source_id, review)

        async def publication_count():
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT count(*) FROM datapilot_catalog.relationship_publications
                        WHERE data_source_id=%s
                    """, (source_id,))
                    return (await cur.fetchone())[0]

        assert await publication_count() == 1
        # Expired evidence must not authorize a new publication.
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    UPDATE datapilot_catalog.relationship_verifications
                    SET verified_at=NOW() - INTERVAL '1 day'
                    WHERE data_source_id=%s
                """, (source_id,))
        assert not await metadata.publish_reviewed_relationship(source_id, review)
        assert await publication_count() == 1  # historical intent, not active authorization

        changed = {**review, "join_policy": "preserve_source"}
        assert not await metadata.publish_reviewed_relationship(source_id, changed)
        await metadata.save_reviewed_relationship(source_id, changed)
        assert await publication_count() == 0
        assert not await metadata.publish_reviewed_relationship(source_id, changed)
        assert await metadata.save_relationship_verification(source_id, changed, proof)
        assert await metadata.publish_reviewed_relationship(source_id, changed)
        assert await publication_count() == 1
        # Even an identical review update revokes the grant.
        await metadata.save_reviewed_relationship(source_id, changed)
        assert await publication_count() == 0
    finally:
        if source_id is not None:
            pool = await metadata._get_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM datapilot_catalog.data_sources WHERE id=%s",
                                      (source_id,))
        await metadata.close()
