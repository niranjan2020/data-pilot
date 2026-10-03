"""Semantic-model administration endpoints."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from datapilot.core.config import get_settings
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.semantic.qdrant import QdrantSemanticIndex

router=APIRouter(prefix="/api/admin/semantic",tags=["Admin - Semantic Model"])

class SemanticSearchRequest(BaseModel):
    source_name:str=Field(min_length=1)
    question:str=Field(min_length=1)
    limit:int=Field(default=8,ge=1,le=25)

class DatasetSemanticRequest(BaseModel):
    source_name:str=Field(min_length=1)
    schema_name:str=Field(min_length=1)
    table_name:str=Field(min_length=1)
    description:Optional[str]=None
    business_meaning:Optional[str]=None
    grain:Optional[str]=None
    identity_semantics:Optional[str]=None
    aliases:list[str]=Field(default_factory=list)
    use_cases:list[str]=Field(default_factory=list)
    query_constraints:list[str]=Field(default_factory=list)

class AttributeRequest(BaseModel):
    name:str=Field(min_length=1)
    description:Optional[str]=None
    column_name:str=Field(min_length=1)
    synonyms:list[str]=Field(default_factory=list)
    operators:list[str]=Field(default_factory=lambda:["="])

class BusinessRuleRequest(BaseModel):
    source_name:str=Field(min_length=1)
    name:str=Field(min_length=1)
    description:str=Field(min_length=1)
    rule_type:str=Field(pattern="^(definition|filter|calculation|interpretation)$")
    entity_id:Optional[int]=None
    metric_id:Optional[int]=None
    priority:int=Field(default=100,ge=1,le=1000)
    enabled:bool=True
    keywords:list[str]=Field(default_factory=list)

class MetricRequest(BaseModel):
    source_name:str=Field(min_length=1)
    name:str=Field(min_length=1)
    description:Optional[str]=None
    entity_id:int
    attribute_name:str=Field(min_length=1)
    aggregation:str=Field(pattern="^(sum|count|count_distinct|avg|min|max)$")
    format:str=Field(default="number",pattern="^(number|currency|percent|integer)$")
    synonyms:list[str]=Field(default_factory=list)

class RelationshipRequest(BaseModel):
    source_name:str=Field(min_length=1)
    name:str=Field(min_length=1)
    from_entity_id:int
    from_column:str=Field(min_length=1)
    to_entity_id:int
    to_column:str=Field(min_length=1)
    cardinality:str=Field(pattern="^(one-to-one|one-to-many|many-to-one|many-to-many)$")
    description:Optional[str]=None

class EntityRequest(BaseModel):
    source_name:str=Field(min_length=1)
    name:str=Field(min_length=1)
    description:Optional[str]=None
    schema_name:str=Field(min_length=1)
    table_name:str=Field(min_length=1)
    key_column:str=Field(min_length=1)
    display_column:Optional[str]=None
    synonyms:list[str]=Field(default_factory=list)
    attributes:list[AttributeRequest]=Field(default_factory=list)

async def sync_semantic_index(
    p: PostgreSQLMetadataProvider, source_name: str, source_id: int
) -> tuple[str, Optional[str]]:
    """Synchronize the source semantic partition after PostgreSQL has committed.

    PostgreSQL remains authoritative. A Qdrant failure never rolls back the saved
    semantic configuration; callers report the index as stale so it can be rebuilt.
    """
    try:
        datasets=await p.list_semantic_datasets(source_id)
        entities=await p.list_semantic_entities(source_id)
        relationships=await p.list_semantic_relationships(source_id)
        metrics=await p.list_semantic_metrics(source_id)
        rules=await p.list_business_rules(source_id)
        index=semantic_index()
        docs=index.build_documents(
            source_name, entities, relationships, metrics, rules, datasets=datasets
        )
        # Rebuild the source partition for dependency correctness. The index adapter
        # also supports stable per-document upserts; targeted dependency sync can
        # replace this implementation without changing the API contract.
        await __import__("asyncio").to_thread(index.rebuild, source_name, docs)
        return "indexed", None
    except Exception as exc:
        return "index_stale", type(exc).__name__

def provider()->PostgreSQLMetadataProvider:
    settings=get_settings()
    if not settings.metadata_database_url:
        raise HTTPException(503,"METADATA_DATABASE_URL is required")
    return PostgreSQLMetadataProvider(settings.metadata_database_url,settings.metadata_database_pool_size)

@router.get("/{source_name}/catalog")
async def semantic_catalog(source_name:str):
    p=provider()
    try:
        source_id=await p.get_data_source_id(source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        return {"source_name":source_name,"tables":await p.list_catalog_tables(source_id),
                "entities":await p.list_semantic_entities(source_id),
                "relationships":await p.list_semantic_relationships(source_id)}
    finally: await p.close()

@router.get("/{source_name}/datasets")
async def semantic_datasets(source_name:str):
    p=provider()
    try:
        source_id=await p.get_data_source_id(source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        return {"source_name":source_name,
                "tables":await p.list_catalog_tables(source_id),
                "datasets":await p.list_semantic_datasets(source_id)}
    finally: await p.close()

@router.post("/datasets")
async def save_dataset(payload:DatasetSemanticRequest):
    p=provider()
    try:
        source_id=await p.get_data_source_id(payload.source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        dataset_id=await p.save_semantic_dataset(
            data_source_id=source_id,
            schema_name=payload.schema_name,
            table_name=payload.table_name,
            description=payload.description,
            business_meaning=payload.business_meaning,
            grain=payload.grain,
            identity_semantics=payload.identity_semantics,
            aliases=payload.aliases,
            use_cases=payload.use_cases,
            query_constraints=payload.query_constraints,
        )
        index_status,index_error=await sync_semantic_index(p,payload.source_name,source_id)
        return {"id":dataset_id,"message":"Dataset semantics saved","index_status":index_status,"index_error":index_error}
    finally: await p.close()

@router.post("/entities")
async def save_entity(payload:EntityRequest):
    p=provider()
    try:
        source_id=await p.get_data_source_id(payload.source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        entity_id=await p.save_semantic_entity(
            data_source_id=source_id,name=payload.name,description=payload.description,
            schema_name=payload.schema_name,table_name=payload.table_name,
            key_column=payload.key_column,display_column=payload.display_column,
            synonyms=payload.synonyms,attributes=[a.model_dump() for a in payload.attributes])
        index_status,index_error=await sync_semantic_index(p,payload.source_name,source_id)
        return {"id":entity_id,"message":"Semantic entity saved","index_status":index_status,"index_error":index_error}
    finally: await p.close()

@router.post("/relationships")
async def save_relationship(payload:RelationshipRequest):
    p=provider()
    try:
        source_id=await p.get_data_source_id(payload.source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        relationship_id=await p.save_semantic_relationship(
            data_source_id=source_id,name=payload.name,
            from_entity_id=payload.from_entity_id,from_column=payload.from_column,
            to_entity_id=payload.to_entity_id,to_column=payload.to_column,
            cardinality=payload.cardinality,description=payload.description)
        index_status,index_error=await sync_semantic_index(p,payload.source_name,source_id)
        return {"id":relationship_id,"message":"Semantic relationship saved","index_status":index_status,"index_error":index_error}
    finally: await p.close()

@router.get("/{source_name}/metrics")
async def semantic_metrics(source_name:str):
    p=provider()
    try:
        source_id=await p.get_data_source_id(source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        return {"source_name":source_name,"entities":await p.list_semantic_entities(source_id),
                "metrics":await p.list_semantic_metrics(source_id)}
    finally: await p.close()

@router.post("/metrics")
async def save_metric(payload:MetricRequest):
    p=provider()
    try:
        source_id=await p.get_data_source_id(payload.source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        metric_id=await p.save_semantic_metric(
            data_source_id=source_id,name=payload.name,description=payload.description,
            entity_id=payload.entity_id,attribute_name=payload.attribute_name,
            aggregation=payload.aggregation,format=payload.format,synonyms=payload.synonyms)
        index_status,index_error=await sync_semantic_index(p,payload.source_name,source_id)
        return {"id":metric_id,"message":"Semantic metric saved","index_status":index_status,"index_error":index_error}
    finally: await p.close()

@router.get("/{source_name}/business-rules")
async def business_rules(source_name:str):
    p=provider()
    try:
        source_id=await p.get_data_source_id(source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        return {"source_name":source_name,
                "entities":await p.list_semantic_entities(source_id),
                "metrics":await p.list_semantic_metrics(source_id),
                "rules":await p.list_business_rules(source_id)}
    finally: await p.close()

@router.post("/business-rules")
async def save_business_rule(payload:BusinessRuleRequest):
    p=provider()
    try:
        source_id=await p.get_data_source_id(payload.source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        rule_id=await p.save_business_rule(
            data_source_id=source_id,name=payload.name,description=payload.description,
            rule_type=payload.rule_type,entity_id=payload.entity_id,metric_id=payload.metric_id,
            priority=payload.priority,enabled=payload.enabled,keywords=payload.keywords)
        index_status,index_error=await sync_semantic_index(p,payload.source_name,source_id)
        return {"id":rule_id,"message":"Business rule saved","index_status":index_status,"index_error":index_error}
    finally: await p.close()

def semantic_index()->QdrantSemanticIndex:
    settings=get_settings()
    return QdrantSemanticIndex(settings.qdrant_url,settings.qdrant_collection,settings.embedding_model)

@router.post("/{source_name}/index/rebuild")
async def rebuild_semantic_index(source_name:str):
    p=provider()
    try:
        source_id=await p.get_data_source_id(source_name)
        if source_id is None: raise HTTPException(404,"Data source not found. Discover it first.")
        datasets=await p.list_semantic_datasets(source_id)
        entities=await p.list_semantic_entities(source_id)
        relationships=await p.list_semantic_relationships(source_id)
        metrics=await p.list_semantic_metrics(source_id)
        rules=await p.list_business_rules(source_id)
        index=semantic_index()
        docs=index.build_documents(
            source_name, entities, relationships, metrics, rules, datasets=datasets
        )
        count=await __import__("asyncio").to_thread(index.rebuild,source_name,docs)
        return {"source_name":source_name,"indexed":count,"message":"Semantic index rebuilt from PostgreSQL catalog"}
    finally: await p.close()

@router.post("/search")
async def semantic_search(payload:SemanticSearchRequest):
    index=semantic_index()
    try:
        results=await index.search(payload.source_name,payload.question,payload.limit)
    except Exception as exc:
        raise HTTPException(503,f"Semantic index unavailable: {type(exc).__name__}") from exc
    return {"source_name":payload.source_name,"question":payload.question,"results":results}
