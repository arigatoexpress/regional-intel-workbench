/* eslint-disable no-undef */
"use strict";

const ADMIN_TOKEN_KEY = "regional_intel_admin_token";
const REGION_KEY = "regional_intel_admin_region";

const els = {
  region: document.getElementById("admin-region"),
  regionName: document.getElementById("admin-region-name"),
  regionBbox: document.getElementById("admin-region-bbox"),
  search: document.getElementById("admin-search"),
  refresh: document.getElementById("admin-refresh"),
  help: document.getElementById("admin-help"),
  tokenBtn: document.getElementById("admin-token-btn"),
  banner: document.getElementById("admin-banner"),
  updatedAt: document.getElementById("admin-updated-at"),
  summary: document.getElementById("admin-summary"),
  feed: document.getElementById("admin-feed"),
  feedCount: document.getElementById("admin-feed-count"),
  sourceHealth: document.getElementById("admin-source-health"),
  sourceCount: document.getElementById("admin-source-count"),
  trends: document.getElementById("admin-trends"),
  trendsMeta: document.getElementById("admin-trends-meta"),
  rules: document.getElementById("admin-rules"),
  rulesCount: document.getElementById("admin-rules-count"),
  modal: document.getElementById("admin-modal"),
  modalTitle: document.getElementById("admin-modal-title"),
  modalBody: document.getElementById("admin-modal-body"),
  modalClose: document.getElementById("admin-modal-close"),
  map: document.getElementById("admin-map"),
};

const state = {
  regions: [],
  currentRegion: localStorage.getItem(REGION_KEY) || "",
  map: null,
  mapLayer: null,
  overview: null,
  searchTimer: null,
};

function getToken() {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

function setToken(token) {
  if (token) {
    localStorage.setItem(ADMIN_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
  }
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  return value;
}

function fmtNum(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString();
}

function fmtTs(value) {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.valueOf())) return value;
    return d.toISOString().replace("T", " ").slice(0, 16) + "Z";
  } catch (_e) {
    return value;
  }
}

function showBanner(message, kind = "info") {
  els.banner.textContent = message;
  els.banner.classList.toggle("is-error", kind === "error");
  els.banner.hidden = !message;
}

function clearBanner() {
  els.banner.hidden = true;
  els.banner.textContent = "";
}

