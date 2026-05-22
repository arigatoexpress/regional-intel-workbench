const regionFilter = document.querySelector("#region-filter");
const refreshButton = document.querySelector("#intel-refresh-button");
const snapshotAge = document.querySelector("#intel-snapshot-age");
const ethicsGrid = document.querySelector("#ethics-grid");
const sourceGrid = document.querySelector("#source-grid");
const clientViewGrid = document.querySelector("#client-view-grid");
const intelMapCanvas = document.querySelector("#intel-map-canvas");
const intelMapLegend = document.querySelector("#intel-map-legend");
const intelMapTopPoints = document.querySelector("#intel-map-top-points");
const commandSurfaceStatus = document.querySelector("#command-surface-status");
const commandLayerList = document.querySelector("#command-layer-list");
const commandMapCanvas = document.querySelector("#command-map-canvas");
const commandInspector = document.querySelector("#command-inspector");
const commandGuardrails = document.querySelector("#command-guardrails");
const commandFeed = document.querySelector("#command-feed");
const regionSummaries = document.querySelector("#region-summaries");
const briefGrid = document.querySelector("#brief-grid");
const watchlistGrid = document.querySelector("#watchlist-grid");
const opportunityGrid = document.querySelector("#opportunity-grid");
const savedWatchlistGrid = document.querySelector("#saved-watchlist-grid");
const collectionGrid = document.querySelector("#collection-grid");
const collectionActiveSelect = document.querySelector("#collection-active-select");
const collectionActiveSummary = document.querySelector("#collection-active-summary");
const collectionTitleInput = document.querySelector("#collection-title-input");
const collectionRegionInput = document.querySelector("#collection-region-input");
const collectionNoteInput = document.querySelector("#collection-note-input");
const collectionCreateButton = document.querySelector("#collection-create-button");
const bundleGrid = document.querySelector("#bundle-grid");
const bundleActiveSelect = document.querySelector("#bundle-active-select");
const bundleActiveSummary = document.querySelector("#bundle-active-summary");
const bundleTitleInput = document.querySelector("#bundle-title-input");
const bundleRegionInput = document.querySelector("#bundle-region-input");
const bundleNoteInput = document.querySelector("#bundle-note-input");
const bundleCreateButton = document.querySelector("#bundle-create-button");
const monitorGrid = document.querySelector("#monitor-grid");
const monitorTitleInput = document.querySelector("#monitor-title-input");
const monitorRegionInput = document.querySelector("#monitor-region-input");
const monitorKindInput = document.querySelector("#monitor-kind-input");
const monitorChangeTypeInput = document.querySelector("#monitor-change-type-input");
const monitorKeywordInput = document.querySelector("#monitor-keyword-input");
const monitorScoreDeltaInput = document.querySelector("#monitor-score-delta-input");
const monitorNoteInput = document.querySelector("#monitor-note-input");
const monitorCreateButton = document.querySelector("#monitor-create-button");
const trendGrid = document.querySelector("#trend-grid");
const sourceHistoryGrid = document.querySelector("#source-history-grid");
const sourceIncidentGrid = document.querySelector("#source-incident-grid");
const regionChangeGrid = document.querySelector("#region-change-grid");
const entityChangeGrid = document.querySelector("#entity-change-grid");
const alertGrid = document.querySelector("#alert-grid");
const regionBriefingGrid = document.querySelector("#region-briefing-grid");
const searchInput = document.querySelector("#intel-search-input");
const searchButton = document.querySelector("#intel-search-button");
const searchResults = document.querySelector("#search-results");
const relationshipGraph = document.querySelector("#relationship-graph");
const entityDetail = document.querySelector("#entity-detail");

let intelSnapshot = null;
let requestInFlight = false;
let currentGraphFocusId = null;
let collectionsPayload = { collections: [] };
let activeCollectionId = window.localStorage?.getItem("intelActiveCollectionId") || "";
let bundlesPayload = { bundles: [] };
let activeBundleId = window.localStorage?.getItem("intelActiveBundleId") || "";
let monitorRulesPayload = { rules: [] };
const initialParams = new URLSearchParams(window.location.search);
const initialRegionParam = initialParams.get("region") || "";
const initialSearchParam = initialParams.get("search") || "";
const initialDetailKindParam = resolveDetailKind(initialParams.get("detail_kind") || "");
const initialDetailIdParam = initialParams.get("detail_id") || "";
let initialNavigationHandled = false;
let commandSurfacePayload = null;
let selectedCommandEntityId = "";
let activeCommandLayers = new Set(parseCommandLayers(initialParams.get("layers")));

if (regionFilter && initialRegionParam) {
  regionFilter.value = initialRegionParam;
}
if (searchInput && initialSearchParam) {
  searchInput.value = initialSearchParam;
}

function resolveDetailKind(kind) {
  const normalized = String(kind || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  const mapping = {
    organization: "organization",
    news: "news",
    news_signal: "news",
    permit: "permit",
    permit_signal: "permit",
    business: "business",
    contact: "contact",
  };
  return mapping[normalized] || "";
}

function detailButton(kind, itemId, label = "View detail") {
  const resolvedKind = resolveDetailKind(kind);
  if (!resolvedKind || !itemId) {
    return "";
  }
  return `<button class="ghost-button intel-detail-button" type="button" data-detail-kind="${escapeHtml(resolvedKind)}" data-detail-id="${escapeHtml(itemId)}">${escapeHtml(label)}</button>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

function parseCommandLayers(value) {
  const fallback = [
    "businesses",
    "organizations",
    "regional_news",
    "development_permits",
    "wildfire_watch",
    "source_health",
  ];
  const parsed = String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return parsed.length ? parsed : fallback;
}

function commandLayerQuery() {
  return Array.from(activeCommandLayers).sort().join(",");
}

function commandViewportQuery() {
  const params = [];
  ["lat", "lon", "zoom"].forEach((key) => {
    const value = initialParams.get(key);
    if (value) {
      params.push(`${key}=${encodeURIComponent(value)}`);
    }
  });
  return params.length ? `&${params.join("&")}` : "";
}

function currentRegionQuery() {
  return regionFilter?.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
}

function commandSurfaceApiUrl(force = false) {
  return `/api/intel/command-surface?force=${force ? "true" : "false"}${currentRegionQuery()}&layers=${encodeURIComponent(commandLayerQuery())}${commandViewportQuery()}`;
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

async function sendJson(path, method, body) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

function syncIntelUrl(updates = {}) {
  const params = new URLSearchParams(window.location.search);
  if (Object.prototype.hasOwnProperty.call(updates, "region")) {
    if (updates.region) {
      params.set("region", updates.region);
    } else {
      params.delete("region");
    }
  }
  if (Object.prototype.hasOwnProperty.call(updates, "search")) {
    if (updates.search) {
      params.set("search", updates.search);
    } else {
      params.delete("search");
    }
  }
  if (
    Object.prototype.hasOwnProperty.call(updates, "detailKind") ||
    Object.prototype.hasOwnProperty.call(updates, "detailId")
  ) {
    if (updates.detailKind && updates.detailId) {
      params.set("detail_kind", updates.detailKind);
      params.set("detail_id", updates.detailId);
    } else {
      params.delete("detail_kind");
      params.delete("detail_id");
    }
  }
  if (Object.prototype.hasOwnProperty.call(updates, "layers")) {
    if (updates.layers) {
      params.set("layers", updates.layers);
    } else {
      params.delete("layers");
    }
  }
  const next = params.toString() ? `${window.location.pathname}?${params.toString()}` : window.location.pathname;
  window.history.replaceState({}, "", next);
}

function renderEthics(snapshot) {
  ethicsGrid.innerHTML = (snapshot.ethics_rules || [])
    .map(
      (rule) => `
        <article class="intel-card">
          <div class="status-label">${escapeHtml(rule.key)}</div>
          <h3>${escapeHtml(rule.title)}</h3>
          <p>${escapeHtml(rule.description)}</p>
        </article>
      `
    )
    .join("");
}

function renderSources(snapshot) {
  const healthByKey = Object.fromEntries((snapshot.source_health || []).map((item) => [item.source_key, item]));
  sourceGrid.innerHTML = (snapshot.sources || [])
    .map(
      (source) => {
        const health = healthByKey[source.source_key];
        return `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(source.category)}</span>
            <span class="intel-tag">${escapeHtml(source.collection_mode)}</span>
            <span class="intel-tag ${source.live_pull ? "live" : "manual"}">${source.live_pull ? "live" : "manual"}</span>
            ${health ? `<span class="intel-tag ${health.status === "live" ? "live" : "manual"}">${escapeHtml(health.status)}</span>` : ""}
          </div>
          <h3>${escapeHtml(source.name)}</h3>
          <p>${escapeHtml(source.notes || "")}</p>
          <div class="subtle mono">${escapeHtml(source.access)}${health ? ` | items: ${escapeHtml(health.item_count)}` : ""}</div>
          ${health?.last_seen_at ? `<div class="subtle mono">last seen ${escapeHtml(relativeAge(health.last_seen_at))}</div>` : ""}
          ${source.url ? `<a class="intel-link" href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
        </article>
      `;
      }
    )
    .join("");
}

