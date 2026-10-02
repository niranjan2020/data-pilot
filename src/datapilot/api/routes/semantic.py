"""Semantic-model administration endpoints."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from datapilot.core.config import get_settings
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider

router=APIRouter(prefix="/api/admin/semantic",tags=["Admin - Semantic Model"])

class AttributeRequest(BaseModel):
    name:str=Field(min_length=1)
    description:Optional[str]=None
    column_name:str=Field(min_length=1)
    synonyms:list[str]=Field(default_factory=list)
    operators:list[str]=Field(default_factory=lambda:["="])

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
                "entities":await p.list_semantic_entities(source_id)}
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
        return {"id":entity_id,"message":"Semantic entity saved"}
    finally: await p.close()
