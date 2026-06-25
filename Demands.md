# 问题
“文本输入	粘贴文章、笔记、代码、面试记录	P0
知识点抽取	AI 自动识别核心概念	P0
原子化拆分	检测一张卡是否问了多个点	P0
双向卡生成	术语 → 定义，定义 → 术语	P0
多角度卡生成	正式定义、直觉解释、例子、反例、边界、应用	P0
用户审核	所有 AI 卡片必须人工确认再入库	P0
同步 Anki	通过 AnkiConnect 创建 note/card	P0
批量生成	一篇文章生成一组卡片	P0
来源绑定	每张卡关联来源片段	P0”这几个功能先做，如何做？通过ai的话，能不能借助langchain等框架实现？对比方案，给出一个实现大纲

# 回答
可以借助 **LangChain / LangGraph** 实现，但我建议你不要一开始就上复杂 Agent。你这个 P0 功能，本质是一个**确定性流水线 + LLM 结构化生成 + 人工审核 + AnkiConnect 同步**，不需要“自由 Agent 到处乱跑”。

最合理的第一版是：

```text
FastAPI / Streamlit / Next.js UI
  ↓
文本输入
  ↓
LLM 结构化抽取知识点
  ↓
LLM 生成多类型卡片
  ↓
LLM 质检与原子化检查
  ↓
人工审核/编辑
  ↓
AnkiConnect 同步到 Anki
```

AnkiConnect 很适合做同步层，因为它会在 Anki 启动时暴露本地 HTTP 服务，外部应用可以通过 HTTP POST 调用 Anki 的功能，比如查询牌组、创建卡片等。([GitHub][1]) LangChain 适合做结构化输出，因为它支持让模型返回 JSON、Pydantic model 或 dataclass 这种可直接被程序消费的数据结构。([LangChain Docs][2]) LangGraph 更适合后续做人审、状态流转、多步骤工作流，因为它的 StateGraph 是“节点读取/写入共享状态”的图式工作流。([langchain-ai.github.io][3])

---

# 1. 先做哪种方案？

## 方案对比

| 方案                       | 技术栈                                    | 优点                     | 缺点            | 适合阶段    |
| ------------------------ | -------------------------------------- | ---------------------- | ------------- | ------- |
| **直接调用 LLM API**         | FastAPI + OpenAI/Claude SDK + Pydantic | 最简单、可控、少依赖             | 多步骤编排要自己写     | MVP 0/1 |
| **LangChain**            | LangChain + Pydantic structured output | 结构化输出、Prompt 管理、模型切换方便 | 对简单流程可能略重     | MVP 1   |
| **LangGraph**            | LangGraph StateGraph                   | 适合多节点、人审、失败重试、状态机      | 学习成本更高        | MVP 2/3 |
| **Anki 原生插件**            | Python/PyQt + Anki 内部 API              | Anki 内体验最好             | UI/兼容性/异步调用麻烦 | 后期      |
| **外部 App + AnkiConnect** | Web UI + AnkiConnect                   | 最灵活，最适合快速迭代            | 需要 Anki 桌面端运行 | 强烈推荐第一版 |

我的建议：

```text
第一版：外部 Web App + AnkiConnect + LangChain structured output
第二版：引入 LangGraph 做完整工作流状态管理
第三版：再做 Anki 插件，只增强复习/编辑界面
```

不要一上来做 Anki 原生插件。Anki 插件开发需要 Python/PyQt，Anki 官方文档也说明 Anki UI 主要基于 Python/PyQt，部分界面使用 TypeScript/Svelte；插件开发要熟悉 Python 和 Anki 内部结构。([addon-docs.ankiweb.net][4]) 这条路适合后期体验优化，不适合第一版验证产品价值。

---

# 2. P0 功能拆解成产品流程

你列的功能可以合成一个核心流程：

```text
输入文本
  ↓
切分 chunk
  ↓
抽取知识点
  ↓
知识点去重/合并
  ↓
生成卡片候选
  ↓
原子化质检
  ↓
补齐双向卡、多角度卡
  ↓
来源绑定
  ↓
人工审核
  ↓
同步 Anki
```

对应你列出的 P0：

