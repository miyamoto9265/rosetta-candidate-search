const config = window.ROSETTA_SEARCH_CONFIG || {};
const apiBaseUrl = (config.apiBaseUrl || "").replace(/\/$/, "");

const queryInput = document.getElementById("query");
const topKInput = document.getElementById("topK");
const dhbaFilterInput = document.getElementById("dhbaFilter");
const searchButton = document.getElementById("searchButton");
const statusText = document.getElementById("status");
const resultsBody = document.getElementById("resultsBody");
const summary = document.getElementById("summary");

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
        candidate.hierarchy_reason ? `hierarchy: ${candidate.hierarchy_reason}` : "",
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
  const topK = Number(topKInput.value || 5);
  const dhbaFilter = dhbaFilterInput.value || "both";

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
      body: JSON.stringify({ query, top_k: topK, dhba_filter: dhbaFilter }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "検索に失敗しました。");
    }

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
