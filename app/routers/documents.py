from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import PipelineResult, SourceDocument, SourceDocumentCreate
from app.services import pipeline


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=SourceDocument)
def create_document(payload: SourceDocumentCreate) -> SourceDocument:
    return pipeline.create_document(payload)


@router.get("", response_model=list[SourceDocument])
def list_documents() -> list[SourceDocument]:
    return pipeline.list_documents()


@router.get("/{document_id}", response_model=SourceDocument)
def get_document(document_id: str) -> SourceDocument:
    try:
        return pipeline.get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/generate", response_model=PipelineResult)
def generate_document_cards(document_id: str) -> PipelineResult:
    try:
        return pipeline.run_pipeline(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{document_id}/knowledge-points")
def list_knowledge_points(document_id: str):
    return pipeline.list_knowledge_points(document_id)


@router.get("/{document_id}/cards")
def list_document_cards(document_id: str, status: str | None = None):
    return pipeline.list_cards(document_id=document_id, status=status)
