from __future__ import annotations

import os
import re
import json

from pydantic import BaseModel, Field

from app.models import CardGenerationResult, CardQualityReport, CardType, ExtractedKnowledgePoint, Flashcard, KnowledgePoint
from app.services.llm import structured_invoke
from app.services.text_cleaner import clean_source_quote, strip_card_markup


REQUIRED_CARD_TYPES = ["definition", "reverse", "intuition", "example", "boundary", "application"]
LOW_SIGNAL_PHRASES = ("最重要", "警惕", "注意", "建议", "结论", "实操", "请背", "核心提醒")


class BatchGeneratedCard(BaseModel):
    point_id: str = Field(description="Knowledge point id from the input list.")
    card_type: CardType
    question: str
    answer: str
    source_quote: str
    tags: list[str] = Field(default_factory=list)


class BatchCardGenerationResult(BaseModel):
    cards: list[BatchGeneratedCard] = Field(default_factory=list)


def generate_cards(point: ExtractedKnowledgePoint) -> CardGenerationResult:
    prompt = f"""
你是严苛的 Anki 原子卡片编辑器，不是聊天助手。

只基于给定知识点和来源片段制卡，不要回答用户，不要写寒暄、铺垫、总结、观点。

知识点标题：{point.title}
知识点摘要：{point.summary}
知识点类型：{point.knowledge_type}
来源片段：{point.source_quote}

必须遵守：
1. 每张卡只考一个可验证事实。
2. question 必须是一个短问题，不能超过 60 个中文字符。
3. answer 必须直接回答 question，不能超过 120 个中文字符。
4. question 和 answer 必须紧扣知识点标题、摘要、来源片段。
5. source_quote 必须引用来源片段中的相关句子，先去掉项目符号、反引号等无关格式符号，但保留原文措辞和足够上下文。
6. 禁止出现这些元话术：这个问题、我先、直接回答、首先、然后给你、最颠覆认知、你的问题、我们来、总结一下、核心骨架。
7. 禁止把一段对话式回答改装成卡片。
8. 生成 card_type：definition、reverse、intuition、example、boundary、application；只在来源支持时生成 misconception/counterexample。
9. 不确定时少生成，不要凑数量。
10. question 不得以项目符号、Markdown 符号、冒号、反引号开头。
11. 如果术语本身是泛词，必须补足上下文，例如“命令”要写成“DDL 命令”。
12. 必须保证语义完整：question 要包含主题、范围和考点；answer 要能独立回答，不得只留下半句话。
13. 尽量保留原文关键词；原文太啰嗦时，只能用相近短语概括，不得改变事实。
14. 禁止使用省略号截断，禁止输出不完整括号，例如“MySQL(8”。

好卡示例：
question: SQL 事务的原子性保证什么？
answer: 事务中的操作要么全部成功，要么全部失败回滚。

坏卡示例：
question: 这个问题问到了 SQL 的核心骨架，我先回答你的三个问题？
answer: 这个问题问到了 SQL 的核心骨架……

输出结构化 JSON。
"""
    result = structured_invoke(CardGenerationResult, prompt, temperature=0.0, label="generate_cards")
    if result is not None and result.cards:
        return sanitize_generation(result)
    return heuristic_generate_cards(point)


