from __future__ import annotations

from app.db import new_id
from app.models import SourceChunk


def split_text(
    document_id: str,
    text: str,
    max_len: int = 1200,
    overlap: int = 150,
) -> list[SourceChunk]:
    if max_len <= overlap:
        raise ValueError("max_len must be greater than overlap")

    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[SourceChunk] = []
    start = 0
    index = 0
    while start < len(normalized):
        end = min(start + max_len, len(normalized))
        if end < len(normalized):
            split_at = max(
                normalized.rfind("\n\n", start, end),
                normalized.rfind("\n", start, end),
                normalized.rfind("。", start, end),
                normalized.rfind(".", start, end),
            )
            if split_at > start + max_len // 2:
                end = split_at + 1

        chunks.append(
            SourceChunk(
                id=new_id("chunk"),
                document_id=document_id,
                index=index,
                text=normalized[start:end],
                start_char=start,
                end_char=end,
            )
        )
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
        index += 1
    return chunks
