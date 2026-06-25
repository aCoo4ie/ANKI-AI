const state = {
  documents: [],
  selectedDocumentId: null,
  cards: [],
  activeTab: "create",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }
  return response.json();
}

function showNotice(message, type = "info") {
  const notice = $("#notice");
  notice.textContent = message;
  notice.className = `notice${type === "error" ? " error" : ""}`;
}

function hideNotice() {
  $("#notice").classList.add("hidden");
}

function setBusy(button, busy, text) {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = text || "处理中";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function switchTab(tabName) {
  state.activeTab = tabName;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === tabName));
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${tabName}`));
  hideNotice();
  if (tabName === "sync") {
    loadSyncData();
  }
}

async function checkHealth() {
  const status = $("#apiStatus");
  try {
    await api("/health");
    status.textContent = "API 已连接";
    status.className = "status-pill ok";
  } catch (error) {
    status.textContent = "API 不可用";
    status.className = "status-pill bad";
  }
}

async function loadDocuments() {
  state.documents = await api("/documents");
  if (!state.selectedDocumentId && state.documents.length) {
    state.selectedDocumentId = state.documents[0].id;
  }
  renderDocuments();
  if (state.selectedDocumentId) {
    await loadCards();
  } else {
    renderCards();
  }
}

function renderDocuments() {
  $("#documentCount").textContent = state.documents.length;
  const list = $("#documentList");
  list.innerHTML = "";
  if (!state.documents.length) {
    list.innerHTML = '<div class="muted">还没有文档。</div>';
    return;
  }
  state.documents.forEach((doc) => {
    const button = window.document.createElement("button");
    button.type = "button";
    button.className = `doc-item${doc.id === state.selectedDocumentId ? " active" : ""}`;
    button.innerHTML = `
      <span class="doc-title"></span>
      <span class="doc-meta"></span>
    `;
    button.querySelector(".doc-title").textContent = doc.title;
    button.querySelector(".doc-meta").textContent = `${doc.source_type} · ${new Date(doc.created_at).toLocaleString()}`;
    button.addEventListener("click", async () => {
      state.selectedDocumentId = doc.id;
      renderDocuments();
      await loadCards();
      switchTab("review");
    });
    list.appendChild(button);
  });
}

async function loadCards() {
  if (!state.selectedDocumentId) {
    state.cards = [];
    renderCards();
    return;
  }
  state.cards = await api(`/documents/${state.selectedDocumentId}/cards`);
  renderCards();
}

function renderCards() {
  const selected = state.documents.find((document) => document.id === state.selectedDocumentId);
  $("#selectedDocumentLabel").textContent = selected ? selected.title : "请选择左侧文档。";

  const counts = {
    draft: 0,
    approved: 0,
    rejected: 0,
    synced: 0,
  };
  state.cards.forEach((card) => {
    counts[card.status] = (counts[card.status] || 0) + 1;
  });
  $("#metricDraft").textContent = counts.draft || 0;
  $("#metricApproved").textContent = counts.approved || 0;
  $("#metricRejected").textContent = counts.rejected || 0;
  $("#metricSynced").textContent = counts.synced || 0;

  const filter = $("#statusFilter").value;
  const cards = filter ? state.cards.filter((card) => card.status === filter) : state.cards;
  const list = $("#cardList");
  list.innerHTML = "";
  if (!cards.length) {
    list.innerHTML = '<div class="muted">当前没有符合条件的卡片。</div>';
    return;
  }

  cards.forEach((card) => list.appendChild(renderCard(card)));
}

function renderCard(card) {
  const item = window.document.createElement("article");
  item.className = "review-card";
  const score = Number(card.quality_score || 0);
  item.innerHTML = `
    <div class="card-main">
      <div>
        <span class="badge ${card.status}"></span>
        <div class="card-type"></div>
      </div>
      <div class="qa">
        <div class="question"></div>
        <div class="answer"></div>
      </div>
      <div class="score ${score < 90 ? "low" : ""}">
        <strong></strong>
        <span>质量</span>
      </div>
    </div>
    <details class="card-details">
      <summary>来源片段 / 编辑</summary>
      <p class="source"></p>
      <div class="edit-grid">
        <label>
          <span>问题</span>
          <textarea class="edit-question"></textarea>
        </label>
        <label>
          <span>答案</span>
          <textarea class="edit-answer"></textarea>
        </label>
      </div>
      <div class="card-actions">
        <button class="save-card" type="button">保存编辑</button>
        <button class="approve-card" type="button">批准</button>
        <button class="reject-card" type="button">拒绝</button>
        <button class="draft-card" type="button">退回草稿</button>
      </div>
    </details>
  `;
  item.querySelector(".badge").textContent = card.status;
  item.querySelector(".card-type").textContent = card.card_type;
  item.querySelector(".question").textContent = card.question;
  item.querySelector(".answer").textContent = card.answer;
  item.querySelector(".score strong").textContent = score.toFixed(0);
  item.querySelector(".source").textContent = card.source_quote;
  item.querySelector(".edit-question").value = card.question;
  item.querySelector(".edit-answer").value = card.answer;
  item.querySelector(".save-card").addEventListener("click", () => saveCard(item, card.id));
  item.querySelector(".approve-card").addEventListener("click", () => setCardStatus(card.id, "approve"));
  item.querySelector(".reject-card").addEventListener("click", () => setCardStatus(card.id, "reject"));
  item.querySelector(".draft-card").addEventListener("click", () => setCardStatus(card.id, "draft"));
  return item;
}

async function saveCard(item, cardId) {
  const button = item.querySelector(".save-card");
  setBusy(button, true, "保存中");
  try {
    await api(`/cards/${cardId}`, {
      method: "PATCH",
      body: JSON.stringify({
        question: item.querySelector(".edit-question").value,
        answer: item.querySelector(".edit-answer").value,
      }),
    });
    await loadCards();
    showNotice("卡片已保存。");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function setCardStatus(cardId, action) {
  try {
    await api(`/cards/${cardId}/${action}`, { method: "POST" });
    await loadCards();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function createAndGenerate(event) {
  event.preventDefault();
  const button = $("#generateButton");
  setBusy(button, true, "生成中");
  showNotice("正在生成卡片。模型调用可能需要一段时间，请保持页面打开。");
  try {
    const payload = {
      title: $("#titleInput").value.trim(),
      source_type: $("#sourceTypeInput").value,
      deck_name: $("#deckInput").value.trim() || "Default",
      tags: $("#tagsInput").value.split(",").map((tag) => tag.trim()).filter(Boolean),
      content: $("#contentInput").value,
    };
    const document = await api("/documents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedDocumentId = document.id;
    const result = await api(`/documents/${document.id}/generate`, { method: "POST" });
    await loadDocuments();
    showNotice(`已生成 ${result.knowledge_points.length} 个知识点、${result.cards.length} 张候选卡。`);
    switchTab("review");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function approveHighQualityDrafts() {
  if (!state.selectedDocumentId) return;
  const button = $("#approveHighQualityButton");
  setBusy(button, true, "批准中");
  try {
    const result = await api(`/cards/approve-drafts?document_id=${encodeURIComponent(state.selectedDocumentId)}&min_quality=90`, {
      method: "POST",
    });
    await loadCards();
    showNotice(`已批准 ${result.approved} 张 90+ 草稿卡。`);
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function loadSyncData() {
  try {
    const [approved, decks, models] = await Promise.all([
      api("/cards?status=approved"),
      api("/anki/decks").catch(() => []),
      api("/anki/models").catch(() => []),
    ]);
    $("#approvedSyncCount").textContent = approved.length;
    $("#syncHelp").textContent = approved.length ? "这些卡片会同步到 Anki。" : "请先在审核页批准卡片。";
    fillSelect($("#ankiDeckSelect"), decks, "Default");
    fillSelect($("#ankiModelSelect"), models, ["问答题", "Basic", "AI Knowledge Card"].find((name) => models.includes(name)) || models[0] || "问答题");
    $("#syncButton").disabled = approved.length === 0;
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function fillSelect(select, options, preferred) {
  select.innerHTML = "";
  const values = options.length ? options : [preferred];
  values.forEach((value) => {
    const option = window.document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = value === preferred;
    select.appendChild(option);
  });
}

async function syncToAnki() {
  const button = $("#syncButton");
  setBusy(button, true, "同步中");
  $("#syncResults").innerHTML = "";
  try {
    const result = await api("/anki/sync", {
      method: "POST",
      body: JSON.stringify({
        deck_name: $("#ankiDeckSelect").value || "Default",
        model_name: $("#ankiModelSelect").value || "问答题",
        allow_low_quality: $("#allowLowQualityInput").checked,
      }),
    });
    renderSyncResults(result);
    await loadDocuments();
    await loadSyncData();
    showNotice(`同步完成：成功 ${result.synced} 张，失败 ${result.failed} 张。`);
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderSyncResults(result) {
  const list = $("#syncResults");
  list.innerHTML = "";
  result.items.forEach((item) => {
    const row = window.document.createElement("div");
    row.className = "result-item";
    row.textContent = item.ok
      ? `${item.card_id} 同步成功，note_id=${item.note_id}`
      : `${item.card_id || "同步"} 失败：${item.error}`;
    list.appendChild(row);
  });
}

function bindEvents() {
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  $("#refreshButton").addEventListener("click", async () => {
    await loadDocuments();
    if (state.activeTab === "sync") await loadSyncData();
  });
  $("#documentForm").addEventListener("submit", createAndGenerate);
  $("#statusFilter").addEventListener("change", renderCards);
  $("#approveHighQualityButton").addEventListener("click", approveHighQualityDrafts);
  $("#syncButton").addEventListener("click", syncToAnki);
}

async function init() {
  bindEvents();
  await checkHealth();
  try {
    await loadDocuments();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

init();
