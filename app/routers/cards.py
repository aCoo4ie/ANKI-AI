from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import CardUpdate, FlashcardCandidate
from app.services import pipeline


router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=list[FlashcardCandidate])
def list_cards(status: str | None = None) -> list[FlashcardCandidate]:
    return pipeline.list_cards(status=status)


@router.patch("/{card_id}", response_model=FlashcardCandidate)
def update_card(card_id: str, payload: CardUpdate) -> FlashcardCandidate:
    try:
        return pipeline.update_card(card_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{card_id}/approve", response_model=FlashcardCandidate)
def approve_card(card_id: str) -> FlashcardCandidate:
    return set_card_status(card_id, "approved")


@router.post("/{card_id}/reject", response_model=FlashcardCandidate)
def reject_card(card_id: str) -> FlashcardCandidate:
    return set_card_status(card_id, "rejected")


@router.post("/{card_id}/draft", response_model=FlashcardCandidate)
def mark_card_draft(card_id: str) -> FlashcardCandidate:
    return set_card_status(card_id, "draft")


@router.post("/approve-drafts")
def approve_drafts(document_id: str | None = None, min_quality: float = 90.0) -> dict[str, int]:
    return {"approved": pipeline.approve_cards(document_id=document_id, min_quality=min_quality)}


def set_card_status(card_id: str, status: str) -> FlashcardCandidate:
    try:
        return pipeline.update_card_status(card_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