def generate_cards_for_points(points: list[KnowledgePoint]) -> dict[str, CardGenerationResult]:
    if not points:
        return {}
    point_lines = []
    for point in points:
        point_lines.append(
            {
                "point_id": point.id,
                "title": point.title,
                "summary": point.summary,
                "knowledge_type": point.knowledge_type,
                "source_quote": point.source_quote,
            }
        )

    prompt = f"""
你是严苛的 Anki 原子卡片编辑器。请为下面多个知识点批量生成卡片。

全局要求：
1. 每张卡只考一个事实，question <= 60 中文字符，answer <= 120 中文字符。
2. 必须语义完整：question 要包含主题、范围和考点；answer 要能独立回答。
3. 尽量保留原文关键词；只删掉“最重要/建议/结论”等包装话。
4. 不要使用省略号截断，不要输出不完整括号。
5. 不要生成低信号 reverse/intuition；如果反向卡会变成半句话，就不要生成。
6. 每个输出必须带回 point_id。
7. 不确定时少生成，不要凑数量。

知识点列表：
{json.dumps(point_lines, ensure_ascii=False)}

只输出 JSON。
"""
    result = structured_invoke(BatchCardGenerationResult, prompt, temperature=0.0, label="batch_generate_cards")
    grouped: dict[str, list[Flashcard]] = {point.id: [] for point in points}
    if result is not None and result.cards:
        for item in result.cards:
            if item.point_id not in grouped:
                continue
            card = sanitize_card(
                Flashcard(
                    card_type=item.card_type,
                    question=item.question,
                    answer=item.answer,
                    source_quote=item.source_quote,
                    tags=item.tags,
                )
            )
            grouped[item.point_id].append(card)

    output: dict[str, CardGenerationResult] = {}
    point_by_id = {point.id: point for point in points}
    for point_id, cards in grouped.items():
        if cards:
            output[point_id] = CardGenerationResult(cards=cards)
        else:
            output[point_id] = heuristic_generate_cards(point_by_id[point_id])
    return output


def revise_card(
    point: ExtractedKnowledgePoint,
    card: Flashcard,
    report: CardQualityReport,
) -> Flashcard:
    if os.getenv("USE_LLM_CARD_REVISION", "0") != "1":
        return heuristic_revise_card(point, card)

    prompt = f"""
你是 Anki 卡片修订器。请把低质量卡片重写成 90 分以上的原子卡。

知识点标题：{point.title}
知识点摘要：{point.summary}
来源片段：{point.source_quote}

原卡类型：{card.card_type}
原问题：{card.question}
原答案：{card.answer}
质量问题：{report.problems}
改写建议：{report.rewrite_suggestion}

重写要求：
1. 保持原 card_type。
2. 只测试一个知识点。
3. question 不超过 60 个中文字符。
4. answer 不超过 120 个中文字符。
5. 不得出现聊天式、解释任务式、铺垫式话术。
6. 不得引入来源片段没有支持的信息。
7. source_quote 必须使用给定来源片段。

只输出一个 Flashcard JSON 对象。
"""
    result = structured_invoke(Flashcard, prompt, temperature=0.0, label="revise_card")
    if result is not None:
        return sanitize_card(result, fallback_source=point.source_quote, fallback_type=card.card_type)
    return heuristic_revise_card(point, card)


def sanitize_generation(result: CardGenerationResult) -> CardGenerationResult:
    cards: list[Flashcard] = []
    seen: set[tuple[str, str]] = set()
    for card in result.cards:
        cleaned = sanitize_card(card)
        key = (cleaned.card_type, cleaned.question.strip())
        if key not in seen:
            cards.append(cleaned)
            seen.add(key)
    return CardGenerationResult(cards=cards)


def sanitize_card(
    card: Flashcard,
    fallback_source: str | None = None,
    fallback_type: str | None = None,
) -> Flashcard:
    card_type = card.card_type or fallback_type or "definition"
    question = strip_noise_prefix(strip_card_markup(card.question)).rstrip("？?") + "？"
    answer = strip_noise_prefix(strip_card_markup(card.answer))
    source_quote = clean_source_quote(card.source_quote or fallback_source or "")
    tags = list(dict.fromkeys([*card.tags, "ai::generated", f"card::{card_type}"]))
    return Flashcard(
        card_type=card_type,
        question=question,
        answer=answer,
        source_quote=source_quote,
        tags=tags,
    )


