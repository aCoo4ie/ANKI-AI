from __future__ import annotations

from functools import lru_cache
from html import escape
import os

import requests

from app.services.text_cleaner import clean_source_quote, strip_card_markup


ANKI_CONNECT_URL = os.getenv("ANKI_CONNECT_URL", "http://localhost:8765")


class AnkiConnectError(Exception):
    pass


def anki_request(action: str, params: dict | None = None):
    payload = {
        "action": action,
        "version": 6,
        "params": params or {},
    }
    try:
        response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AnkiConnectError(f"Cannot reach AnkiConnect at {ANKI_CONNECT_URL}: {exc}") from exc

    data = response.json()
    if data.get("error"):
        raise AnkiConnectError(str(data["error"]))
    return data.get("result")


def get_deck_names() -> list[str]:
    return anki_request("deckNames")


def create_deck(deck_name: str):
    return anki_request("createDeck", {"deck": deck_name})


def get_model_names() -> list[str]:
    return anki_request("modelNames")


@lru_cache(maxsize=32)
def get_model_field_names(model_name: str) -> list[str]:
    return anki_request("modelFieldNames", {"modelName": model_name})


def create_ai_knowledge_model(model_name: str = "AI Knowledge Card"):
    return anki_request(
        "createModel",
        {
            "modelName": model_name,
            "inOrderFields": [
                "Question",
                "Answer",
                "CardType",
                "SourceQuote",
            ],
            "css": """
.card {
  font-family: Arial, "Microsoft YaHei", sans-serif;
  font-size: 20px;
  text-align: left;
  color: #222;
  background-color: #fff;
  line-height: 1.55;
}
.meta {
  margin-top: 18px;
  padding-top: 10px;
  border-top: 1px solid #ddd;
  color: #666;
  font-size: 14px;
}
""".strip(),
            "cardTemplates": [
                {
                    "Name": "AI Knowledge Card",
                    "Front": """
<div class="question">{{Question}}</div>
<div class="meta">{{CardType}}</div>
""".strip(),
                    "Back": """
<div class="question">{{Question}}</div>
<hr id="answer">
<div class="answer">{{Answer}}</div>
<div class="meta">
  <div>{{CardType}}</div>
  <div>{{SourceQuote}}</div>
</div>
""".strip(),
                }
            ],
        },
    )


def ensure_deck(deck_name: str) -> None:
    if deck_name not in get_deck_names():
        create_deck(deck_name)


def ensure_ai_knowledge_model(model_name: str = "AI Knowledge Card") -> None:
    model_names = get_model_names()
    if model_name not in model_names:
        create_ai_knowledge_model(model_name)
        return

    required_fields = {"Question", "Answer", "CardType", "SourceQuote"}
    existing_fields = set(get_model_field_names(model_name))
    missing = required_fields - existing_fields
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise AnkiConnectError(
            f'model "{model_name}" exists but is missing fields: {missing_list}. '
            "Please add those fields in Anki or use a different note type name."
        )


def _pick_field(field_names: list[str], candidates: tuple[str, ...]) -> str | None:
    existing = set(field_names)
    for candidate in candidates:
        if candidate in existing:
            return candidate
    return None


def _format_back(answer: str, card_type: str, source_quote: str) -> str:
    clean_answer = strip_card_markup(answer)
    clean_source = clean_source_quote(source_quote)
    parts = [f"<div>{escape(clean_answer)}</div>"]
    meta = []
    if card_type:
        meta.append(f"<div>类型：{escape(card_type)}</div>")
    if clean_source:
        meta.append(f"<div>来源：{escape(clean_source)}</div>")
    if meta:
        parts.append('<hr><div style="font-size: 0.85em; color: #666;">')
        parts.extend(meta)
        parts.append("</div>")
    return "\n".join(parts)


def build_note_fields(
    model_name: str,
    question: str,
    answer: str,
    card_type: str,
    source_quote: str,
    extra_fields: dict[str, str] | None = None,
) -> dict[str, str]:
    field_names = get_model_field_names(model_name)
    clean_question = strip_card_markup(question)
    clean_answer = strip_card_markup(answer)
    clean_source = clean_source_quote(source_quote)
    front_field = _pick_field(field_names, ("Question", "Front", "正面"))
    back_field = _pick_field(field_names, ("Answer", "Back", "背面"))
    type_field = _pick_field(field_names, ("CardType", "Type", "类型"))
    source_field = _pick_field(field_names, ("SourceQuote", "Source", "来源", "出处"))

    if front_field and back_field:
        fields = {
            front_field: clean_question,
            back_field: clean_answer
            if back_field == "Answer"
            else _format_back(clean_answer, card_type, clean_source),
        }
    elif len(field_names) >= 2:
        fields = {
            field_names[0]: clean_question,
            field_names[1]: _format_back(clean_answer, card_type, clean_source),
        }
    else:
        raise AnkiConnectError(
            f'model "{model_name}" must have at least two fields, '
            "for example Front/Back or 正面/背面."
        )

    if type_field:
        fields[type_field] = card_type
    if source_field:
        fields[source_field] = clean_source

    for key, value in (extra_fields or {}).items():
        if key in field_names:
            fields[key] = value
    return fields


def add_ai_card(
    deck_name: str,
    model_name: str,
    question: str,
    answer: str,
    card_type: str,
    source_quote: str,
    tags: list[str],
    extra_fields: dict[str, str] | None = None,
):
    fields = build_note_fields(
        model_name=model_name,
        question=question,
        answer=answer,
        card_type=card_type,
        source_quote=source_quote,
        extra_fields=extra_fields,
    )
    return anki_request(
        "addNote",
        {
            "note": {
                "deckName": deck_name,
                "modelName": model_name,
                "fields": fields,
                "tags": tags,
            }
        },
    )
