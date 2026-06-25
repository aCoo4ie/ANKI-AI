from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import AnkiSyncItem, AnkiSyncRequest, AnkiSyncResult
from app.services import pipeline
from app.services.anki_client import (
    AnkiConnectError,
    add_ai_card,
    ensure_deck,
    get_deck_names,
    get_model_names,
)


router = APIRouter(prefix="/anki", tags=["anki"])


@router.get("/decks", response_model=list[str])
def decks() -> list[str]:
    try:
        return get_deck_names()
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/models", response_model=list[str])
def models() -> list[str]:
    try:
        return get_model_names()
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/sync", response_model=AnkiSyncResult)
def sync_to_anki(payload: AnkiSyncRequest) -> AnkiSyncResult:
    cards = pipeline.list_cards(status="approved")
    if payload.card_ids is not None:
        wanted = set(payload.card_ids)
        cards = [card for card in cards if card.id in wanted]

    items: list[AnkiSyncItem] = []
    if not cards:
        return AnkiSyncResult(
            synced=0,
            failed=1,
            items=[
                AnkiSyncItem(
                    card_id="",
                    ok=False,
                    error="no_approved_cards_to_sync",
                )
            ],
        )

    try:
        ensure_deck(payload.deck_name)
    except AnkiConnectError as exc:
        return AnkiSyncResult(
            synced=0,
            failed=len(cards),
            items=[
                AnkiSyncItem(card_id=card.id, ok=False, error=str(exc))
                for card in cards
            ],
        )

    for card in cards:
        if not payload.allow_low_quality and (card.quality_score or 0) < 90:
            items.append(
                AnkiSyncItem(
                    card_id=card.id,
                    ok=False,
                    error="quality_score_below_90",
                )
            )
            continue

        try:
            note_id = add_ai_card(
                deck_name=payload.deck_name,
                model_name=payload.model_name,
                question=card.question,
                answer=card.answer,
                card_type=card.card_type,
                source_quote=card.source_quote,
                tags=card.tags + ["ai::reviewed", f"card::{card.card_type}"],
            )
            pipeline.update_anki_note_id(card.id, note_id)
            items.append(AnkiSyncItem(card_id=card.id, ok=True, note_id=note_id))
        except AnkiConnectError as exc:
            items.append(AnkiSyncItem(card_id=card.id, ok=False, error=str(exc)))

    return AnkiSyncResult(
        synced=sum(1 for item in items if item.ok),
        failed=sum(1 for item in items if not item.ok),
        items=items,
    )
