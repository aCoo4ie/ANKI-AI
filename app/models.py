from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceType = Literal["article", "note", "code", "interview", "manual"]
KnowledgeType = Literal[
    "concept",
    "mechanism",
    "process",
    "comparison",
    "misconception",
    "application",
    "code",
    "interview",
]
Confidence = Literal["low", "medium", "high"]
CardType = Literal[
    "definition",
    "reverse",
    "mechanism",
    "compare",
    "intuition",
    "example",
    "counterexample",
    "boundary",
    "application",
    "misconception",
    "interview",
]
CardStatus = Literal["draft", "approved", "rejected", "synced"]


class SourceDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    source_type: SourceType = "note"
    deck_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class SourceDocument(SourceDocumentCreate):
    id: str
    created_at: datetime


class SourceChunk(BaseModel):
    id: str
    document_id: str
    index: int
    text: str
    start_char: int
    end_char: int


class ExtractedKnowledgePoint(BaseModel):
    title: str
    summary: str
    knowledge_type: KnowledgeType
    importance: int = Field(ge=1, le=5)
    confidence: Confidence = "medium"
    source_quote: str
    reason: str = ""


class KnowledgePoint(ExtractedKnowledgePoint):
    id: str
    document_id: str
    chunk_id: str
    status: Literal["draft", "kept", "rejected"] = "draft"
    created_at: datetime


class KnowledgeExtractionResult(BaseModel):
    points: list[ExtractedKnowledgePoint]


class Flashcard(BaseModel):
    card_type: CardType
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class FlashcardCandidate(Flashcard):
    id: str
    knowledge_id: str
    status: CardStatus = "draft"
    quality_score: float | None = None
    anki_note_id: str | None = None
    created_at: datetime


class CardGenerationResult(BaseModel):
    cards: list[Flashcard]


class CardQualityReport(BaseModel):
    atomicity_score: int = Field(ge=0, le=10)
    clarity_score: int = Field(ge=0, le=10)
    assessability_score: int = Field(ge=0, le=10)
    context_score: int = Field(ge=0, le=10)
    source_alignment_score: int = Field(ge=0, le=10)
    problems: list[str] = Field(default_factory=list)
    should_split: bool = False
    rewrite_suggestion: str | None = None
    missing_card_types: list[str] = Field(default_factory=list)


class StoredCardQualityReport(CardQualityReport):
    id: str
    card_id: str
    created_at: datetime


class PipelineResult(BaseModel):
    document: SourceDocument
    chunks: list[SourceChunk]
    knowledge_points: list[KnowledgePoint]
    cards: list[FlashcardCandidate]
    quality_reports: list[StoredCardQualityReport]


class CardUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    card_type: CardType | None = None
    source_quote: str | None = None
    tags: list[str] | None = None


class AnkiSyncRequest(BaseModel):
    deck_name: str
    model_name: str = "问答题"
    card_ids: list[str] | None = None
    allow_low_quality: bool = False


class AnkiSyncItem(BaseModel):
    card_id: str
    ok: bool
    note_id: str | int | None = None
    error: str | None = None


class AnkiSyncResult(BaseModel):
    synced: int
    failed: int
    items: list[AnkiSyncItem]