| 功能      | 实现方式                                                                            |
| ------- | ------------------------------------------------------------------------------- |
| 文本输入    | Web 表单 / Markdown 粘贴 / 文件上传                                                     |
| 知识点抽取   | LLM structured output                                                           |
| 原子化拆分   | LLM 质检 + 规则检查                                                                   |
| 双向卡生成   | 针对术语/定义类知识点自动生成 reverse card                                                    |
| 多角度卡生成  | 按 card_type 生成 definition/intuitive/example/counterexample/boundary/application |
| 用户审核    | 前端表格逐条编辑、删除、合并、批准                                                               |
| 同步 Anki | AnkiConnect `addNote` / 批量调用                                                    |
| 批量生成    | chunk 级并发处理 + 汇总去重                                                              |
| 来源绑定    | 每张卡保存 source_text、source_chunk_id、source_offset                                 |

---

# 3. 第一版推荐架构

## 技术栈

```text
前端：
- Streamlit：最快做 MVP
或
- Next.js / React：更适合长期产品化

后端：
- FastAPI

AI 编排：
- LangChain structured output
- 后续可升级 LangGraph

数据校验：
- Pydantic

数据库：
- SQLite 起步
- 后续 PostgreSQL

Anki 同步：
- AnkiConnect

任务队列：
- MVP 可不用
- 后续 Celery / RQ / Dramatiq

LLM：
- OpenAI / Claude / Gemini / DeepSeek API
- 通过统一 Model Adapter 封装
```

## 架构图

```text
┌────────────────────────────┐
│          Web UI             │
│ 文本输入 / 卡片审核 / 同步按钮 │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│         FastAPI Backend     │
│ 项目管理 / 流程控制 / 数据校验 │
└───────┬───────────┬────────┘
        ↓           ↓
┌─────────────┐   ┌────────────────────┐
│   SQLite    │   │  LangChain / LLM     │
│ 项目/知识点/卡片 │   │ 抽取/生成/质检       │
└─────────────┘   └────────────────────┘
        ↓
┌────────────────────────────┐
│        AnkiConnect          │
│ HTTP POST localhost:8765    │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│            Anki             │
│ Deck / Note / Card / FSRS   │
└────────────────────────────┘
```

---

# 4. 核心数据模型设计

## 4.1 SourceDocument：输入文本

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class SourceDocument(BaseModel):
    id: str
    title: str
    content: str
    source_type: Literal["article", "note", "code", "interview", "manual"]
    created_at: datetime
```

---

## 4.2 SourceChunk：文本切片

```python
class SourceChunk(BaseModel):
    id: str
    document_id: str
    index: int
    text: str
    start_char: int
    end_char: int
