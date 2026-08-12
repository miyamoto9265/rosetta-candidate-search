const config = window.ROSETTA_SEARCH_CONFIG || {};
const apiBaseUrl = (config.apiBaseUrl || "").replace(/\/$/, "");
const candidatesPath = config.candidatesPath || "/candidates-ebl";

const queryInput = document.getElementById("query");
const contextInput = document.getElementById("context");
const topKInput = document.getElementById("topK");
const levelInput = document.getElementById("level");
const searchButton = document.getElementById("searchButton");
const statusText = document.getElementById("status");
const resultsBody = document.getElementById("resultsBody");
const summary = document.getElementById("summary");
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
  if (meta.engine) parts.push(meta.engine);
  if (meta.rcs_ebl_version) parts.push(`EBL v${meta.rcs_ebl_version}`);
  if (meta.base_rcs_version) parts.push(`RCS base v${meta.base_rcs_version}`);
  if (data.level) parts.push(`level=${data.level}`);
  engineMeta.textContent = parts.join(" · ") || "RCS_EBL";
}

function renderResults(data) {
  const candidates = data.candidates || [];
  if (candidates.length === 0) {
    renderEmpty("候補が見つかりませんでした。");
    return;
  }

  summary.textContent = `${data.query} / ${candidates.length}件`;
  resultsBody.innerHTML = candidates
    .map((candidate, index) => {
      const labels =
        candidate.bna_label_id ||
        [candidate.bna_label_id_l, candidate.bna_label_id_r].filter(Boolean).join(" / ");
      const evidence = [
        candidate.methods,
        candidate.matched_lit_name ? `lit: ${candidate.matched_lit_name}` : "",
        candidate.matched_alias ? `alias: ${candidate.matched_alias}` : "",
        candidate.laterality && candidate.laterality !== "unknown"
          ? `hemi: ${candidate.laterality}`
          : "",
        candidate.k_papers != null ? `k=${candidate.k_papers}` : "",
      ]
        .filter(Boolean)
        .join(" / ");

      return `
        <tr>
          <td>${index + 1}</td>
          <td class="mono">${escapeHtml(candidate.bna_area_abbr || candidate.acronym)}</td>
          <td>${escapeHtml(candidate.bna_area_name || candidate.name)}</td>
          <td class="mono">${escapeHtml(candidate.bna_l2_abbr || candidate.dhba_name || "")}</td>
          <td class="mono">${escapeHtml(labels)}</td>
          <td class="mono">${Number(candidate.p_raw ?? 0).toFixed(4)}</td>
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
  const level = levelInput.value || "l3";

  if (!apiBaseUrl) {
    setStatus("config.js の apiBaseUrl を設定してください。", true);
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
    const response = await fetch(`${apiBaseUrl}${candidatesPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        context,
        top_k: topK,
        level,
        use_ai_preprocess: false,
        use_ai_postprocess: false,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "検索に失敗しました。");
    }
    renderMeta(data);
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