def heuristic_generate_cards(point: ExtractedKnowledgePoint) -> CardGenerationResult:
    base_tags = [
        "ai::generated",
        f"type::{point.knowledge_type}",
        f"confidence::{point.confidence}",
    ]
    quote = clean_source_quote(point.source_quote or point.summary)
    title = contextual_card_title(point)
    summary = compact(point.summary)
    specialized = specialized_cards(title, summary, quote, base_tags)
    if specialized:
        return CardGenerationResult(cards=specialized)

    cards = [
        Flashcard(
            card_type="definition",
            question=definition_question(title, summary),
            answer=clean_answer(summary, title),
            source_quote=quote,
            tags=base_tags + ["card::definition"],
        ),
    ]
    if is_reverse_safe(title, summary):
        cards.append(
            Flashcard(
                card_type="reverse",
                question=f"哪个术语指：{short_text(summary, 44)}？",
                answer=title,
                source_quote=quote,
                tags=base_tags + ["card::reverse"],
            )
        )
    return CardGenerationResult(cards=cards)


def heuristic_revise_card(point: ExtractedKnowledgePoint, card: Flashcard) -> Flashcard:
    quote = clean_source_quote(point.source_quote or card.source_quote or point.summary)
    title = contextual_card_title(point)
    if card.card_type == "reverse":
        question = f"哪个术语指：{short_text(point.summary, 44)}？"
        answer = title
    elif card.card_type == "boundary" and title == "DDL 隐式提交":
        question = "为什么 DDL 操作不能依赖 ROLLBACK 回滚？"
        answer = "因为 DDL 通常会隐式提交，不能像普通 DML 一样依赖 ROLLBACK。"
    else:
        question = natural_question(f"{title} 是什么？")
        answer = clean_answer(point.summary, title)
    return Flashcard(
        card_type=card.card_type,
        question=question,
        answer=answer,
        source_quote=quote,
        tags=list(dict.fromkeys([*card.tags, "ai::revised"])),
    )


def compact(text: str) -> str:
    return " ".join(strip_card_markup(str(text)).replace("\u3000", " ").split())


def shorten(text: str, limit: int) -> str:
    return short_text(text, limit)


def short_text(text: str, limit: int) -> str:
    clean = compact(text)
    if len(clean) <= limit:
        return clean
    for mark in ("。", "；", ";", "，", ","):
        cut = clean.rfind(mark, 0, limit)
        if cut >= 8:
            return clean[:cut].rstrip("，,；;。 ")
    return clean[:limit].rstrip("，,；;:：、()（） ")


def definition_question(title: str, summary: str) -> str:
    source = f"{title} {summary}".upper()
    if any(marker in summary for marker in LOW_SIGNAL_PHRASES):
        if "DDL" in source and any(db in source for db in ("ORACLE", "SQL SERVER", "MYSQL")):
            return "DDL 语句在不同数据库中的提交行为要警惕什么？"
        if "DDL" in source and ("ROLLBACK" in source or "隐式提交" in summary):
            return "DDL 操作为什么不能依赖 ROLLBACK 回滚？"
    return natural_question(f"{title} 是什么？")


def natural_question(question: str) -> str:
    question = compact(question)
    question = re.sub(r"\s+(是什么|有哪些|为什么|如何|属于)", r"\1", question)
    question = re.sub(r"\s+？", "？", question)
    return question


def clean_answer(answer: str, title: str) -> str:
    clean = compact(answer)
    clean = re.sub(r"^(命令|特点|结果|结论|定义|最重要要警惕的是|最重要警惕的是)\s*[:：]\s*", "", clean)
    if title and clean.startswith(f"{title}:"):
        clean = clean[len(title) + 1 :].strip()
    if title and clean.startswith(f"{title}："):
        clean = clean[len(title) + 1 :].strip()
    return short_text(clean, 120)


