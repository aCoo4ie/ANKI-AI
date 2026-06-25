# AI Anki Workbench

一个最小可运行的 AI 制卡工作台，覆盖需求里的 P0 闭环：

- 文本输入：粘贴文章、笔记、代码、面试记录。
- 知识点抽取：优先使用 OpenAI-compatible LLM API；未配置 `LLM_API_KEY` 时使用启发式兜底。
- 原子化质检：本地硬规则 + 可选 AI 质检，标记一题多问、过长、指代不清、聊天废话、来源不贴合等问题。
- 循环质量门控：生成后会评测，不达 90 分会改写重测；仍不达标的卡自动标记 `rejected`，默认不进入审核列表。
- 双向卡与多角度卡：生成 definition、reverse、intuition、boundary、application 等候选卡。
- 用户审核：卡片默认是 `draft`，必须人工 `approve` 后才能同步。
- 来源绑定：每个知识点和卡片都保存 `source_quote`。
- 同步 Anki：通过 AnkiConnect 调用 `addNote`。

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

配置 `.env` 或环境变量。后端只需要通用 `LLM_*` 配置，方便切换 DeepSeek、OpenAI-compatible 网关或其他兼容服务：

```powershell
$env:LLM_API_KEY="你的 Key"
$env:LLM_BASE_URL="https://api.deepseek.com"
$env:LLM_MODEL_ID="deepseek-v4-pro"
```

质量门控开关：

```powershell
$env:MAX_QUALITY_ATTEMPTS="2"
$env:USE_LLM_QUALITY_CHECK="0"
$env:USE_LLM_CARD_REVISION="0"
$env:BATCH_CARD_GENERATION="1"
$env:LLM_STRUCTURED_METHOD="manual_json"
$env:LLM_TRACE="1"
```

默认使用本地硬规则做 90 分门控，避免逐卡远程质检太慢。需要更重的模型评审时，把后两个开关设为 `1`。

性能建议：

- `LLM_STRUCTURED_METHOD=manual_json`：对 DeepSeek/OpenAI-compatible 网关只发一次 JSON prompt，避免 structured output 失败后再 fallback 导致双倍等待。
- `BATCH_CARD_GENERATION=1`：多个知识点合并为一次制卡请求，减少 API 往返。
- `LLM_TRACE=1`：后端日志会显示每次 LLM 调用的 schema、prompt 长度、耗时和失败原因。
- `USE_LLM_QUALITY_CHECK=0`、`USE_LLM_CARD_REVISION=0`：质量门控走本地硬规则，避免每张卡再调用模型。

启动后端：

```powershell
.\scripts\start_backend.ps1
```

启动 Streamlit：

```powershell
.\scripts\start_ui.ps1
```

如果不用脚本，也可以显式指定端口：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8008
```

`.env` 里的 `AI_ANKI_API_BASE` 是前端访问后端的地址，不会自动改变 `uvicorn` 的监听端口；直接运行 `uvicorn app.main:app --reload` 会默认使用 8000。

没有 `LLM_API_KEY` 也能跑通流程，但生成质量只是演示级；配置模型后会走 LLM 结构化输出。

## Anki 准备

1. 安装并启用 AnkiConnect。
2. 保持 Anki 桌面端运行。
3. 建议创建 Note Type：`AI Knowledge Card`。
4. 字段至少包含：

```text
Question
Answer
CardType
SourceQuote
```

## API

- `POST /documents`：创建文档。
- `POST /documents/{id}/generate`：切分文本、抽取知识点、生成卡片、质检。
- `GET /documents/{id}/cards`：查看候选卡。
- `PATCH /cards/{id}`：编辑卡片。
- `POST /cards/{id}/approve`：批准卡片。
- `POST /cards/{id}/reject`：拒绝卡片。
- `POST /anki/sync`：同步已批准卡片。

## 后续路线

第一版保持确定性流水线。等人审、重试、版本和错误日志需求变复杂后，再把 `pipeline.py` 拆成 LangGraph 的 `split -> extract -> deduplicate -> generate -> critique -> review -> sync` 状态机。
