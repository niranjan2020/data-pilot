"""First-run onboarding status API."""

import logging
import hashlib
import json

_logger = logging.getLogger("datapilot.setup")

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr, Field

from datapilot.application.setup_state import SetupStatus, derive_setup_status
from datapilot.application.semantic_bootstrap import DatasetProposal, propose_datasets
from datapilot.application.relationship_bootstrap import RelationshipCandidate, propose_relationships
from datapilot.application.relationship_verification import preflight_relationship
from datapilot.application.relationship_publication import assess_relationship_publication
from datapilot.application.relationship_evidence import review_fingerprint
from datapilot.infrastructure.database.relationship_cardinality import verify_live_cardinality
from datapilot.infrastructure.database.relationship_integrity import verify_referential_integrity
from datapilot.application.data_source_onboarding import PostgreSQLConnectionInput, test_postgresql_connection
from datapilot.domain.interfaces.ai_configuration import (
    AIProviderConfiguration,
    AIProviderKind,
    AIProviderSecretInput,
)
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore
from datapilot.infrastructure.secrets.local_data_source import LocalDataSourceSecretStore
from datapilot.infrastructure.database.saved_connection import open_saved_data_source

router = APIRouter(prefix="/api/setup", tags=["Setup"])


class AIProviderSetupRequest(AIProviderConfiguration):
    api_key: str = ""


async def _setup_metadata(request: Request):
    settings = request.app.state.settings
    metadata = getattr(request.app.state, "setup_metadata", None)
    if metadata is not None:
        return metadata, False
    if not settings.metadata_database_url:
        raise HTTPException(status_code=503, detail="Platform metadata storage is not configured.")
    return PostgreSQLMetadataProvider(
        settings.metadata_database_url,
        pool_size=settings.metadata_database_pool_size,
    ), True


@router.get("/ai-provider", response_model=AIProviderConfiguration)
async def get_ai_provider(request: Request) -> AIProviderConfiguration:
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "ai_secret_store", LocalEnvAIProviderSecretStore())
    try:
        configuration = await metadata.get_ai_provider_configuration()
        if configuration is None:
            raise HTTPException(status_code=404, detail="AI provider is not configured.")
        has_secret = await secret_store.has_ai_provider_secret(configuration.provider)
        return configuration.model_copy(update={"credential_configured": has_secret})
    finally:
        if owns_metadata:
            await metadata.close()


@router.put("/ai-provider", response_model=AIProviderConfiguration)
async def configure_ai_provider(payload: AIProviderSetupRequest, request: Request) -> AIProviderConfiguration:
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "ai_secret_store", LocalEnvAIProviderSecretStore())
    try:
        # Any provider/model change invalidates previously validated readiness before
        # persisting or testing the replacement configuration.
        await metadata.update_setup_facts(ai_provider_ready=False)
        safe = AIProviderConfiguration(
            provider=payload.provider,
            model=payload.model,
            endpoint=payload.endpoint,
        )
        saved = await metadata.save_ai_provider_configuration(safe)
        if payload.api_key.strip():
            await secret_store.put_ai_provider_secret(
                payload.provider,
                AIProviderSecretInput(api_key=payload.api_key),
            )
        has_secret = await secret_store.has_ai_provider_secret(payload.provider)
        validator = getattr(request.app.state, "ai_provider_validator", None)
        validated = False
        if has_secret and validator is not None:
            try:
                await validator.validate(saved)
                validated = True
            except Exception as exc:
                await metadata.update_setup_facts(ai_provider_ready=False)
                raise HTTPException(status_code=422, detail="AI provider validation failed.") from exc
        await metadata.update_setup_facts(ai_provider_ready=validated)
        return saved.model_copy(update={"credential_configured": has_secret})
    finally:
        if owns_metadata:
            await metadata.close()


class SystemReadiness(BaseModel):
    ready: bool
    setup_ready: bool
    metadata_storage: str
    ai_provider: str
    data_source: str


@router.get("/readiness", response_model=SystemReadiness)
async def system_readiness(request: Request) -> SystemReadiness:
    """Report product readiness from persisted onboarding facts, not static env presence."""
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        facts = await metadata.get_setup_facts()
        setup = derive_setup_status(**facts)
        return SystemReadiness(
            ready=setup.ready,
            setup_ready=setup.ready,
            metadata_storage="ready",
            ai_provider="ready" if facts["ai_provider_ready"] else "not_ready",
            data_source="ready" if facts["data_source_ready"] else "not_ready",
        )
    finally:
        if owns_metadata:
            await metadata.close()


