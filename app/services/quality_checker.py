from __future__ import annotations

import re
import os

from app.models import CardQualityReport, Flashcard
from app.services.llm import structured_invoke


QUALITY_THRESHOLD = 90.0

META_PHRASES = [
    "这个问题",
    "我先",
    "直接回答",
    "首先",
    "然后给你",
    "最颠覆认知",
    "你的问题",
    "你的三个问题",
    "我们来",
    "总结一下",
    "核心骨架",
    "不区分它们",
    "不仅仅是",
    "而是会导致",
]
LOW_SIGNAL_PHRASES = ["最重要", "警惕", "注意", "建议", "结论", "实操", "请背"]

VAGUE_PHRASES = ["说说", "谈谈", "理解一下", "介绍一下", "简述一下"]
AMBIGUOUS_REFERENCES = ["它", "这个", "这些", "上述", "前者", "后者"]
MULTI_QUESTION_MARKERS = ["分别", "并说明", "以及", "同时解释", "三个问题", "多个问题"]
GENERIC_QUESTION_RE = re.compile(r"^(命令|操作|语句|结果|问题|数据|概念|特点)\s*(是|指|有哪些|如何|为什么)")
FORMAT_NOISE_RE = re.compile(r"[•●▪▫◦·`*_#]{1,}|�|\?\?\?|…")


def check_card_quality(card: Flashcard) -> CardQualityReport:
    rule_problems = rule_based_card_check(card)
    if rule_problems:
        return heuristic_quality_check(card)
    if os.getenv("USE_LLM_QUALITY_CHECK", "0") != "1":
        return heuristic_quality_check(card)

    prompt = f"""
你是严格的 Anki 卡片质检器。请按真实学习可用性打分，不要宽松。

卡片：
类型：{card.card_type}
问题：{card.question}
答案：{card.answer}
来源片段：{card.source_quote}

评分标准，每项 0-10：
1. atomicity_score：是否只问一个点；一题多问最高 5。
2. clarity_score：问题是否明确；出现“这个问题/我先/首先/你的问题”等聊天话术最高 4。
3. assessability_score：答案是否可评分；泛泛而谈最高 6。
4. context_score：脱离原文是否仍能理解；指代不清最高 6。
5. source_alignment_score：答案是否被来源片段直接支持；不贴来源最高 5，编造最高 3。

通过 90 分的条件：五项都必须 >=9，且 problems 为空，should_split 为 false。

请输出结构化 JSON。
"""
    result = structured_invoke(CardQualityReport, prompt, temperature=0.0)
    if result is None:
        result = heuristic_quality_check(card)

    merged = list(dict.fromkeys([*result.problems, *rule_problems]))
    should_split = result.should_split or "multi_question" in merged
    capped = apply_problem_caps(result, merged)
    return capped.model_copy(update={"problems": merged, "should_split": should_split})


def quality_score(report: CardQualityReport) -> float:
    values = [
        report.atomicity_score,
        report.clarity_score,
        report.assessability_score,
        report.context_score,
        report.source_alignment_score,
    ]
    score = round(sum(values) / len(values) * 10, 1)
    if report.should_split:
        score = min(score, 59.0)
    if report.problems:
        score = min(score, 89.0)
    return score


def passes_quality(report: CardQualityReport, threshold: float = QUALITY_THRESHOLD) -> bool:
    values = [
        report.atomicity_score,
        report.clarity_score,
        report.assessability_score,
        report.context_score,
        report.source_alignment_score,
    ]
    return (
        quality_score(report) >= threshold
        and min(values) >= 9
        and not report.problems
        and not report.should_split
    )


def rule_based_card_check(card: Flashcard) -> list[str]:
    problems: list[str] = []
    question = compact(card.question)
    answer = compact(card.answer)
    source = compact(card.source_quote)
    combined = f"{question} {answer}"

    if FORMAT_NOISE_RE.search(f"{question} {answer} {source}"):
        problems.append("format_noise")
    if has_incomplete_syntax(question) or has_incomplete_syntax(answer):
        problems.append("incomplete_syntax")
    if is_low_signal_card(card.card_type, question, answer):
        problems.append("semantic_incomplete")
    if GENERIC_QUESTION_RE.search(question):
        problems.append("missing_context_in_question")
    if len(question) > 60:
        problems.append("question_too_long")
    if any(mark in question for mark in ("。", "；", ";")):
        problems.append("question_contains_full_sentence")
    if len(answer) > 120:
        problems.append("answer_too_long")
    if not source:
        problems.append("missing_source_quote")
    if any(phrase in question for phrase in VAGUE_PHRASES):
        problems.append("question_too_vague")
    if card.card_type in {"application", "boundary", "example", "counterexample", "misconception"}:
        if not source_supports_card_angle(card.card_type, source):
            problems.append("card_angle_not_supported_by_source")
    if any(phrase in question for phrase in AMBIGUOUS_REFERENCES):
        problems.append("ambiguous_reference")
    if any(phrase in combined for phrase in META_PHRASES):
        problems.append("assistant_meta_talk")
    question_marks = len(re.findall(r"[?？]", question))
    if question_marks > 1 or any(token in question for token in MULTI_QUESTION_MARKERS):
        problems.append("multi_question")
    if source and answer and lexical_overlap(answer, source) < 0.18:
        problems.append("answer_not_supported_by_source")
    if source and question and lexical_overlap(question, source) < 0.08 and card.card_type != "reverse":
        problems.append("question_not_grounded_in_source")
    return problems