```

来源绑定一定要从第一版就做，否则后面无法追溯卡片质量。

---

## 4.3 KnowledgePoint：知识点

```python
class KnowledgePoint(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    title: str
    summary: str
    knowledge_type: Literal[
        "concept",
        "mechanism",
        "process",
        "comparison",
        "misconception",
        "application",
        "code",
        "interview"
    ]
    importance: int = Field(ge=1, le=5)
    confidence: Literal["low", "medium", "high"]
    source_quote: str
```

---

## 4.4 FlashcardCandidate：卡片候选

```python
class FlashcardCandidate(BaseModel):
    id: str
    knowledge_id: str
    card_type: Literal[
        "definition",
        "reverse",
        "mechanism",
        "compare",
        "intuition",
        "example",
        "counterexample",
        "boundary",
        "application",
        "interview"
    ]
    question: str
    answer: str
    source_quote: str
    tags: list[str]
    status: Literal["draft", "approved", "rejected", "synced"] = "draft"
```

---

## 4.5 CardQualityReport：卡片质检

```python
class CardQualityReport(BaseModel):
    card_id: str
    atomicity_score: int = Field(ge=0, le=10)
    clarity_score: int = Field(ge=0, le=10)
    assessability_score: int = Field(ge=0, le=10)
    context_score: int = Field(ge=0, le=10)
    source_alignment_score: int = Field(ge=0, le=10)
    problems: list[str]
    rewrite_suggestion: Optional[str] = None
    should_split: bool
    missing_card_types: list[str]
```

---

# 5. AI 流程如何设计？

## Step 1：文本输入

用户粘贴：

```text
标题：Go runtime 与 epoll
类型：note
内容：……
目标 deck：AI工程::并发模型
```

后端保存为 `SourceDocument`。

---

## Step 2：文本切分

不要直接整篇文章丢给模型。第一版建议：

```text
中文技术文档：
- 800～1500 中文字一个 chunk
- 保留标题层级
- chunk 之间 overlap 100～200 字
```

伪代码：

```python
def split_text(text: str, max_len: int = 1200, overlap: int = 150) -> list[SourceChunk]:
    chunks = []
    start = 0
    index = 0

    while start < len(text):
        end = min(start + max_len, len(text))
        chunk_text = text[start:end]

        chunks.append(SourceChunk(
            id=f"chunk_{index}",
            document_id="doc_id",
            index=index,
            text=chunk_text,
            start_char=start,
            end_char=end,
        ))

        start = end - overlap
        index += 1

    return chunks
```

---

## Step 3：知识点抽取

这里非常适合用 LangChain 的 structured output。LangChain 文档说明 structured output 可以让模型返回指定格式的数据，而不是自然语言文本，程序可以直接拿到 JSON/Pydantic 对象。([LangChain Docs][2])

### 输出 schema

```python
class ExtractedKnowledgePoint(BaseModel):
    title: str
    summary: str
    knowledge_type: Literal[
        "concept",
        "mechanism",
        "process",
        "comparison",
        "misconception",
        "application",
        "code",
        "interview"
    ]
    importance: int = Field(ge=1, le=5)
    source_quote: str
    reason: str


class KnowledgeExtractionResult(BaseModel):
    points: list[ExtractedKnowledgePoint]
```

### Prompt

```text
你是技术学习知识工程师。

请从下面文本中抽取适合做成 Anki 卡片的核心知识点。

要求：
1. 只抽取重要知识点，不要抽无意义细节。
2. 每个知识点必须能独立理解。
3. 标注知识点类型：concept/mechanism/process/comparison/misconception/application/code/interview。
4. 每个知识点必须绑定原文 source_quote。
5. 如果内容不适合制卡，少抽或不抽。
6. 不要编造原文没有的信息。

文本：
{{chunk_text}}
```

---

## Step 4：知识点去重/合并

同一篇文章多个 chunk 可能抽出重复知识点。

第一版可以用两层去重：

```text
规则去重：
- title 完全相同
- summary 高度相似

AI 去重：
- 给模型一组候选知识点，让它合并重复项
```

MVP 阶段可以简单做：

```python
def normalize_title(title: str) -> str:
    return title.lower().replace(" ", "").replace("：", ":")

def dedup_points(points):
    seen = set()
    result = []
    for p in points:
        key = normalize_title(p.title)
        if key not in seen:
            result.append(p)
            seen.add(key)
    return result
```

后续再加 embedding similarity。

---

## Step 5：多类型卡片生成

每个知识点生成卡片时，不要让模型随意发挥，而要明确卡片类型。

### 卡片类型策略

| 知识点类型         | 默认生成卡片                                        |
| ------------- | --------------------------------------------- |
| concept       | definition、reverse、intuition、example、boundary |
| mechanism     | mechanism、intuition、application、misconception |
| process       | sequence、step_reverse、application             |
| comparison    | compare、boundary、misconception                |
| misconception | misconception、corrective、compare              |
| application   | application、interview、debug                   |
| code          | code_explain、bug、application                  |
| interview     | interview、follow_up、concise_answer            |

你列的 P0 中包括双向卡和多角度卡，第一版可以统一生成这几类：

```text
definition：正式定义
reverse：反向卡
intuition：直觉解释
example：例子
counterexample：反例
boundary：边界条件
application：应用场景
misconception：误区卡
```

### Prompt

```text
你是 Anki 制卡专家。

请基于下面知识点生成高质量 Anki 卡片。

知识点：
标题：{{title}}
摘要：{{summary}}
类型：{{knowledge_type}}
来源片段：{{source_quote}}

制卡要求：
1. 一张卡只测试一个知识点。
2. 问题必须明确，不要使用“它”“这个”等缺少上下文的指代。
3. 答案必须可评分。
4. 答案尽量简洁。
5. 必须绑定来源片段，不要编造来源没有的结论。
6. 至少生成：
   - definition：正式定义
   - reverse：定义反问术语
   - intuition：直觉解释
   - example：例子
   - boundary：边界/适用条件
   - application：应用卡
   - misconception：误区卡，如果知识点适合

输出结构化 JSON。
```

---

## Step 6：原子化质检

这一步很关键。不要“生成完就入库”。

每张卡过一次 AI 质检：

```text
检查：
1. 是否一题多问？
2. 问题是否明确？
3. 答案是否可评分？
4. 是否脱离上下文？
5. 是否和来源片段一致？
6. 是否需要拆分？
7. 是否缺少反向卡/误区卡/例子卡？
```

### Prompt

```text
你是 Anki 卡片质量审查器。

请审查下面卡片：

问题：
{{question}}

答案：
{{answer}}

来源片段：
{{source_quote}}

请从 0-10 评分：
1. 原子性
2. 清晰性
3. 可评分性
4. 上下文完整性
5. 来源一致性

请判断：
- 是否一题多问
- 是否建议拆分
- 是否建议改写
- 是否存在来源没有支持的内容
- 还缺哪些类型的卡片

输出结构化 JSON。
```

### 规则过滤

除了 AI，也建议加硬规则：

```python
def rule_based_card_check(card: FlashcardCandidate) -> list[str]:
    problems = []

    if len(card.question) > 120:
        problems.append("question_too_long")

    if len(card.answer) > 300:
        problems.append("answer_too_long")

    bad_phrases = ["说说", "谈谈", "理解一下", "介绍一下"]
    if any(p in card.question for p in bad_phrases):
        problems.append("question_too_vague")

    if "它" in card.question or "这个" in card.question:
        problems.append("ambiguous_reference")

    return problems
```

AI 质检 + 规则质检结合，比单纯 AI 更稳。

---

## Step 7：人工审核

这是第一版必须有的功能。

前端需要一个审核表格：

| 字段   | 操作                  |
| ---- | ------------------- |
| 卡片类型 | 可改                  |
| 问题   | 可编辑                 |
| 答案   | 可编辑                 |
| 来源片段 | 可展开                 |
| 质量评分 | 显示                  |
| 标签   | 可编辑                 |
| 操作   | 批准 / 拒绝 / 重新生成 / 拆分 |

审核状态：

```text
draft → approved → synced
draft → rejected
draft → regenerate
```

**重点：AI 不能直接写入 Anki，必须人工审核。**
否则很容易把错误卡片长期固化。

---

## Step 8：同步 Anki

同步层用 AnkiConnect。它的价值是你不用写 Anki 插件，也能创建卡片。AnkiConnect 官方说明外部应用可通过本地 HTTP API 与 Anki 通信，默认会在 Anki 启动时初始化本地 HTTP 服务。([GitHub][1])

### Anki Note Type 建议

建立一个自定义 Note Type：

```text
AI Knowledge Card
```

字段：

```text
Question
Answer
CardType
KnowledgeTitle
SourceQuote
SourceDocument
Confidence
QualityScore
GeneratedBy
```

### Tags 建议

```text
ai::generated
ai::reviewed
source::article
type::definition
type::reverse
type::boundary
topic::go-runtime
status::active
```

### AnkiConnect 调用示例

```python
import requests


ANKI_CONNECT_URL = "http://localhost:8765"


def anki_request(action: str, params: dict | None = None):
    payload = {
        "action": action,
        "version": 6,
        "params": params or {},
    }
    response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("error"):
        raise RuntimeError(data["error"])

    return data["result"]


def add_note_to_anki(
    deck_name: str,
    model_name: str,
    question: str,
    answer: str,
    card_type: str,
    source_quote: str,
    tags: list[str],
):
    return anki_request("addNote", {
        "note": {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": {
                "Question": question,
                "Answer": answer,
                "CardType": card_type,
                "SourceQuote": source_quote,
            },
            "tags": tags,
        }
    })
