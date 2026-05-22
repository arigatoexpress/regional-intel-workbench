let fieldLeafletMap = null;
let fieldLayerGroups = {};

function fieldEscapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fieldSeverityClass(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "critical" || normalized === "blocked" || normalized === "exclusion" || normalized === "offline") return "critical";
  if (normalized === "high" || normalized === "review" || normalized === "coordination") return "high";
  if (normalized === "medium" || normalized === "needs_live_check") return "medium";
  return "low";
}

function fieldPretty(value) {
  return String(value ?? "--").replaceAll("_", " ");
}

function fieldStatusToken(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
}

function fieldFormatAge(milliseconds) {
  if (!Number.isFinite(milliseconds)) return "unknown age";
  const minutes = Math.max(0, Math.round(milliseconds / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function fieldFreshnessInfo(properties = {}) {
  const raw = properties.last_update_utc || properties.timestamp || properties.retrieved_at;
  if (!raw) {
    return {
      label: "Freshness unknown",
      status: "unknown",
      className: "field-freshness-unknown",
      source: null,
    };
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return {
      label: "Freshness invalid",
      status: "unknown",
      className: "field-freshness-unknown",
      source: raw,
    };
  }
  const ageMs = Date.now() - parsed.getTime();
  if (ageMs > 6 * 60 * 60 * 1000) {
    return {
      label: `STALE DATA - ${fieldFormatAge(ageMs)}`,
      status: "stale",
      className: "field-freshness-stale",
      source: raw,
    };
  }
  if (ageMs > 60 * 60 * 1000) {
    return {
      label: `Review freshness - ${fieldFormatAge(ageMs)}`,
      status: "review",
      className: "field-freshness-review",
      source: raw,
    };
  }
  return {
    label: `Fresh - ${fieldFormatAge(ageMs)}`,
    status: "fresh",
    className: "field-freshness-fresh",
    source: raw,
  };
}

function fieldMetricStatus(value) {
  return fieldSeverityClass(value || "low");
}

function renderMetrics(payload) {
  const target = document.querySelector("#field-metrics");
  if (!target) return;
  target.innerHTML = (payload.metrics || [])
    .map(
      (metric) => `
        <article class="field-metric field-state-${fieldMetricStatus(metric.status)}">
          <div class="status-label">${fieldEscapeHtml(metric.label)}</div>
          <strong>${fieldEscapeHtml(metric.value)}</strong>
          <p>${fieldEscapeHtml(metric.detail)}</p>
        </article>
      `
    )
    .join("");
}

function renderLayers(payload) {
  const target = document.querySelector("#field-layer-list");
  if (!target) return;
  target.innerHTML = (payload.layers || [])
    .map(
      (layer) => `
        <button class="field-layer-button is-active" type="button" data-layer="${fieldEscapeHtml(layer.layer_id)}">
          <span>${fieldEscapeHtml(layer.label)}</span>
          <strong>${fieldEscapeHtml(layer.item_count)}</strong>
        </button>
      `
    )
    .join("");
}

function renderWeather(payload) {
  const target = document.querySelector("#field-weather-gates");
  if (!target) return;
  target.innerHTML = (payload.weather_gates || [])
    .map(
      (gate) => `
        <article class="field-weather-card field-state-${fieldSeverityClass(gate.status)}">
          <div class="status-label">${fieldEscapeHtml(gate.label)}</div>
          <strong>${fieldEscapeHtml(fieldPretty(gate.status))}</strong>
          <p>${fieldEscapeHtml(gate.threshold)}</p>
        </article>
      `
    )
    .join("");
}

function renderReferencePanel(payload) {
  const target = document.querySelector("#field-reference-panel");
  if (!target) return;
  target.innerHTML = (payload.external_references || [])
    .map(
      (item) => `
        <article class="field-reference-card field-state-${fieldSeverityClass(item.status)}">
          <div class="status-label">${fieldEscapeHtml(fieldPretty(item.kind))}</div>
          <strong>${fieldEscapeHtml(item.label)}</strong>
          <p>${fieldEscapeHtml(item.summary)}</p>
          ${item.source_url ? `<a class="intel-link" href="${fieldEscapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
        </article>
      `
    )
    .join("");
}

function buildFactGrid(items) {
  return `
    <div class="field-fact-grid">
      ${items
        .map(
          ([label, value]) => `
            <div>
              <span>${fieldEscapeHtml(label)}</span>
              <strong>${fieldEscapeHtml(value ?? "--")}</strong>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function fieldFeatureProperties(item, kind) {
  if (!item) return {};
  if (kind === "signal") {
    return {
      entity_type: "wildfire_signal",
      signal_id: item.signal_id,
      title: item.title,
      severity: item.severity,
      risk_score: item.risk_score,
      confidence: item.confidence,
      zone_id: item.zone_id,
      signal_type: item.signal_type,
      recommended_action: item.recommended_action,
      safe_action_label: item.safe_action_label,
      timestamp: item.timestamp,
      last_update_utc: item.timestamp,
      source_id: item.source_id,
      source_url: item.source_url,
    };
  }
  if (kind === "asset") {
    return {
      entity_type: "uas_asset",
      asset_id: item.asset_id,
      label: item.label,
      layer: item.layer,
      status: item.status,
      comms_link: item.comms_link,
      last_update_utc: item.last_update_utc,
      lat: item.lat,
      lon: item.lon,
      source_id: item.source_id,
      ...item.readiness,
    };
  }
  if (kind === "landmark") {
    return {
      entity_type: "aor_landmark",
      landmark_id: item.landmark_id,
      label: item.label,
      kind: item.kind,
      elevation_m: item.elevation_m,
      lat: item.lat,
      lon: item.lon,
      source_id: item.source_id,
    };
  }
  return {
    entity_type: "zone_overlay",
    zone_id: item.zone_id,
    label: item.label,
    zone_type: item.zone_type,
    fuel_load_class: item.fuel_load_class,
    primary_risk: item.primary_risk,
    phase: item.phase,
    regulatory_basis: item.regulatory_basis,
    source_id: item.source_id,
  };
}

function buildPropertiesPanel(properties) {
  const entries = Object.entries(properties).filter(([, value]) => {
    return value !== null && value !== undefined && value !== "";
  });
  if (!entries.length) {
    return `<div class="field-property-empty">No JSON properties available for this feature.</div>`;
  }
  return `
    <div class="field-property-panel">
      <div class="status-label">Feature Properties</div>
      <dl>
        ${entries
          .map(
            ([key, value]) => `
              <div>
                <dt>${fieldEscapeHtml(fieldPretty(key))}</dt>
                <dd>${fieldEscapeHtml(typeof value === "object" ? JSON.stringify(value) : value)}</dd>
              </div>
            `
          )
          .join("")}
      </dl>
    </div>
  `;
}

function buildFreshnessBadge(properties) {
  const freshness = fieldFreshnessInfo(properties);
  return `
    <div class="field-freshness ${freshness.className}">
      <strong>${fieldEscapeHtml(freshness.label)}</strong>
      ${freshness.source ? `<span>${fieldEscapeHtml(freshness.source)}</span>` : "<span>No last_update_utc supplied</span>"}
    </div>
  `;
}

function buildInspectorHtml(item, kind) {
  if (!item) {
    return `
      <div class="status-label">Inspector</div>
      <h2>No selection</h2>
      <p class="subtle">Select a zone, signal, asset, or landmark on the map to inspect provenance and readiness state.</p>
    `;
  }
  const properties = fieldFeatureProperties(item, kind);
  const freshnessHtml = buildFreshnessBadge(properties);
  const propertiesHtml = buildPropertiesPanel(properties);
  if (kind === "signal") {
    return `
      <div class="status-label">Wildfire signal</div>
      <h2>${fieldEscapeHtml(item.title)}</h2>
      <p>${fieldEscapeHtml(item.summary)}</p>
      ${freshnessHtml}
      ${buildFactGrid([
        ["Severity", item.severity],
        ["Risk", item.risk_score],
        ["Confidence", item.confidence],
        ["Zone", item.zone_id],
      ])}
      <div class="field-safe-action">${fieldEscapeHtml(item.safe_action_label)}</div>
      ${propertiesHtml}
      <ul class="intel-list">${(item.notes || []).map((note) => `<li class="intel-item"><div class="subtle">${fieldEscapeHtml(note)}</div></li>`).join("")}</ul>
    `;
  }
  if (kind === "asset") {
    return `
      <div class="status-label">UAS readiness asset</div>
      <h2>${fieldEscapeHtml(item.label)}</h2>
      <p>${fieldEscapeHtml(item.summary)}</p>
      ${freshnessHtml}
      ${buildFactGrid([
        ["Status", fieldPretty(item.status)],
        ["Comms", item.comms_link || "--"],
        ["Lat", Number.isFinite(item.lat) ? Number(item.lat).toFixed(4) : "--"],
        ["Lon", Number.isFinite(item.lon) ? Number(item.lon).toFixed(4) : "--"],
      ])}
      <div class="field-safe-action">${fieldEscapeHtml(fieldPretty(item.status))}</div>
      ${propertiesHtml}
      <ul class="intel-list">
        ${Object.entries(item.readiness || {}).map(([key, value]) => `<li class="intel-item"><strong>${fieldEscapeHtml(fieldPretty(key))}</strong><div class="subtle">${fieldEscapeHtml(value)}</div></li>`).join("")}
      </ul>
    `;
  }
  if (kind === "landmark") {
    return `
      <div class="status-label">AOR landmark</div>
      <h2>${fieldEscapeHtml(item.label)}</h2>
      <p>${fieldEscapeHtml(item.summary)}</p>
      ${freshnessHtml}
      ${buildFactGrid([
        ["Type", fieldPretty(item.kind)],
        ["Elevation", item.elevation_m === null || item.elevation_m === undefined ? "--" : `${item.elevation_m} m`],
        ["Lat", Number(item.lat).toFixed(4)],
        ["Lon", Number(item.lon).toFixed(4)],
      ])}
      ${propertiesHtml}
      <ul class="intel-list">${(item.notes || []).slice(0, 2).map((note) => `<li class="intel-item"><div class="subtle">${fieldEscapeHtml(note)}</div></li>`).join("")}</ul>
    `;
  }
  return `
    <div class="status-label">Zone overlay</div>
    <h2>${fieldEscapeHtml(item.label)}</h2>
    <p>${fieldEscapeHtml(item.primary_risk || item.regulatory_basis || "Planning zone")}</p>
    ${freshnessHtml}
    ${buildFactGrid([
      ["Type", fieldPretty(item.zone_type)],
      ["Fuel", item.fuel_load_class || "--"],
      ["Phase", item.phase ?? "--"],
      ["Basis", item.regulatory_basis || "--"],
    ])}
    ${propertiesHtml}
    <ul class="intel-list">${(item.notes || []).slice(0, 2).map((note) => `<li class="intel-item"><div class="subtle">${fieldEscapeHtml(note)}</div></li>`).join("")}</ul>
  `;
}

function setInspector(item, kind) {
  const target = document.querySelector("#inspector-panel");
  if (!target) return;
  target.innerHTML = buildInspectorHtml(item, kind);
}

function zoneStyle(zone) {
  const palette = {
    exclusion: { color: "#ff6b6b", fillColor: "#ff6b6b", dashArray: "8 7", fillOpacity: 0.16 },
    coordination: { color: "#ffc857", fillColor: "#ffc857", dashArray: "4 6", fillOpacity: 0.12 },
    mission_zone: { color: "#54f2c3", fillColor: "#54f2c3", dashArray: null, fillOpacity: 0.12 },
  };
  const picked = palette[zone.zone_type] || palette.mission_zone;
  return {
    color: picked.color,
    fillColor: picked.fillColor,
    fillOpacity: picked.fillOpacity,
    weight: zone.zone_type === "exclusion" ? 3 : 2,
    opacity: 0.9,
    dashArray: picked.dashArray,
  };
}

function signalStyle(severity) {
  const palette = {
    critical: { color: "#ff6b6b", radius: 11 },
    high: { color: "#ffc857", radius: 10 },
    medium: { color: "#8ad7ff", radius: 8 },
    low: { color: "#54f2c3", radius: 7 },
  };
  return palette[fieldSeverityClass(severity)] || palette.low;
}

function landmarkColor(kind) {
  const colors = {
    airspace: "#ffc857",
    drainage: "#54f2c3",
    exclusion: "#ff6b6b",
    public_safety: "#8ad7ff",
    town: "#ffffff",
  };
  return colors[kind] || "#8ad7ff";
}

function buildDayNightPolygon() {
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), 0, 0));
  const dayOfYear = Math.floor((now - start) / 86400000);
  const declination = -23.44 * Math.cos((2 * Math.PI * (dayOfYear + 10)) / 365);
  const declinationRad = (declination * Math.PI) / 180;
  const utcHours = now.getUTCHours() + now.getUTCMinutes() / 60;
  const subsolarLon = (12 - utcHours) * 15;
  const line = [];
  for (let lon = -180; lon <= 180; lon += 4) {
    const lonRad = ((lon - subsolarLon) * Math.PI) / 180;
    const lat = (Math.atan(-Math.cos(lonRad) / Math.tan(declinationRad)) * 180) / Math.PI;
    line.push([lat, lon]);
  }
  const darkPole = declination >= 0 ? -90 : 90;
  return [...line, [darkPole, 180], [darkPole, -180]];
}

function addMapLegend(map) {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const node = L.DomUtil.create("div", "field-map-legend");
    node.innerHTML = `
      <div class="status-label">Legend</div>
      <span><i style="background:#54f2c3"></i> Mission zone</span>
      <span><i style="background:#ffc857"></i> Coordination / high</span>
      <span><i style="background:#ff6b6b"></i> Exclusion / critical</span>
      <span><i style="background:#8ad7ff"></i> Asset / public marker</span>
    `;
    return node;
  };
  legend.addTo(map);
}

function makeDivIcon(label, className) {
  return L.divIcon({
    className: `field-div-icon ${className}`,
    html: `<span>${fieldEscapeHtml(label)}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function renderMap(payload) {
  const target = document.querySelector("#field-map");
  if (!target) return;
  target.innerHTML = `
    <div id="field-leaflet-map" class="field-leaflet-map"></div>
    <div id="field-map-readout" class="field-map-readout">Hover map for coordinates</div>
  `;

  if (!window.L) {
    target.innerHTML = `
      <div class="field-error">
        Leaflet did not load, so the real map tiles are unavailable. Check network access to the CDN and reload.
      </div>
    `;
    setInspector((payload.signals || [])[0], "signal");
    return;
  }

  if (fieldLeafletMap) {
    fieldLeafletMap.remove();
  }

  fieldLayerGroups = {};
  const map = L.map("field-leaflet-map", {
    zoomControl: true,
    preferCanvas: true,
    worldCopyJump: false,
  });
  fieldLeafletMap = map;

  const cartoDark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  });
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });
  const imagery = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19,
    attribution: "Tiles &copy; Esri",
  });
  cartoDark.addTo(map);
  L.control.layers({ "Dark map": cartoDark, Streets: osm, Satellite: imagery }, null, { collapsed: true }).addTo(map);

  const fitBounds = L.latLngBounds([]);
  const extendFit = (lat, lon) => {
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      fitBounds.extend([lat, lon]);
    }
  };

  fieldLayerGroups["wildfire-zones"] = L.layerGroup().addTo(map);
  fieldLayerGroups["wildfire-signals"] = L.layerGroup().addTo(map);
  fieldLayerGroups["uas-readiness"] = L.layerGroup().addTo(map);
  fieldLayerGroups["aor-landmarks"] = L.layerGroup().addTo(map);
  fieldLayerGroups["day-night"] = L.layerGroup().addTo(map);

  for (const zone of payload.zones || []) {
    if (!zone.geometry || !zone.geometry.type) continue;
    const layer = L.geoJSON(zone.geometry, {
      style: () => zoneStyle(zone),
      onEachFeature: (_feature, featureLayer) => {
        featureLayer.bindTooltip(zone.label, {
          sticky: true,
          className: "field-map-tooltip",
        });
        featureLayer.on("click", () => setInspector(zone, "zone"));
      },
    });
    layer.addTo(fieldLayerGroups["wildfire-zones"]);
    if (layer.getBounds().isValid()) {
      fitBounds.extend(layer.getBounds());
    }
  }

  for (const signal of payload.signals || []) {
    const style = signalStyle(signal.severity);
    extendFit(signal.lat, signal.lon);
    L.circleMarker([signal.lat, signal.lon], {
      radius: style.radius,
      color: style.color,
      fillColor: style.color,
      fillOpacity: 0.92,
      opacity: 0.96,
      weight: 2,
      className: "field-leaflet-signal",
    })
      .bindTooltip(`${signal.title} | risk ${signal.risk_score}`, {
        className: "field-map-tooltip",
      })
      .on("click", () => setInspector(signal, "signal"))
      .addTo(fieldLayerGroups["wildfire-signals"]);
  }

  for (const asset of payload.assets || []) {
    if (!Number.isFinite(asset.lat) || !Number.isFinite(asset.lon)) continue;
    extendFit(asset.lat, asset.lon);
    const initials = asset.label
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
    L.marker([asset.lat, asset.lon], {
      icon: makeDivIcon(
        initials,
        `field-div-icon-asset field-state-${fieldSeverityClass(asset.status)} field-status-${fieldStatusToken(asset.status)}`
      ),
    })
      .bindTooltip(asset.label, { className: "field-map-tooltip" })
      .on("click", () => setInspector(asset, "asset"))
      .addTo(fieldLayerGroups["uas-readiness"]);
  }

  for (const landmark of payload.landmarks || []) {
    extendFit(landmark.lat, landmark.lon);
    const color = landmarkColor(landmark.kind);
    L.circleMarker([landmark.lat, landmark.lon], {
      radius: landmark.kind === "town" ? 6 : 5,
      color,
      fillColor: color,
      fillOpacity: 0.88,
      opacity: 0.9,
      weight: 2,
    })
      .bindTooltip(landmark.label, {
        permanent: true,
        direction: "top",
        offset: [0, -8],
        className: "field-map-label",
      })
      .on("click", () => setInspector(landmark, "landmark"))
      .addTo(fieldLayerGroups["aor-landmarks"]);
  }

  L.polygon(buildDayNightPolygon(), {
    color: "#0b1020",
    fillColor: "#050914",
    fillOpacity: 0.14,
    weight: 0,
    interactive: false,
  }).addTo(fieldLayerGroups["day-night"]);

  if (fitBounds.isValid()) {
    map.fitBounds(fitBounds.pad(0.12), { maxZoom: 11 });
  } else {
    map.setView([38.84, -106.98], 10);
  }

  addMapLegend(map);
  const readout = document.querySelector("#field-map-readout");
  map.on("mousemove", (event) => {
    if (readout) {
      readout.textContent = `${event.latlng.lat.toFixed(4)}, ${event.latlng.lng.toFixed(4)} | zoom ${map.getZoom().toFixed(1)}`;
    }
  });

  wireLayerButtons();
  const firstSignal = (payload.signals || []).find((item) => item.severity === "critical") || (payload.signals || [])[0];
  setInspector(firstSignal, firstSignal ? "signal" : "");
}

