const protocolVoteInputs = {
  blackhole: document.querySelector("#vote-power-blackhole"),
  supernova: document.querySelector("#vote-power-supernova"),
  fullsail: document.querySelector("#vote-power-fullsail"),
};

const refreshButton = document.querySelector("#refresh-button");
const protocolGrid = document.querySelector("#protocol-grid");
const globalNotes = document.querySelector("#global-notes");
const snapshotAge = document.querySelector("#snapshot-age");

let dashboardSnapshot = null;
let strategySnapshot = null;
let snapshotRequestInFlight = false;
let strategyRequestInFlight = false;
let strategyRequestToken = 0;
let strategyRefreshTimeout = null;
let strategyErrorMessage = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatUsd(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value);
}

function formatCompactNumber(value, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits,
  }).format(value);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `${Number(value).toFixed(2)}%`;
}

function formatSignedPercent(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function relativeAge(isoString) {
  if (!isoString) {
    return "--";
  }
  const ageSeconds = Math.max(0, Math.floor((Date.now() - new Date(isoString).getTime()) / 1000));
  if (ageSeconds < 60) {
    return `${ageSeconds}s ago`;
  }
  if (ageSeconds < 3600) {
    return `${Math.floor(ageSeconds / 60)}m ago`;
  }
  return `${Math.floor(ageSeconds / 3600)}h ago`;
}

function countdownLabel(endsAtMs) {
  if (!endsAtMs) {
    return "Live";
  }
  const delta = Math.max(0, Math.floor((endsAtMs - Date.now()) / 1000));
  const days = Math.floor(delta / 86400);
  const hours = Math.floor((delta % 86400) / 3600);
  const minutes = Math.floor((delta % 3600) / 60);
  const seconds = delta % 60;
  return `${String(days).padStart(2, "0")}d:${String(hours).padStart(2, "0")}h:${String(minutes).padStart(2, "0")}m:${String(seconds).padStart(2, "0")}s`;
}

function getVotePower(protocolId) {
  const raw = Number.parseFloat(protocolVoteInputs[protocolId]?.value ?? "0");
  return Number.isFinite(raw) && raw > 0 ? raw : 0;
}

function modelRewards(pool) {
  return pool?.expected_rewards_usd ?? pool?.total_rewards_usd ?? null;
}

function projectedPayout(pool, votePower) {
  const rewards = modelRewards(pool);
  if (!votePower || !rewards || !pool?.current_votes) {
    return null;
  }
  return (rewards * votePower) / (pool.current_votes + votePower);
}

function renderGlobalNotes(notes) {
  globalNotes.innerHTML = "";
  notes.forEach((note) => {
    const item = document.createElement("li");
    item.textContent = note;
    globalNotes.appendChild(item);
  });
}

function currentStrategy(protocolId) {
  const strategy = strategySnapshot?.protocols?.find((item) => item.protocol_id === protocolId);
  if (!strategy) {
    return null;
  }
  const votePower = getVotePower(protocolId);
  if (Math.abs((strategy.vote_power ?? 0) - votePower) > 1e-6) {
    return null;
  }
  return strategy;
}

function isPreferredFullsailPool(pool) {
  return String(pool?.name ?? "").toUpperCase().includes("IKA");
}

function buildWatchlist(protocol) {
  const pools = [...(protocol.pools || [])]
    .filter((pool) => Number.isFinite(pool.analysis_score))
    .sort((left, right) => {
      if (protocol.id === "fullsail") {
        const preferredDelta = Number(isPreferredFullsailPool(right)) - Number(isPreferredFullsailPool(left));
        if (preferredDelta) {
          return preferredDelta;
        }
      }
      return (right.analysis_score ?? 0) - (left.analysis_score ?? 0);
    });

  if (protocol.id === "fullsail" && pools.some((pool) => isPreferredFullsailPool(pool))) {
    return pools.filter((pool) => isPreferredFullsailPool(pool)).slice(0, 1);
  }
  return pools.slice(0, 3);
}

function renderWatchlist(protocol) {
  const pools = buildWatchlist(protocol);
  if (!pools.length) {
    return `
      <section class="strategy-card">
        <div class="strategy-head">
          <div>
            <div class="top-pool-kicker">Weekly Strategy</div>
            <h4>Enter your ${escapeHtml(protocol.vote_power_symbol)} balance</h4>
            <p class="subtle">The strategy engine needs your vote size to optimize a split across pools.</p>
          </div>
        </div>
      </section>
    `;
  }

  if (protocol.id === "fullsail") {
    const items = pools
      .map(
        (pool) => `
          <div class="watch-item">
            <div>
              <div class="watch-name">${escapeHtml(pool.name)}</div>
              <div class="subtle mono">${escapeHtml(pool.fee_tier || "No fee tier")}${isPreferredFullsailPool(pool) ? " · Preferred" : ""}</div>
            </div>
            <div class="watch-metrics">
              <span>${formatUsd(pool.forecast_volume_usd ?? pool.predicted_volume_usd)}</span>
              <span>${formatUsd(pool.forecast_volume_low_usd)} to ${formatUsd(pool.forecast_volume_high_usd)}</span>
              <span>${(pool.model_confidence ?? pool.prediction_confidence) === null ? "--" : formatPercent((pool.model_confidence ?? pool.prediction_confidence) * 100)}</span>
            </div>
          </div>
        `
      )
      .join("");

    return `
      <section class="strategy-card">
        <div class="strategy-head">
          <div>
            <div class="top-pool-kicker">Prediction Watchlist</div>
            <h4>Full Sail Volume Forecast</h4>
            <p class="subtle">Full Sail rewards prediction accuracy. The watchlist prioritizes your IKA holding preference and shows the next-epoch volume target.</p>
          </div>
        </div>
        <div class="watch-header subtle mono">
          <span>Pool</span>
          <span>Forecast</span>
          <span>Range</span>
          <span>Confidence</span>
        </div>
        <div class="watch-list">${items}</div>
      </section>
    `;
  }

  const items = pools
    .map(
      (pool) => `
        <div class="watch-item">
          <div>
            <div class="watch-name">${escapeHtml(pool.name)}</div>
            <div class="subtle mono">${escapeHtml(pool.fee_tier || "No fee tier")}</div>
          </div>
          <div class="watch-metrics">
            <span>${formatPercent(pool.expected_apr ?? pool.apr)}</span>
            <span>${formatUsd(modelRewards(pool))}</span>
            <span>${pool.stability_score === null ? "--" : formatPercent(pool.stability_score * 100)}</span>
          </div>
        </div>
      `
    )
    .join("");

  return `
    <section class="strategy-card">
      <div class="strategy-head">
        <div>
          <div class="top-pool-kicker">Weekly Strategy</div>
          <h4>Watchlist Before Sizing</h4>
          <p class="subtle">Highest risk-adjusted pools from the live snapshot plus local history. Enter your vote power above to size an optimal split.</p>
        </div>
      </div>
      <div class="watch-header subtle mono">
        <span>Pool</span>
        <span>Model APR</span>
        <span>Model Rewards</span>
        <span>Stability</span>
      </div>
      <div class="watch-list">${items}</div>
    </section>
  `;
}

function renderAllocationStrategy(protocol, strategy) {
  const allocations = (strategy.allocations || [])
    .map(
      (allocation) => `
        <li class="allocation-item">
          <div class="allocation-head">
            <div>
              <div class="allocation-name">${allocation.rank}. ${escapeHtml(allocation.name)}</div>
              <div class="subtle mono">${escapeHtml(allocation.fee_tier || protocol.vote_power_symbol)}</div>
            </div>
            <div class="allocation-size">
              <div class="allocation-pct">${formatPercent(allocation.allocation_pct)}</div>
              <div class="subtle">${formatCompactNumber(allocation.allocation_votes)} ${escapeHtml(protocol.vote_power_symbol)}</div>
            </div>
          </div>
          <div class="allocation-bar"><span style="width: ${Math.min(allocation.allocation_pct, 100)}%"></span></div>
          <div class="allocation-grid">
            <div class="mini-stat">
              <div class="label">Expected Payout</div>
              <div class="value">${formatUsd(allocation.expected_weekly_payout_usd)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Model APR</div>
              <div class="value">${formatPercent(allocation.expected_apr)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Capture</div>
              <div class="value">${formatPercent(allocation.expected_capture_pct)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">History</div>
              <div class="value">${allocation.history_points || "--"}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Stability</div>
              <div class="value">${allocation.stability_score === null ? "--" : formatPercent(allocation.stability_score * 100)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Confidence</div>
              <div class="value">${allocation.model_confidence === null ? "--" : formatPercent(allocation.model_confidence * 100)}</div>
            </div>
          </div>
        </li>
      `
    )
    .join("");

  const notes = (strategy.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");

  return `
    <section class="strategy-card">
      <div class="strategy-head">
        <div>
          <div class="top-pool-kicker">Weekly Strategy</div>
          <h4>Optimal Split For ${formatCompactNumber(strategy.vote_power)} ${escapeHtml(protocol.vote_power_symbol)}</h4>
          <p class="subtle">This uses the protocol's current vote depth plus the app's local historical model.</p>
        </div>
        <div class="strategy-total">
          <div class="status-label">Expected Weekly Payout</div>
          <div class="status-value">${formatUsd(strategy.expected_weekly_payout_usd)}</div>
        </div>
      </div>
      <div class="strategy-summary">
        <div class="summary-stat">
          <div class="label">Best Single Pool</div>
          <div class="value">${escapeHtml(strategy.best_single_pool_name || "--")}</div>
        </div>
        <div class="summary-stat">
          <div class="label">Single-Pool Payout</div>
          <div class="value">${formatUsd(strategy.best_single_pool_payout_usd)}</div>
        </div>
        <div class="summary-stat">
          <div class="label">Lift Vs Single</div>
          <div class="value">${formatSignedPercent(strategy.improvement_vs_best_single_pct)}</div>
        </div>
        <div class="summary-stat">
          <div class="label">History Samples</div>
          <div class="value">${strategy.history_samples || "--"}</div>
        </div>
      </div>
      <ol class="allocation-list">${allocations}</ol>
      <ul class="strategy-notes">${notes}</ul>
    </section>
  `;
}

function renderPredictionStrategy(protocol, strategy) {
  const allocation = strategy.allocations?.[0];
  const notes = (strategy.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");
  const forecastRange =
    allocation && allocation.prediction_range_low_usd !== null && allocation.prediction_range_high_usd !== null
      ? `${formatUsd(allocation.prediction_range_low_usd)} to ${formatUsd(allocation.prediction_range_high_usd)}`
      : "--";

  return `
    <section class="strategy-card">
      <div class="strategy-head">
        <div>
          <div class="top-pool-kicker">Prediction Plan</div>
          <h4>Full Sail Plan For ${formatCompactNumber(strategy.vote_power)} ${escapeHtml(protocol.vote_power_symbol)}</h4>
          <p class="subtle">${escapeHtml(strategy.preference_label || "Prediction-based pool selection")}</p>
        </div>
        <div class="strategy-total">
          <div class="status-label">Expected Weekly Payout</div>
          <div class="status-value">${formatUsd(strategy.expected_weekly_payout_usd)}</div>
        </div>
      </div>
      <div class="strategy-summary">
        <div class="summary-stat">
          <div class="label">Chosen Pool</div>
          <div class="value">${escapeHtml(allocation?.name || "--")}</div>
        </div>
        <div class="summary-stat">
          <div class="label">Suggested Volume</div>
          <div class="value">${formatUsd(allocation?.suggested_prediction_usd)}</div>
        </div>
        <div class="summary-stat">
          <div class="label">Forecast Band</div>
          <div class="value">${forecastRange}</div>
        </div>
        <div class="summary-stat">
          <div class="label">Unrestricted Leader</div>
          <div class="value">${escapeHtml(strategy.best_single_pool_name || "--")}</div>
        </div>
      </div>
      <ol class="allocation-list">
        <li class="allocation-item">
          <div class="allocation-head">
            <div>
              <div class="allocation-name">1. ${escapeHtml(allocation?.name || "--")}</div>
              <div class="subtle mono">${escapeHtml(allocation?.fee_tier || protocol.vote_power_symbol)}</div>
            </div>
            <div class="allocation-size">
              <div class="allocation-pct">${formatPercent(allocation?.allocation_pct)}</div>
              <div class="subtle">${formatCompactNumber(allocation?.allocation_votes)} ${escapeHtml(protocol.vote_power_symbol)}</div>
            </div>
          </div>
          <div class="allocation-bar"><span style="width: ${Math.min(allocation?.allocation_pct || 0, 100)}%"></span></div>
          <div class="allocation-grid">
            <div class="mini-stat">
              <div class="label">Prediction Target</div>
              <div class="value">${formatUsd(allocation?.suggested_prediction_usd)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Forecast Band</div>
              <div class="value">${forecastRange}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Expected Payout</div>
              <div class="value">${formatUsd(allocation?.expected_weekly_payout_usd)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Model APR</div>
              <div class="value">${formatPercent(allocation?.expected_apr)}</div>
            </div>
            <div class="mini-stat">
              <div class="label">History</div>
              <div class="value">${allocation?.history_points || "--"}</div>
            </div>
            <div class="mini-stat">
              <div class="label">Confidence</div>
              <div class="value">${allocation?.model_confidence === null || allocation?.model_confidence === undefined ? "--" : formatPercent(allocation.model_confidence * 100)}</div>
            </div>
          </div>
        </li>
      </ol>
      <ul class="strategy-notes">${notes}</ul>
    </section>
  `;
}

function renderStrategy(protocol) {
  const votePower = getVotePower(protocol.id);
  if (!votePower) {
    return renderWatchlist(protocol);
  }

  const strategy = currentStrategy(protocol.id);
  if (!strategy) {
    if (strategyErrorMessage && !strategyRequestInFlight) {
      return `
        <section class="strategy-card">
          <div class="error-card">
            <strong>Strategy refresh failed.</strong>
            <p>${escapeHtml(strategyErrorMessage)}</p>
          </div>
        </section>
      `;
    }
    return `
      <section class="strategy-card">
        <div class="loading">Updating weekly strategy for ${formatCompactNumber(votePower)} ${escapeHtml(protocol.vote_power_symbol)}…</div>
      </section>
    `;
  }

  if (strategy.strategy_mode === "prediction") {
    return renderPredictionStrategy(protocol, strategy);
  }
  return renderAllocationStrategy(protocol, strategy);
}

function renderProtocol(protocol) {
  const card = document.createElement("article");
  card.className = "protocol-card";

  if (protocol.error) {
    card.innerHTML = `
      <div class="protocol-header">
        <div class="protocol-title-wrap">
          <h3>${escapeHtml(protocol.name)}</h3>
          <div class="protocol-meta">
            <span class="chip">${escapeHtml(protocol.chain)}</span>
            <span class="chip">${escapeHtml(protocol.vote_power_symbol)}</span>
          </div>
        </div>
      </div>
      <div class="error-card">
        <strong>Refresh failed.</strong>
        <p>${escapeHtml(protocol.error)}</p>
      </div>
    `;
    return card;
  }

  const topPool = protocol.pools[0];
  const votePower = getVotePower(protocol.id);
  const topProjected = projectedPayout(topPool, votePower);
  const topConfidence = topPool?.model_confidence ?? topPool?.prediction_confidence ?? null;

  const summaryStats = (protocol.key_stats || [])
    .map(
      (stat) => `
        <div class="summary-stat">
          <div class="label">${escapeHtml(stat.label)}</div>
          <div class="value">${escapeHtml(stat.value)}</div>
        </div>
      `
    )
    .join("");

  const notes = (protocol.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");

  const topPoolMarkup = topPool
    ? `
      <section class="top-pool-card">
        <div class="top-pool-head">
          <div>
            <div class="top-pool-kicker">Current Leader</div>
            <h4>${escapeHtml(topPool.name)}</h4>
            <div class="protocol-meta">
              ${topPool.fee_tier ? `<span class="chip">${escapeHtml(topPool.fee_tier)}</span>` : ""}
              <span class="chip">${escapeHtml(protocol.vote_power_symbol)}</span>
            </div>
          </div>
          <div class="apr-pill">${formatPercent(topPool.apr)}</div>
        </div>
        <div class="top-pool-grid">
          <div class="mini-stat">
            <div class="label">Live Rewards</div>
            <div class="value">${formatUsd(topPool.total_rewards_usd)}</div>
          </div>
          <div class="mini-stat">
            <div class="label">Model Rewards</div>
            <div class="value">${formatUsd(modelRewards(topPool))}</div>
          </div>
          <div class="mini-stat">
            <div class="label">Current Votes</div>
            <div class="value">${formatCompactNumber(topPool.current_votes)}</div>
          </div>
          <div class="mini-stat">
            <div class="label">All-In Payout</div>
            <div class="value">${topProjected === null ? "--" : formatUsd(topProjected)}</div>
          </div>
          <div class="mini-stat">
            <div class="label">Model APR</div>
            <div class="value">${formatPercent(topPool.expected_apr ?? topPool.apr)}</div>
          </div>
          <div class="mini-stat">
            <div class="label">Confidence</div>
            <div class="value">${topConfidence === null ? "--" : formatPercent(topConfidence * 100)}</div>
          </div>
        </div>
      </section>
    `
    : `<div class="empty-state">No pool data was returned for ${escapeHtml(protocol.name)}.</div>`;

  const rows = (protocol.pools || [])
    .map((pool) => {
      const payout = projectedPayout(pool, votePower);
      const confidence = pool.model_confidence ?? pool.prediction_confidence ?? null;
      return `
        <tr>
          <td>
            <div class="pool-name">${pool.rank}. ${escapeHtml(pool.name)}</div>
            <div class="subtle mono">${escapeHtml(pool.fee_tier || "No fee tier")}</div>
            <div class="subtle">Fees ${formatUsd(pool.fees_usd)} · Incentives ${formatUsd(pool.incentives_usd)}</div>
          </td>
          <td>${formatPercent(pool.apr)}</td>
          <td>${formatPercent(pool.expected_apr ?? pool.apr)}</td>
          <td>${formatUsd(pool.total_rewards_usd)}</td>
          <td>${formatUsd(modelRewards(pool))}</td>
          <td>${formatCompactNumber(pool.current_votes)}</td>
          <td>${formatPercent(pool.vote_share_pct)}</td>
          <td>${formatUsd(payout)}</td>
          <td>${formatUsd(pool.tvl_usd)}</td>
          <td>${formatUsd(pool.predicted_volume_usd ?? pool.weekly_volume_usd)}</td>
          <td>${pool.history_points || "--"}</td>
          <td>${pool.stability_score === null ? "--" : formatPercent(pool.stability_score * 100)}</td>
          <td>${confidence === null ? "--" : formatPercent(confidence * 100)}</td>
        </tr>
      `;
    })
    .join("");

  card.innerHTML = `
    <div class="protocol-header">
      <div class="protocol-title-wrap">
        <h3>${escapeHtml(protocol.name)}</h3>
        <div class="protocol-meta">
          <span class="chip">${escapeHtml(protocol.chain)}</span>
          <span class="chip">${escapeHtml(protocol.vote_power_symbol)}</span>
          <span class="chip">${escapeHtml(protocol.source)}</span>
          ${protocol.epoch_label ? `<span class="chip">${escapeHtml(protocol.epoch_label)}</span>` : ""}
        </div>
      </div>
      <div class="chip countdown" data-ends-at="${protocol.ends_at_ms || ""}">
        ${protocol.ends_at_ms ? countdownLabel(protocol.ends_at_ms) : escapeHtml(protocol.countdown || "Live")}
      </div>
    </div>
    <div class="summary-strip">${summaryStats}</div>
    <div class="analysis-line">
      <span class="subtle">${escapeHtml(protocol.ranking_basis)}</span>
      ${protocol.analysis_basis ? `<span class="subtle">${escapeHtml(protocol.analysis_basis)}</span>` : ""}
    </div>
    ${topPoolMarkup}
    ${renderStrategy(protocol)}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Pool</th>
            <th>Live APR</th>
            <th>Model APR</th>
            <th>Live Rewards</th>
            <th>Model Rewards</th>
            <th>Votes</th>
            <th>Vote Share</th>
            <th>All-In Payout</th>
            <th>TVL</th>
            <th>Volume</th>
            <th>Hist</th>
            <th>Stability</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <ul class="protocol-notes">${notes}</ul>
  `;

  return card;
}

function renderSnapshot(snapshot) {
  dashboardSnapshot = snapshot;
  snapshotAge.textContent = relativeAge(snapshot.updated_at);
  renderGlobalNotes(snapshot.global_notes || []);
  protocolGrid.innerHTML = "";
  (snapshot.protocols || []).forEach((protocol) => {
    protocolGrid.appendChild(renderProtocol(protocol));
  });
}

async function loadSnapshot(force = false) {
  if (snapshotRequestInFlight) {
    return null;
  }
  snapshotRequestInFlight = true;
  refreshButton.disabled = true;
  refreshButton.textContent = force ? "Refreshing…" : "Loading…";
  if (!dashboardSnapshot) {
    protocolGrid.innerHTML = `<div class="loading">Pulling live vote and history data…</div>`;
  }

  try {
    const response = await fetch(`/api/snapshot${force ? "?force=true" : ""}`);
    if (!response.ok) {
      throw new Error(`Snapshot request failed with status ${response.status}`);
    }
    const snapshot = await response.json();
    renderSnapshot(snapshot);
    return snapshot;
  } catch (error) {
    protocolGrid.innerHTML = `
      <div class="error-card">
        <strong>Snapshot load failed.</strong>
        <p>${escapeHtml(error instanceof Error ? error.message : "Unknown error")}</p>
      </div>
    `;
    return null;
  } finally {
    snapshotRequestInFlight = false;
    refreshButton.disabled = false;
    refreshButton.textContent = "Refresh Snapshot";
  }
}

async function loadStrategy(force = false) {
  const requestToken = ++strategyRequestToken;
  strategyRequestInFlight = true;

  try {
    const params = new URLSearchParams({
      blackhole: String(getVotePower("blackhole")),
      supernova: String(getVotePower("supernova")),
      fullsail: String(getVotePower("fullsail")),
    });
    if (force) {
      params.set("force", "true");
    }

    const response = await fetch(`/api/strategy?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Strategy request failed with status ${response.status}`);
    }

    const strategy = await response.json();
    if (requestToken !== strategyRequestToken) {
      return null;
    }
    strategySnapshot = strategy;
    strategyErrorMessage = null;
    rerender();
    return strategy;
  } catch (error) {
    if (requestToken === strategyRequestToken) {
      strategyErrorMessage = error instanceof Error ? error.message : "Unknown error";
      rerender();
    }
    return null;
  } finally {
    if (requestToken === strategyRequestToken) {
      strategyRequestInFlight = false;
    }
  }
}

async function loadDashboard(force = false) {
  const snapshot = await loadSnapshot(force);
  if (!snapshot) {
    return;
  }
  await loadStrategy(force);
}

function rerender() {
  if (dashboardSnapshot) {
    renderSnapshot(dashboardSnapshot);
  }
}

function scheduleStrategyRefresh() {
  if (strategyRefreshTimeout) {
    window.clearTimeout(strategyRefreshTimeout);
  }
  strategyRefreshTimeout = window.setTimeout(() => {
    loadStrategy(false);
  }, 250);
}

refreshButton.addEventListener("click", () => {
  loadDashboard(true);
});

Object.entries(protocolVoteInputs).forEach(([, input]) => {
  input.addEventListener("input", () => {
    rerender();
    scheduleStrategyRefresh();
  });
});

window.setInterval(() => {
  if (dashboardSnapshot) {
    snapshotAge.textContent = relativeAge(dashboardSnapshot.updated_at);
    document.querySelectorAll("[data-ends-at]").forEach((element) => {
      const endsAt = Number(element.getAttribute("data-ends-at"));
      if (endsAt) {
        element.textContent = countdownLabel(endsAt);
      }
    });
  }
}, 1000);

window.setInterval(() => {
  loadDashboard(false);
}, 180000);

loadDashboard(false);
