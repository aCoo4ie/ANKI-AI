from __future__ import annotations

import re

from app.models import ExtractedKnowledgePoint, KnowledgeExtractionResult
from app.services.llm import structured_invoke
from app.services.text_cleaner import clean_source_quote


GENERIC_TITLES = {"命令", "操作", "语句", "结果", "问题", "数据", "概念", "区别", "用法", "特点"}
ADVICE_TITLE_MARKERS = ("最重要", "警惕", "注意", "建议", "结论", "实操", "请背", "核心提醒")


def extract_knowledge_points(chunk_text: str, context_title: str = "") -> KnowledgeExtractionResult:
    prompt = f"""
你是技术学习知识工程师。

请从下面文本中抽取适合做成 Anki 卡片的核心知识点。

文档/章节上下文：{context_title or "未提供"}

要求：
1. 只抽取重要知识点，不要抽无意义细节。
2. 每个知识点必须能独立理解。
3. 标注知识点类型：concept/mechanism/process/comparison/misconception/application/code/interview。
4. 每个知识点必须绑定原文 source_quote，source_quote 必须是原文中的连续片段，并保留足够上下文。
5. 如果内容不适合制卡，少抽或不抽。
6. 不要编造原文没有的信息。
7. 技术概念、定义、机制、对比、边界条件、常见误区都适合制卡。
8. title 不能是“命令/操作/结果/问题”这种缺少上下文的泛词；必须补成“DDL 命令”“DROP 与 DELETE 的回滚差异”这类完整标题。
9. 不要把“最重要要警惕的是/建议/结论/请背下来”这类提示语当成 title；要抽成其背后的知识点，例如“DDL 语句的隐式提交风险”。

文本：
{chunk_text}
"""
    result = structured_invoke(KnowledgeExtractionResult, prompt, temperature=0.1, label="extract_knowledge_points")
    if result is not None and result.points:
        grounded = [
            point
            for point in result.points
            if point.source_quote.strip() and point.source_quote.strip() in chunk_text
        ]
        if grounded:
            return KnowledgeExtractionResult(points=[contextualize_point(p, context_title, chunk_text) for p in grounded])
    return heuristic_extract(chunk_text, context_title=context_title)


def heuristic_extract(chunk_text: str, context_title: str = "") -> KnowledgeExtractionResult:
    sentences = split_sentences(chunk_text)
    candidates = [s for s in sentences if 18 <= len(s) <= 260]
    if not candidates and chunk_text.strip():
        candidates = [chunk_text.strip()[:260]]

    points: list[ExtractedKnowledgePoint] = []
    for sentence in candidates[:6]:
        title = contextualize_title(make_title(sentence), sentence, context_title)
        points.append(
            ExtractedKnowledgePoint(
                title=title,
                summary=sentence,
                knowledge_type=infer_knowledge_type(sentence),
                importance=4 if len(sentence) > 40 else 3,
                confidence="low",
            source_quote=clean_source_quote(sentence),
                reason="Heuristic fallback extracted this sentence because no LLM is configured.",
            )
        )
    return KnowledgeExtractionResult(points=points)


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buffer: list[str] = []
    for index, char in enumerate(text):
        buffer.append(char)
        previous_char = text[index - 1] if index > 0 else ""
        next_char = text[index + 1] if index + 1 < len(text) else ""
        is_decimal_point = char == "." and previous_char.isdigit() and next_char.isdigit()
        is_sentence_end = char in "。！？!?" or (char == "." and not is_decimal_point)
        if is_sentence_end or char == "\n":
            sentence = "".join(buffer).strip("。！？.!? \t\n")
            if sentence:
                sentences.append(sentence)
            buffer = []
    tail = "".join(buffer).strip("。！？.!? \t\n")
    if tail:
        sentences.append(tail)
    return sentences


def make_title(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip(" ：:，,。.")
    for sep in ("包含", "表示", "保证", "用于", "是", "指", "：", ":", " means ", " is "):
        if sep in clean:
            prefix = clean.split(sep, 1)[0].strip()
            if 2 <= len(prefix) <= 40:
                return prefix
    if "。" in clean:
        clean = clean.split("。", 1)[0].strip()
    return clean[:36]


def contextualize_point(
    point: ExtractedKnowledgePoint,
    context_title: str,
    source_text: str,
) -> ExtractedKnowledgePoint:
    source_quote = clean_source_quote(complete_source_quote(point.source_quote, source_text))
    title = contextualize_title(point.title, source_quote or source_text, context_title)
    summary = clean_source_quote(point.summary, limit=260)
    if is_generic_title(point.title) and title not in summary:
        summary = f"{title}：{summary}"
    if has_incomplete_syntax(summary):
        summary = source_quote
    return point.model_copy(update={"title": title, "summary": summary, "source_quote": source_quote})


def contextualize_title(title: str, source: str, context_title: str = "") -> str:
    clean = re.sub(r"\s+", " ", title).strip(" ：:，,。.!?？")
    if not is_generic_title(clean) and not is_advice_title(clean) and not has_incomplete_syntax(clean):
        return clean
    source_upper = source.upper()
    context = context_title.strip()
    if any(marker in source for marker in ADVICE_TITLE_MARKERS):
        if "DDL" in source_upper and any(db in source_upper for db in ("ORACLE", "SQL SERVER", "MYSQL")):
            return "DDL 语句的隐式提交风险"
        if "DDL" in source_upper and ("隐式提交" in source or "ROLLBACK" in source_upper):
            return "DDL 隐式提交"
    if "隐式提交" in source or "ROLLBACK" in source_upper:
        if "DDL" in source_upper:
            return "DDL 隐式提交"
    if "DDL" in source_upper or any(token in source_upper for token in ("CREATE", "ALTER", "DROP", "TRUNCATE")):
        return "DDL 命令"
    if "DML" in source_upper or any(token in source_upper for token in ("SELECT", "INSERT", "UPDATE", "DELETE")):
        return "DML 命令"
    if "DCL" in source_upper or any(token in source_upper for token in ("GRANT", "REVOKE")):
        return "DCL 命令"
    if "SQL" in source_upper:
        return "SQL 命令"
    if context:
        return f"{context}中的{clean}"
    return clean


def is_generic_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    return compact in GENERIC_TITLES or len(compact) <= 2 or bool(re.match(r"^[0-9.)）]", compact))


def is_advice_title(title: str) -> bool:
    return any(marker in title for marker in ADVICE_TITLE_MARKERS)


def has_incomplete_syntax(text: str) -> bool:
    compact = text.strip()
    if compact.endswith(("(", "（", ":", "：", ",", "，", "、", "和", "或")):
        return True
    return compact.count("(") != compact.count(")") or compact.count("（") != compact.count("）")


def complete_source_quote(quote: str, source_text: str) -> str:
    quote = clean_source_quote(quote)
    if quote and quote in source_text and not has_incomplete_syntax(quote):
        return quote
    if quote and quote in source_text:
        for sentence in split_sentences(source_text):
            if quote in sentence:
                return sentence
    return quote or source_text.strip()


def infer_knowledge_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("vs", "compare", "区别", "对比", "不同")):
        return "comparison"
    if any(token in lowered for token in ("误区", "不是", "不能", "不要")):
        return "misconception"
    if any(token in lowered for token in ("步骤", "流程", "先", "然后")):
        return "process"
    if any(token in lowered for token in ("代码", "函数", "class", "def ", "return")):
        return "code"
    if any(token in lowered for token in ("因为", "机制", "原理", "导致")):
        return "mechanism"
    return "concept"
