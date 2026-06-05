const rowsEl = document.querySelector("#leaderboard-rows");
const feedEl = document.querySelector("#promotion-feed");
const bestScoreEl = document.querySelector("#best-score");
const lastUpdateEl = document.querySelector("#last-update");

fetch("./public/leaderboard.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    rowsEl.innerHTML = `<tr><td colspan="6">Leaderboard unavailable: ${escapeHtml(error.message)}</td></tr>`;
    feedEl.innerHTML = "<li>No promotions loaded.</li>";
  });

function render(data) {
  const rows = data.rows || [];
  if (rows.length === 0) {
    rowsEl.innerHTML = '<tr><td colspan="6">No verified candidates yet.</td></tr>';
    feedEl.innerHTML = "<li>No promotions yet.</li>";
    return;
  }

  const best = rows[0];
  bestScoreEl.textContent = best.score;
  lastUpdateEl.textContent = formatDate(best.discovered_at);

  rowsEl.innerHTML = rows
    .map(
      (row) => `<tr>
        <td>${row.rank}</td>
        <td class="score">${row.score}</td>
        <td class="mono">${escapeHtml(row.candidate_hash_short || row.candidate_hash.slice(0, 12))}</td>
        <td>${escapeHtml(row.model_id)}<br><span class="mono">${escapeHtml(row.provider_id)}</span></td>
        <td class="mono">${escapeHtml(row.receipt_signature_short || "pending")}</td>
        <td>${formatDate(row.discovered_at)}</td>
      </tr>`
    )
    .join("");

  feedEl.innerHTML = rows
    .slice(0, 5)
    .map(
      (row) =>
        `<li><strong>${row.score} instructions</strong> for <span class="mono">${escapeHtml(
          row.candidate_hash_short
        )}</span> via ${escapeHtml(row.provider_id)}.</li>`
    )
    .join("");
}

function formatDate(value) {
  if (!value) return "--";
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
