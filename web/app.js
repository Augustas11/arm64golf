const rowsEl = document.querySelector("#leaderboard-rows");
const bestScoreEl = document.querySelector("#best-score");
const bestCellEl = document.querySelector("#best-cell");
const bestHashEl = document.querySelector("#best-hash");
const lastUpdateEl = document.querySelector("#last-update");
const attemptCountEl = document.querySelector("#attempt-count");
const candidateResponseCountEl = document.querySelector("#candidate-response-count");

fetch("./public/leaderboard.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    rowsEl.innerHTML = `<tr><td colspan="7">Score history unavailable: ${escapeHtml(error.message)}</td></tr>`;
  });

function render(data) {
  const rows = data.rows || [];
  if (rows.length === 0) {
    rowsEl.innerHTML = '<tr><td colspan="7">No verified candidates yet.</td></tr>';
    return;
  }

  const best = rows[0];
  const candidateResponses = data.candidate_response_count ?? 0;
  const attempts = data.attempt_count ?? rows.length;

  bestScoreEl.textContent = numOrDash(best.score);
  candidateResponseCountEl.textContent = candidateResponses.toLocaleString();
  attemptCountEl.textContent = `${attempts.toLocaleString()} attempts evaluated`;
  lastUpdateEl.textContent = formatDate(data.last_update || best.discovered_at);

  if (bestCellEl && bestHashEl) {
    bestCellEl.innerHTML = `${numOrDash(best.score)} (<code class="mono">${escapeHtml(best.candidate_hash_short)}</code>)`;
  }

  rowsEl.innerHTML = rows
    .map(
      (row) => `<tr>
        <td>${numOrDash(row.rank)}</td>
        <td class="score">${numOrDash(row.score)}</td>
        <td class="mono">${escapeHtml(row.candidate_hash_short || row.candidate_hash.slice(0, 12))}</td>
        <td><span class="mono">${escapeHtml(row.model_id)}</span></td>
        <td><span class="mono">${escapeHtml(row.provider_id)}</span></td>
        <td class="mono">${escapeHtml(row.receipt_signature_short || "pending")}</td>
        <td>${formatDate(row.discovered_at)}</td>
      </tr>`
    )
    .join("");
}

function numOrDash(value) {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : "—";
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