```

---

# 6. LangChain / LangGraph 怎么选？

## 6.1 直接 LLM API：最简单

适合 MVP 0。

```python
client.chat.completions.create(...)
json.loads(...)
```

优点：

```text
简单、透明、调试容易
```

缺点：

```text
结构化输出、重试、模型切换、Prompt 管理要自己封装
```

---

## 6.2 LangChain：适合第一版

你这几个 P0 功能很适合 LangChain：

```text
- 知识点抽取：structured output
- 卡片生成：structured output
- 卡片质检：structured output
- 模型切换：统一接口
- Prompt 模板管理：方便
```

LangChain 当前文档明确推荐用 structured output 获得可预测的数据结构，比如 JSON objects、Pydantic models 或 dataclasses。([LangChain Docs][2])

### LangChain 伪代码

```python
from pydantic import BaseModel, Field
from typing import Literal
from langchain_openai import ChatOpenAI


class Card(BaseModel):
    card_type: Literal[
        "definition", "reverse", "intuition",
        "example", "counterexample", "boundary",
        "application", "misconception"
    ]
    question: str
    answer: str
    source_quote: str
    tags: list[str]


class CardGenerationResult(BaseModel):
    cards: list[Card]


llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.2)

structured_llm = llm.with_structured_output(CardGenerationResult)