function renderClientViews(payload) {
  if (!clientViewGrid) {
    return;
  }
  const items = payload?.views || [];
  if (!items.length) {
    clientViewGrid.innerHTML = `<div class="subtle">No client-specific feeds available yet.</div>`;
    return;
  }
  clientViewGrid.innerHTML = items
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">client_view</span>
            ${item.region_id ? `<span class="intel-tag">${escapeHtml(item.region_id)}</span>` : ""}
            <span class="intel-tag">${escapeHtml(item.client_name || "client")}</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          ${item.audience ? `<div class="subtle">${escapeHtml(item.audience)}</div>` : ""}
          <div class="client-feed-actions">
            <a class="ghost-button" href="${escapeHtml(item.alias_url || item.page_url)}">Open tailored feed</a>
            <a class="intel-link" href="${escapeHtml(item.intel_url || "/intel")}">Open in intel</a>
            <a class="intel-link" href="${escapeHtml(item.api_url)}" target="_blank" rel="noreferrer">Open API</a>
          </div>
        </article>
      `
    )
    .join("");
}

function commandSeverityRank(value) {
  return { high: 3, medium: 2, low: 1 }[value] || 0;
}

function commandProjectPoint(entity, viewport) {
  const bbox = viewport?.bbox || [];
  const fallback = [
    Number(viewport?.center_lat || 39) - 0.35,
    Number(viewport?.center_lon || -98) - 0.35,
    Number(viewport?.center_lat || 39) + 0.35,
    Number(viewport?.center_lon || -98) + 0.35,
  ];
  const [south, west, north, east] = bbox.length === 4 ? bbox : fallback;
  const lonSpan = Math.max(0.0001, east - west);
  const latSpan = Math.max(0.0001, north - south);
  return {
    left: Math.max(3, Math.min(97, ((entity.lon - west) / lonSpan) * 100)),
    top: Math.max(5, Math.min(95, 100 - ((entity.lat - south) / latSpan) * 100)),
  };
}

function commandLayerClass(layerId) {
  return String(layerId || "").replace(/[^a-z0-9_-]/g, "-");
}

function renderCommandInspector(entity, payload) {
  if (!commandInspector) {
    return;
  }
  if (!entity) {
    commandInspector.innerHTML = `<div class="subtle">No visible entity selected.</div>`;
    return;
  }
  const facts = Object.entries(entity.facts || {});
  commandInspector.innerHTML = `
    <div class="status-label">Inspector</div>
    <h3>${escapeHtml(entity.title)}</h3>
    <p>${escapeHtml(entity.summary || "")}</p>
    <div class="intel-tag-row">
      <span class="intel-tag">${escapeHtml(entity.layer_id)}</span>
      <span class="intel-tag ${entity.severity === "high" ? "manual" : entity.severity === "low" ? "live" : ""}">${escapeHtml(entity.severity)}</span>
      <span class="intel-tag">score ${escapeHtml(entity.score)}</span>
    </div>
    <div class="command-fact-grid">
      ${
        facts.length
          ? facts
              .slice(0, 6)
              .map(
                ([key, value]) => `
                  <div class="intel-map-fact">
                    <span>${escapeHtml(key)}</span>
                    <strong>${escapeHtml(value || "--")}</strong>
                  </div>
                `
              )
              .join("")
          : `<div class="subtle">No additional facts attached.</div>`
      }
    </div>
    <ul class="intel-list command-note-list">
      ${(entity.notes || []).slice(0, 4).map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`).join("")}
    </ul>
    <div class="client-feed-actions">
      ${entity.intel_url ? `<a class="ghost-button" href="${escapeHtml(entity.intel_url)}">Open in Intel</a>` : ""}
      ${entity.source_url ? `<a class="intel-link" href="${escapeHtml(entity.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
    </div>
    <div class="subtle mono command-inspector-meta">
      ${escapeHtml(entity.source_name || "No source label")} | ${escapeHtml(payload.surface_id || "")}
    </div>
  `;
}

function renderCommandSurface(payload) {
  commandSurfacePayload = payload;
  if (!payload || !commandMapCanvas) {
    return;
  }
  activeCommandLayers = new Set((payload.layers || []).filter((layer) => layer.enabled).map((layer) => layer.layer_id));
  const entities = (payload.entities || []).slice().sort((left, right) => {
    return (
      commandSeverityRank(right.severity) - commandSeverityRank(left.severity) ||
      right.score - left.score ||
      left.title.localeCompare(right.title)
    );
  });
  const mapped = entities.filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon));
  const selected =
    entities.find((item) => item.entity_id === selectedCommandEntityId) ||
    mapped[0] ||
    entities[0] ||
    null;
  selectedCommandEntityId = selected?.entity_id || "";

  if (commandSurfaceStatus) {
    commandSurfaceStatus.innerHTML = `
      <div class="status-label">Mode</div>
      <div class="status-value">${escapeHtml(payload.mode || "read_only")}</div>
      <div class="subtle mono">${escapeHtml(relativeAge(payload.updated_at))}</div>
    `;
  }

  if (commandLayerList) {
    commandLayerList.innerHTML = (payload.layers || [])
      .map(
        (layer) => `
          <button class="command-layer-button ${layer.enabled ? "is-active" : ""}" type="button" data-command-layer-id="${escapeHtml(layer.layer_id)}">
            <span>
              <strong>${escapeHtml(layer.label)}</strong>
              <small>${escapeHtml(layer.category)} | ${escapeHtml(layer.retrieval_mode)}</small>
            </span>
            <em>${escapeHtml(layer.count)}</em>
          </button>
        `
      )
      .join("");
  }

  const dots = mapped
    .map((entity) => {
      const point = commandProjectPoint(entity, payload.viewport);
      const size = Math.max(11, Math.min(30, 10 + entity.score / 12));
      return `
        <button
          class="command-dot command-dot-${escapeHtml(commandLayerClass(entity.layer_id))} ${entity.entity_id === selectedCommandEntityId ? "is-selected" : ""}"
          type="button"
          data-command-entity-id="${escapeHtml(entity.entity_id)}"
          style="left:${point.left.toFixed(2)}%; top:${point.top.toFixed(2)}%; --dot-size:${size.toFixed(1)}px"
          title="${escapeHtml(entity.title)}"
          aria-label="${escapeHtml(entity.title)}"
        >
          <span></span>
        </button>
      `;
    })
    .join("");

  commandMapCanvas.innerHTML = `
    <div class="command-map-stage">
      <div class="intel-map-grid"></div>
      <div class="intel-map-axis intel-map-axis-x"></div>
      <div class="intel-map-axis intel-map-axis-y"></div>
      <div class="intel-map-overlay intel-map-overlay-top-left">
        <div class="status-label">Viewport</div>
        <strong>${escapeHtml(Number(payload.viewport?.center_lat || 0).toFixed(3))}, ${escapeHtml(Number(payload.viewport?.center_lon || 0).toFixed(3))}</strong>
      </div>
      <div class="intel-map-overlay intel-map-overlay-top-right">
        <div class="status-label">Layers</div>
        <strong>${escapeHtml(String(activeCommandLayers.size))} active</strong>
      </div>
      <div class="intel-map-overlay intel-map-overlay-bottom-left">
        <div class="status-label">Entities</div>
        <strong>${escapeHtml(String(entities.length))} visible</strong>
      </div>
      ${dots || `<div class="intel-map-empty-state"><div class="status-label">No mapped entities</div><strong>Selected layers are feed-only right now</strong></div>`}
    </div>
  `;

  renderCommandInspector(selected, payload);

  if (commandGuardrails) {
    const sourceSummary = payload.source_summary || {};
    commandGuardrails.innerHTML = `
      <div class="status-label">Guardrails</div>
      <ul class="intel-list">
        ${(payload.guardrails || [])
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.label)}</strong>
                  <span class="intel-tag live">${escapeHtml(item.status)}</span>
                </div>
                <div class="subtle">${escapeHtml(item.detail)}</div>
              </li>
            `
          )
          .join("")}
      </ul>
      <div class="command-source-summary">
        <span class="intel-tag">sources ${escapeHtml(sourceSummary.total || 0)}</span>
        <span class="intel-tag live">live ${escapeHtml(sourceSummary.live || 0)}</span>
        <span class="intel-tag">manual ${escapeHtml(sourceSummary.manual || 0)}</span>
        <span class="intel-tag manual">empty ${escapeHtml(sourceSummary.empty || 0)}</span>
      </div>
    `;
  }

  if (commandFeed) {
    const feed = payload.feed || [];
    commandFeed.innerHTML = feed.length
      ? feed
          .slice(0, 18)
          .map(
            (entity) => `
              <article class="command-feed-item ${entity.entity_id === selectedCommandEntityId ? "is-selected" : ""}">
                <div class="intel-tag-row">
                  <span class="intel-tag">${escapeHtml(entity.layer_id)}</span>
                  <span class="intel-tag">${escapeHtml(entity.region_id || "multi_region")}</span>
                  <span class="intel-tag ${entity.severity === "high" ? "manual" : entity.severity === "low" ? "live" : ""}">${escapeHtml(entity.severity)}</span>
                </div>
                <h3>${escapeHtml(entity.title)}</h3>
                <p>${escapeHtml(entity.summary || "")}</p>
                <div class="client-feed-actions">
                  <button class="ghost-button" type="button" data-command-entity-id="${escapeHtml(entity.entity_id)}">Inspect</button>
                  ${entity.intel_url ? `<a class="ghost-button" href="${escapeHtml(entity.intel_url)}">Open in Intel</a>` : ""}
                  ${entity.source_url ? `<a class="intel-link" href="${escapeHtml(entity.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
                </div>
              </article>
            `
          )
          .join("")
      : `<div class="subtle">No command feed entities for the selected layers.</div>`;
  }
}

async function loadCommandSurface(force = false) {
  const payload = await fetchJson(commandSurfaceApiUrl(force));
  renderCommandSurface(payload);
  return payload;
}

function renderIntelligenceMap(snapshot) {
  if (!intelMapCanvas || !window.IntelMap) {
    return;
  }
  const regionId = regionFilter?.value || snapshot?.regions?.[0]?.id || null;
  const data = window.IntelMap.buildPointsFromSnapshot(snapshot, regionId);
  window.IntelMap.renderMap({
    canvas: intelMapCanvas,
    legend: intelMapLegend,
    topList: intelMapTopPoints,
    data,
    emptyText: "No mapped public business intelligence is available for this region yet.",
  });
}

function renderBriefs(snapshot) {
  briefGrid.innerHTML = (snapshot.briefs || [])
    .map(
      (brief) => `
        <article class="intel-card">
          <div class="status-label">${escapeHtml(brief.region_id)}</div>
          <h3>${escapeHtml(brief.headline)}</h3>
          <p>${escapeHtml(brief.summary)}</p>
          <ul class="intel-list">
            ${(brief.notes || [])
              .map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`)
              .join("")}
          </ul>
        </article>
      `
    )
    .join("");
}

function renderWatchlist(payload) {
  const items = payload?.watchlist || [];
  if (items.length === 0) {
    watchlistGrid.innerHTML = `<div class="subtle">No watchlist items available yet.</div>`;
    return;
  }
  watchlistGrid.innerHTML = items
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.kind)}</span>
            <span class="intel-tag">${escapeHtml(item.region_id)}</span>
            <span class="intel-tag">${escapeHtml(item.score)}</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.subtitle || "")}</p>
          <div class="subtle">${escapeHtml(item.detail || "")}</div>
          <div class="subtle">${escapeHtml(item.reason || "")}</div>
          ${detailButton(item.kind, item.item_id, "View detail")}
          <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(item.kind)}" data-collection-add-label="${escapeHtml(item.title)}" data-collection-add-region="${escapeHtml(item.region_id)}" data-collection-add-item-id="${escapeHtml(item.item_id || "")}" data-collection-add-url="${escapeHtml(item.url || "")}">Add to collection</button>
          ${item.url ? `<a class="intel-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
        </article>
      `
    )
    .join("");
}

