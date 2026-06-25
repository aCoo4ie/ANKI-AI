from __future__ import annotations

import os
import time

from app.db import connect, json_text, new_id, rows_to_dicts, utcnow_iso
from app.models import (
    Flashcard,
    FlashcardCandidate,
    CardQualityReport,
    KnowledgePoint,
    PipelineResult,
    SourceDocument,
    SourceDocumentCreate,
    StoredCardQualityReport,
)
from app.services.card_generator import generate_cards, generate_cards_for_points, revise_card
from app.services.chunker import split_text
from app.services.extractor import extract_knowledge_points
from app.services.text_cleaner import clean_input_text, clean_title
from app.services.quality_checker import QUALITY_THRESHOLD, check_card_quality, passes_quality, quality_score


MAX_QUALITY_ATTEMPTS = int(os.getenv("MAX_QUALITY_ATTEMPTS", "2"))
BATCH_CARD_GENERATION = os.getenv("BATCH_CARD_GENERATION", "1") == "1"


def log_timing(stage: str, started_at: float, **metadata) -> None:
    if os.getenv("PIPELINE_TIMING", "1") != "1":
        return
    elapsed = time.perf_counter() - started_at
    details = " ".join(f"{key}={value}" for key, value in metadata.items())
    print(f"[pipeline] {stage} elapsed={elapsed:.2f}s {details}".strip(), flush=True)


def create_document(payload: SourceDocumentCreate) -> SourceDocument:
    document_id = new_id("doc")
    created_at = utcnow_iso()
    title = clean_title(payload.title)
    content = clean_input_text(payload.content)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, title, source_type, content, deck_name, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                title,
                payload.source_type,
                content,
                payload.deck_name,
                json_text(payload.tags),
                created_at,
            ),
        )
    return get_document(document_id)


def get_document(document_id: str) -> SourceDocument:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise KeyError(f"document not found: {document_id}")
    from app.db import row_to_dict

    return SourceDocument(**row_to_dict(row))


def list_documents() -> list[SourceDocument]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [SourceDocument(**row) for row in rows_to_dicts(rows)]


def run_pipeline(document_id: str) -> PipelineResult:
    pipeline_started_at = time.perf_counter()
    document = get_document(document_id)
    chunks = split_text(document.id, document.content)
    log_timing("split_text", pipeline_started_at, chunks=len(chunks))
    with connect() as conn:
        old_card_rows = conn.execute(
            """
            SELECT c.id
            FROM flashcard_candidates c
            JOIN knowledge_points k ON k.id = c.knowledge_id
            WHERE k.document_id = ?
            """,
            (document.id,),
        ).fetchall()
        old_card_ids = [row["id"] for row in old_card_rows]
        if old_card_ids:
            placeholders = ",".join("?" for _ in old_card_ids)
            conn.execute(f"DELETE FROM card_quality_reports WHERE card_id IN ({placeholders})", old_card_ids)
            conn.execute(f"DELETE FROM flashcard_candidates WHERE id IN ({placeholders})", old_card_ids)
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document.id,))
        conn.execute("DELETE FROM knowledge_points WHERE document_id = ?", (document.id,))
        for chunk in chunks:
            conn.execute(
                """
                INSERT INTO chunks (id, document_id, chunk_index, text, start_char, end_char)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chunk.id, chunk.document_id, chunk.index, chunk.text, chunk.start_char, chunk.end_char),
            )

    points: list[KnowledgePoint] = []
    seen_titles: set[str] = set()
    extract_started_at = time.perf_counter()
    for chunk in chunks:
        chunk_started_at = time.perf_counter()
        result = extract_knowledge_points(chunk.text, context_title=document.title)
        log_timing("extract_chunk", chunk_started_at, chunk=chunk.index, points=len(result.points))
        for point in result.points:
            key = normalize_title(point.title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            stored = KnowledgePoint(
                id=new_id("kp"),
                document_id=document.id,
                chunk_id=chunk.id,
                status="draft",
                created_at=utcnow_iso(),
                **point.model_dump(),
            )
            points.append(stored)
    log_timing("extract_total", extract_started_at, points=len(points))

    with connect() as conn:
        for point in points:
            conn.execute(
                """
                INSERT INTO knowledge_points (
                    id, document_id, chunk_id, title, summary, knowledge_type, importance,
                    confidence, source_quote, reason, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.id,
                    point.document_id,
                    point.chunk_id,
                    point.title,
                    point.summary,
                    point.knowledge_type,
                    point.importance,
                    point.confidence,
                    point.source_quote,
                    point.reason,
                    point.status,
                    point.created_at.isoformat(),
                ),
            )

    cards: list[FlashcardCandidate] = []
    reports: list[StoredCardQualityReport] = []
    generation_started_at = time.perf_counter()
    batch_generated = generate_cards_for_points(points) if BATCH_CARD_GENERATION else {}
    for point in points:
        point_started_at = time.perf_counter()
        generated = batch_generated.get(point.id) if BATCH_CARD_GENERATION else generate_cards(point)
        if generated is None:
            generated = generate_cards(point)
        log_timing("generate_cards", point_started_at, point=point.title, cards=len(generated.cards))
        for card in generated.cards:
            refine_started_at = time.perf_counter()
            final_card, report, score = refine_card_until_quality(point, card)
            passed = passes_quality(report, QUALITY_THRESHOLD)
            log_timing("refine_card", refine_started_at, card_type=card.card_type, score=score, passed=passed)
            status = "draft" if passed else "rejected"
            stored_card = FlashcardCandidate(
                id=new_id("card"),
                knowledge_id=point.id,
                status=status,
                quality_score=score,
                anki_note_id=None,
                created_at=utcnow_iso(),
                **final_card.model_dump(),
            )
            stored_report = StoredCardQualityReport(
                id=new_id("qr"),
                card_id=stored_card.id,
                created_at=utcnow_iso(),
                **report.model_dump(),
            )
            cards.append(stored_card)
            reports.append(stored_report)
    log_timing("generate_quality_total", generation_started_at, cards=len(cards), reports=len(reports))

    persist_started_at = time.perf_counter()
    with connect() as conn:
        for card in cards:
            conn.execute(
                """
                INSERT INTO flashcard_candidates (
                    id, knowledge_id, card_type, question, answer, source_quote, tags,
                    status, quality_score, anki_note_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.id,
                    card.knowledge_id,
                    card.card_type,
                    card.question,
                    card.answer,
                    card.source_quote,
                    json_text(card.tags),
                    card.status,
                    card.quality_score,
                    card.anki_note_id,
                    card.created_at.isoformat(),
                ),
            )
        for report in reports:
            conn.execute(
                """
                INSERT INTO card_quality_reports (
                    id, card_id, atomicity_score, clarity_score, assessability_score,
                    context_score, source_alignment_score, problems, rewrite_suggestion,
                    should_split, missing_card_types, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.card_id,
                    report.atomicity_score,
                    report.clarity_score,
                    report.assessability_score,
                    report.context_score,
                    report.source_alignment_score,
                    json_text(report.problems),
                    report.rewrite_suggestion,
                    int(report.should_split),
                    json_text(report.missing_card_types),
                    report.created_at.isoformat(),
                ),
            )
    log_timing("persist_results", persist_started_at, cards=len(cards), reports=len(reports))
    log_timing("pipeline_total", pipeline_started_at, document_id=document.id, points=len(points), cards=len(cards))

    return PipelineResult(
        document=document,
        chunks=chunks,
        knowledge_points=points,
        cards=cards,
        quality_reports=reports,
    )


