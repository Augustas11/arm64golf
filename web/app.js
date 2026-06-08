const rowsEl = document.querySelector("#leaderboard-rows");
const bestScoreEl = document.querySelector("#best-score");
const bestCellEl = document.querySelector("#best-cell");
const bestHashEl = document.querySelector("#best-hash");
const lastUpdateEl = document.querySelector("#last-update");
const attemptCountEl = document.querySelector("#attempt-count");
const candidateResponseCountEl = document.querySelector("#candidate-response-count");
const pairsRowsEl = document.querySelector("#pairs-table-rows");
const improvementChartEl = document.querySelector("#improvement-chart");
const trajectoryChartEl = document.querySelector("#trajectory-chart");
const heroBestScoreEl = document.querySelector("#hero-best-score");
const heroCurrentComparisonScoreEl = document.querySelector("#hero-current-comparison-score");

fetch("./public/leaderboard.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    rowsEl.innerHTML = `<tr><td colspan="7">Score history unavailable: ${escapeHtml(error.message)}</td></tr>`;
    if (pairsRowsEl) {
      pairsRowsEl.innerHTML = `<tr><td colspan="5">Marketplace canaries unavailable: ${escapeHtml(error.message)}</td></tr>`;
    }
    renderChartError(improvementChartEl, "Marketplace data unavailable", error);
    renderChartError(trajectoryChartEl, "Score trajectory unavailable", error);
  });