function renderOpportunities(payload) {
  const items = payload?.opportunities || [];
  if (items.length === 0) {
    opportunityGrid.innerHTML = `<div class="subtle">No ranked opportunities available yet.</div>`;
    return;
  }
  opportunityGrid.innerHTML = items
    .slice(0, 12)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.kind)}</span>
            <span class="intel-tag">${escapeHtml(item.region_id)}</span>
            <span class="intel-tag">${escapeHtml(item.score)}</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          <ul class="intel-list">
            ${(item.reasons || []).map((reason) => `<li class="intel-item"><div class="subtle">${escapeHtml(reason)}</div></li>`).join("")}
          </ul>
          ${detailButton(item.kind, item.item_ids?.[0], "Open detail")}
          <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(item.kind)}" data-collection-add-label="${escapeHtml(item.title)}" data-collection-add-region="${escapeHtml(item.region_id)}" data-collection-add-item-id="${escapeHtml(item.item_ids?.[0] || "")}" data-collection-add-url="${escapeHtml(item.urls?.[0] || "")}">Add to collection</button>
          <button class="ghost-button intel-save-button" type="button" data-save-kind="${escapeHtml(item.kind)}" data-save-label="${escapeHtml(item.title)}" data-save-region="${escapeHtml(item.region_id)}" data-save-item-id="${escapeHtml(item.item_ids?.[0] || "")}" data-save-url="${escapeHtml(item.urls?.[0] || "")}">Save</button>
          ${item.urls?.[0] ? `<a class="intel-link" href="${escapeHtml(item.urls[0])}" target="_blank" rel="noreferrer">Open source</a>` : ""}
        </article>
      `
    )
    .join("");
}

function renderSavedWatchlist(payload) {
  const items = payload?.items || [];
  if (items.length === 0) {
    savedWatchlistGrid.innerHTML = `<div class="subtle">No saved watchlist items yet.</div>`;
    return;
  }
  savedWatchlistGrid.innerHTML = items
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.entry.kind)}</span>
            <span class="intel-tag">${escapeHtml(item.entry.region_id || "unknown_region")}</span>
            <span class="intel-tag ${item.is_live ? "live" : "manual"}">${item.is_live ? "live" : "saved_only"}</span>
          </div>
          <h3>${escapeHtml(item.entry.label)}</h3>
          <p>${escapeHtml(item.summary || item.entry.note || "")}</p>
          ${item.entry.note ? `<div class="subtle">${escapeHtml(item.entry.note)}</div>` : ""}
          ${item.annotation?.note ? `<div class="subtle"><strong>Analyst:</strong> ${escapeHtml(item.annotation.note)}</div>` : ""}
          ${item.annotation?.tags?.length ? `<div class="intel-tag-row">${item.annotation.tags.map((tag) => `<span class="intel-tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
          <div class="intel-tag-row">
            ${detailButton(item.entry.kind, item.entry.item_id, "Open detail")}
            <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(item.entry.kind)}" data-collection-add-label="${escapeHtml(item.entry.label)}" data-collection-add-region="${escapeHtml(item.entry.region_id || "")}" data-collection-add-item-id="${escapeHtml(item.entry.item_id || "")}" data-collection-add-url="${escapeHtml(item.entry.source_url || "")}" data-collection-add-note="${escapeHtml(item.entry.note || "")}">Add to collection</button>
            <button class="ghost-button intel-delete-button" type="button" data-watchlist-delete-id="${escapeHtml(item.entry.entry_id)}">Remove</button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderCollections(payload) {
  collectionsPayload = payload || { collections: [] };
  const collections = collectionsPayload.collections || [];
  const activeExists = collections.some((item) => item.collection.collection_id === activeCollectionId);
  if (!activeExists) {
    activeCollectionId = "";
    window.localStorage?.removeItem("intelActiveCollectionId");
  }

  if (collectionActiveSelect) {
    collectionActiveSelect.innerHTML = `
      <option value="">No active collection</option>
      ${collections
        .map(
          (item) => `
            <option value="${escapeHtml(item.collection.collection_id)}" ${item.collection.collection_id === activeCollectionId ? "selected" : ""}>
              ${escapeHtml(item.collection.title)}
            </option>
          `
        )
        .join("")}
    `;
  }

  const activeCollection = collections.find((item) => item.collection.collection_id === activeCollectionId);
  if (collectionActiveSummary) {
    collectionActiveSummary.textContent = activeCollection
      ? `Active collection: ${activeCollection.collection.title}. Quick-save actions will route into this dossier.`
      : "No active collection selected. Pick one to route quick-save actions into a dossier.";
  }

  if (!collectionGrid) {
    return;
  }
  if (collections.length === 0) {
    collectionGrid.innerHTML = `<div class="subtle">No collections yet. Create one to start assembling dossiers.</div>`;
    return;
  }
  collectionGrid.innerHTML = collections
    .map((item) => {
      const collection = item.collection;
      const isActive = collection.collection_id === activeCollectionId;
      const previewItems = (item.items || []).slice(0, 6);
      return `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag ${isActive ? "live" : ""}">${escapeHtml(isActive ? "active" : "saved")}</span>
            <span class="intel-tag">${escapeHtml(collection.region_id || "multi_region")}</span>
            <span class="intel-tag">${escapeHtml(String((collection.items || []).length))} items</span>
            <span class="intel-tag">${escapeHtml(String(item.live_count || 0))} live</span>
          </div>
          <h3>${escapeHtml(collection.title)}</h3>
          <p>${escapeHtml(collection.note || "No collection note yet.")}</p>
          ${collection.tags?.length ? `<div class="intel-tag-row">${collection.tags.map((tag) => `<span class="intel-tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
          <div class="intel-tag-row">
            <button class="ghost-button" type="button" data-collection-activate-id="${escapeHtml(collection.collection_id)}">${isActive ? "Active" : "Set active"}</button>
            <button class="ghost-button intel-bundle-add-button" type="button" data-bundle-add-collection-id="${escapeHtml(collection.collection_id)}" data-bundle-add-label="${escapeHtml(collection.title)}">Add to bundle</button>
            <a class="intel-link" href="/api/intel/collections/${encodeURIComponent(collection.collection_id)}/briefing/markdown" target="_blank" rel="noreferrer">Open pack</a>
            <button class="ghost-button intel-delete-button" type="button" data-collection-delete-id="${escapeHtml(collection.collection_id)}">Delete</button>
          </div>
          <details class="intel-markdown-block">
            <summary>Show items</summary>
            <ul class="intel-list">
              ${previewItems.length
                ? previewItems
                    .map(
                      (entry) => `
                        <li class="intel-item">
                          <div class="intel-item-head">
                            <strong>${escapeHtml(entry.ref.label || entry.resolved.name || entry.resolved.title || entry.resolved.address || "Saved item")}</strong>
                            <span class="intel-tag">${escapeHtml(entry.ref.kind)}</span>
                          </div>
                          <div class="subtle">${escapeHtml(entry.summary || entry.ref.note || "")}</div>
                          <div class="intel-tag-row">
                            ${detailButton(entry.ref.kind, entry.ref.item_id, "Open detail")}
                            <button class="ghost-button intel-delete-button" type="button" data-collection-item-delete="${escapeHtml(entry.ref.ref_id)}" data-collection-item-parent="${escapeHtml(collection.collection_id)}">Remove</button>
                          </div>
                        </li>
                      `
                    )
                    .join("")
                : `<li class="intel-item"><div class="subtle">No items saved yet.</div></li>`}
            </ul>
          </details>
        </article>
      `;
    })
    .join("");
}

function renderBundles(payload) {
  bundlesPayload = payload || { bundles: [] };
  const bundles = bundlesPayload.bundles || [];
  const activeExists = bundles.some((item) => item.bundle.bundle_id === activeBundleId);
  if (!activeExists) {
    activeBundleId = "";
    window.localStorage?.removeItem("intelActiveBundleId");
  }

  if (bundleActiveSelect) {
    bundleActiveSelect.innerHTML = `
      <option value="">No active bundle</option>
      ${bundles
        .map(
          (item) => `
            <option value="${escapeHtml(item.bundle.bundle_id)}" ${item.bundle.bundle_id === activeBundleId ? "selected" : ""}>
              ${escapeHtml(item.bundle.title)}
            </option>
          `
        )
        .join("")}
    `;
  }

  const activeBundle = bundles.find((item) => item.bundle.bundle_id === activeBundleId);
  if (bundleActiveSummary) {
    bundleActiveSummary.textContent = activeBundle
      ? `Active bundle: ${activeBundle.bundle.title}. Collection cards can now be packaged into this bundle.`
      : "No active bundle selected. Pick one to route collection-level packaging into a top-level briefing.";
  }

  if (!bundleGrid) {
    return;
  }
  if (bundles.length === 0) {
    bundleGrid.innerHTML = `<div class="subtle">No bundles yet. Create one after you have a few collections worth packaging together.</div>`;
    return;
  }
  bundleGrid.innerHTML = bundles
    .map((item) => {
      const bundle = item.bundle;
      const isActive = bundle.bundle_id === activeBundleId;
      const refs = item.collections || [];
      return `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag ${isActive ? "live" : ""}">${escapeHtml(isActive ? "active" : "saved")}</span>
            <span class="intel-tag">${escapeHtml(bundle.region_id || "multi_region")}</span>
            <span class="intel-tag">${escapeHtml(String((bundle.collections || []).length))} collections</span>
            <span class="intel-tag">${escapeHtml(String(item.live_count || 0))} live items</span>
          </div>
          <h3>${escapeHtml(bundle.title)}</h3>
          <p>${escapeHtml(bundle.note || "No bundle note yet.")}</p>
          ${bundle.tags?.length ? `<div class="intel-tag-row">${bundle.tags.map((tag) => `<span class="intel-tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
          <div class="intel-tag-row">
            <button class="ghost-button" type="button" data-bundle-activate-id="${escapeHtml(bundle.bundle_id)}">${isActive ? "Active" : "Set active"}</button>
            <a class="intel-link" href="/api/intel/bundles/${encodeURIComponent(bundle.bundle_id)}/briefing/markdown" target="_blank" rel="noreferrer">Open pack</a>
            <button class="ghost-button intel-delete-button" type="button" data-bundle-delete-id="${escapeHtml(bundle.bundle_id)}">Delete</button>
          </div>
          <details class="intel-markdown-block">
            <summary>Show collections</summary>
            <ul class="intel-list">
              ${refs.length
                ? refs
                    .map(
                      (entry) => `
                        <li class="intel-item">
                          <div class="intel-item-head">
                            <strong>${escapeHtml(entry.ref.label)}</strong>
                            <span class="intel-tag ${entry.is_live ? "live" : "manual"}">${escapeHtml(entry.is_live ? "live" : "missing")}</span>
                          </div>
                          <div class="subtle">${escapeHtml(entry.collection?.note || `${entry.item_count || 0} items`)}</div>
                          <div class="intel-tag-row">
                            ${entry.collection?.collection_id ? `<a class="intel-link" href="/api/intel/collections/${encodeURIComponent(entry.collection.collection_id)}/briefing/markdown" target="_blank" rel="noreferrer">Open collection</a>` : ""}
                            <button class="ghost-button intel-delete-button" type="button" data-bundle-ref-delete="${escapeHtml(entry.ref.ref_id)}" data-bundle-ref-parent="${escapeHtml(bundle.bundle_id)}">Remove</button>
                          </div>
                        </li>
                      `
                    )
                    .join("")
                : `<li class="intel-item"><div class="subtle">No collections attached yet.</div></li>`}
            </ul>
          </details>
        </article>
      `;
    })
    .join("");
}

function renderMonitorRules(payload) {
  monitorRulesPayload = payload || { rules: [] };
  const rules = monitorRulesPayload.rules || [];
  if (!monitorGrid) {
    return;
  }
  if (rules.length === 0) {
    monitorGrid.innerHTML = `<div class="subtle">No monitor rules yet. Create one to track the changes that matter most.</div>`;
    return;
  }
  monitorGrid.innerHTML = rules
    .map(
      (entry) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(entry.rule.region_id || "all_regions")}</span>
            <span class="intel-tag">${escapeHtml(String((entry.matches || []).length))} matches</span>
          </div>
          <h3>${escapeHtml(entry.rule.title)}</h3>
          <p>${escapeHtml(entry.summary || entry.rule.note || "")}</p>
          ${entry.rule.tags?.length ? `<div class="intel-tag-row">${entry.rule.tags.map((tag) => `<span class="intel-tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
          <details class="intel-markdown-block" ${entry.matches?.length ? "open" : ""}>
            <summary>Show matches</summary>
            <ul class="intel-list">
              ${(entry.matches || [])
                .slice(0, 6)
                .map(
                  (item) => `
                    <li class="intel-item">
                      <div class="intel-item-head">
                        <strong>${escapeHtml(item.title)}</strong>
                        <span class="intel-tag ${item.severity === "high" ? "manual" : item.severity === "medium" ? "" : "live"}">${escapeHtml(item.severity)}</span>
                      </div>
                      <div class="subtle">${escapeHtml(item.summary || "")}</div>
                      <div class="intel-tag-row">
                        ${item.item_id ? detailButton(item.kind || item.source_kind, item.item_id, "Open detail") : ""}
                        ${item.url ? `<a class="intel-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
                      </div>
                    </li>
                  `
                )
                .join("") || `<li class="intel-item"><div class="subtle">No matches right now.</div></li>`}
            </ul>
          </details>
          <div class="intel-tag-row">
            <button class="ghost-button intel-delete-button" type="button" data-monitor-delete-id="${escapeHtml(entry.rule.rule_id)}">Delete</button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderTrends(payload) {
  const series = payload?.series || [];
  if (series.length === 0) {
    trendGrid.innerHTML = `<div class="subtle">No trend history available yet.</div>`;
    return;
  }
  trendGrid.innerHTML = series
    .slice(-6)
    .map(
      (point) => `
        <article class="intel-card">
          <div class="status-label">${escapeHtml(relativeAge(point.updated_at))}</div>
          <h3>${escapeHtml(point.updated_at)}</h3>
          <ul class="intel-list">
            ${(point.regions || [])
              .map(
                (row) => `
                  <li class="intel-item">
                    <div class="intel-item-head">
                      <strong>${escapeHtml(row.region_id)}</strong>
                      <span class="intel-tag">${escapeHtml(row.news + row.permits + row.businesses + row.contacts + row.organizations)} items</span>
                    </div>
                    <div class="subtle">news ${escapeHtml(row.news)} | permits ${escapeHtml(row.permits)} | businesses ${escapeHtml(row.businesses)} | contacts ${escapeHtml(row.contacts)} | orgs ${escapeHtml(row.organizations)}</div>
                  </li>
                `
              )
              .join("")}
          </ul>
        </article>
      `
    )
    .join("");
}

function renderSourceHistory(payload) {
  const items = payload?.sources || [];
  if (!sourceHistoryGrid) {
    return;
  }
  if (items.length === 0) {
    sourceHistoryGrid.innerHTML = `<div class="subtle">No source history available yet.</div>`;
    return;
  }
  sourceHistoryGrid.innerHTML = items
    .slice(0, 16)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.category)}</span>
            <span class="intel-tag ${item.last_status === "live" ? "live" : "manual"}">${escapeHtml(item.last_status || "unknown")}</span>
            <span class="intel-tag">${escapeHtml(item.last_item_count)}</span>
          </div>
          <h3>${escapeHtml(item.name || item.source_key)}</h3>
          <p>${escapeHtml(`non-empty runs ${item.non_empty_runs} | empty runs ${item.empty_runs} | manual runs ${item.manual_runs}`)}</p>
          <div class="subtle mono">${escapeHtml((item.points || []).slice(-4).map((point) => `${point.status}:${point.item_count}`).join(" • "))}</div>
        </article>
      `
    )
    .join("");
}

function renderSourceIncidents(payload) {
  const items = payload?.incidents || [];
  if (!sourceIncidentGrid) {
    return;
  }
  if (items.length === 0) {
    sourceIncidentGrid.innerHTML = `<div class="subtle">No source incidents detected in the current history window.</div>`;
    return;
  }
  sourceIncidentGrid.innerHTML = items
    .slice(0, 16)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag ${item.severity === "high" ? "manual" : item.severity === "medium" ? "" : "live"}">${escapeHtml(item.severity)}</span>
            <span class="intel-tag">${escapeHtml(item.incident_type)}</span>
            <span class="intel-tag">${escapeHtml(item.category)}</span>
          </div>
          <h3>${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          <div class="subtle mono">started ${escapeHtml(relativeAge(item.started_at))} | latest ${escapeHtml(relativeAge(item.latest_at))} | runs ${escapeHtml(item.run_count)} | items ${escapeHtml(item.last_item_count)}</div>
        </article>
      `
    )
    .join("");
}

function renderRegionChanges(payload) {
  const items = payload?.changes || [];
  if (!regionChangeGrid) {
    return;
  }
  if (items.length === 0) {
    regionChangeGrid.innerHTML = `<div class="subtle">No regional changes detected in the current history window.</div>`;
    return;
  }
  regionChangeGrid.innerHTML = items
    .slice(0, 18)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.region_id)}</span>
            <span class="intel-tag">${escapeHtml(relativeAge(item.latest_at))}</span>
          </div>
          <h3>${escapeHtml(item.summary || "")}</h3>
          <div class="intel-tag-row">
            <span class="intel-tag">news ${escapeHtml(item.delta_news >= 0 ? `+${item.delta_news}` : `${item.delta_news}`)}</span>
            <span class="intel-tag">permits ${escapeHtml(item.delta_permits >= 0 ? `+${item.delta_permits}` : `${item.delta_permits}`)}</span>
            <span class="intel-tag">biz ${escapeHtml(item.delta_businesses >= 0 ? `+${item.delta_businesses}` : `${item.delta_businesses}`)}</span>
            <span class="intel-tag">contacts ${escapeHtml(item.delta_contacts >= 0 ? `+${item.delta_contacts}` : `${item.delta_contacts}`)}</span>
            <span class="intel-tag">orgs ${escapeHtml(item.delta_organizations >= 0 ? `+${item.delta_organizations}` : `${item.delta_organizations}`)}</span>
          </div>
          <ul class="intel-list">
            ${(item.notable_lines || []).map((line) => `<li class="intel-item"><div class="subtle">${escapeHtml(line)}</div></li>`).join("")}
          </ul>
        </article>
      `
    )
    .join("");
}

function renderEntityChanges(payload, selector = "#entity-change-grid") {
  const holder = document.querySelector(selector);
  if (!holder) {
    return;
  }
  const items = payload?.changes || [];
  if (items.length === 0) {
    holder.innerHTML = `<div class="subtle">No entity-level changes detected in the current history window.</div>`;
    return;
  }
  holder.innerHTML = items
    .slice(0, selector === "#entity-change-grid" ? 18 : 10)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.region_id)}</span>
            <span class="intel-tag">${escapeHtml(item.kind)}</span>
            <span class="intel-tag ${item.change_type === "added" ? "live" : item.change_type === "removed" ? "manual" : ""}">${escapeHtml(item.change_type)}</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          <div class="subtle mono">${escapeHtml(relativeAge(item.latest_at))}${item.score_before !== null || item.score_after !== null ? ` | score ${escapeHtml(item.score_before ?? "n/a")} -> ${escapeHtml(item.score_after ?? "n/a")}` : ""}</div>
          <div class="intel-tag-row">
            ${detailButton(item.kind, item.item_id, "Open detail")}
            <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(item.kind)}" data-collection-add-label="${escapeHtml(item.title)}" data-collection-add-region="${escapeHtml(item.region_id)}" data-collection-add-item-id="${escapeHtml(item.item_id || "")}">Add to collection</button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderAlerts(payload) {
  const items = payload?.alerts || [];
  if (!alertGrid) {
    return;
  }
  if (items.length === 0) {
    alertGrid.innerHTML = `<div class="subtle">No active alerts right now.</div>`;
    return;
  }
  alertGrid.innerHTML = items
    .slice(0, 16)
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag ${item.severity === "high" ? "manual" : item.severity === "medium" ? "" : "live"}">${escapeHtml(item.severity)}</span>
            <span class="intel-tag">${escapeHtml(item.kind)}</span>
            <span class="intel-tag">${escapeHtml(item.score)}</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          ${item.urls?.[0] ? `<a class="intel-link" href="${escapeHtml(item.urls[0])}" target="_blank" rel="noreferrer">Open source</a>` : ""}
        </article>
      `
    )
    .join("");
}