def specialized_cards(
    title: str,
    summary: str,
    quote: str,
    base_tags: list[str],
) -> list[Flashcard]:
    source_upper = f"{summary} {quote}".upper()
    if title == "DDL 命令" and all(token in source_upper for token in ("CREATE", "ALTER", "DROP", "TRUNCATE")):
        answer = "CREATE(建表)、ALTER(改列)、DROP(删表)、TRUNCATE(清空表结构)。"
        cards = [
            Flashcard(
                card_type="definition",
                question="DDL 命令包括哪些常见操作？",
                answer=answer,
                source_quote=quote,
                tags=base_tags + ["card::definition"],
            ),
            Flashcard(
                card_type="reverse",
                question="CREATE、ALTER、DROP、TRUNCATE 属于哪类 SQL 命令？",
                answer="DDL 命令。",
                source_quote=quote,
                tags=base_tags + ["card::reverse"],
            ),
        ]
        if "隐式提交" in summary or "隐式提交" in quote or "ROLLBACK" in source_upper:
            cards.append(
                Flashcard(
                    card_type="boundary",
                    question="为什么 DDL 操作不能依赖 ROLLBACK 回滚？",
                    answer="因为 DDL 通常会隐式提交。",
                    source_quote=quote,
                    tags=base_tags + ["card::boundary"],
                )
            )
        return cards
    if title == "DDL 隐式提交" and ("隐式提交" in summary or "隐式提交" in quote or "ROLLBACK" in source_upper):
        return [
            Flashcard(
                card_type="definition",
                question="DDL 隐式提交意味着什么？",
                answer="DDL 执行时通常会自动提交事务。",
                source_quote=quote,
                tags=base_tags + ["card::definition"],
            ),
            Flashcard(
                card_type="boundary",
                question="为什么 DDL 操作不能依赖 ROLLBACK 回滚？",
                answer="因为 DDL 通常会隐式提交，不能像普通 DML 一样依赖 ROLLBACK。",
                source_quote=quote,
                tags=base_tags + ["card::boundary"],
            ),
        ]
    if title == "DDL 语句的隐式提交风险":
        answer = clean_answer(summary, title)
        if not answer or any(marker in answer for marker in LOW_SIGNAL_PHRASES):
            answer = "DDL 语句可能隐式提交，导致 ROLLBACK 不能回滚 DDL 之前的事务。"
        return [
            Flashcard(
                card_type="definition",
                question="DDL 语句在不同数据库中的提交行为要警惕什么？",
                answer=short_text(answer, 120),
                source_quote=quote,
                tags=base_tags + ["card::definition"],
            )
        ]
    return []


def strip_noise_prefix(text: str) -> str:
    return re.sub(r"^[•●▪▫◦·\-\*\+>#:：\s]+", "", text).strip()


def contextual_card_title(point: ExtractedKnowledgePoint) -> str:
    title = strip_noise_prefix(strip_card_markup(point.title)).strip(" ：:，,。.!?？")
    source = f"{point.summary} {point.source_quote}".upper()
    if any(marker in title for marker in LOW_SIGNAL_PHRASES):
        if "DDL" in source and any(db in source for db in ("ORACLE", "SQL SERVER", "MYSQL")):
            return "DDL 语句的隐式提交风险"
        if "DDL" in source and ("隐式提交" in point.summary or "ROLLBACK" in source):
            return "DDL 隐式提交"
    if title in {"命令", "操作", "语句", "结果", "问题", "数据", "概念", "特点"} or len(title) <= 2:
        if "DDL" in source or any(token in source for token in ("CREATE", "ALTER", "DROP", "TRUNCATE")):
            return "DDL 命令"
        if "DML" in source or any(token in source for token in ("SELECT", "INSERT", "UPDATE", "DELETE")):
            return "DML 命令"
        if "DCL" in source or any(token in source for token in ("GRANT", "REVOKE")):
            return "DCL 命令"
        if "SQL" in source:
            return "SQL 命令"
    return title


def is_reverse_safe(title: str, summary: str) -> bool:
    if any(marker in title or marker in summary for marker in LOW_SIGNAL_PHRASES):
        return False
    if len(summary) > 54:
        return False
    if has_incomplete_syntax(summary):
        return False
    return True


def has_incomplete_syntax(text: str) -> bool:
    compacted = compact(text)
    if compacted.endswith(("(", "（", ":", "：", ",", "，", "、")):
        return True
    return compacted.count("(") != compacted.count(")") or compacted.count("（") != compacted.count("）")