result = structured_llm.invoke("""
请基于下面知识点生成 Anki 卡片……
""")

cards = result.cards
```

---

## 6.3 LangGraph：适合第二版

当你想做完整流程状态机时，LangGraph 更合适。

原因：

```text
1. 流程有多个节点：chunk → extract → generate → critique → review → sync
2. 有条件分支：质检不过 → 重新生成
3. 有人工审核：approved 才能进入 sync
4. 有状态累积：document、chunks、points、cards、reports
5. 有失败重试：LLM 输出失败、AnkiConnect 失败
```

LangGraph 官方介绍它适合 long-running、stateful workflow；StateGraph 的节点通过共享状态通信，每个节点读取状态并返回部分状态更新。([LangChain Docs][5])

### LangGraph 流程图

```text
START
  ↓
split_text
  ↓
extract_knowledge_points
  ↓
deduplicate_points
  ↓
generate_cards
  ↓
quality_check
  ↓
needs_regeneration?
  ├─ yes → regenerate_cards → quality_check
  └─ no  → wait_for_human_review
             ↓
          sync_to_anki
             ↓
            END
```

### 状态定义

```python
from typing import TypedDict


class CardPipelineState(TypedDict):
    document_id: str
    title: str
    content: str
    chunks: list[dict]
    knowledge_points: list[dict]
    card_candidates: list[dict]
    quality_reports: list[dict]
    approved_cards: list[dict]
    sync_results: list[dict]
    errors: list[str]
```

### 节点设计

```python
def split_text_node(state: CardPipelineState) -> dict:
    chunks = split_text(state["content"])
    return {"chunks": [c.model_dump() for c in chunks]}


def extract_points_node(state: CardPipelineState) -> dict:
    all_points = []
    for chunk in state["chunks"]:
        result = extract_knowledge_points(chunk["text"])
        all_points.extend(result.points)
    return {"knowledge_points": [p.model_dump() for p in all_points]}


def generate_cards_node(state: CardPipelineState) -> dict:
    cards = []
    for point in state["knowledge_points"]:
        result = generate_cards(point)
        cards.extend(result.cards)
    return {"card_candidates": [c.model_dump() for c in cards]}


def quality_check_node(state: CardPipelineState) -> dict:
    reports = []
    for card in state["card_candidates"]:
        report = check_card_quality(card)
        reports.append(report)
    return {"quality_reports": [r.model_dump() for r in reports]}