function renderRegionBriefings(payload) {
  const items = payload?.packs || [];
  if (!regionBriefingGrid) {
    return;
  }
  if (items.length === 0) {
    regionBriefingGrid.innerHTML = `<div class="subtle">No regional briefing packs available yet.</div>`;
    return;
  }
  regionBriefingGrid.innerHTML = items
    .map(
      (item) => `
        <article class="intel-card intel-graph-summary">
          <div class="intel-tag-row">
            <span class="intel-tag">${escapeHtml(item.region_id)}</span>
            <span class="intel-tag">${escapeHtml((item.top_opportunities || []).length)} opps</span>
            <span class="intel-tag">${escapeHtml((item.source_alerts || []).length)} alerts</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          <div class="subtle"><strong>Top opportunities:</strong> ${escapeHtml((item.top_opportunities || []).slice(0, 3).map((entry) => entry.title).join(", ") || "None")}</div>
          <div class="subtle"><strong>Contacts:</strong> ${escapeHtml((item.top_contacts || []).slice(0, 3).map((entry) => entry.name).join(", ") || "None")}</div>
          <div class="intel-tag-row">
            <a class="intel-link" href="/api/intel/region-briefing/${encodeURIComponent(item.region_id)}/markdown" target="_blank" rel="noreferrer">Open markdown</a>
          </div>
          <details class="intel-markdown-block">
            <summary>Show briefing pack</summary>
            <pre class="intel-markdown-pre">${escapeHtml(item.markdown || "")}</pre>
          </details>
        </article>
      `
    )
    .join("");
}