function wireLayerButtons() {
  document.querySelectorAll(".field-layer-button").forEach((button) => {
    const layerId = button.dataset.layer;
    const group = fieldLayerGroups[layerId];
    const isToggleable = Boolean(group);
    button.classList.toggle("is-muted", !isToggleable);
    button.addEventListener("click", () => {
      if (!group || !fieldLeafletMap) return;
      const enabled = fieldLeafletMap.hasLayer(group);
      if (enabled) {
        fieldLeafletMap.removeLayer(group);
      } else {
        group.addTo(fieldLeafletMap);
      }
      button.classList.toggle("is-active", !enabled);
    });
  });
}

function renderActions(payload) {
  const target = document.querySelector("#field-action-queue");
  if (!target) return;
  target.innerHTML = (payload.action_queue || [])
    .map(
      (item) => `
        <article class="field-action field-state-${fieldSeverityClass(item.status)}">
          <div class="status-label">${fieldEscapeHtml(fieldPretty(item.status))}</div>
          <h3>${fieldEscapeHtml(item.label)}</h3>
          <p>${fieldEscapeHtml(item.summary)}</p>
        </article>
      `
    )
    .join("");
}

function renderProvenance(payload) {
  const target = document.querySelector("#field-provenance");
  if (!target) return;
  target.innerHTML = `
    <div class="status-label">Provenance</div>
    <h2>${fieldEscapeHtml(payload.provenance_summary?.rights_posture || "derived analysis")}</h2>
    <div class="field-source-list">
      ${(payload.sources || [])
        .map(
          (source) => `
            <article class="field-source">
              <strong>${fieldEscapeHtml(source.title)}</strong>
              <p>${fieldEscapeHtml(source.output_policy)}</p>
              ${source.source_url ? `<a class="intel-link" href="${fieldEscapeHtml(source.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
              <div class="subtle mono">${fieldEscapeHtml(source.source_id)} | ${fieldEscapeHtml(source.retrieval_mode)}</div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function renderRegionalContext(payload) {
  const target = document.querySelector("#field-regional-context");
  if (!target) return;
  target.innerHTML = (payload.regional_context || [])
    .map(
      (item) => `
        <article class="intel-card">
          <div class="intel-tag-row">
            <span class="intel-tag">${fieldEscapeHtml(item.kind)}</span>
            ${item.score === null || item.score === undefined ? "" : `<span class="intel-tag">${fieldEscapeHtml(item.score)} score</span>`}
          </div>
          <h3>${fieldEscapeHtml(item.title)}</h3>
          <p>${fieldEscapeHtml(item.summary)}</p>
          ${item.source_url ? `<a class="intel-link" href="${fieldEscapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
        </article>
      `
    )
    .join("");
}

async function loadFieldOps() {
  const response = await fetch("/api/intel/field-ops");
  if (!response.ok) {
    throw new Error(`Field ops request failed (${response.status})`);
  }
  const payload = await response.json();
  document.querySelector("#field-posture").textContent = fieldPretty(payload.posture.mode);
  document.querySelector("#field-posture-copy").textContent = payload.posture.notes?.[0] || "Read-only planning.";
  renderMetrics(payload);
  renderLayers(payload);
  renderWeather(payload);
  renderReferencePanel(payload);
  renderMap(payload);
  renderActions(payload);
  renderProvenance(payload);
  renderRegionalContext(payload);
}

loadFieldOps().catch((error) => {
  const target = document.querySelector("#field-map");
  if (target) {
    target.innerHTML = `<div class="field-error">Unable to load field ops payload: ${fieldEscapeHtml(error.message)}</div>`;
  }
});