def refine_card_until_quality(
    point: KnowledgePoint,
    card: Flashcard,
) -> tuple[Flashcard, CardQualityReport, float]:
    current = card
    last_report = check_card_quality(current)
    last_score = quality_score(last_report)
    for _ in range(1, MAX_QUALITY_ATTEMPTS + 1):
        if passes_quality(last_report, QUALITY_THRESHOLD):
            break
        current = revise_card(point, current, last_report)
        last_report = check_card_quality(current)
        last_score = quality_score(last_report)
    return current, last_report, last_score


def list_knowledge_points(document_id: str) -> list[KnowledgePoint]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_points WHERE document_id = ? ORDER BY created_at",
            (document_id,),
        ).fetchall()
    return [KnowledgePoint(**row) for row in rows_to_dicts(rows)]


def list_cards(document_id: str | None = None, status: str | None = None) -> list[FlashcardCandidate]:
    query = """
        SELECT c.*
        FROM flashcard_candidates c
        JOIN knowledge_points k ON k.id = c.knowledge_id
        WHERE 1 = 1
    """
    params: list[str] = []
    if document_id:
        query += " AND k.document_id = ?"
        params.append(document_id)
    if status:
        query += " AND c.status = ?"
        params.append(status)
    query += " ORDER BY c.created_at"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [FlashcardCandidate(**row) for row in rows_to_dicts(rows)]


def get_card(card_id: str) -> FlashcardCandidate:
    with connect() as conn:
        row = conn.execute("SELECT * FROM flashcard_candidates WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise KeyError(f"card not found: {card_id}")
    from app.db import row_to_dict

    return FlashcardCandidate(**row_to_dict(row))


def update_card_status(card_id: str, status: str) -> FlashcardCandidate:
    with connect() as conn:
        conn.execute("UPDATE flashcard_candidates SET status = ? WHERE id = ?", (status, card_id))
    return get_card(card_id)


def approve_cards(document_id: str | None = None, min_quality: float = 90.0) -> int:
    query = """
        UPDATE flashcard_candidates
        SET status = 'approved'
        WHERE status = 'draft'
          AND COALESCE(quality_score, 0) >= ?
    """
    params: list[object] = [min_quality]
    if document_id:
        query += """
          AND knowledge_id IN (
            SELECT id FROM knowledge_points WHERE document_id = ?
          )
        """
        params.append(document_id)
    with connect() as conn:
        cursor = conn.execute(query, params)
        return cursor.rowcount


def update_card(card_id: str, values: dict) -> FlashcardCandidate:
    allowed = {"question", "answer", "card_type", "source_quote", "tags"}
    updates = {key: value for key, value in values.items() if key in allowed and value is not None}
    if not updates:
        return get_card(card_id)
    assignments = []
    params = []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        params.append(json_text(value) if key == "tags" else value)
    params.append(card_id)
    with connect() as conn:
        conn.execute(f"UPDATE flashcard_candidates SET {', '.join(assignments)} WHERE id = ?", params)
    return get_card(card_id)


def update_anki_note_id(card_id: str, note_id: str | int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE flashcard_candidates SET status = 'synced', anki_note_id = ? WHERE id = ?",
            (str(note_id), card_id),
        )


def normalize_title(title: str) -> str:
    return title.lower().replace(" ", "").replace("：", ":").strip()


def card_to_flashcard(card: FlashcardCandidate) -> Flashcard:
    return Flashcard(
        card_type=card.card_type,
        question=card.question,
        answer=card.answer,
        source_quote=card.source_quote,
        tags=card.tags,
    )
