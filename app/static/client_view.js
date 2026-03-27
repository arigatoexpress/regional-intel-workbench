const shell = document.querySelector(".client-view-shell");
const viewId = shell?.dataset?.viewId || "";
const regionId = shell?.dataset?.regionId || "";
const refreshButton = document.querySelector("#client-view-refresh-button");
const statusNode = document.querySelector("#client-view-status");
const metricsNode = document.querySelector("#client-view-metrics");
const playbookNode = document.querySelector("#client-view-playbook");
const notesNode = document.querySelector("#client-view-notes");
const sectionsNode = document.querySelector("#client-view-sections");
const clientMapCanvas = document.querySelector("#client-view-map-canvas");
const clientMapLegend = document.querySelector("#client-view-map-legend");
const clientMapTopPoints = document.querySelector("#client-view-map-top-points");

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

function formatStatusTime(isoString) {
  if (!isoString) {
    return "Ready";
  }
  return `Ready • snapshot ${relativeAge(isoString)}`;
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

function renderMetrics(metrics) {
  if (!metricsNode) {
    return;
  }
  if (!metrics?.length) {
    metricsNode.innerHTML = `<div class="subtle">No metrics available yet.</div>`;
    return;
  }
  metricsNode.innerHTML = metrics
    .map(
      (item) => `
        <article class="intel-card client-metric-card">
          <div class="status-label">${escapeHtml(item.label)}</div>
          <div class="client-metric-value">${escapeHtml(item.value)}</div>
          <div class="subtle">${escapeHtml(item.detail || "")}</div>
        </article>
      `
    )
    .join("");
}

function renderPlaybook(playbook) {
  if (!playbookNode) {
    return;
  }
  if (!playbook?.length) {
    playbookNode.innerHTML = `<div class="subtle">No playbook guidance available.</div>`;
    return;
  }
  playbookNode.innerHTML = playbook
    .map(
      (item, index) => `
        <article class="intel-card client-playbook-card">
          <div class="status-label">Step ${index + 1}</div>
          <h3>${escapeHtml(item)}</h3>
          <p class="subtle">This step is tuned to the workflow this client view is optimizing for.</p>
        </article>
      `
    )
    .join("");
}

function renderNotes(notes) {
  if (!notesNode) {
    return;
  }
  notesNode.innerHTML = (notes || [])
    .map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`)
    .join("");
}

function renderItemCard(item) {
  const tagRow = (item.tags || []).slice(0, 5).map((tag) => `<span class="intel-tag">${escapeHtml(tag)}</span>`).join("");
  const notes = (item.notes || []).slice(0, 3).map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`).join("");
  const actions = `
    <div class="client-feed-actions">
      ${item.intel_url ? `<a class="ghost-button" href="${escapeHtml(item.intel_url)}">Open in Intel</a>` : ""}
      ${item.source_url ? `<a class="intel-link" href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
    </div>
  `;
  return `
    <article class="intel-card client-feed-card">
      <div class="intel-tag-row">
        <span class="intel-tag">${escapeHtml(item.item_kind)}</span>
        ${item.region_id ? `<span class="intel-tag">${escapeHtml(item.region_id)}</span>` : ""}
        <span class="intel-tag">score ${escapeHtml(item.score)}</span>
        ${tagRow}
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      ${item.subtitle ? `<p>${escapeHtml(item.subtitle)}</p>` : ""}
      <div class="subtle">${escapeHtml(item.summary || "")}</div>
      ${item.why_it_matters ? `<div class="client-feed-block"><strong>Why it matters</strong><p class="subtle">${escapeHtml(item.why_it_matters)}</p></div>` : ""}
      ${item.recommended_action ? `<div class="client-feed-block"><strong>Recommended action</strong><p class="subtle">${escapeHtml(item.recommended_action)}</p></div>` : ""}
      ${notes ? `<ul class="intel-list client-feed-notes">${notes}</ul>` : ""}
      ${actions}
    </article>
  `;
}

function renderSections(sections) {
  if (!sectionsNode) {
    return;
  }
  if (!sections?.length) {
    sectionsNode.innerHTML = `<section class="protocols-panel intel-panel"><div class="subtle">No feed sections available yet.</div></section>`;
    return;
  }
  sectionsNode.innerHTML = sections
    .map(
      (section) => `
        <section class="protocols-panel intel-panel client-section-panel" id="section-${escapeHtml(section.section_id)}">
          <div class="panel-header">
            <h2>${escapeHtml(section.title)}</h2>
            <p>${escapeHtml(section.summary || "")}</p>
          </div>
          ${section.notes?.length ? `<ul class="intel-list client-section-notes">${section.notes.map((note) => `<li class="intel-item"><div class="subtle">${escapeHtml(note)}</div></li>`).join("")}</ul>` : ""}
          <div class="intel-grid client-feed-grid">
            ${(section.items || []).map((item) => renderItemCard(item)).join("") || `<div class="subtle">No items in this section yet.</div>`}
          </div>
        </section>
      `
    )
    .join("");
}

function renderClientMap(snapshot) {
  if (!clientMapCanvas || !window.IntelMap) {
    return;
  }
  const data = window.IntelMap.buildPointsFromSnapshot(snapshot, regionId);
  window.IntelMap.renderMap({
    canvas: clientMapCanvas,
    legend: clientMapLegend,
    topList: clientMapTopPoints,
    data,
    emptyText: "No mapped Austin business intelligence points are available yet.",
  });
}

async function loadClientView(force = false) {
  if (!viewId) {
    if (statusNode) {
      statusNode.textContent = "Missing view id";
    }
    return;
  }
  if (refreshButton) {
    refreshButton.disabled = true;
  }
  if (statusNode) {
    statusNode.textContent = "Loading…";
  }
  try {
    const [payload, snapshot] = await Promise.all([
      fetchJson(`/api/client-views/${encodeURIComponent(viewId)}?force=${force ? "true" : "false"}`),
      fetchJson(`/api/intel/snapshot?force=${force ? "true" : "false"}${regionId ? `&region=${encodeURIComponent(regionId)}` : ""}`),
    ]);
    renderMetrics(payload.hero_metrics || []);
    renderPlaybook(payload.playbook || []);
    renderNotes(payload.notes || []);
    renderSections(payload.sections || []);
    renderClientMap(snapshot);
    if (statusNode) {
      statusNode.textContent = formatStatusTime(snapshot.generated_at || payload.generated_at || "");
    }
  } catch (error) {
    if (statusNode) {
      statusNode.textContent = "Load failed";
    }
    if (sectionsNode) {
      sectionsNode.innerHTML = `<section class="protocols-panel intel-panel"><div class="subtle">Failed to load this client feed.</div></section>`;
    }
    if (clientMapCanvas) {
      clientMapCanvas.innerHTML = `<div class="subtle">Failed to load intelligence map.</div>`;
    }
  } finally {
    if (refreshButton) {
      refreshButton.disabled = false;
    }
  }
}

refreshButton?.addEventListener("click", () => {
  loadClientView(true).catch(() => {});
});

loadClientView(false);