function render(data) {
  const rows = data.rows || [];
  const pairs = data.pairs || [];
  renderHeroStat(rows);
  renderPairs(pairs);
  renderImprovementChart(pairs);
  renderTrajectoryChart(rows);

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

function renderHeroStat(rows) {
  const currentBest = rows.length > 0 ? numOrDash(rows[0].score) : "—";
  if (heroBestScoreEl) heroBestScoreEl.textContent = currentBest;
  if (heroCurrentComparisonScoreEl) heroCurrentComparisonScoreEl.textContent = currentBest;
}

function renderImprovementChart(pairs) {
  if (!improvementChartEl) return;

  if (pairs.length === 0) {
    improvementChartEl.innerHTML = '<p class="placeholder">No marketplace data yet.</p>';
    return;
  }

  const scoredPairs = pairs.map((pair) => {
    const score = Number(pair.best_verified_score);
    return {
      label: pairLabel(pair),
      score: Number.isFinite(score) ? score : null,
      evaluated: Number(pair.evaluated_responses),
      verified: Number(pair.verified_count),
    };
  });
  const finiteScores = scoredPairs
    .map((pair) => pair.score)
    .filter((score) => Number.isFinite(score));
  const maxScore = Math.max(...finiteScores, 18);
  const minScore = Math.min(...finiteScores, 12);
  const width = 980;
  const rowHeight = 46;
  const margin = { top: 34, right: 86, bottom: 42, left: 310 };
  const chartWidth = width - margin.left - margin.right;
  const height = margin.top + margin.bottom + scoredPairs.length * rowHeight;
  const axisY = height - margin.bottom + 8;

  const rows = scoredPairs
    .map((pair, index) => {
      const y = margin.top + index * rowHeight;
      const barY = y + 11;
      const ratio = pair.score === null ? 0 : pair.score / maxScore;
      const barWidth = pair.score === null ? 34 : Math.max(10, chartWidth * ratio);
      const color = pair.score === null ? "#e4e6ea" : scoreColor(pair.score, minScore, maxScore);
      const scoreText = pair.score === null ? "none" : String(pair.score);
      const label = trimLabel(pair.label, 43);
      const detail = pair.score === null
        ? `${numOrDash(pair.verified)} / ${numOrDash(pair.evaluated)}`
        : `${scoreText} instructions`;

      return `<g>
        <text x="${margin.left - 16}" y="${y + 25}" text-anchor="end" class="chart-label">${escapeHtml(label)}</text>
        <rect x="${margin.left}" y="${barY}" width="${barWidth.toFixed(1)}" height="20" rx="3" fill="${color}"></rect>
        <text x="${margin.left + barWidth + 10}" y="${y + 27}" class="chart-value">${escapeHtml(detail)}</text>
      </g>`;
    })
    .join("");

  improvementChartEl.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" aria-labelledby="improvement-svg-title improvement-svg-desc" role="img">
    <title id="improvement-svg-title">Best verified per provider, model, and template</title>
    <desc id="improvement-svg-desc">Horizontal bar chart where shorter bars mean lower verified instruction counts.</desc>
    <line x1="${margin.left}" y1="${axisY}" x2="${margin.left + chartWidth}" y2="${axisY}" class="axis-line"></line>
    <text x="${margin.left}" y="${height - 10}" class="axis-text">0</text>
    <text x="${margin.left + chartWidth}" y="${height - 10}" text-anchor="end" class="axis-text">${maxScore} instructions</text>
    ${rows}
  </svg>`;
}

function renderTrajectoryChart(rows) {
  if (!trajectoryChartEl) return;

  if (rows.length === 0) {
    trajectoryChartEl.innerHTML = '<p class="placeholder">No verified candidates yet.</p>';
    return;
  }

  const events = rows
    .map((row) => ({
      score: Number(row.score),
      date: new Date(row.discovered_at),
      label: `${numOrDash(row.score)} · ${shortModel(row.model_id)}`,
    }))
    .filter((row) => Number.isFinite(row.score) && !Number.isNaN(row.date.getTime()))
    .sort((a, b) => a.date.getTime() - b.date.getTime());

  if (events.length === 0) {
    trajectoryChartEl.innerHTML = '<p class="placeholder">No verified candidates yet.</p>';
    return;
  }

  const width = 980;
  const height = 340;
  const margin = { top: 34, right: 86, bottom: 56, left: 64 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const rowBestScore = Number(rows[0]?.score);
  const currentBestScore = Number.isFinite(rowBestScore) ? rowBestScore : Math.min(...events.map((event) => event.score));
  const scores = events.map((event) => event.score).concat([currentBestScore, 18]);
  const minScore = Math.min(...scores);
  const maxScore = Math.max(...scores);
  const startTime = events[0].date.getTime();
  const endTime = events[events.length - 1].date.getTime();
  const timeSpan = Math.max(1, endTime - startTime);
  const scoreSpan = Math.max(1, maxScore - minScore);
  const xFor = (date) => margin.left + ((date.getTime() - startTime) / timeSpan) * chartWidth;
  const yFor = (score) => margin.top + ((score - minScore) / scoreSpan) * chartHeight;

  const dotMarkup = events
    .map((event) => {
      const x = xFor(event.date);
      const y = yFor(event.score);
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" class="chart-dot">
        <title>${escapeHtml(event.label)} on ${escapeHtml(event.date.toISOString())}</title>
      </circle>`;
    })
    .join("");

  let best = events[0].score;
  const stepPoints = [`${xFor(events[0].date).toFixed(1)},${yFor(best).toFixed(1)}`];
  for (const event of events.slice(1)) {
    const x = xFor(event.date);
    const previousY = yFor(best);
    if (event.score < best) {
      best = event.score;
      stepPoints.push(`${x.toFixed(1)},${previousY.toFixed(1)}`);
      stepPoints.push(`${x.toFixed(1)},${yFor(best).toFixed(1)}`);
    } else {
      stepPoints.push(`${x.toFixed(1)},${previousY.toFixed(1)}`);
    }
  }

  const baselineY = yFor(18);
  const currentY = yFor(currentBestScore);
  const currentText = `${numOrDash(currentBestScore)} (current)`;
  const axisBottom = margin.top + chartHeight;
  trajectoryChartEl.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" aria-labelledby="trajectory-svg-title trajectory-svg-desc" role="img">
    <title id="trajectory-svg-title">Best-known instruction count over time</title>
    <desc id="trajectory-svg-desc">Step chart of the running minimum verified ARM64 sort3 instruction count.</desc>
    <line x1="${margin.left}" y1="${axisBottom}" x2="${margin.left + chartWidth}" y2="${axisBottom}" class="axis-line"></line>
    <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${axisBottom}" class="axis-line"></line>
    <line x1="${margin.left}" y1="${baselineY.toFixed(1)}" x2="${margin.left + chartWidth}" y2="${baselineY.toFixed(1)}" class="guide-line"></line>
    <text x="${margin.left + chartWidth - 8}" y="${baselineY - 8}" text-anchor="end" class="chart-annotation">18 (baseline)</text>
    <text x="${margin.left + chartWidth - 8}" y="${currentY - 8}" text-anchor="end" class="chart-annotation">${escapeHtml(currentText)}</text>
    <polyline points="${stepPoints.join(" ")}" class="step-line"></polyline>
    ${dotMarkup}
    <text x="${margin.left}" y="${height - 18}" class="axis-text">${escapeHtml(formatAxisDate(events[0].date))}</text>
    <text x="${margin.left + chartWidth}" y="${height - 18}" text-anchor="end" class="axis-text">${escapeHtml(formatAxisDate(events[events.length - 1].date))}</text>
    <text x="18" y="${margin.top + 8}" class="axis-text">${minScore}</text>
    <text x="18" y="${axisBottom}" class="axis-text">${maxScore}</text>
  </svg>`;
}

function renderPairs(pairs) {
  if (!pairsRowsEl) return;

  if (pairs.length === 0) {
    pairsRowsEl.innerHTML = '<tr><td colspan="5">No marketplace canaries yet.</td></tr>';
    return;
  }

  pairsRowsEl.innerHTML = pairs
    .map(
      (pair) => `<tr>
        <td><span class="mono">${escapeHtml(pair.provider_id || "—")}</span></td>
        <td><span class="mono">${escapeHtml(shortModel(pair.model_id))}</span></td>
        <td>
          <span class="mono">${escapeHtml(pair.template_name || "—")}</span>
          ${pair.template_id ? `<span class="secondary">${escapeHtml(pair.template_id)}</span>` : ""}
        </td>
        <td class="score">${formatBestScore(pair.best_verified_score)}</td>
        <td>${numOrDash(pair.verified_count)} / ${numOrDash(pair.evaluated_responses)}</td>
      </tr>`
    )
    .join("");
}

function renderChartError(element, label, error) {
  if (!element) return;
  element.innerHTML = `<p class="placeholder">${escapeHtml(label)}: ${escapeHtml(error.message)}</p>`;
}

function formatBestScore(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n} instructions` : "none";
}

function shortModel(modelId) {
  return String(modelId || "—").replace("mlx-community/", "");
}

function pairLabel(pair) {
  return `${pair.provider_id || "—"} · ${shortModel(pair.model_id)} · ${pair.template_name || "—"}`;
}

function trimLabel(value, maxLength) {
  const text = String(value || "—");
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function scoreColor(score, minScore, maxScore) {
  const span = Math.max(1, maxScore - minScore);
  const t = Math.min(1, Math.max(0, (score - minScore) / span));
  const dark = [17, 18, 20];
  const light = [184, 190, 199];
  const channel = (index) => Math.round(dark[index] + (light[index] - dark[index]) * t);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
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

function formatAxisDate(value) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  }).format(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
