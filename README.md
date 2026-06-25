# AI Anki Workbench

一个本地 AI 制卡工作台：粘贴文章、笔记、代码或面试记录，自动清洗文本、抽取知识点、生成 Anki 原子卡片、做 90 分质量门控，并通过 AnkiConnect 同步到 Anki。

## 功能

- 文本清洗：去掉 Markdown、HTML、列表符号、反引号和复制噪声。
- 知识点抽取：保留来源片段，并尽量补足必要上下文。
- 卡片生成：生成短小、可验证、语义完整的 Anki 卡片。
- 质量门控：默认本地规则质检，低于 90 分的卡不会进入同步队列。
- 人工审核：HTML 前端支持编辑、批准、拒绝、退回草稿。
- Anki 同步：默认适配中文 Anki 的 `Default` 牌组和 `问答题` 笔记类型，也兼容 `Basic`。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

配置 `.env`。后端只依赖通用 `LLM_*` 配置，方便切换 DeepSeek、OpenAI-compatible 网关或其他兼容服务：

```env
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_ID=deepseek-v4-pro
LLM_STRUCTURED_METHOD=manual_json
LLM_REQUEST_TIMEOUT=45
MAX_QUALITY_ATTEMPTS=2
BATCH_CARD_GENERATION=1
USE_LLM_QUALITY_CHECK=0
USE_LLM_CARD_REVISION=0
ANKI_CONNECT_URL=http://localhost:8765
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8008
AI_ANKI_API_BASE=http://127.0.0.1:8008
```

## 启动

```powershell
.\scripts\start_backend.ps1
```

然后打开：

```text
http://127.0.0.1:8008
```

现在前端由 FastAPI 直接提供，不需要再启动 Streamlit。`scripts/start_ui.ps1` 只保留为提示脚本。

## Anki 准备

1. 安装并启用 AnkiConnect。
2. 保持 Anki 桌面端运行。
3. 使用默认 `Default` 牌组即可。
4. 中文 Anki 默认 `问答题` 笔记类型可直接同步，字段会自动映射到 `正面 / 背面`。

如果使用英文 Anki，默认 `Basic` 的 `Front / Back` 也会自动适配。

## API

- `POST /documents`：创建文档。
- `POST /documents/{id}/generate`：抽取知识点、生成卡片、质检。
- `GET /documents/{id}/cards`：查看候选卡。
- `PATCH /cards/{id}`：编辑卡片。
- `POST /cards/{id}/approve`：批准卡片。
- `POST /cards/{id}/reject`：拒绝卡片。
- `POST /cards/approve-drafts`：一键批准 90+ 草稿。
- `GET /anki/decks`：读取 Anki 牌组。
- `GET /anki/models`：读取 Anki 笔记类型。
- `POST /anki/sync`：同步已批准卡片。

## 性能建议

- `LLM_STRUCTURED_METHOD=manual_json`：对 DeepSeek/OpenAI-compatible 网关只发一次 JSON prompt，避免结构化输出失败后的二次等待。
- `BATCH_CARD_GENERATION=1`：多个知识点合并成一次制卡请求，减少 API 往返。
- `USE_LLM_QUALITY_CHECK=0`、`USE_LLM_CARD_REVISION=0`：质量门控走本地硬规则，避免每张卡都再次调用模型。
- `LLM_TRACE=1`：后端日志显示每次 LLM 调用的 schema、prompt 长度、耗时和失败原因。