async function api(path) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) headers["X-Admin-Token"] = token;
  const res = await fetch(path, { headers });
  if (res.status === 401) {
    showBanner("Admin token required. Click 'Set token' to enter one.", "error");
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || path}`);
  }
  return res.json();
}

async function loadRegions() {
  const data = await api("/api/admin/regions");
  state.regions = (data && data.regions) || [];
  const sel = els.region;
  sel.innerHTML = "";
  if (!state.regions.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no regions configured)";
    sel.appendChild(opt);
    return;
  }
  state.regions.forEach((region) => {
    const opt = document.createElement("option");
    opt.value = region.id;
    opt.textContent = region.name || region.id;
    sel.appendChild(opt);
  });
  if (!state.currentRegion || !state.regions.some((r) => r.id === state.currentRegion)) {
    state.currentRegion = state.regions[0].id;
  }
  sel.value = state.currentRegion;
}

function ensureMap() {
  if (state.map) return state.map;
  state.map = L.map(els.map, {
    zoomControl: true,
    attributionControl: true,
  }).setView([30.27, -97.74], 9);
  L.tileLayer(
    "https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png",
    {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      subdomains: "abcd",
      maxZoom: 19,
    },
  ).addTo(state.map);
  return state.map;
}

function renderMapForRegion(regionId) {
  const region = state.regions.find((r) => r.id === regionId);
  if (!region) {
    els.regionName.textContent = "—";
    els.regionBbox.textContent = "bbox: —";
    return;
  }
  els.regionName.textContent = region.name || region.id;
  const bbox = region.bbox || [];
  els.regionBbox.textContent = bbox.length === 4
    ? `bbox: ${bbox.map((n) => n.toFixed(3)).join(", ")}`
    : "bbox: —";

  const map = ensureMap();
  if (state.mapLayer) {
    state.mapLayer.remove();
    state.mapLayer = null;
  }
  if (region.bounds) {
    state.mapLayer = L.rectangle(region.bounds, {
      color: "#6ef6c7",
      weight: 1.5,
      opacity: 0.9,
      fillOpacity: 0.10,
    }).addTo(map);
    map.fitBounds(region.bounds, { padding: [24, 24] });
  } else if (region.center) {
    map.setView(region.center, 10);
  }
  // Force Leaflet to recompute size after a possible layout change.
  setTimeout(() => map.invalidateSize(), 50);
}

function renderSummary(summary) {
  els.updatedAt.textContent = `updated ${fmtTs(summary && summary.updated_at)}`;
  const counts = (summary && summary.counts) || {};
  els.summary.querySelectorAll(".admin-stat").forEach((node) => {
    const key = node.dataset.key;
    const valueEl = node.querySelector(".admin-stat-value");
    const v = counts[key];
    valueEl.textContent = v == null ? "—" : fmtNum(v);
  });
}

function categoryGroups(itemsByCategory) {
  const order = ["news", "permit", "business", "organization", "contact"];
  const labels = {
    news: "News",
    permit: "Permits",
    business: "Businesses",
    organization: "Organizations",
    contact: "Contacts",
  };
  const out = [];
  const seen = new Set();
  order.forEach((key) => {
    if (itemsByCategory[key] && itemsByCategory[key].length) {
      out.push({ key, label: labels[key] || key, items: itemsByCategory[key] });
      seen.add(key);
    }
  });
  Object.keys(itemsByCategory).forEach((key) => {
    if (!seen.has(key) && itemsByCategory[key] && itemsByCategory[key].length) {
      out.push({ key, label: key, items: itemsByCategory[key] });
    }
  });
  return out;
}

function renderFeed(itemsByCategory) {
  const groups = categoryGroups(itemsByCategory || {});
  const total = groups.reduce((acc, g) => acc + g.items.length, 0);
  els.feedCount.textContent = total ? `${fmtNum(total)} items` : "—";
  els.feed.innerHTML = "";
  els.feed.classList.toggle("admin-empty", total === 0);
  if (!total) {
    els.feed.innerHTML = "<p class=\"admin-muted\">No recent items for this region.</p>";
    return;
  }
  const frag = document.createDocumentFragment();
  groups.forEach((group) => {
    const wrap = document.createElement("div");
    wrap.className = "admin-feed-group";
    const head = document.createElement("div");
    head.className = "admin-feed-group-header";
    head.innerHTML = `<span>${group.label}</span><span class="admin-mono">${fmtNum(group.items.length)}</span>`;
    wrap.appendChild(head);
    group.items.slice(0, 12).forEach((item) => {
      wrap.appendChild(feedItemNode(item));
    });
    frag.appendChild(wrap);
  });
  els.feed.appendChild(frag);
}

function feedItemNode(item) {
  const node = document.createElement("div");
  node.className = "admin-feed-item";
  const kind = (item.kind || "other").toLowerCase();
  const score = typeof item.score === "number" ? item.score.toFixed(2) : "—";
  const summary = item.summary || "";
  const sourceName = item.source_name || "—";
  const ts = fmtTs(item.timestamp);
  node.innerHTML = `
    <span class="admin-feed-kind kind-${kind}">${kind}</span>
    <div class="admin-feed-body">
      <div class="admin-feed-title">${escapeHtml(item.title || "—")}</div>
      ${summary ? `<div class="admin-feed-meta">${escapeHtml(summary)}</div>` : ""}
      <div class="admin-feed-meta admin-mono">${escapeHtml(sourceName)} · ${escapeHtml(ts)}</div>
    </div>
    <span class="admin-feed-score admin-mono">${score}</span>
  `;
  if (item.url) {
    node.style.cursor = "pointer";
    node.addEventListener("click", () => window.open(item.url, "_blank", "noopener"));
  }
  return node;
}

function escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderSourceHealth(payload, sourceHistory) {
  const sources = (payload && payload.source_health) || [];
  const historyByKey = {};
  ((sourceHistory && sourceHistory.sources) || []).forEach((row) => {
    historyByKey[row.source_key] = row;
  });
  els.sourceCount.textContent = sources.length ? `${fmtNum(sources.length)} sources` : "—";
  els.sourceHealth.innerHTML = "";
  els.sourceHealth.classList.toggle("admin-empty", sources.length === 0);
  if (!sources.length) {
    els.sourceHealth.innerHTML = "<p class=\"admin-muted\">No source health data.</p>";
    return;
  }
  sources.forEach((src) => {
    const row = document.createElement("div");
    row.className = "admin-source-row";
    const status = (src.status || "unknown").toLowerCase();
    const hist = historyByKey[src.source_key] || {};
    const lastFetch = src.last_fetched_at || src.last_fetch_at || hist.points?.slice(-1)[0]?.updated_at;
    row.innerHTML = `
      <div>
        <div class="admin-source-name">${escapeHtml(src.name || src.source_key || "—")}</div>
        <div class="admin-source-cat">${escapeHtml(src.category || "—")}</div>
      </div>
      <span class="admin-source-status status-${status}">${escapeHtml(status)}</span>
      <span class="admin-mono admin-muted" title="last item count">${fmtNum(src.item_count ?? hist.last_item_count ?? 0)}</span>
      <span class="admin-mono admin-muted" title="non-empty runs / last fetch">
        ${fmtNum(hist.non_empty_runs ?? 0)} runs · ${escapeHtml(fmtTs(lastFetch))}
      </span>
    `;
    els.sourceHealth.appendChild(row);
  });
}

function renderTrends(trends) {
  const series = (trends && trends.series) || [];
  els.trendsMeta.textContent = series.length ? `${fmtNum(series.length)} snapshots` : "—";
  els.trends.innerHTML = "";
  els.trends.classList.toggle("admin-empty", series.length === 0);
  if (!series.length) {
    els.trends.innerHTML = "<p class=\"admin-muted\">No trend history for this region.</p>";
    return;
  }
  const cats = ["news", "permits", "businesses", "contacts", "organizations"];
  const points = {};
  cats.forEach((c) => { points[c] = []; });
  series.forEach((row) => {
    const r = (row.regions || [])[0] || {};
    cats.forEach((c) => {
      points[c].push(Number(r[c] || 0));
    });
  });
  cats.forEach((c) => {
    const values = points[c];
    const total = values.reduce((a, b) => a + b, 0);
    if (!values.length || total === 0) return; // hide empty rows per "no null cells" rule
    const row = document.createElement("div");
    row.className = "admin-trend-row";
    row.innerHTML = `
      <span class="admin-trend-label">${c}</span>
      ${sparkline(values)}
      <span class="admin-trend-total admin-mono">${fmtNum(total)}</span>
    `;
    els.trends.appendChild(row);
  });
  if (!els.trends.children.length) {
    els.trends.classList.add("admin-empty");
    els.trends.innerHTML = "<p class=\"admin-muted\">All categories at zero across the window.</p>";
  }
}

function sparkline(values) {
  if (!values || !values.length) return "";
  const w = 240;
  const h = 32;
  const pad = 2;
  const max = Math.max(...values, 1);
  const stepX = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = pad + i * stepX;
    const y = h - pad - (v / max) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `
    <svg class="admin-trend-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline fill="none" stroke="#6ef6c7" stroke-width="1.5" points="${points}" />
    </svg>
  `;
}

function renderRules(monitor) {
  const rules = (monitor && monitor.rules) || [];
  els.rulesCount.textContent = rules.length ? `${fmtNum(rules.length)} rules` : "—";
  els.rules.innerHTML = "";
  els.rules.classList.toggle("admin-empty", rules.length === 0);
  if (!rules.length) {
    els.rules.innerHTML = "<p class=\"admin-muted\">No monitor rules configured for this region.</p>";
    return;
  }
  rules.forEach((rule) => {
    const r = rule.rule || rule;
    const matches = rule.matches || rule.match_count || (Array.isArray(rule.events) ? rule.events.length : 0);
    const row = document.createElement("div");
    row.className = "admin-rule-row";
    const meta = [
      r.region_id || "all regions",
      (r.entity_kinds || []).join(", "),
      r.keyword ? `keyword: ${r.keyword}` : null,
      r.min_score_delta ? `Δ score ≥ ${r.min_score_delta}` : null,
    ].filter(Boolean).join(" · ");
    row.innerHTML = `
      <div>
        <div class="admin-rule-title">${escapeHtml(r.title || r.rule_id || "—")}</div>
        ${meta ? `<div class="admin-rule-meta">${escapeHtml(meta)}</div>` : ""}
      </div>
      <span class="admin-rule-matches admin-mono">${fmtNum(matches)}</span>
    `;
    els.rules.appendChild(row);
  });
}

async function loadOverview() {
  const region = state.currentRegion;
  if (!region) return;
  showBanner("Loading...");
  try {
    const data = await api(
      `/api/admin/overview?region=${encodeURIComponent(region)}&days=14&limit=60`,
    );
    state.overview = data;
    renderSummary(data.summary);
    renderMapForRegion(region);
    renderFeed(data.items_by_category);
    renderSourceHealth(data.source_health, data.source_history);
    renderTrends(data.trends);
    renderRules(data.monitor);
    clearBanner();
  } catch (err) {
    if (err.message !== "unauthorized") {
      showBanner(`Failed to load: ${err.message}`, "error");
    }
  }
}

async function runSearch(query) {
  if (!query) {
    if (state.overview) renderFeed(state.overview.items_by_category);
    return;
  }
  try {
    const region = state.currentRegion;
    const data = await api(
      `/api/admin/search?q=${encodeURIComponent(query)}&region=${encodeURIComponent(region)}`,
    );
    const grouped = {};
    (data.results || data.items || []).forEach((item) => {
      const k = (item.kind || "other").toLowerCase();
      grouped[k] = grouped[k] || [];
      // Search results use `subtitle`/`detail` instead of `source_name`/`summary`;
      // normalize so the feed renderer doesn't show null cells.
      grouped[k].push({
        ...item,
        source_name: item.source_name || item.subtitle || "—",
        summary: item.summary || item.detail || "",
        timestamp: item.timestamp || item.published_at || "",
        url: item.url || item.source_url || "",
      });
    });
    renderFeed(grouped);
  } catch (err) {
    if (err.message !== "unauthorized") {
      showBanner(`Search failed: ${err.message}`, "error");
    }
  }
}

function showHelp() {
  els.modalTitle.textContent = "How to interpret this dashboard";
  els.modalBody.innerHTML = `
    <h3>Region selector</h3>
    <ul>
      <li>Pick a region to scope every panel below. Selection is persisted in localStorage.</li>
      <li>The map renders the configured <code>bbox</code> for the region. Empty bbox &rarr; "—".</li>
    </ul>
    <h3>Latest intel</h3>
    <ul>
      <li>Items are grouped by <code>kind</code> (news / permit / business / organization / contact).</li>
      <li>The score on the right is the source's <code>signal_score</code> rounded to 2dp; click an item to open its source URL in a new tab.</li>
    </ul>
    <h3>Source health</h3>
    <ul>
      <li><code>status=live</code> with item_count &gt; 0 means a successful non-empty fetch in the latest run.</li>
      <li><code>empty</code> is a fetch that returned zero rows; <code>error</code> means the fetch raised; <code>manual</code> is a hand-curated entry.</li>
      <li>The "runs" number is non-empty runs over the lookback window (last 14d).</li>
    </ul>
    <h3>Trends</h3>
    <ul>
      <li>Sparklines show item counts per category across the last 14 daily snapshots. Categories with zero across the entire window are hidden (no null cells).</li>
    </ul>
    <h3>Search</h3>
    <ul>
      <li>Full-text filter against the latest snapshot for the selected region. Results replace the feed; clear the box to restore the grouped view.</li>
    </ul>
    <h3>Monitor rules</h3>
    <ul>
      <li>Read-only list of configured rules. The number on the right is matches across the 14d lookback. Mutation endpoints are intentionally not exposed in the admin surface yet.</li>
    </ul>
    <h3>Auth</h3>
    <ul>
      <li>The admin token is sent as <code>X-Admin-Token</code>. Set it once via the "Set token" button; it's stored in localStorage and never sent to any third party.</li>
      <li>If <code>ADMIN_TOKEN</code> is unset on the server, the gate is open (dev mode).</li>
    </ul>
  `;
  els.modal.hidden = false;
}

function hideModal() {
  els.modal.hidden = true;
}

function init() {
  els.region.addEventListener("change", () => {
    state.currentRegion = els.region.value;
    localStorage.setItem(REGION_KEY, state.currentRegion);
    loadOverview();
  });

  els.search.addEventListener("input", (event) => {
    clearTimeout(state.searchTimer);
    const q = event.target.value.trim();
    state.searchTimer = setTimeout(() => runSearch(q), 220);
  });

  els.refresh.addEventListener("click", () => loadOverview());
  els.help.addEventListener("click", () => showHelp());
  els.modalClose.addEventListener("click", () => hideModal());
  els.modal.addEventListener("click", (event) => {
    if (event.target === els.modal) hideModal();
  });

  els.tokenBtn.addEventListener("click", () => {
    const current = getToken();
    const next = window.prompt(
      "Paste admin token (leave blank to clear):",
      current,
    );
    if (next === null) return;
    setToken(next.trim());
    showBanner(next.trim() ? "Token saved. Refreshing..." : "Token cleared.");
    loadOverview();
  });

  loadRegions()
    .then(() => loadOverview())
    .catch((err) => {
      if (err.message !== "unauthorized") {
        showBanner(`Init failed: ${err.message}`, "error");
      }
    });
}

document.addEventListener("DOMContentLoaded", init);
