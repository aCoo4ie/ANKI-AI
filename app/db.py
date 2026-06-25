from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DB_PATH = Path("data/ai_anki.sqlite3")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              source_type TEXT NOT NULL,
              content TEXT NOT NULL,
              deck_name TEXT,
              tags TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              text TEXT NOT NULL,
              start_char INTEGER NOT NULL,
              end_char INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_points (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              chunk_id TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL,
              knowledge_type TEXT NOT NULL,
              importance INTEGER NOT NULL,
              confidence TEXT NOT NULL,
              source_quote TEXT NOT NULL,
              reason TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS flashcard_candidates (
              id TEXT PRIMARY KEY,
              knowledge_id TEXT NOT NULL,
              card_type TEXT NOT NULL,
              question TEXT NOT NULL,
              answer TEXT NOT NULL,
              source_quote TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'draft',
              quality_score REAL,
              anki_note_id TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS card_quality_reports (
              id TEXT PRIMARY KEY,
              card_id TEXT NOT NULL,
              atomicity_score INTEGER NOT NULL,
              clarity_score INTEGER NOT NULL,
              assessability_score INTEGER NOT NULL,
              context_score INTEGER NOT NULL,
              source_alignment_score INTEGER NOT NULL,
              problems TEXT NOT NULL DEFAULT '[]',
              rewrite_suggestion TEXT,
              should_split INTEGER NOT NULL,
              missing_card_types TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL
            );
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("tags", "problems", "missing_card_types"):
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    if "should_split" in data:
        data["should_split"] = bool(data["should_split"])
    return data


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
