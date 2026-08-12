const config = window.ROSETTA_SEARCH_CONFIG || {};
const apiBaseUrl = (config.apiBaseUrl || "").replace(/\/$/, "");

const queryInput = document.getElementById("query");
const contextInput = document.getElementById("context");
const topKInput = document.getElementById("topK");
const dhbaFilterInput = document.getElementById("dhbaFilter");
const useAiPreprocessInput = document.getElementById("useAiPreprocess");
const useAiPostprocessInput = document.getElementById("useAiPostprocess");
const searchButton = document.getElementById("searchButton");
const statusText = document.getElementById("status");
const resultsBody = document.getElementById("resultsBody");
const summary = document.getElementById("summary");
const aiCard = document.getElementById("aiCard");
const aiSummary = document.getElementById("aiSummary");
const aiPreprocess = document.getElementById("aiPreprocess");
const aiResultsBody = document.getElementById("aiResultsBody");
const engineMeta = document.getElementById("engineMeta");

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderEmpty(message) {
  resultsBody.innerHTML = `<tr><td colspan="8" class="empty">${escapeHtml(message)}</td></tr>`;
  summary.textContent = "";
}

function renderMeta(data) {
  const meta = data.meta || {};
  const parts = [];
  if (meta.rcs_version) parts.push(`Engine v${meta.rcs_version}`);
  if (meta.ai_model) parts.push(`AI: ${meta.ai_model}`);
  engineMeta.textContent = parts.join(" · ") || "Engine";
}

function relationBadge(rel) {
  const cls = rel === "'=" ? "rel-eq" : rel === "<" ? "rel-lt" : "rel-gt";
  return `<span class="rel-badge ${cls}">${escapeHtml(rel)}</span>`;
}

function renderAi(data) {
  const showPre = data.use_ai_preprocess && data.preprocess;
  const showPost = data.use_ai_postprocess && data.ai;
  const oldError = document.getElementById("aiError");
  if (oldError) oldError.remove();
  if (!showPre && !showPost) {
    aiCard.hidden = true;
    return;
  }
  aiCard.hidden = false;

  // preprocess
  if (showPre) {
    const pre = data.preprocess;
    if (pre.error) {
      aiPreprocess.hidden = false;
      aiPreprocess.innerHTML = `<span class="ai-error">AI 前処理に失敗しました（原文で検索）。</span>`;
    } else {
      const removed = (pre.removed || [])
        .map((r) => `<span class="mono">${escapeHtml(r.text)}</span> <small>(${escapeHtml(r.kind)})</small>`)
        .join(", ");
      aiPreprocess.hidden = false;
      aiPreprocess.innerHTML =
        `<strong>検索クエリ:</strong> ${escapeHtml(pre.roi_query)}` +
        (removed ? `<br><strong>除去:</strong> ${removed}` : "");
    }
  } else {
    aiPreprocess.hidden = true;
  }

  // postprocess
  if (showPost) {
    const ai = data.ai;
    if (ai.error) {
      aiSummary.textContent = "";
      aiResultsBody.innerHTML = "";
      aiPreprocess.insertAdjacentHTML(
        "afterend",
        `<p class="ai-error" id="aiError">AI 判定に失敗しました。RCS 候補をご覧ください。</p>`
      );
      return;
    }
    const results = ai.results || [];
    aiSummary.textContent = results.length ? `${results.length}件（先頭が最良）` : "該当なし";
    if (results.length === 0) {
      aiResultsBody.innerHTML = `<tr><td colspan="8" class="empty">AI は妥当な対応を見つけませんでした。</td></tr>`;
      return;
    }
    aiResultsBody.innerHTML = results
      .map(
        (r, i) => `
        <tr class="${i === 0 ? "ai-best" : ""}">
          <td>${i + 1}</td>
          <td class="mono">${escapeHtml(r.homba_id)}</td>
          <td>${escapeHtml(r.name)}</td>
          <td>${escapeHtml(r.acronym)}</td>
          <td>${escapeHtml(r.dhba_name)}</td>
          <td>${escapeHtml(r.dhba_acronym)}</td>
          <td>${relationBadge(r.relation)}</td>
          <td>${escapeHtml(r.reason)}</td>
        </tr>`
      )
      .join("");
  } else {
    aiSummary.textContent = "";
    aiResultsBody.innerHTML = "";
  }
}

function renderResults(data) {
  const candidates = data.candidates || [];
  if (candidates.length === 0) {
    renderEmpty("候補が見つかりませんでした。");
    return;
  }

  summary.textContent = `${escapeHtml(data.query)} / ${candidates.length}件`;
  resultsBody.innerHTML = candidates
    .map((candidate, index) => {
      const evidence = [
        candidate.methods,
        candidate.matched_alias ? `alias: ${candidate.matched_alias}` : "",
      ]
        .filter(Boolean)
        .join(" / ");

      return `
        <tr>
          <td>${index + 1}</td>
          <td class="mono">${escapeHtml(candidate.homba_id)}</td>
          <td>${escapeHtml(candidate.name)}</td>
          <td>${escapeHtml(candidate.acronym)}</td>
          <td>${escapeHtml(candidate.dhba_name)}</td>
          <td>${escapeHtml(candidate.dhba_acronym)}</td>
          <td class="mono">${Number(candidate.score ?? 0).toFixed(6)}</td>
          <td>${escapeHtml(evidence)}</td>
        </tr>
      `;
    })
    .join("");
}

async function search() {
  const query = queryInput.value.trim();
  const context = contextInput.value.trim();
  const topK = Number(topKInput.value || 10);
  const dhbaFilter = dhbaFilterInput.value || "both";
  const useAiPreprocess = useAiPreprocessInput.checked;
  const useAiPostprocess = useAiPostprocessInput.checked;

  if (!apiBaseUrl || apiBaseUrl.includes("REPLACE_WITH")) {
    setStatus("config.js の apiBaseUrl をAPI GatewayのURLに置き換えてください。", true);
    return;
  }

  if (!query) {
    setStatus("入力テキストを入れてください。", true);
    queryInput.focus();
    return;
  }

  searchButton.disabled = true;
  setStatus("検索しています...");

  try {
    const response = await fetch(`${apiBaseUrl}/candidates`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query,
        context,
        top_k: topK,
        dhba_filter: dhbaFilter,
        use_ai_preprocess: useAiPreprocess,
        use_ai_postprocess: useAiPostprocess,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "検索に失敗しました。");
    }

    renderMeta(data);
    renderAi(data);
    renderResults(data);
    setStatus("検索が完了しました。");
  } catch (error) {
    renderEmpty("検索結果を表示できませんでした。");
    setStatus(error.message || "検索中にエラーが発生しました。", true);
  } finally {
    searchButton.disabled = false;
  }
}

searchButton.addEventListener("click", search);
queryInput.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    search();
  }
});