function renderGraph(payload) {
  if (!relationshipGraph) {
    return;
  }
  const nodes = payload?.nodes || [];
  const edges = payload?.edges || [];
  if (nodes.length === 0) {
    relationshipGraph.innerHTML = `<div class="subtle">No relationship graph available yet.</div>`;
    return;
  }
  const byKind = {};
  for (const node of nodes) {
    if (!byKind[node.kind]) {
      byKind[node.kind] = [];
    }
    byKind[node.kind].push(node);
  }
  const focusNode = currentGraphFocusId ? nodes.find((item) => item.node_id === currentGraphFocusId) : null;
  relationshipGraph.innerHTML = `
    <div class="intel-grid">
      <article class="intel-card intel-graph-summary">
        <div class="status-label">${escapeHtml(payload.region || "all_regions")}</div>
        <h3>${escapeHtml(focusNode ? `Focused graph: ${focusNode.label}` : "Regional relationship graph")}</h3>
        <p>${escapeHtml((payload.notes || []).join(" ") || "Cross-source links across organizations, contacts, public signals, and permits.")}</p>
        <div class="intel-tag-row">
          <span class="intel-tag">${escapeHtml(`${nodes.length} nodes`)}</span>
          <span class="intel-tag">${escapeHtml(`${edges.length} edges`)}</span>
          ${focusNode ? `<button id="intel-clear-focus-button" class="ghost-button" type="button">Clear focus</button>` : ""}
        </div>
      </article>
      ${Object.entries(byKind)
        .map(
          ([kind, items]) => `
            <article class="intel-card">
              <div class="status-label">${escapeHtml(kind)}</div>
              <h3>${escapeHtml(String(items.length))}</h3>
              <ul class="intel-list">
                ${items
                  .slice(0, 6)
                  .map(
                    (item) => `
                      <li class="intel-item">
                        <div class="intel-item-head">
                          <strong>${escapeHtml(item.label)}</strong>
                          <span class="intel-tag">${escapeHtml(item.score || 0)}</span>
                        </div>
                        <div class="subtle">${escapeHtml(item.subtitle || item.address || "")}</div>
                        ${detailButton(item.kind, item.node_id, "View detail")}
                      </li>
                    `
                  )
                  .join("")}
              </ul>
            </article>
          `
        )
        .join("")}
      <article class="intel-card intel-graph-edges">
        <div class="status-label">edges</div>
        <h3>Active links</h3>
        <ul class="intel-list">
          ${edges
            .slice(0, 18)
            .map((edge) => {
              const source = nodes.find((item) => item.node_id === edge.source_id);
              const target = nodes.find((item) => item.node_id === edge.target_id);
              return `
                <li class="intel-item">
                  <div class="intel-item-head">
                    <strong>${escapeHtml(source?.label || edge.source_id)}</strong>
                    <span class="intel-tag">${escapeHtml(edge.relation)}</span>
                  </div>
                  <div class="subtle">${escapeHtml(target?.label || edge.target_id)}</div>
                </li>
              `;
            })
            .join("")}
        </ul>
      </article>
    </div>
  `;
}

function renderRegion(snapshot, region) {
  const news = (snapshot.news || []).filter((item) => item.region_id === region.id).slice(0, 8);
  const permits = (snapshot.permits || []).filter((item) => item.region_id === region.id).slice(0, 8);
  const businesses = (snapshot.businesses || []).filter((item) => item.region_id === region.id).slice(0, 8);
  const contacts = (snapshot.contacts || []).filter((item) => item.region_id === region.id).slice(0, 6);
  const organizations = (snapshot.organizations || []).filter((item) => item.region_id === region.id).slice(0, 6);

  const newsHtml =
    news.length > 0
      ? news
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.title)}</strong>
                  <span class="intel-tag ${item.actionable ? "live" : "manual"}">${item.signal_type}</span>
                </div>
                <div class="intel-meta">${escapeHtml(item.source_name)} | score ${escapeHtml(item.signal_score)} | ${escapeHtml(relativeAge(item.published_at))}</div>
                <div class="subtle">${escapeHtml(item.address_hint || item.summary || "")}</div>
                ${detailButton("news", item.item_id, "Open detail")}
              </li>
            `
          )
          .join("")
      : `<li class="intel-item"><div class="subtle">No news items right now.</div></li>`;

  const permitsHtml =
    permits.length > 0
      ? permits
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.address)}</strong>
                  <span class="intel-tag">${escapeHtml(item.county)}</span>
                </div>
                <div class="intel-meta">${escapeHtml(item.permit_type)} | ${escapeHtml(item.status)} | score ${escapeHtml(item.signal_score)}</div>
                <div class="subtle mono">${escapeHtml(item.permit_number)} | ${escapeHtml(relativeAge(item.status_date))}</div>
                ${detailButton("permit", item.item_id, "Open detail")}
              </li>
            `
          )
          .join("")
      : `<li class="intel-item"><div class="subtle">No permit items live for this region yet.</div></li>`;

  const businessesHtml =
    businesses.length > 0
      ? businesses
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.name)}</strong>
                  <span class="intel-tag">${escapeHtml(item.category)}</span>
                </div>
                <div class="intel-meta">${escapeHtml(item.address)} | score ${escapeHtml(item.lead_score)}</div>
                <div class="subtle">${escapeHtml(item.website || item.phone || "Public contact not tagged")}</div>
                ${detailButton("business", item.item_id, "Open detail")}
              </li>
            `
          )
          .join("")
      : `<li class="intel-item"><div class="subtle">No business leads found.</div></li>`;

  const contactsHtml =
    contacts.length > 0
      ? contacts
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.name)}</strong>
                  <span class="intel-tag">${escapeHtml(item.organization)}</span>
                </div>
                <div class="intel-meta">${escapeHtml(item.title || "Public contact")} | score ${escapeHtml(item.contact_score)}</div>
                <div class="subtle">${escapeHtml(item.email || item.phone || item.address || item.website || "")}</div>
                ${detailButton("contact", item.item_id, "Open detail")}
              </li>
            `
          )
          .join("")
      : `<li class="intel-item"><div class="subtle">No official public contacts collected yet.</div></li>`;

  const organizationsHtml =
    organizations.length > 0
      ? organizations
          .map(
            (item) => `
              <li class="intel-item">
                <div class="intel-item-head">
                  <strong>${escapeHtml(item.name)}</strong>
                  <span class="intel-tag">${escapeHtml(item.news_signal_count + item.business_lead_count + item.contact_count + (item.permit_signal_count || 0))} signals</span>
                </div>
                <div class="intel-meta">${escapeHtml((item.categories || []).slice(0, 3).join(", ") || "Organization")} | score ${escapeHtml(item.organization_score)}</div>
                <div class="subtle">${escapeHtml(item.address || item.website || item.phone || "")}</div>
                ${detailButton("organization", item.item_id, "View detail")}
              </li>
            `
          )
          .join("")
      : `<li class="intel-item"><div class="subtle">No organization profiles available yet.</div></li>`;

  return `
    <section class="intel-column">
      <div class="panel-header">
        <h2>${escapeHtml(region.name)}</h2>
        <p>${escapeHtml(region.summary)}</p>
      </div>
      <div class="intel-stats">
        <div class="intel-stat"><span>News</span><strong>${news.length}</strong></div>
        <div class="intel-stat"><span>Permits</span><strong>${permits.length}</strong></div>
        <div class="intel-stat"><span>Contacts</span><strong>${contacts.length}</strong></div>
        <div class="intel-stat"><span>Orgs</span><strong>${organizations.length}</strong></div>
        <div class="intel-stat"><span>Businesses</span><strong>${businesses.length}</strong></div>
      </div>
      <div class="intel-section">
        <h3>News Signals</h3>
        <ul class="intel-list">${newsHtml}</ul>
      </div>
      <div class="intel-section">
        <h3>Permit Signals</h3>
        <ul class="intel-list">${permitsHtml}</ul>
      </div>
      <div class="intel-section">
        <h3>Organizations To Watch</h3>
        <ul class="intel-list">${organizationsHtml}</ul>
      </div>
      <div class="intel-section">
        <h3>Public Contacts</h3>
        <ul class="intel-list">${contactsHtml}</ul>
      </div>
      <div class="intel-section">
        <h3>Business Leads</h3>
        <ul class="intel-list">${businessesHtml}</ul>
      </div>
    </section>
  `;
}

function renderRegions(snapshot) {
  regionSummaries.innerHTML = (snapshot.regions || []).map((region) => renderRegion(snapshot, region)).join("");
}

function renderEntityDetail(payload) {
  if (!payload?.organization) {
    entityDetail.innerHTML = `<div class="subtle">No organization selected yet.</div>`;
    return;
  }
  const org = payload.organization;
  entityDetail.innerHTML = `
    <div class="intel-grid">
      <article class="intel-card">
        <div class="status-label">${escapeHtml(org.region_id)}</div>
        <h3>${escapeHtml(org.name)}</h3>
        <p>${escapeHtml((org.categories || []).join(", ") || "Organization profile")}</p>
        <div class="subtle">${escapeHtml(org.address || org.website || org.phone || org.email || "")}</div>
      </article>
      <article class="intel-card">
        <div class="status-label">Businesses</div>
        <h3>${escapeHtml(String((payload.businesses || []).length))}</h3>
        <p>${escapeHtml((payload.businesses || []).slice(0, 3).map((item) => item.name).join(", ") || "No linked businesses")}</p>
      </article>
      <article class="intel-card">
        <div class="status-label">Contacts</div>
        <h3>${escapeHtml(String((payload.contacts || []).length))}</h3>
        <p>${escapeHtml((payload.contacts || []).slice(0, 3).map((item) => item.name).join(", ") || "No linked contacts")}</p>
      </article>
      <article class="intel-card">
        <div class="status-label">News</div>
        <h3>${escapeHtml(String((payload.news || []).length))}</h3>
        <p>${escapeHtml((payload.news || []).slice(0, 2).map((item) => item.title).join(" | ") || "No linked news signals")}</p>
      </article>
      <article class="intel-card">
        <div class="status-label">Permits</div>
        <h3>${escapeHtml(String((payload.permits || []).length))}</h3>
        <p>${escapeHtml((payload.permits || []).slice(0, 2).map((item) => item.address).join(" | ") || "No linked permit or development signals")}</p>
      </article>
    </div>
    <div class="intel-grid">
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Actions</div>
        <h3>Track this entity</h3>
        <p>Save this organization to the persistent watchlist and review its evidence trail below.</p>
        <div class="intel-tag-row">
          ${detailButton("organization", org.item_id, "Refresh detail")}
          <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="organization" data-collection-add-label="${escapeHtml(org.name)}" data-collection-add-region="${escapeHtml(org.region_id)}" data-collection-add-item-id="${escapeHtml(org.item_id)}" data-collection-add-url="${escapeHtml(org.website || "")}">Add to collection</button>
          <button class="ghost-button intel-save-button" type="button" data-save-kind="organization" data-save-label="${escapeHtml(org.name)}" data-save-region="${escapeHtml(org.region_id)}" data-save-item-id="${escapeHtml(org.item_id)}" data-save-url="${escapeHtml(org.website || "")}">Save to watchlist</button>
        </div>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Timeline</div>
        <h3>Evidence trail</h3>
        <div id="entity-timeline"><div class="subtle">Loading timeline…</div></div>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Changes</div>
        <h3>What changed</h3>
        <div id="entity-change-trail"><div class="subtle">Loading entity changes…</div></div>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Briefing</div>
        <h3>Operator memo</h3>
        <div id="entity-briefing"><div class="subtle">Loading briefing pack…</div></div>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Analyst Notes</div>
        <h3>Persistent annotation</h3>
        <p>Store your own note and tags on this organization so future briefings include human context.</p>
        <label class="vote-input-card">
          <span>Note</span>
          <textarea id="entity-annotation-note" class="intel-note-input" rows="4">${escapeHtml(payload.annotation?.note || "")}</textarea>
        </label>
        <label class="vote-input-card">
          <span>Tags (comma separated)</span>
          <input id="entity-annotation-tags" class="intel-search-input" type="text" value="${escapeHtml((payload.annotation?.tags || []).join(", "))}" />
        </label>
        <div class="intel-tag-row">
          <button class="ghost-button intel-annotation-save-button" type="button" data-annotation-target-kind="organization" data-annotation-target-id="${escapeHtml(org.item_id)}">Save note</button>
          <button class="ghost-button intel-annotation-delete-button" type="button" data-annotation-target-kind="organization" data-annotation-target-id="${escapeHtml(org.item_id)}">Clear note</button>
        </div>
      </article>
    </div>
  `;
}