def apply_problem_caps(report: CardQualityReport, problems: list[str]) -> CardQualityReport:
    atomicity = report.atomicity_score
    clarity = report.clarity_score
    assessability = report.assessability_score
    context = report.context_score
    source_alignment = report.source_alignment_score

    if "multi_question" in problems:
        atomicity = min(atomicity, 5)
    if "assistant_meta_talk" in problems:
        clarity = min(clarity, 4)
        assessability = min(assessability, 5)
    if "format_noise" in problems:
        clarity = min(clarity, 5)
        context = min(context, 6)
    if "incomplete_syntax" in problems:
        clarity = min(clarity, 5)
        assessability = min(assessability, 5)
    if "semantic_incomplete" in problems:
        clarity = min(clarity, 5)
        context = min(context, 5)
        assessability = min(assessability, 6)
    if "missing_context_in_question" in problems:
        clarity = min(clarity, 5)
        context = min(context, 5)
    if "question_too_long" in problems:
        clarity = min(clarity, 7)
    if "question_contains_full_sentence" in problems:
        clarity = min(clarity, 6)
        context = min(context, 7)
    if "answer_too_long" in problems:
        assessability = min(assessability, 7)
    if "ambiguous_reference" in problems or "question_too_vague" in problems:
        clarity = min(clarity, 6)
        context = min(context, 6)
    if "missing_source_quote" in problems:
        source_alignment = min(source_alignment, 4)
    if "card_angle_not_supported_by_source" in problems:
        source_alignment = min(source_alignment, 6)
        assessability = min(assessability, 7)
    if "answer_not_supported_by_source" in problems:
        source_alignment = min(source_alignment, 6)
    if "question_not_grounded_in_source" in problems:
        context = min(context, 7)

    return report.model_copy(
        update={
            "atomicity_score": atomicity,
            "clarity_score": clarity,
            "assessability_score": assessability,
            "context_score": context,
            "source_alignment_score": source_alignment,
        }
    )


def heuristic_quality_check(card: Flashcard) -> CardQualityReport:
    problems = rule_based_card_check(card)
    atomicity = 10
    clarity = 10
    assessability = 10
    context = 10
    alignment = 10
    report = CardQualityReport(
        atomicity_score=atomicity,
        clarity_score=clarity,
        assessability_score=assessability,
        context_score=context,
        source_alignment_score=alignment,
        problems=problems,
        should_split="multi_question" in problems,
        rewrite_suggestion=None if not problems else "重写为短问题和直接答案，只保留来源片段支持的一个知识点。",
        missing_card_types=[],
    )
    return apply_problem_caps(report, problems)


def compact(text: str) -> str:
    return " ".join(str(text).replace("\u3000", " ").split())


def lexical_overlap(left: str, right: str) -> float:
    left_tokens = meaningful_tokens(left)
    right_tokens = meaningful_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def meaningful_tokens(text: str) -> set[str]:
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]{1,}", lowered))
    chinese_terms: set[str] = set()
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        chinese_terms.add(segment)
        for size in (2, 3, 4):
            for index in range(0, max(0, len(segment) - size + 1)):
                chinese_terms.add(segment[index : index + size])
    stop_terms = {
        "什么",
        "哪个",
        "如何",
        "用于",
        "可以",
        "解释",
        "理解",
        "一个",
        "知识点",
    }
    return {token for token in ascii_words | chinese_terms if token not in stop_terms}


def source_supports_card_angle(card_type: str, source: str) -> bool:
    markers = {
        "application": ("应用", "场景", "用于", "用来", "适合", "解决", "帮助"),
        "boundary": ("边界", "条件", "前提", "限制", "只有", "除非", "不适合"),
        "example": ("例如", "比如", "例子", "case", "example"),
        "counterexample": ("反例", "不是", "不能", "错误", "counterexample"),
        "misconception": ("误区", "不是", "不能", "错误", "混淆", "不要"),
    }
    return any(marker in source for marker in markers.get(card_type, ()))


def has_incomplete_syntax(text: str) -> bool:
    compacted = compact(text)
    if compacted.endswith(("(", "（", ":", "：", ",", "，", "、", "、", "和", "或")):
        return True
    return compacted.count("(") != compacted.count(")") or compacted.count("（") != compacted.count("）")


def is_low_signal_card(card_type: str, question: str, answer: str) -> bool:
    if card_type == "reverse" and any(marker in question for marker in LOW_SIGNAL_PHRASES):
        return True
    if question.startswith("如何直观理解") and any(marker in question for marker in LOW_SIGNAL_PHRASES):
        return True
    if answer in question or question.rstrip("？?") in answer:
        return True
    if any(marker in answer for marker in LOW_SIGNAL_PHRASES) and not any(term in question for term in ("DDL", "DML", "SQL", "DROP", "DELETE")):
        return True
    return False