```

第一版不一定要上 LangGraph，但你的产品路线如果要继续做“人审 + 质检失败重试 + 错误日志 + 知识版本”，LangGraph 会越来越适合。

---

# 7. MVP 页面怎么设计？

## 页面 1：新建制卡任务

字段：

```text
标题
文本类型：文章 / 笔记 / 代码 / 面试记录
目标 Deck
主题标签
输入文本
生成按钮
```

---

## 页面 2：知识点抽取结果

表格：

| 是否保留 | 知识点                  | 类型            | 重要性 | 来源片段             |
| ---- | -------------------- | ------------- | --: | ---------------- |
| ✅    | Go runtime netpoller | mechanism     |   5 | netpoller 会封装... |
| ✅    | Go runtime 不等于事件循环   | misconception |   5 | Go runtime 包含... |

操作：

```text
保留 / 删除 / 合并 / 编辑 / 重新抽取
```

---

## 页面 3：卡片候选审核

表格：

| 状态    | 类型         | 问题                | 答案  | 质量分 | 来源 | 操作       |
| ----- | ---------- | ----------------- | --- | --: | -- | -------- |
| draft | definition | netpoller 的作用是什么？ | ... |  91 | 展开 | 批准/拒绝/改写 |
| draft | reverse    | 哪个组件负责 fd 就绪唤醒？   | ... |  86 | 展开 | 批准/拒绝/改写 |

操作：

```text
批量批准
批量拒绝
AI 改写
AI 拆分
生成反向卡
生成误区卡
同步到 Anki
```

---

## 页面 4：同步结果

显示：

```text
成功同步：28 张
失败：2 张
失败原因：
- duplicate note
- deck not found
```

可操作：

```text
重试
修改 deck
允许重复
导出 CSV
```

---

# 8. 后端 API 设计

```text
POST /documents
创建输入文档

POST /documents/{id}/extract
抽取知识点

GET /documents/{id}/knowledge-points
查看知识点

POST /knowledge-points/{id}/generate-cards
生成卡片

POST /cards/{id}/quality-check
卡片质检

POST /cards/{id}/approve
批准卡片

POST /cards/{id}/reject
拒绝卡片

POST /cards/{id}/regenerate
重新生成卡片

POST /anki/sync
同步批准卡片到 Anki

GET /anki/decks
读取 Anki 牌组

GET /tasks/{id}
查看任务状态
```

---

# 9. 数据库表设计 MVP

```sql
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source_type TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  start_char INTEGER,
  end_char INTEGER
);

CREATE TABLE knowledge_points (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  chunk_id TEXT,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  knowledge_type TEXT NOT NULL,
  importance INTEGER,
  confidence TEXT,
  source_quote TEXT,
  status TEXT DEFAULT 'draft',
  created_at TEXT NOT NULL
);