function renderIntelItemDetail(payload) {
  if (!payload?.item) {
    entityDetail.innerHTML = `<div class="subtle">No item selected yet.</div>`;
    return;
  }
  const item = payload.item;
  const kind = payload.kind || "item";
  const title = item.title || item.name || item.address || "Detail item";
  const subtitle =
    item.source_name ||
    item.organization ||
    item.category ||
    item.permit_type ||
    item.title ||
    "";
  const primaryDetail =
    item.summary ||
    item.address_hint ||
    item.address ||
    item.email ||
    item.phone ||
    "";
  const relatedOrganizations = payload.related_organizations || [];
  const relatedContacts = payload.related_contacts || [];
  const relatedBusinesses = payload.related_businesses || [];
  const relatedNews = payload.related_news || [];
  const relatedPermits = payload.related_permits || [];
  entityDetail.innerHTML = `
    <div class="intel-grid">
      <article class="intel-card">
        <div class="status-label">${escapeHtml(item.region_id || kind)}</div>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(subtitle)}</p>
        <div class="subtle">${escapeHtml(primaryDetail)}</div>
        <div class="intel-tag-row">
          ${detailButton(kind, item.item_id, "Refresh detail")}
          <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(kind)}" data-collection-add-label="${escapeHtml(title)}" data-collection-add-region="${escapeHtml(item.region_id || "")}" data-collection-add-item-id="${escapeHtml(item.item_id || "")}" data-collection-add-url="${escapeHtml(item.website || item.source_url || "")}">Add to collection</button>
          <button class="ghost-button intel-save-button" type="button" data-save-kind="${escapeHtml(kind)}" data-save-label="${escapeHtml(title)}" data-save-region="${escapeHtml(item.region_id || "")}" data-save-item-id="${escapeHtml(item.item_id || "")}" data-save-url="${escapeHtml(item.website || item.source_url || "")}">Save to watchlist</button>
          ${(item.website || item.source_url) ? `<a class="intel-link" href="${escapeHtml(item.website || item.source_url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
        </div>
      </article>
      <article class="intel-card">
        <div class="status-label">Linked organizations</div>
        <h3>${escapeHtml(String(relatedOrganizations.length))}</h3>
        <ul class="intel-list">
          ${relatedOrganizations.length
            ? relatedOrganizations
                .slice(0, 6)
                .map(
                  (org) => `
                    <li class="intel-item">
                      <div class="intel-item-head">
                        <strong>${escapeHtml(org.name)}</strong>
                        <span class="intel-tag">${escapeHtml(org.organization_score || 0)}</span>
                      </div>
                      <div class="subtle">${escapeHtml(org.address || org.website || "")}</div>
                      ${detailButton("organization", org.item_id, "Open detail")}
                    </li>
                  `
                )
                .join("")
            : `<li class="intel-item"><div class="subtle">No linked organizations detected.</div></li>`}
        </ul>
      </article>
      <article class="intel-card">
        <div class="status-label">Related contacts</div>
        <h3>${escapeHtml(String(relatedContacts.length))}</h3>
        <ul class="intel-list">
          ${relatedContacts.length
            ? relatedContacts
                .slice(0, 6)
                .map(
                  (contact) => `
                    <li class="intel-item">
                      <div class="intel-item-head">
                        <strong>${escapeHtml(contact.name)}</strong>
                        <span class="intel-tag">${escapeHtml(contact.organization)}</span>
                      </div>
                      <div class="subtle">${escapeHtml(contact.email || contact.phone || contact.address || "")}</div>
                      ${detailButton("contact", contact.item_id, "Open detail")}
                    </li>
                  `
                )
                .join("")
            : `<li class="intel-item"><div class="subtle">No related contacts detected.</div></li>`}
        </ul>
      </article>
      <article class="intel-card">
        <div class="status-label">Related signals</div>
        <h3>${escapeHtml(String(relatedNews.length + relatedPermits.length + relatedBusinesses.length))}</h3>
        <ul class="intel-list">
          ${[
            ...relatedNews.slice(0, 3).map((row) => ({ kind: "news", title: row.title, subtitle: row.source_name || row.publication || "", item_id: row.item_id })),
            ...relatedPermits.slice(0, 3).map((row) => ({ kind: "permit", title: row.address, subtitle: row.permit_type || row.county || "", item_id: row.item_id })),
            ...relatedBusinesses.slice(0, 3).map((row) => ({ kind: "business", title: row.name, subtitle: row.category || row.address || "", item_id: row.item_id })),
          ]
            .slice(0, 8)
            .map(
              (row) => `
                <li class="intel-item">
                  <div class="intel-item-head">
                    <strong>${escapeHtml(row.title)}</strong>
                    <span class="intel-tag">${escapeHtml(row.kind)}</span>
                  </div>
                  <div class="subtle">${escapeHtml(row.subtitle)}</div>
                  ${detailButton(row.kind, row.item_id, "Open detail")}
                </li>
              `
            )
            .join("") || `<li class="intel-item"><div class="subtle">No related signals detected.</div></li>`}
        </ul>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Notes</div>
        <h3>Interpretation guidance</h3>
        <ul class="intel-list">
          ${(payload.notes || []).map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`).join("")}
          ${(item.notes || []).map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`).join("")}
        </ul>
      </article>
      <article class="intel-card intel-graph-summary">
        <div class="status-label">Changes</div>
        <h3>What changed</h3>
        <div id="entity-change-trail"><div class="subtle">Loading entity changes…</div></div>
      </article>
    </div>
  `;
}

function renderTimeline(payload) {
  const holder = document.querySelector("#entity-timeline");
  if (!holder) {
    return;
  }
  const items = payload?.timeline || [];
  if (items.length === 0) {
    holder.innerHTML = `<div class="subtle">No timeline events available.</div>`;
    return;
  }
  holder.innerHTML = `
    <ul class="intel-list">
      ${items
        .slice(0, 12)
        .map(
          (item) => `
            <li class="intel-item">
              <div class="intel-item-head">
                <strong>${escapeHtml(item.title)}</strong>
                <span class="intel-tag">${escapeHtml(item.kind)}</span>
              </div>
              <div class="intel-meta">${escapeHtml(relativeAge(item.occurred_at))} | score ${escapeHtml(item.score)}</div>
              <div class="subtle">${escapeHtml(item.subtitle || item.detail || "")}</div>
            </li>
          `
        )
        .join("")}
    </ul>
  `;
}

function renderBriefing(payload) {
  const holder = document.querySelector("#entity-briefing");
  if (!holder) {
    return;
  }
  if (!payload?.title) {
    holder.innerHTML = `<div class="subtle">No briefing available.</div>`;
    return;
  }
  holder.innerHTML = `
    <div class="subtle">${escapeHtml(payload.summary || "")}</div>
    <ul class="intel-list">
      ${(payload.reasons || []).map((reason) => `<li class="intel-item"><div class="subtle">${escapeHtml(reason)}</div></li>`).join("")}
    </ul>
    <div class="subtle"><strong>Contacts:</strong> ${escapeHtml((payload.public_contacts || []).map((item) => item.name).join(", ") || "None linked")}</div>
    <div class="subtle"><strong>Sources:</strong> ${escapeHtml((payload.sources || []).slice(0, 4).map((item) => item.name).join(", ") || "None linked")}</div>
    <div class="intel-tag-row">
      <a class="intel-link" href="/api/intel/briefing/${encodeURIComponent(payload.item_id)}/markdown" target="_blank" rel="noreferrer">Open markdown</a>
    </div>
    <details class="intel-markdown-block">
      <summary>Show markdown brief</summary>
      <pre class="intel-markdown-pre">${escapeHtml(payload.markdown || "")}</pre>
    </details>
  `;
}

function renderSearchResults(payload) {
  const results = payload?.results || [];
  if (results.length === 0) {
    searchResults.innerHTML = `<div class="subtle">No matches yet. Try a company name, address, official contact, or publication.</div>`;
    return;
  }
  searchResults.innerHTML = `
    <div class="intel-grid">
      ${results
        .map(
          (item) => `
            <article class="intel-card">
              <div class="intel-tag-row">
                <span class="intel-tag">${escapeHtml(item.kind)}</span>
                <span class="intel-tag">${escapeHtml(item.region_id)}</span>
                <span class="intel-tag">${escapeHtml(item.score)}</span>
              </div>
              <h3>${escapeHtml(item.title)}</h3>
              <p>${escapeHtml(item.subtitle || "")}</p>
              <div class="subtle">${escapeHtml(item.detail || "")}</div>
              ${detailButton(item.kind, item.item_id, "View detail")}
              <button class="ghost-button intel-collection-add-button" type="button" data-collection-add-kind="${escapeHtml(item.kind)}" data-collection-add-label="${escapeHtml(item.title)}" data-collection-add-region="${escapeHtml(item.region_id)}" data-collection-add-item-id="${escapeHtml(item.item_id || "")}" data-collection-add-url="${escapeHtml(item.url || "")}">Add to collection</button>
              <button class="ghost-button intel-save-button" type="button" data-save-kind="${escapeHtml(item.kind)}" data-save-label="${escapeHtml(item.title)}" data-save-region="${escapeHtml(item.region_id)}" data-save-item-id="${escapeHtml(item.item_id || "")}" data-save-url="${escapeHtml(item.url || "")}">Save</button>
              ${item.url ? `<a class="intel-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

async function runSearch(force = false) {
  const query = searchInput?.value?.trim();
  if (!query) {
    renderSearchResults({ results: [] });
    syncIntelUrl({ search: "" });
    return;
  }
  searchButton.disabled = true;
  try {
    const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
    const payload = await fetchJson(`/api/intel/search?q=${encodeURIComponent(query)}&force=${force ? "true" : "false"}${region}`);
    renderSearchResults(payload);
    syncIntelUrl({ search: query });
  } catch (error) {
    searchResults.innerHTML = `<div class="subtle">Search failed.</div>`;
  } finally {
    searchButton.disabled = false;
  }
}

async function loadOrganizationDetail(orgId) {
  if (!orgId) {
    return;
  }
  currentGraphFocusId = orgId;
  entityDetail.innerHTML = `<div class="subtle">Loading organization detail…</div>`;
  try {
    const [payload] = await Promise.all([
      fetchJson(`/api/intel/organizations/${encodeURIComponent(orgId)}`),
      loadGraph(false, orgId, false),
    ]);
    renderEntityDetail(payload);
    syncIntelUrl({ detailKind: "organization", detailId: orgId });
    await Promise.all([loadTimeline(orgId), loadBriefing(orgId), loadEntityChanges("organization", orgId)]);
  } catch (error) {
    entityDetail.innerHTML = `<div class="subtle">Failed to load organization detail.</div>`;
  }
}

async function loadIntelItemDetail(kind, itemId) {
  if (!kind || !itemId) {
    return;
  }
  entityDetail.innerHTML = `<div class="subtle">Loading item detail…</div>`;
  try {
    const payload = await fetchJson(`/api/intel/items/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`);
    renderIntelItemDetail(payload);
    syncIntelUrl({ detailKind: kind, detailId: itemId });
    await loadEntityChanges(kind, itemId);
  } catch (error) {
    entityDetail.innerHTML = `<div class="subtle">Failed to load item detail.</div>`;
  }
}

async function loadDetail(kind, itemId) {
  const resolvedKind = resolveDetailKind(kind);
  if (!resolvedKind || !itemId) {
    return;
  }
  if (resolvedKind === "organization") {
    await loadOrganizationDetail(itemId);
    return;
  }
  await loadIntelItemDetail(resolvedKind, itemId);
}

async function loadTimeline(itemId) {
  try {
    const payload = await fetchJson(`/api/intel/timeline/${encodeURIComponent(itemId)}`);
    renderTimeline(payload);
  } catch (error) {
    renderTimeline({ timeline: [] });
  }
}

async function loadBriefing(itemId) {
  try {
    const payload = await fetchJson(`/api/intel/briefing/${encodeURIComponent(itemId)}`);
    renderBriefing(payload);
  } catch (error) {
    renderBriefing(null);
  }
}

async function loadEntityChanges(kind, itemId) {
  try {
    const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
    const payload = await fetchJson(`/api/intel/entity-changes?days=14&kind=${encodeURIComponent(kind)}&item_id=${encodeURIComponent(itemId)}${region}`);
    renderEntityChanges(payload, "#entity-change-trail");
  } catch (error) {
    renderEntityChanges({ changes: [] }, "#entity-change-trail");
  }
}

async function loadRegionBriefings(force = false, regions = []) {
  const selected = regionFilter.value;
  const regionIds = selected ? [selected] : regions;
  if (!regionIds.length) {
    renderRegionBriefings({ packs: [] });
    return;
  }
  const packs = await Promise.all(
    regionIds.map((regionId) => fetchJson(`/api/intel/region-briefing/${encodeURIComponent(regionId)}?force=${force ? "true" : "false"}`))
  );
  renderRegionBriefings({ packs });
}

async function loadGraph(force = false, focusNodeId = null, skipRender = false) {
  const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
  const focus = focusNodeId ? `&focus_node_id=${encodeURIComponent(focusNodeId)}` : "";
  const payload = await fetchJson(`/api/intel/graph?force=${force ? "true" : "false"}${region}${focus}`);
  if (!skipRender) {
    renderGraph(payload);
  }
  return payload;
}

async function loadOpportunities(force = false) {
  const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
  const payload = await fetchJson(`/api/intel/opportunities?force=${force ? "true" : "false"}${region}`);
  renderOpportunities(payload);
}

async function loadSavedWatchlist(force = false) {
  const payload = await fetchJson(`/api/intel/watchlist-items?force=${force ? "true" : "false"}`);
  renderSavedWatchlist(payload);
}

async function loadCollections(force = false) {
  const payload = await fetchJson(`/api/intel/collections?force=${force ? "true" : "false"}`);
  renderCollections(payload);
}

async function loadBundles(force = false) {
  const payload = await fetchJson(`/api/intel/bundles?force=${force ? "true" : "false"}`);
  renderBundles(payload);
}

async function loadMonitorRules(force = false) {
  const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
  const payload = await fetchJson(`/api/intel/monitor-rules?force=${force ? "true" : "false"}${region}`);
  renderMonitorRules(payload);
}

async function saveWatchlistFromTarget(target) {
  const payload = {
    kind: target.getAttribute("data-save-kind") || "item",
    label: target.getAttribute("data-save-label") || "Saved item",
    region_id: target.getAttribute("data-save-region") || null,
    item_id: target.getAttribute("data-save-item-id") || null,
    source_url: target.getAttribute("data-save-url") || null,
  };
  await sendJson("/api/intel/watchlist-items", "POST", payload);
  await loadSavedWatchlist(false);
}

async function deleteWatchlistEntry(entryId) {
  await fetch(`/api/intel/watchlist-items/${encodeURIComponent(entryId)}`, { method: "DELETE" });
  await loadSavedWatchlist(false);
}

async function createCollection() {
  const title = collectionTitleInput?.value?.trim();
  if (!title) {
    window.alert("Collection title is required.");
    return;
  }
  const response = await sendJson("/api/intel/collections", "POST", {
    title,
    region_id: collectionRegionInput?.value || null,
    note: collectionNoteInput?.value?.trim() || null,
  });
  activeCollectionId = response.collection.collection_id;
  window.localStorage?.setItem("intelActiveCollectionId", activeCollectionId);
  if (collectionTitleInput) {
    collectionTitleInput.value = "";
  }
  if (collectionRegionInput) {
    collectionRegionInput.value = "";
  }
  if (collectionNoteInput) {
    collectionNoteInput.value = "";
  }
  await loadCollections(false);
}

async function saveCollectionItemFromTarget(target) {
  const collectionId = activeCollectionId || collectionActiveSelect?.value || "";
  if (!collectionId) {
    window.alert("Select an active collection first.");
    return;
  }
  await sendJson(`/api/intel/collections/${encodeURIComponent(collectionId)}/items`, "POST", {
    kind: target.getAttribute("data-collection-add-kind") || "item",
    label: target.getAttribute("data-collection-add-label") || "Saved item",
    region_id: target.getAttribute("data-collection-add-region") || null,
    item_id: target.getAttribute("data-collection-add-item-id") || null,
    source_url: target.getAttribute("data-collection-add-url") || null,
    note: target.getAttribute("data-collection-add-note") || null,
  });
  await loadCollections(false);
}

async function deleteCollection(collectionId) {
  await fetch(`/api/intel/collections/${encodeURIComponent(collectionId)}`, { method: "DELETE" });
  if (activeCollectionId === collectionId) {
    activeCollectionId = "";
    window.localStorage?.removeItem("intelActiveCollectionId");
  }
  await loadCollections(false);
}

async function deleteCollectionItem(collectionId, refId) {
  await fetch(`/api/intel/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(refId)}`, { method: "DELETE" });
  await loadCollections(false);
}

async function createBundle() {
  const title = bundleTitleInput?.value?.trim();
  if (!title) {
    window.alert("Bundle title is required.");
    return;
  }
  const response = await sendJson("/api/intel/bundles", "POST", {
    title,
    region_id: bundleRegionInput?.value || null,
    note: bundleNoteInput?.value?.trim() || null,
  });
  activeBundleId = response.bundle.bundle_id;
  window.localStorage?.setItem("intelActiveBundleId", activeBundleId);
  if (bundleTitleInput) {
    bundleTitleInput.value = "";
  }
  if (bundleRegionInput) {
    bundleRegionInput.value = "";
  }
  if (bundleNoteInput) {
    bundleNoteInput.value = "";
  }
  await loadBundles(false);
}

async function createMonitorRule() {
  const title = monitorTitleInput?.value?.trim();
  if (!title) {
    window.alert("Monitor rule title is required.");
    return;
  }
  const changeType = monitorChangeTypeInput?.value || "";
  const incidentTypes = ["repeated_empty", "recovery", "volume_surge", "stale_source"].includes(changeType) ? [changeType] : [];
  const changeTypes = changeType && !incidentTypes.length ? [changeType] : [];
  await sendJson("/api/intel/monitor-rules", "POST", {
    title,
    region_id: monitorRegionInput?.value || null,
    entity_kinds: monitorKindInput?.value ? [monitorKindInput.value] : [],
    change_types: changeTypes,
    incident_types: incidentTypes,
    keyword: monitorKeywordInput?.value?.trim() || null,
    min_score_delta: monitorScoreDeltaInput?.value ? Number(monitorScoreDeltaInput.value) : null,
    note: monitorNoteInput?.value?.trim() || null,
  });
  if (monitorTitleInput) monitorTitleInput.value = "";
  if (monitorRegionInput) monitorRegionInput.value = "";
  if (monitorKindInput) monitorKindInput.value = "";
  if (monitorChangeTypeInput) monitorChangeTypeInput.value = "";
  if (monitorKeywordInput) monitorKeywordInput.value = "";
  if (monitorScoreDeltaInput) monitorScoreDeltaInput.value = "";
  if (monitorNoteInput) monitorNoteInput.value = "";
  await loadMonitorRules(false);
}

async function deleteMonitorRule(ruleId) {
  await fetch(`/api/intel/monitor-rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
  await loadMonitorRules(false);
}

async function saveBundleCollectionFromTarget(target) {
  const bundleId = activeBundleId || bundleActiveSelect?.value || "";
  if (!bundleId) {
    window.alert("Select an active bundle first.");
    return;
  }
  await sendJson(`/api/intel/bundles/${encodeURIComponent(bundleId)}/collections`, "POST", {
    collection_id: target.getAttribute("data-bundle-add-collection-id"),
    label: target.getAttribute("data-bundle-add-label") || "Saved collection",
  });
  await loadBundles(false);
}

async function deleteBundle(bundleId) {
  await fetch(`/api/intel/bundles/${encodeURIComponent(bundleId)}`, { method: "DELETE" });
  if (activeBundleId === bundleId) {
    activeBundleId = "";
    window.localStorage?.removeItem("intelActiveBundleId");
  }
  await loadBundles(false);
}

async function deleteBundleRef(bundleId, refId) {
  await fetch(`/api/intel/bundles/${encodeURIComponent(bundleId)}/collections/${encodeURIComponent(refId)}`, { method: "DELETE" });
  await loadBundles(false);
}

async function saveAnnotation(targetKind, targetId) {
  const note = document.querySelector("#entity-annotation-note")?.value || "";
  const tags = (document.querySelector("#entity-annotation-tags")?.value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  await sendJson("/api/intel/annotations", "POST", {
    target_kind: targetKind,
    target_id: targetId,
    note,
    tags,
  });
  await loadOrganizationDetail(targetId);
  await loadSavedWatchlist(false);
}

async function deleteAnnotation(targetKind, targetId) {
  await fetch(`/api/intel/annotations/${encodeURIComponent(targetKind)}/${encodeURIComponent(targetId)}`, { method: "DELETE" });
  await loadOrganizationDetail(targetId);
  await loadSavedWatchlist(false);
}

async function loadSnapshot(force = false) {
  if (requestInFlight) {
    return;
  }
  requestInFlight = true;
  refreshButton.disabled = true;
  try {
    const region = regionFilter.value ? `&region=${encodeURIComponent(regionFilter.value)}` : "";
    const [commandSurfacePayloadLocal, snapshotPayload, watchlistPayload, trendPayload, sourceHistoryPayload, sourceIncidentPayload, regionChangePayload, entityChangePayload, alertPayload, graphPayload, opportunityPayload, savedWatchlistPayload, collectionsPayloadLocal, bundlesPayloadLocal, monitorRulesPayloadLocal, clientViewsPayload] = await Promise.all([
      fetchJson(commandSurfaceApiUrl(force)),
      fetchJson(`/api/intel/snapshot?force=${force ? "true" : "false"}${region}`),
      fetchJson(`/api/intel/watchlist?force=${force ? "true" : "false"}${region}`),
      fetchJson(`/api/intel/trends?days=7${region}`),
      fetchJson(`/api/intel/source-history?days=14${region}`),
      fetchJson(`/api/intel/source-incidents?days=14${region}`),
      fetchJson(`/api/intel/region-changes?days=14${region}`),
      fetchJson(`/api/intel/entity-changes?days=14${region}`),
      fetchJson(`/api/intel/alerts?force=${force ? "true" : "false"}${region}`),
      loadGraph(force, currentGraphFocusId, true),
      fetchJson(`/api/intel/opportunities?force=${force ? "true" : "false"}${region}`),
      fetchJson(`/api/intel/watchlist-items?force=${force ? "true" : "false"}`),
      fetchJson(`/api/intel/collections?force=${force ? "true" : "false"}`),
      fetchJson(`/api/intel/bundles?force=${force ? "true" : "false"}`),
      fetchJson(`/api/intel/monitor-rules?force=${force ? "true" : "false"}${region}`),
      fetchJson(`/api/client-views`),
    ]);
    intelSnapshot = snapshotPayload;
    snapshotAge.textContent = relativeAge(intelSnapshot.updated_at);
    renderCommandSurface(commandSurfacePayloadLocal);
    renderEthics(intelSnapshot);
    renderSources(intelSnapshot);
    renderBriefs(intelSnapshot);
    renderIntelligenceMap(intelSnapshot);
    renderWatchlist(watchlistPayload);
    renderOpportunities(opportunityPayload);
    renderSavedWatchlist(savedWatchlistPayload);
    renderCollections(collectionsPayloadLocal);
    renderBundles(bundlesPayloadLocal);
    renderMonitorRules(monitorRulesPayloadLocal);
    renderClientViews(clientViewsPayload);
    renderTrends(trendPayload);
    renderSourceHistory(sourceHistoryPayload);
    renderSourceIncidents(sourceIncidentPayload);
    renderRegionChanges(regionChangePayload);
    renderEntityChanges(entityChangePayload);
    renderAlerts(alertPayload);
    renderGraph(graphPayload);
    renderRegions(intelSnapshot);
    await loadRegionBriefings(force, (intelSnapshot.regions || []).map((item) => item.id));
  } catch (error) {
    snapshotAge.textContent = "Error";
    regionSummaries.innerHTML = `<section class="intel-column"><div class="subtle">Failed to load intelligence snapshot.</div></section>`;
    watchlistGrid.innerHTML = `<div class="subtle">Failed to load watchlist.</div>`;
    opportunityGrid.innerHTML = `<div class="subtle">Failed to load opportunities.</div>`;
    savedWatchlistGrid.innerHTML = `<div class="subtle">Failed to load saved watchlist.</div>`;
    if (collectionGrid) {
      collectionGrid.innerHTML = `<div class="subtle">Failed to load collections.</div>`;
    }
    if (bundleGrid) {
      bundleGrid.innerHTML = `<div class="subtle">Failed to load bundles.</div>`;
    }
    if (monitorGrid) {
      monitorGrid.innerHTML = `<div class="subtle">Failed to load monitor rules.</div>`;
    }
    if (clientViewGrid) {
      clientViewGrid.innerHTML = `<div class="subtle">Failed to load client feeds.</div>`;
    }
    if (commandMapCanvas) {
      commandMapCanvas.innerHTML = `<div class="subtle">Failed to load command surface.</div>`;
    }
    if (commandLayerList) {
      commandLayerList.innerHTML = `<div class="subtle">Layer controls unavailable.</div>`;
    }
    if (commandInspector) {
      commandInspector.innerHTML = `<div class="subtle">Command inspector unavailable.</div>`;
    }
    if (commandFeed) {
      commandFeed.innerHTML = `<div class="subtle">Command feed unavailable.</div>`;
    }
    if (intelMapCanvas) {
      intelMapCanvas.innerHTML = `<div class="subtle">Failed to load intelligence map.</div>`;
    }
    if (intelMapLegend) {
      intelMapLegend.innerHTML = `<div class="subtle">Map summary unavailable.</div>`;
    }
    if (intelMapTopPoints) {
      intelMapTopPoints.innerHTML = `<div class="subtle">Mapped shortlist unavailable.</div>`;
    }
    trendGrid.innerHTML = `<div class="subtle">Failed to load trend history.</div>`;
    sourceHistoryGrid.innerHTML = `<div class="subtle">Failed to load source history.</div>`;
    if (sourceIncidentGrid) {
      sourceIncidentGrid.innerHTML = `<div class="subtle">Failed to load source incidents.</div>`;
    }
    if (regionChangeGrid) {
      regionChangeGrid.innerHTML = `<div class="subtle">Failed to load region changes.</div>`;
    }
    if (entityChangeGrid) {
      entityChangeGrid.innerHTML = `<div class="subtle">Failed to load entity changes.</div>`;
    }
    alertGrid.innerHTML = `<div class="subtle">Failed to load alerts.</div>`;
    regionBriefingGrid.innerHTML = `<div class="subtle">Failed to load region briefings.</div>`;
    relationshipGraph.innerHTML = `<div class="subtle">Failed to load relationship graph.</div>`;
  } finally {
    requestInFlight = false;
    refreshButton.disabled = false;
  }
}

refreshButton?.addEventListener("click", () => loadSnapshot(true));
regionFilter?.addEventListener("change", () => {
  currentGraphFocusId = null;
  syncIntelUrl({ region: regionFilter.value || "", detailKind: "", detailId: "" });
  loadSnapshot(false);
});
collectionActiveSelect?.addEventListener("change", () => {
  activeCollectionId = collectionActiveSelect.value || "";
  if (activeCollectionId) {
    window.localStorage?.setItem("intelActiveCollectionId", activeCollectionId);
  } else {
    window.localStorage?.removeItem("intelActiveCollectionId");
  }
  renderCollections(collectionsPayload);
});
collectionCreateButton?.addEventListener("click", () => {
  createCollection().catch(() => {});
});
bundleActiveSelect?.addEventListener("change", () => {
  activeBundleId = bundleActiveSelect.value || "";
  if (activeBundleId) {
    window.localStorage?.setItem("intelActiveBundleId", activeBundleId);
  } else {
    window.localStorage?.removeItem("intelActiveBundleId");
  }
  renderBundles(bundlesPayload);
});
bundleCreateButton?.addEventListener("click", () => {
  createBundle().catch(() => {});
});
monitorCreateButton?.addEventListener("click", () => {
  createMonitorRule().catch(() => {});
});
searchButton?.addEventListener("click", () => runSearch(false));
searchInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runSearch(false);
  }
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-detail-kind][data-detail-id], [data-org-id]");
  if (!target) {
    return;
  }
  const detailKind = target.getAttribute("data-detail-kind") || "organization";
  const detailId = target.getAttribute("data-detail-id") || target.getAttribute("data-org-id");
  loadDetail(detailKind, detailId);
  return;
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-save-kind]");
  if (!target) {
    return;
  }
  saveWatchlistFromTarget(target).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-watchlist-delete-id]");
  if (!target) {
    return;
  }
  deleteWatchlistEntry(target.getAttribute("data-watchlist-delete-id")).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-collection-add-kind]");
  if (!target) {
    return;
  }
  saveCollectionItemFromTarget(target).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-collection-activate-id]");
  if (!target) {
    return;
  }
  activeCollectionId = target.getAttribute("data-collection-activate-id") || "";
  if (activeCollectionId) {
    window.localStorage?.setItem("intelActiveCollectionId", activeCollectionId);
  } else {
    window.localStorage?.removeItem("intelActiveCollectionId");
  }
  renderCollections(collectionsPayload);
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-collection-delete-id]");
  if (!target) {
    return;
  }
  deleteCollection(target.getAttribute("data-collection-delete-id")).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-collection-item-delete]");
  if (!target) {
    return;
  }
  deleteCollectionItem(
    target.getAttribute("data-collection-item-parent"),
    target.getAttribute("data-collection-item-delete")
  ).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-bundle-add-collection-id]");
  if (!target) {
    return;
  }
  saveBundleCollectionFromTarget(target).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-bundle-activate-id]");
  if (!target) {
    return;
  }
  activeBundleId = target.getAttribute("data-bundle-activate-id") || "";
  if (activeBundleId) {
    window.localStorage?.setItem("intelActiveBundleId", activeBundleId);
  } else {
    window.localStorage?.removeItem("intelActiveBundleId");
  }
  renderBundles(bundlesPayload);
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-bundle-delete-id]");
  if (!target) {
    return;
  }
  deleteBundle(target.getAttribute("data-bundle-delete-id")).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-bundle-ref-delete]");
  if (!target) {
    return;
  }
  deleteBundleRef(
    target.getAttribute("data-bundle-ref-parent"),
    target.getAttribute("data-bundle-ref-delete")
  ).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-monitor-delete-id]");
  if (!target) {
    return;
  }
  deleteMonitorRule(target.getAttribute("data-monitor-delete-id")).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-command-layer-id]");
  if (!target) {
    return;
  }
  const layerId = target.getAttribute("data-command-layer-id");
  if (!layerId) {
    return;
  }
  if (activeCommandLayers.has(layerId)) {
    activeCommandLayers.delete(layerId);
  } else {
    activeCommandLayers.add(layerId);
  }
  if (activeCommandLayers.size === 0) {
    activeCommandLayers.add(layerId);
  }
  syncIntelUrl({ layers: commandLayerQuery() });
  selectedCommandEntityId = "";
  loadCommandSurface(false).catch(() => {
    if (commandMapCanvas) {
      commandMapCanvas.innerHTML = `<div class="subtle">Failed to load command surface.</div>`;
    }
  });
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-command-entity-id]");
  if (!target) {
    return;
  }
  selectedCommandEntityId = target.getAttribute("data-command-entity-id") || "";
  renderCommandSurface(commandSurfacePayload);
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-annotation-target-id].intel-annotation-save-button");
  if (!target) {
    return;
  }
  saveAnnotation(
    target.getAttribute("data-annotation-target-kind"),
    target.getAttribute("data-annotation-target-id")
  ).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-annotation-target-id].intel-annotation-delete-button");
  if (!target) {
    return;
  }
  deleteAnnotation(
    target.getAttribute("data-annotation-target-kind"),
    target.getAttribute("data-annotation-target-id")
  ).catch(() => {});
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("#intel-clear-focus-button");
  if (!target) {
    return;
  }
  currentGraphFocusId = null;
  syncIntelUrl({ detailKind: "", detailId: "" });
  loadSnapshot(false);
});

async function applyInitialNavigation() {
  if (initialNavigationHandled) {
    return;
  }
  initialNavigationHandled = true;
  if (initialSearchParam) {
    await runSearch(false);
  }
  if (initialDetailKindParam && initialDetailIdParam) {
    await loadDetail(initialDetailKindParam, initialDetailIdParam);
  }
}

async function bootIntelPage() {
  await loadSnapshot(false);
  await applyInitialNavigation();
}

bootIntelPage().catch(() => {});
