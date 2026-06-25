from __future__ import annotations

import os
import json
import re
import time
from typing import Any, TypeVar

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience
    load_dotenv = None


if load_dotenv:
    load_dotenv(override=True)


T = TypeVar("T")


def clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def structured_invoke(
    schema: type[T],
    prompt: str,
    temperature: float = 0.1,
    label: str | None = None,
) -> T | None:
    """Return structured LLM output when LangChain and an API key are configured.

    The app remains usable without an API key through deterministic fallbacks in
    each service. This keeps the MVP demoable before model credentials exist.
    """
    api_key = clean_env("LLM_API_KEY") or clean_env("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    model = clean_env("LLM_MODEL_ID") or clean_env("OPENAI_MODEL") or "gpt-4.1-mini"
    base_url = clean_env("LLM_BASE_URL") or clean_env("OPENAI_BASE_URL")
    llm_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "api_key": api_key,
        "max_retries": 1,
        "request_timeout": float(clean_env("LLM_REQUEST_TIMEOUT") or "45"),
    }
    if base_url:
        llm_kwargs["base_url"] = base_url

    llm = ChatOpenAI(**llm_kwargs)
    method = clean_env("LLM_STRUCTURED_METHOD")
    if not method:
        method = "manual_json" if base_url else "json_schema"

    json_prompt = build_json_prompt(schema, prompt)
    trace_label = label or schema.__name__
    trace_started_at = time.perf_counter()
    trace_llm_start(trace_label, schema, model, base_url, method, prompt, json_prompt)
    if method == "manual_json":
        try:
            raw_result = llm.invoke(json_prompt)
            content = raw_result.content if hasattr(raw_result, "content") else str(raw_result)
            result = parse_json_response(schema, str(content))
            trace_llm_end(trace_label, trace_started_at, ok=True, path="manual_json")
            return result
        except Exception as exc:
            trace_llm_end(trace_label, trace_started_at, ok=False, path="manual_json", error=exc)
            return None

    try:
        structured = llm.with_structured_output(schema, method=method)
        result: Any = structured.invoke(json_prompt if method == "json_mode" else prompt)
        trace_llm_end(trace_label, trace_started_at, ok=True, path=f"structured:{method}")
        return result
    except Exception as first_exc:
        trace_llm_end(trace_label, trace_started_at, ok=False, path=f"structured:{method}", error=first_exc)
        fallback_started_at = time.perf_counter()
        try:
            raw_result = llm.invoke(json_prompt)
            content = raw_result.content if hasattr(raw_result, "content") else str(raw_result)
            result = parse_json_response(schema, str(content))
            trace_llm_end(trace_label, fallback_started_at, ok=True, path="fallback_json")
            return result
        except Exception as exc:
            trace_llm_end(trace_label, fallback_started_at, ok=False, path="fallback_json", error=exc)
            return None


def build_json_prompt(schema: type[T], prompt: str) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return f"""
{prompt}

请只返回一个 JSON 对象，不要包含 Markdown 代码块或额外解释。
JSON 必须符合下面的 schema：
{schema_json}
"""


def parse_json_response(schema: type[T], content: str) -> T:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    return schema.model_validate(data)


def trace_llm_start(
    label: str,
    schema: type,
    model: str,
    base_url: str | None,
    method: str,
    prompt: str,
    json_prompt: str,
) -> None:
    if clean_env("LLM_TRACE") != "1":
        return
    provider = base_url or "default"
    print(
        "[llm] start "
        f"label={label} schema={schema.__name__} model={model} method={method} "
        f"provider={provider} prompt_chars={len(prompt)} json_prompt_chars={len(json_prompt)}",
        flush=True,
    )


def trace_llm_end(
    label: str,
    started_at: float,
    ok: bool,
    path: str,
    error: Exception | None = None,
) -> None:
    if clean_env("LLM_TRACE") != "1":
        return
    elapsed = time.perf_counter() - started_at
    status = "ok" if ok else "failed"
    error_text = f" error={type(error).__name__}:{str(error)[:160]}" if error else ""
    print(
        f"[llm] end label={label} path={path} status={status} elapsed={elapsed:.2f}s{error_text}",
        flush=True,
    )