CREATE TABLE flashcard_candidates (
  id TEXT PRIMARY KEY,
  knowledge_id TEXT NOT NULL,
  card_type TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  source_quote TEXT,
  tags TEXT,
  status TEXT DEFAULT 'draft',
  quality_score REAL,
  anki_note_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE card_quality_reports (
  id TEXT PRIMARY KEY,
  card_id TEXT NOT NULL,
  atomicity_score INTEGER,
  clarity_score INTEGER,
  assessability_score INTEGER,
  context_score INTEGER,
  source_alignment_score INTEGER,
  problems TEXT,
  rewrite_suggestion TEXT,
  should_split INTEGER,
  created_at TEXT NOT NULL
);
```

---

# 10. 实现顺序建议

## 第 1 周：打通最小闭环

目标：

```text
粘贴文本 → 生成卡片 → 人工审核 → 同步 Anki
```

只做：

```text
1. FastAPI 项目
2. Streamlit 简单 UI
3. LangChain structured output
4. SQLite 存储
5. AnkiConnect addNote
```

不做：

```text
复杂知识图谱
复杂状态机
Obsidian 集成
Anki 插件
多用户系统
```

---

## 第 2 周：加入质检和来源绑定

新增：

```text
1. source_quote 强制绑定
2. AI 质量评分
3. 问题卡片标红
4. AI 改写按钮
5. 批量审核
```

---

## 第 3 周：加入批量生成和去重

新增：

```text
1. 长文本 chunk
2. 多 chunk 并发抽取
3. 知识点去重
4. 卡片去重
5. 失败重试
```

---

## 第 4 周：引入 LangGraph

当流程稳定后，把原来的线性代码改成图工作流：

```text
split
extract
deduplicate
generate
critique
regenerate
review
sync
```

这样你后续加错误日志、版本修正会顺很多。

---

# 11. 第一版不要做什么？

这些功能很诱人，但第一版先别做：

```text
1. 不要重写 Anki 调度算法
2. 不要做移动端
3. 不要做复杂知识图谱
4. 不要做全自动入库
5. 不要做多人协作
6. 不要做 Anki 原生插件
7. 不要做 RAG 检索增强
8. 不要做全量 Obsidian 双向同步
```

第一版的核心验证是：

> **AI 是否能稳定生成比手写更快、更好的原子卡片，并且保留人工审核权。**

---

# 12. 一个最小可运行项目结构

```text
ai-anki-workbench/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── models.py                # Pydantic schemas
│   ├── db.py                    # SQLite 初始化
│   ├── services/
│   │   ├── chunker.py            # 文本切分
│   │   ├── extractor.py          # 知识点抽取
│   │   ├── card_generator.py     # 卡片生成
│   │   ├── quality_checker.py    # 卡片质检
│   │   └── anki_client.py        # AnkiConnect
│   ├── prompts/
│   │   ├── extract.md
│   │   ├── generate_cards.md
│   │   └── quality_check.md
│   └── routers/
│       ├── documents.py
│       ├── cards.py
│       └── anki.py
├── ui/
│   └── streamlit_app.py
├── requirements.txt
└── README.md
```

---

# 13. 核心代码骨架

## 13.1 models.py

```python
from pydantic import BaseModel, Field
from typing import Literal


class ExtractedKnowledgePoint(BaseModel):
    title: str
    summary: str
    knowledge_type: Literal[
        "concept",
        "mechanism",
        "process",
        "comparison",
        "misconception",
        "application",
        "code",
        "interview",
    ]
    importance: int = Field(ge=1, le=5)
    confidence: Literal["low", "medium", "high"]
    source_quote: str
    reason: str


class KnowledgeExtractionResult(BaseModel):
    points: list[ExtractedKnowledgePoint]


class Flashcard(BaseModel):
    card_type: Literal[
        "definition",
        "reverse",
        "mechanism",
        "compare",
        "intuition",
        "example",
        "counterexample",
        "boundary",
        "application",
        "misconception",
        "interview",
    ]
    question: str
    answer: str
    source_quote: str
    tags: list[str]


class CardGenerationResult(BaseModel):
    cards: list[Flashcard]


class CardQualityReport(BaseModel):
    atomicity_score: int = Field(ge=0, le=10)
    clarity_score: int = Field(ge=0, le=10)
    assessability_score: int = Field(ge=0, le=10)
    context_score: int = Field(ge=0, le=10)
    source_alignment_score: int = Field(ge=0, le=10)
    problems: list[str]
    should_split: bool
    rewrite_suggestion: str | None = None
    missing_card_types: list[str]
```

---

## 13.2 extractor.py

```python
from langchain_openai import ChatOpenAI
from app.models import KnowledgeExtractionResult


llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)
extractor = llm.with_structured_output(KnowledgeExtractionResult)


def extract_knowledge_points(chunk_text: str) -> KnowledgeExtractionResult:
    prompt = f"""
你是技术学习知识工程师。

请从下面文本中抽取适合做成 Anki 卡片的核心知识点。

要求：
1. 只抽取重要知识点，不要抽无意义细节。
2. 每个知识点必须能独立理解。
3. 标注知识点类型。
4. 每个知识点必须绑定原文 source_quote。
5. 不要编造原文没有的信息。

文本：
{chunk_text}
"""
    return extractor.invoke(prompt)
```

---

## 13.3 card_generator.py

```python
from langchain_openai import ChatOpenAI
from app.models import CardGenerationResult, ExtractedKnowledgePoint


llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.2)
card_generator = llm.with_structured_output(CardGenerationResult)


def generate_cards(point: ExtractedKnowledgePoint) -> CardGenerationResult:
    prompt = f"""
你是 Anki 制卡专家。

请基于下面知识点生成高质量 Anki 卡片。

知识点标题：{point.title}
知识点摘要：{point.summary}
知识点类型：{point.knowledge_type}
来源片段：{point.source_quote}

要求：
1. 一张卡只测试一个知识点。
2. 问题必须明确。
3. 答案必须可评分。
4. 答案尽量简洁。
5. 必须绑定来源片段。
6. 至少覆盖：
   - definition
   - reverse
   - intuition
   - example
   - boundary
   - application
   - misconception，如果适合
"""
    return card_generator.invoke(prompt)