@router.get("/status", response_model=SetupStatus)
async def setup_status(request: Request) -> SetupStatus:
    settings = request.app.state.settings
    if not settings.metadata_database_url:
        raise HTTPException(
            status_code=503,
            detail="Platform metadata storage is not configured.",
        )
    metadata = getattr(request.app.state, "setup_metadata", None)
    owns_metadata = metadata is None
    if metadata is None:
        metadata = PostgreSQLMetadataProvider(
            settings.metadata_database_url,
            pool_size=settings.metadata_database_pool_size,
        )
    try:
        facts = await metadata.get_setup_facts()
        return derive_setup_status(**facts)
    finally:
        if owns_metadata:
            await metadata.close()


class ConnectionTestResult(BaseModel):
    connected: bool


@router.post("/data-source/test", response_model=ConnectionTestResult)
async def test_data_source_connection(payload: PostgreSQLConnectionInput) -> ConnectionTestResult:
    """Validate customer PostgreSQL connectivity without persisting credentials or readiness."""
    try:
        connected = await test_postgresql_connection(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.") from exc
    if not connected:
        raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.")
    return ConnectionTestResult(connected=True)


class SavedDataSource(BaseModel):
    id: int
    name: str
    connected: bool


@router.post("/data-source", response_model=SavedDataSource)
async def save_setup_data_source(payload: PostgreSQLConnectionInput, request: Request) -> SavedDataSource:
    """Validate, persist non-secret metadata and encrypted credential, then advance."""
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "data_source_secret_store", None)
    if secret_store is None:
        secret_store = LocalDataSourceSecretStore()
    try:
        await metadata.update_setup_facts(data_source_ready=False, data_selection_ready=False, semantic_model_ready=False)
        try:
            connected = await test_postgresql_connection(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.") from exc
        if not connected:
            raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.")
        source_id = await metadata.save_data_source(
            name=payload.name, provider="postgresql", host=payload.host,
            port=payload.port, database_name=payload.database,
            username=payload.username, sslmode=payload.sslmode,
        )
        try:
            secret_store.put(source_id, payload.password.get_secret_value())
            if secret_store.resolve_for_runtime(source_id) != payload.password.get_secret_value():
                raise RuntimeError("Credential verification failed")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Unable to persist datasource credentials.") from exc
        await metadata.set_active_data_source_id(source_id)
        await metadata.update_setup_facts(data_source_ready=True)
        return SavedDataSource(id=source_id, name=payload.name, connected=True)
    finally:
        if owns_metadata:
            await metadata.close()



@router.get("/data-sources")
async def list_setup_data_sources(request: Request):
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        return await metadata.list_saved_data_sources()
    finally:
        if owns_metadata:
            await metadata.close()


@router.post("/data-source/{source_id}/activate")
async def activate_setup_data_source(source_id: int, request: Request):
    """Activate only a stored, reachable connection with an available credential."""
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    provider = None
    try:
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            if not await provider.ping():
                raise ValueError("Connection unavailable")
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Saved datasource cannot be connected. Reconfigure its credentials if needed.") from exc
        await metadata.set_active_data_source_id(source_id)
        await metadata.update_setup_facts(data_source_ready=True, data_selection_ready=False, semantic_model_ready=False)
        record = await metadata.get_data_source(source_id)
        return {"id": record["id"], "name": record["name"], "provider": record["provider"]}
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()


class DataSourceCredentialRotation(BaseModel):
    password: SecretStr


@router.put("/data-source/{source_id}/credential")
async def rotate_saved_data_source_credential(
    source_id: int, payload: DataSourceCredentialRotation, request: Request
):
    """Validate a replacement password before atomically replacing the saved secret."""
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    try:
        record = await metadata.get_data_source(source_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Saved datasource not found.")
        if record["provider"] != "postgresql":
            raise HTTPException(status_code=422, detail="Unsupported datasource provider.")
        replacement = PostgreSQLConnectionInput(
            name=record["name"], host=record["host"], port=record["port"],
            database=record["database"], username=record["username"],
            sslmode=record["sslmode"], password=payload.password,
        )
        try:
            connected = await test_postgresql_connection(replacement)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Replacement credential validation failed; existing credential unchanged.") from exc
        if not connected:
            raise HTTPException(status_code=422, detail="Replacement credential validation failed; existing credential unchanged.")
        try:
            store.put(source_id, payload.password.get_secret_value())
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Unable to save replacement credential.") from exc
        return {"updated": True, "connected": True}
    finally:
        if owns_metadata:
            await metadata.close()


class DataSourceLoginUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr


@router.put("/data-source/{source_id}/login")
async def update_saved_data_source_login(
    source_id: int, payload: DataSourceLoginUpdate, request: Request
):
    """Validate username/password together before replacing either saved value."""
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    try:
        record = await metadata.get_data_source(source_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Saved datasource not found.")
        if record["provider"] != "postgresql":
            raise HTTPException(status_code=422, detail="Unsupported datasource provider.")
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=422, detail="Username must not be empty.")
        replacement = PostgreSQLConnectionInput(
            name=record["name"], host=record["host"], port=record["port"],
            database=record["database"], username=username,
            sslmode=record["sslmode"], password=payload.password,
        )
        try:
            connected = await test_postgresql_connection(replacement)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="New login validation failed; saved login unchanged.") from exc
        if not connected:
            raise HTTPException(status_code=422, detail="New login validation failed; saved login unchanged.")
        old_password = store.resolve_for_runtime(source_id)
        if old_password is None:
            raise HTTPException(status_code=503, detail="Existing datasource secret unavailable.")
        try:
            await metadata.update_data_source_username(source_id, username)
            store.put(source_id, payload.password.get_secret_value())
        except Exception as exc:
            try:
                await metadata.update_data_source_username(source_id, record["username"])
                store.put(source_id, old_password)
            except Exception:
                _logger.exception("Datasource login rollback failed for source id %s", source_id)
                raise HTTPException(status_code=503, detail="Credential update failed; recovery required.") from exc
            raise HTTPException(status_code=503, detail="Credential update failed; saved login restored.") from exc
        return {"updated": True, "connected": True}
    finally:
        if owns_metadata:
            await metadata.close()


@router.get("/data-source/{source_id}/details")
async def saved_data_source_details(source_id: int, request: Request):
    """Read non-secret connection settings without returning stored credentials."""
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        record = await metadata.get_data_source(source_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Saved datasource not found.")
        return record
    finally:
        if owns_metadata:
            await metadata.close()


@router.post("/data-source/{source_id}/test")
async def test_saved_data_source(source_id: int, request: Request):
    """Test the stored datasource and credential without mutating setup readiness."""
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    provider = None
    try:
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            connected = await provider.ping()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Saved datasource connection failed. Check connectivity and stored credentials.") from exc
        if not connected:
            raise HTTPException(status_code=422, detail="Saved datasource connection failed. Check connectivity and stored credentials.")
        return {"connected": True}
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()


@router.get("/data-source/active")
async def active_setup_data_source(request: Request):
    """Return the selected non-secret datasource identity after restart."""
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        source_id = await metadata.get_active_data_source_id()
        if source_id is None:
            raise HTTPException(status_code=404, detail="No active datasource selected.")
        record = await metadata.get_data_source(source_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Active datasource no longer exists.")
        return {"id": record["id"], "name": record["name"], "provider": record["provider"]}
    finally:
        if owns_metadata:
            await metadata.close()


class SavedDiscoveryResponse(BaseModel):
    data_source_id: int
    schemas: list[str]
    tables: int
    persisted: bool


@router.post("/data-source/{source_id}/discover", response_model=SavedDiscoveryResponse)
async def discover_saved_source(source_id: int, request: Request) -> SavedDiscoveryResponse:
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    provider = None
    stage = "connection"
    try:
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            stage = "schema_listing"
            names = await provider.list_schemas()
            stage = "schema_introspection"
            schemas = [await provider.introspect_schema(name) for name in names]
            stage = "metadata_persistence"
            for schema in schemas:
                # Deterministic schema fingerprint: identical structures reuse snapshots.
                payload = schema.model_dump(mode="json", exclude={"version"})
                schema.version = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
                ).hexdigest()[:24]
                await metadata.save_schema(schema, data_source_id=source_id)
            return SavedDiscoveryResponse(
                data_source_id=source_id,
                schemas=names,
                tables=sum(len(schema.tables) for schema in schemas),
                persisted=True,
            )
        except Exception as exc:
            # Never log exception messages: drivers can include connection details.
            _logger.error("Saved datasource discovery failed: stage=%s error_type=%s", stage, type(exc).__name__)
            raise HTTPException(status_code=422, detail="Saved datasource discovery failed at " + stage + ".") from exc
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()


class DatasetSelectionItem(BaseModel):
    schema_name: str
    table_name: str


class DatasetSelectionRequest(BaseModel):
    datasets: list[DatasetSelectionItem]


@router.get("/data-source/{source_id}/datasets")
async def list_discovered_datasets(source_id: int, request: Request):
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Select this datasource before browsing datasets.")
        return {
            "datasets": await metadata.list_catalog_tables(source_id),
            "selected": await metadata.get_selected_datasets(source_id),
        }
    finally:
        if owns:
            await metadata.close()


@router.put("/data-source/{source_id}/datasets")
async def approve_discovered_datasets(source_id: int, payload: DatasetSelectionRequest, request: Request):
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        try:
            await metadata.replace_selected_datasets(source_id, [item.model_dump() for item in payload.datasets])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Select at least one valid discovered dataset.") from exc
        await metadata.update_setup_facts(data_selection_ready=True, semantic_model_ready=False)
        return {"selected_count": len(set((item.schema_name, item.table_name) for item in payload.datasets)), "ready": True}
    finally:
        if owns:
            await metadata.close()


@router.get("/data-source/{source_id}/semantic-proposals", response_model=list[DatasetProposal])
async def preview_semantic_proposals(source_id: int, request: Request):
    """Preview non-authoritative, schema-grounded drafts for approved datasets."""
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        if not selected:
            raise HTTPException(status_code=409, detail="Approve datasets before semantic bootstrap.")
        catalog = await metadata.list_catalog_tables(source_id)
        try:
            return propose_datasets(catalog, selected)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Selected datasets require schema rediscovery.") from exc
    finally:
        if owns:
            await metadata.close()


class SemanticDraftApproval(BaseModel):
    schema_name: str
    table_name: str
    description: str = Field(min_length=1, max_length=4000)
    business_meaning: str = Field(min_length=1, max_length=4000)
    grain: str = Field(min_length=1, max_length=1000)
    aliases: list[str] = Field(default_factory=list)


@router.get("/data-source/{source_id}/semantic-approved")
async def list_approved_setup_semantics(source_id: int, request: Request):
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        allowed = {(s["schema_name"], s["table_name"]) for s in selected}
        records = await metadata.list_semantic_datasets(source_id)
        return [record for record in records if (record["schema_name"], record["table_name"]) in allowed]
    finally:
        if owns:
            await metadata.close()


@router.put("/data-source/{source_id}/semantic-approved")
async def approve_setup_semantic_draft(source_id: int, payload: SemanticDraftApproval, request: Request):
    """Explicit human approval of dataset meaning; does not imply indexing readiness."""
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        if (payload.schema_name, payload.table_name) not in {
            (item["schema_name"], item["table_name"]) for item in selected
        }:
            raise HTTPException(status_code=422, detail="Only selected discovered datasets can be approved.")
        dataset_id = await metadata.save_semantic_dataset(
            data_source_id=source_id,
            schema_name=payload.schema_name,
            table_name=payload.table_name,
            description=payload.description.strip(),
            business_meaning=payload.business_meaning.strip(),
            grain=payload.grain.strip(),
            identity_semantics=None,
            aliases=payload.aliases,
            use_cases=[],
            query_constraints=[],
        )
        # Semantic readiness remains false until all selected datasets are approved
        # and the semantic indexing workflow has completed.
        return {"dataset_id": dataset_id, "status": "approved", "indexed": False}
    finally:
        if owns:
            await metadata.close()


@router.post("/data-source/{source_id}/semantic-review/complete")
async def complete_semantic_review(source_id: int, request: Request):
    """Finish human dataset review; do not publish any relationship."""
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        facts = await metadata.get_setup_facts()
        if not (facts["ai_provider_ready"] and facts["data_source_ready"] and facts["data_selection_ready"]):
            raise HTTPException(status_code=409, detail="Complete provider, datasource and dataset selection first.")
        selected = await metadata.get_selected_datasets(source_id)
        if not selected:
            raise HTTPException(status_code=409, detail="Select at least one discovered dataset.")
        approved = await metadata.list_semantic_datasets(source_id)
        approved_keys = {
            (item["schema_name"], item["table_name"])
            for item in approved
            if all(str(item.get(field) or "").strip() for field in ("description", "business_meaning", "grain"))
        }
        missing = sorted({
            (item["schema_name"], item["table_name"]) for item in selected
        } - approved_keys)
        if missing:
            raise HTTPException(
                status_code=409,
                detail="Approve dataset description, business meaning and row grain for every selected dataset: "
                       + ", ".join(f"{schema}.{table}" for schema, table in missing),
            )
        # This is an explicit human-reviewed baseline, not a claim that
        # semantic indexing, metric governance or relationship publication ran.
        await metadata.update_setup_facts(semantic_model_ready=True)
        return {"ready": True, "reviewed_datasets": len(approved_keys),
                "relationships_published": False, "semantic_indexing_verified": False}
    finally:
        if owns:
            await metadata.close()


@router.get("/data-source/{source_id}/relationship-proposals", response_model=list[RelationshipCandidate])
async def preview_relationship_proposals(source_id: int, request: Request):
    """Suggest joins without promoting naming heuristics to verified constraints."""
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        if not selected:
            raise HTTPException(status_code=409, detail="Approve datasets before relationship discovery.")
        return propose_relationships(
            await metadata.list_catalog_tables(source_id),
            selected,
            await metadata.list_catalog_foreign_keys(source_id),
        )
    finally:
        if owns:
            await metadata.close()


class RelationshipReviewInput(BaseModel):
    join_policy: str = "unconfigured"
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str
    cardinality: str
    review_status: str
    description: str = ""


@router.get("/data-source/{source_id}/relationship-reviews")
async def get_relationship_reviews(source_id: int, request: Request):
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        return await metadata.list_reviewed_relationships(source_id)
    finally:
        if owns:
            await metadata.close()


@router.get("/data-source/{source_id}/relationship-verifications")
async def list_relationship_verifications(source_id: int, request: Request):
    """Show persisted evidence for current reviews; stale evidence stays hidden."""
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        reviews = await metadata.list_reviewed_relationships(source_id)
        results = []
        for review in reviews:
            record = await metadata.get_relationship_verification(source_id, review)
            from datapilot.application.relationship_freshness import assess_verification_freshness
            freshness = assess_verification_freshness(review, record)
            results.append({
                "from_schema": review["from_schema"],
                "from_table": review["from_table"],
                "from_column": review["from_column"],
                "to_schema": review["to_schema"],
                "to_table": review["to_table"],
                "to_column": review["to_column"],
                "review_status": review["review_status"],
                "verified": record is not None,
                "evidence_current": freshness.current,
                "evidence_reasons": list(freshness.reasons),
                "verification": record,
                "governed_join_active": False,
            })
        return results
    finally:
        if owns:
            await metadata.close()


@router.put("/data-source/{source_id}/relationship-reviews")
async def save_relationship_review(source_id: int, payload: RelationshipReviewInput, request: Request):
    """Store a human decision, without automatically activating SQL joins."""
    if payload.review_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Review must be approved or rejected.")
    if payload.cardinality not in {"many_to_one", "one_to_many", "one_to_one", "many_to_many", "unknown"}:
        raise HTTPException(status_code=422, detail="Invalid relationship cardinality.")
    if payload.join_policy not in {"unconfigured", "preserve_source", "matched_only"}:
        raise HTTPException(status_code=422, detail="Invalid join policy.")
    if payload.review_status == "approved" and payload.cardinality == "unknown":
        raise HTTPException(status_code=422, detail="Confirm cardinality before approving.")
    metadata, owns = await _setup_metadata(request)
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        proposals = propose_relationships(
            await metadata.list_catalog_tables(source_id),
            selected,
            await metadata.list_catalog_foreign_keys(source_id),
        )
        identity = (payload.from_schema, payload.from_table, payload.from_column,
                    payload.to_schema, payload.to_table, payload.to_column)
        if not any((p.from_schema, p.from_table, p.from_column, p.to_schema,
                    p.to_table, p.to_column) == identity for p in proposals):
            raise HTTPException(status_code=422, detail="Relationship is not a current selected-dataset candidate.")
        await metadata.save_reviewed_relationship(source_id, payload.model_dump())
        return {"review_status": payload.review_status, "governed_join_active": False}
    finally:
        if owns:
            await metadata.close()


@router.post("/data-source/{source_id}/relationship-verification")
async def verify_reviewed_relationship(source_id: int, payload: RelationshipReviewInput, request: Request):
    """Verify a persisted human review against current schema and live data.

    Never activates a governed join. All unavailable or stale evidence fails closed.
    """
    metadata, owns = await _setup_metadata(request)
    provider = None
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        identity = ("from_schema", "from_table", "from_column", "to_schema", "to_table", "to_column")
        reviews = await metadata.list_reviewed_relationships(source_id)
        saved = next((r for r in reviews if all(r.get(k) == getattr(payload, k) for k in identity)), None)
        if saved is None:
            raise HTTPException(status_code=404, detail="Relationship review not found.")
        if saved.get("review_status") != "approved":
            raise HTTPException(status_code=409, detail="Relationship must be approved before verification.")
        if saved.get("join_policy") != payload.join_policy:
            raise HTTPException(status_code=409, detail="Join policy has changed; refresh before verification.")
        if saved.get("review_status") != payload.review_status:
            raise HTTPException(status_code=409, detail="Review decision has changed; refresh before verification.")
        if saved.get("cardinality") != payload.cardinality:
            raise HTTPException(status_code=409, detail="Review has changed; refresh before verification.")
        selected = await metadata.get_selected_datasets(source_id)
        allowed = {(r["schema_name"], r["table_name"]) for r in selected}
        if (saved["from_schema"], saved["from_table"]) not in allowed or (saved["to_schema"], saved["to_table"]) not in allowed:
            raise HTTPException(status_code=409, detail="Relationship datasets are no longer selected.")
        catalog = await metadata.list_catalog_tables(source_id)
        foreign_keys = await metadata.list_catalog_foreign_keys(source_id)
        structural = preflight_relationship(saved, catalog, foreign_keys)
        if not structural.structurally_valid:
            return {"structurally_valid": False, "live_cardinality_verified": False,
                    "cardinality_holds": False, "publishable": False, "reasons": structural.reasons}
        store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            evidence = await verify_live_cardinality(provider, saved)
        except Exception:
            _logger.warning("Relationship verification unavailable: source_id=%s", source_id)
            return {"structurally_valid": True, "live_cardinality_verified": False,
                    "cardinality_holds": False, "publishable": False,
                    "reasons": ["Live verification unavailable."]}
        integrity = None
        if evidence.checked and evidence.cardinality_holds:
            integrity = await verify_referential_integrity(provider, saved)
        reasons = [evidence.reason] if evidence.reason else []
        if integrity is not None and integrity.reason:
            reasons.append(integrity.reason)
        eligibility = assess_relationship_publication(
            saved,
            structural_valid=True,
            live_cardinality_verified=evidence.checked,
            cardinality_holds=evidence.cardinality_holds,
            referential_integrity_checked=integrity.checked if integrity else False,
            unmatched_references=integrity.unmatched_references if integrity else None,
            nullable_references=integrity.nullable_references if integrity else None,
            policy_enforced_by_sql_governance=False,
        )
        reasons.extend(eligibility.reasons)
        verification_record = {
            "structurally_valid": True,
            "live_cardinality_verified": evidence.checked,
            "cardinality_holds": evidence.cardinality_holds,
            "referential_integrity_checked": integrity.checked if integrity else False,
            "unmatched_references": integrity.unmatched_references if integrity else None,
            "nullable_references": integrity.nullable_references if integrity else None,
            "publishable": False,
            "reasons": reasons,
        }
        if not await metadata.save_relationship_verification(source_id, saved, verification_record):
            raise HTTPException(status_code=409, detail="Relationship review changed during verification; retry.")
        return {"review_fingerprint": review_fingerprint(saved), "structurally_valid": True, "live_cardinality_verified": evidence.checked,
                "cardinality_holds": evidence.cardinality_holds,
                "referential_integrity_checked": integrity.checked if integrity else False,
                "unmatched_references": integrity.unmatched_references if integrity else None,
                "nullable_references": integrity.nullable_references if integrity else None,
                "publishable": False, "reasons": reasons}
    finally:
        if provider is not None:
            await provider.close()
        if owns:
            await metadata.close()

class CategoricalProposalRequest(BaseModel):
    schema_name: str = Field(min_length=1, max_length=128)
    table_name: str = Field(min_length=1, max_length=128)
    column_name: str = Field(min_length=1, max_length=128)


@router.post("/data-source/{source_id}/categorical-proposals")
async def propose_saved_source_categorical_values(
    source_id: int, payload: CategoricalProposalRequest, request: Request
):
    """Explicit administrator proposal for one selected, discovered text column.

    Does not persist values, change onboarding readiness, or publish mappings.
    """
    metadata, owns_metadata = await _setup_metadata(request)
    provider = None
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(status_code=409, detail="Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        if (payload.schema_name, payload.table_name) not in {
            (item["schema_name"], item["table_name"]) for item in selected
        }:
            raise HTTPException(status_code=403, detail="Dataset is not approved for discovery.")
        catalog = await metadata.list_catalog_tables(source_id)
        table = next(
            (item for item in catalog if item["schema_name"] == payload.schema_name
             and item["table_name"] == payload.table_name),
            None,
        )
        if table is None:
            raise HTTPException(status_code=404, detail="Discovered dataset not found.")
        column = next((item for item in table["columns"] if item["name"] == payload.column_name), None)
        if column is None:
            raise HTTPException(status_code=404, detail="Discovered column not found.")
        if column["data_type"].lower() not in {"text", "character varying", "character", "varchar", "char"}:
            raise HTTPException(status_code=422, detail="Categorical proposals support text columns only.")
        store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            result = await provider.propose_categorical_values(
                payload.schema_name, payload.table_name, payload.column_name,
                max_values=50, timeout_seconds=2.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Categorical discovery could not be completed.") from exc
        return {
            "schema_name": payload.schema_name,
            "table_name": payload.table_name,
            "column_name": payload.column_name,
            **result,
            "published": False,
        }
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()



class ApprovedCategoricalMapping(BaseModel):
    canonical_value: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)

class PublishCategoricalMappingsRequest(CategoricalProposalRequest):
    mappings: list[ApprovedCategoricalMapping] = Field(min_length=1, max_length=50)

@router.post("/data-source/{source_id}/categorical-mappings/publish")
async def publish_saved_source_categorical_mappings(
    source_id: int, payload: PublishCategoricalMappingsRequest, request: Request
):
    """Explicit approval; publish only verified exact values on a selected dataset."""
    metadata, owns_metadata = await _setup_metadata(request)
    source = None
    try:
        if await metadata.get_active_data_source_id() != source_id:
            raise HTTPException(409, "Datasource is not active.")
        selected = await metadata.get_selected_datasets(source_id)
        if (payload.schema_name, payload.table_name) not in {
            (d["schema_name"], d["table_name"]) for d in selected
        }:
            raise HTTPException(403, "Dataset is not approved.")
        catalog = await metadata.list_catalog_tables(source_id)
        table = next((t for t in catalog if t["schema_name"] == payload.schema_name and t["table_name"] == payload.table_name), None)
        column = next((c for c in table["columns"] if c["name"] == payload.column_name), None) if table else None
        if not column or column["data_type"].lower() not in {"text", "character varying", "character", "varchar", "char"}:
            raise HTTPException(422, "A discovered text column is required.")
        store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
        try:
            source = await open_saved_data_source(metadata, store, source_id)
            discovery = await source.propose_categorical_values(
                payload.schema_name, payload.table_name, payload.column_name,
                max_values=50, timeout_seconds=2.0,
            )
        except Exception as exc:
            raise HTTPException(422, "Cannot verify current database values.") from exc
        if not discovery.get("complete"):
            raise HTTPException(409, "Discovery is incomplete; publishing is disabled.")
        verified = set(discovery.get("values") or [])
        requested = [m.canonical_value.strip() for m in payload.mappings]
        if len(requested) != len(set(requested)) or any(v not in verified for v in requested):
            raise HTTPException(422, "Selected canonical values must exactly match discovered database values.")
        try:
            count = await metadata.publish_categorical_mappings(
                data_source_id=source_id, schema_name=payload.schema_name,
                table_name=payload.table_name, column_name=payload.column_name,
                mappings=[m.model_dump() for m in payload.mappings],
            )
        except Exception as exc:
            raise HTTPException(409, "Publication failed: semantic attribute missing or mappings conflict.") from exc
        return {"published": True, "count": count, "message": "Categorical mappings published"}
    finally:
        if source is not None:
            await source.close()
        if owns_metadata:
            await metadata.close()
