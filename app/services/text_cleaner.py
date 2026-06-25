from __future__ import annotations

import html
import re
import unicodedata


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_LINK_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)|\[([^\]]+)\]\([^)]+\)")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+•●▪▫◦·]|[0-9]+[.)、]|[一二三四五六七八九十]+[、.])\s*")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
TABLE_BORDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
DECORATION_RE = re.compile(r"^\s*[-=*_`~]{3,}\s*$")
MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)")
CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n?|```")


def clean_input_text(text: str) -> str:
    """Normalize pasted article/chat/markdown/html into model-friendly plain text."""
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    normalized = html.unescape(normalized)
    normalized = CODE_FENCE_RE.sub("\n", normalized)
    normalized = MARKDOWN_LINK_RE.sub(lambda m: m.group(1) or m.group(2) or "", normalized)
    normalized = HTML_TAG_RE.sub(" ", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines: list[str] = []
    previous_blank = False
    for raw_line in normalized.split("\n"):
        line = clean_line(raw_line)
        if not line:
            if not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def clean_title(title: str) -> str:
    return clean_line(title).strip("。！？.!? ")


def clean_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if TABLE_BORDER_RE.match(line) or DECORATION_RE.match(line):
        return ""
    line = HEADING_RE.sub("", line)
    line = LIST_MARKER_RE.sub("", line)
    line = re.sub(r"^\s*>\s?", "", line)
    line = line.replace("`", "")
    line = MARKDOWN_EMPHASIS_RE.sub("", line)
    line = line.replace("　", " ")
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"([：:])\s+", r"\1", line)
    return line.strip()


def strip_card_markup(text: str) -> str:
    text = clean_line(str(text))
    text = re.sub(r"^[：:;；,，、\s]+", "", text)
    return text.strip()


def clean_source_quote(text: str, limit: int = 360) -> str:
    """Clean copied markup from a source excerpt while preserving original wording."""
    normalized = unicodedata.normalize("NFC", str(text or ""))
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    normalized = html.unescape(normalized)
    normalized = CODE_FENCE_RE.sub("\n", normalized)
    normalized = MARKDOWN_LINK_RE.sub(lambda m: m.group(1) or m.group(2) or "", normalized)
    normalized = HTML_TAG_RE.sub(" ", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

    lines = [clean_line(line) for line in normalized.split("\n")]
    cleaned = " ".join(line for line in lines if line)
    cleaned = cleaned.strip("`'\"“”‘’ ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"([：:])\s+", r"\1", cleaned)
    cleaned = re.sub(r"^[：:;；,，、\s]+", "", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    for mark in ("。", "；", ";", "，", ","):
        cut = cleaned.rfind(mark, 0, limit)
        if cut >= 40:
            return cleaned[: cut + 1].strip()
    return cleaned[:limit].rstrip("，,；;:：、()（） ")