```

---

## 13.4 quality_checker.py

```python
from langchain_openai import ChatOpenAI
from app.models import Flashcard, CardQualityReport


llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)
quality_checker = llm.with_structured_output(CardQualityReport)


def check_card_quality(card: Flashcard) -> CardQualityReport:
    prompt = f"""
你是 Anki 卡片质量审查器。

请审查下面卡片：

问题：
{card.question}

答案：
{card.answer}

来源片段：
{card.source_quote}

请从 0-10 评分：
1. 原子性
2. 清晰性
3. 可评分性
4. 上下文完整性
5. 来源一致性

请判断是否一题多问、是否建议拆分、是否需要改写。
"""
    return quality_checker.invoke(prompt)
```

---

## 13.5 anki_client.py

```python
import requests


ANKI_CONNECT_URL = "http://localhost:8765"


class AnkiConnectError(Exception):
    pass


def anki_request(action: str, params: dict | None = None):
    payload = {
        "action": action,
        "version": 6,
        "params": params or {},
    }

    response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
    response.raise_for_status()

    data = response.json()

    if data.get("error"):
        raise AnkiConnectError(data["error"])

    return data["result"]


def get_deck_names() -> list[str]:
    return anki_request("deckNames")


def add_ai_card(
    deck_name: str,
    model_name: str,
    question: str,
    answer: str,
    card_type: str,
    source_quote: str,
    tags: list[str],
):
    return anki_request("addNote", {
        "note": {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": {
                "Question": question,
                "Answer": answer,
                "CardType": card_type,
                "SourceQuote": source_quote,
            },
            "tags": tags,
        }
    })
```

---

# 14. 质量控制原则

第一版要遵守几个强约束。

## 约束 1：禁止无来源卡片

每张卡必须有：

```text
source_quote
source_document
source_chunk_id
```

否则不允许同步。

---

## 约束 2：AI 生成必须人工审核

卡片状态必须是：

```text
draft → approved → synced
```

不能：

```text
draft → synced
```

---

## 约束 3：低质量卡不能同步

例如：

```text
atomicity_score < 7
clarity_score < 7
source_alignment_score < 8
```

默认禁止同步，除非用户强制批准。

---

## 约束 4：一题多问自动标红

比如问题中出现：

```text
“分别解释 A、B、C”
“是什么？为什么？如何使用？”
“对比 A 和 B，并说明应用场景”
```

这类大概率需要拆分。

---

# 15. 最终推荐方案

你的 P0 功能，我建议这样落地：

```text
实现形态：
外部 Web App，不做 Anki 原生插件

AI 框架：
第一版用 LangChain structured output
第二版引入 LangGraph 编排状态流

同步方式：
AnkiConnect

前端：
先用 Streamlit 快速验证
后续改 Next.js

后端：
FastAPI + SQLite

核心闭环：
文本输入 → 知识点抽取 → 多类型卡片生成 → 质量检查 → 人工审核 → Anki 同步
```

一句话：

> **第一版不要做“智能 Agent”，而是做“可控的 AI 制卡流水线”。LangChain 负责结构化生成，AnkiConnect 负责同步，人工审核负责质量兜底。等流程复杂后，再用 LangGraph 把它升级成状态机。**

[1]: https://github.com/amikey/anki-connect?utm_source=chatgpt.com "AnkiConnect"
[2]: https://docs.langchain.com/oss/python/langchain/structured-output?utm_source=chatgpt.com "Structured output - Docs by LangChain"
[3]: https://langchain-ai.github.io/langgraphjs/reference/classes/langgraph.StateGraph.html?utm_source=chatgpt.com "StateGraph | LangGraph.js API Reference"
[4]: https://addon-docs.ankiweb.net/?utm_source=chatgpt.com "Writing Anki Add-ons: Introduction"
[5]: https://docs.langchain.com/oss/python/langgraph/overview?utm_source=chatgpt.com "LangGraph overview - Docs by LangChain"
