from __future__ import annotations

import os

import requests
import streamlit as st

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience
    load_dotenv = None


if load_dotenv:
    load_dotenv(override=True)


API_BASE = os.getenv("AI_ANKI_API_BASE", "http://localhost:8000").strip()
API_TIMEOUT = int(os.getenv("STREAMLIT_API_TIMEOUT", "300"))


st.set_page_config(page_title="AI Anki Workbench", layout="wide")
st.title("AI Anki Workbench")


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{API_BASE}{path}", timeout=API_TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.caption(f"API: {API_BASE}")
    if st.button("刷新文档"):
        st.rerun()


tab_create, tab_review, tab_sync = st.tabs(["新建任务", "审核卡片", "同步 Anki"])

with tab_create:
    with st.form("document_form"):
        title = st.text_input("标题")
        source_type = st.selectbox("文本类型", ["note", "article", "code", "interview", "manual"])
        deck_name = st.text_input("目标 Deck", value="Default")
        tags = st.text_input("标签，用逗号分隔", value="ai::generated")
        content = st.text_area("输入文本", height=320)
        submitted = st.form_submit_button("生成卡片")

    if submitted:
        payload = {
            "title": title,
            "source_type": source_type,
            "deck_name": deck_name,
            "tags": [tag.strip() for tag in tags.split(",") if tag.strip()],
            "content": content,
        }
        try:
            document = api("POST", "/documents", json=payload)
            result = api("POST", f"/documents/{document['id']}/generate")
            st.success(
                f"已生成 {len(result['knowledge_points'])} 个知识点、"
                f"{len(result['cards'])} 张候选卡。"
            )
            st.session_state["document_id"] = document["id"]
        except Exception as exc:
            st.error(str(exc))

with tab_review:
    documents = api("GET", "/documents")
    options = {f"{doc['title']} ({doc['id']})": doc["id"] for doc in documents}
    selected_label = st.selectbox("选择文档", list(options.keys())) if options else None
    selected_document_id = options[selected_label] if selected_label else None

    if selected_document_id:
        show_rejected = st.checkbox("显示未达 90 分的 rejected 卡片", value=False)
        cards = api("GET", f"/documents/{selected_document_id}/cards")
        draft_count = sum(1 for card in cards if card["status"] == "draft")
        approved_count = sum(1 for card in cards if card["status"] == "approved")
        summary_cols = st.columns([1, 1, 2])
        summary_cols[0].metric("草稿", draft_count)
        summary_cols[1].metric("已批准", approved_count)
        if summary_cols[2].button("一键批准当前文档 90+ 草稿", disabled=draft_count == 0):
            result = api(
                "POST",
                "/cards/approve-drafts",
                params={"document_id": selected_document_id, "min_quality": 90},
            )
            st.success(f"已批准 {result['approved']} 张卡片。")
            st.rerun()
        if not show_rejected:
            cards = [card for card in cards if card["status"] != "rejected"]
        if not cards:
            st.info("当前没有可审核卡片。未达 90 分的卡片已自动拦截，可勾选上方选项查看。")
        for card in cards:
            with st.container(border=True):
                cols = st.columns([1, 1, 4, 4, 1])
                cols[0].badge(card["status"])
                cols[1].write(card["card_type"])
                cols[2].write(card["question"])
                cols[3].write(card["answer"])
                cols[4].metric("质量", card.get("quality_score") or 0)

                with st.expander("来源片段 / 编辑"):
                    st.write(card["source_quote"])
                    question = st.text_input("问题", value=card["question"], key=f"q_{card['id']}")
                    answer = st.text_area("答案", value=card["answer"], key=f"a_{card['id']}")
                    if st.button("保存编辑", key=f"save_{card['id']}"):
                        api("PATCH", f"/cards/{card['id']}", json={"question": question, "answer": answer})
                        st.rerun()

                actions = st.columns([1, 1, 1])
                if actions[0].button("批准", key=f"approve_{card['id']}"):
                    api("POST", f"/cards/{card['id']}/approve")
                    st.rerun()
                if actions[1].button("拒绝", key=f"reject_{card['id']}"):
                    api("POST", f"/cards/{card['id']}/reject")
                    st.rerun()
                if actions[2].button("退回草稿", key=f"draft_{card['id']}"):
                    api("POST", f"/cards/{card['id']}/draft")
                    st.rerun()

with tab_sync:
    approved = api("GET", "/cards", params={"status": "approved"})
    drafts = api("GET", "/cards", params={"status": "draft"})
    st.write(f"待同步卡片：{len(approved)}")
    if not approved:
        st.warning(f"当前没有 approved 卡片。还有 {len(drafts)} 张 draft 卡，请先到“审核卡片”里批准，或使用一键批准 90+ 草稿。")
    try:
        deck_options = api("GET", "/anki/decks")
    except Exception:
        deck_options = []
    try:
        model_options = api("GET", "/anki/models")
    except Exception:
        model_options = []

    if deck_options:
        deck_index = deck_options.index("Default") if "Default" in deck_options else 0
        deck = st.selectbox("Anki Deck", deck_options, index=deck_index)
    else:
        deck = st.text_input("Anki Deck", value="Default")

    preferred_model = next(
        (name for name in ["问答题", "Basic", "AI Knowledge Card"] if name in model_options),
        model_options[0] if model_options else "问答题",
    )
    if model_options:
        model = st.selectbox(
            "Note Type",
            model_options,
            index=model_options.index(preferred_model),
        )
    else:
        model = st.text_input("Note Type", value=preferred_model)
    allow_low_quality = st.checkbox("允许同步质量分低于 90 的卡片", value=False)

    if st.button("同步已批准卡片", disabled=len(approved) == 0):
        try:
            result = api(
                "POST",
                "/anki/sync",
                json={
                    "deck_name": deck,
                    "model_name": model,
                    "allow_low_quality": allow_low_quality,
                },
            )
            st.success(f"成功 {result['synced']} 张，失败 {result['failed']} 张。")
            st.json(result["items"])
        except Exception as exc:
            st.error(str(exc))
