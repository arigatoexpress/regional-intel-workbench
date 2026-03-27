function intelMapEscapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function intelMapNormalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function intelDetailUrl(regionId, kind, itemId) {
  const params = new URLSearchParams();
  if (regionId) {
    params.set("region", regionId);
  }
  if (kind && itemId) {
    params.set("detail_kind", kind);
    params.set("detail_id", itemId);
  }
  return `/intel?${params.toString()}`;
}

function buildPermitCountByOrg(snapshot, regionId) {
  const counts = new Map();
  const orgs = (snapshot.organizations || []).filter((item) => item.region_id === regionId);
  const permits = (snapshot.permits || []).filter((item) => item.region_id === regionId);
  for (const permit of permits) {
    const noteText = (permit.notes || []).join(" ").toLowerCase();
    for (const org of orgs) {
      const name = String(org.name || "").toLowerCase();
      if (name && noteText.includes(name)) {
        counts.set(intelMapNormalize(org.name), (counts.get(intelMapNormalize(org.name)) || 0) + 1);
      }
    }
  }
  return counts;
}

function buildPointsFromSnapshot(snapshot, regionId) {
  const region = (snapshot.regions || []).find((item) => item.id === regionId) || (snapshot.regions || [])[0] || null;
  if (!region) {
    return {
      region: null,
      points: [],
      counts: { total: 0, orgLinked: 0, newsLinked: 0, contactLinked: 0, permitLinked: 0 },
      notes: ["No region metadata was available for map rendering."],
    };
  }

  const businesses = (snapshot.businesses || []).filter(
    (item) => item.region_id === region.id && Number.isFinite(item.lat) && Number.isFinite(item.lon)
  );
  const organizations = (snapshot.organizations || []).filter((item) => item.region_id === region.id);
  const contacts = (snapshot.contacts || []).filter((item) => item.region_id === region.id);
  const news = (snapshot.news || []).filter((item) => item.region_id === region.id);
  const permitCountByOrg = buildPermitCountByOrg(snapshot, region.id);

  const orgByName = new Map(organizations.map((item) => [intelMapNormalize(item.name), item]));
  const contactCountByOrg = new Map();
  const newsCountByOrg = new Map();

  for (const item of contacts) {
    const key = intelMapNormalize(item.organization);
    if (!key) {
      continue;
    }
    contactCountByOrg.set(key, (contactCountByOrg.get(key) || 0) + 1);
  }

  for (const item of news) {
    for (const orgName of item.organizations || []) {
      const key = intelMapNormalize(orgName);
      if (!key) {
        continue;
      }
      newsCountByOrg.set(key, (newsCountByOrg.get(key) || 0) + 1);
    }
  }

  const points = businesses
    .map((business) => {
      const normalizedName = intelMapNormalize(business.name);
      const organization = orgByName.get(normalizedName) || null;
      const contactCount = contactCountByOrg.get(normalizedName) || 0;
      const newsCount = newsCountByOrg.get(normalizedName) || 0;
      const permitCount = permitCountByOrg.get(normalizedName) || 0;
      const footprintCount = Math.max(1, Number(organization?.business_lead_count || 1));
      const signalCount = footprintCount + contactCount + newsCount + permitCount;
      const score = Math.max(Number(business.lead_score || 0), Number(organization?.organization_score || 0));
      const tags = [business.category];
      if (organization) tags.push("org-linked");
      if (footprintCount > 1) tags.push(`${footprintCount} locations`);
      if (newsCount) tags.push(`${newsCount} news`);
      if (contactCount) tags.push(`${contactCount} contacts`);
      if (permitCount) tags.push(`${permitCount} permit links`);
      return {
        point_id: business.item_id,
        region_id: region.id,
        title: business.name,
        subtitle: business.address || business.category || "Mapped business signal",
        lat: Number(business.lat),
        lon: Number(business.lon),
        score,
        signal_count: signalCount,
        kind: organization ? "organization" : "business",
        detail_kind: organization ? "organization" : "business",
        detail_id: organization ? organization.item_id : business.item_id,
        intel_url: intelDetailUrl(region.id, organization ? "organization" : "business", organization ? organization.item_id : business.item_id),
        source_url: business.website || business.source_url || "",
        tags,
        org_linked: Boolean(organization),
        footprint_count: footprintCount,
        news_count: newsCount,
        contact_count: contactCount,
        permit_count: permitCount,
      };
    })
    .sort((left, right) => {
      return (right.score - left.score) || (right.signal_count - left.signal_count) || left.title.localeCompare(right.title);
    })
    .slice(0, 140);

  return {
    region,
    points,
    counts: {
      total: points.length,
      orgLinked: points.filter((item) => item.org_linked).length,
      newsLinked: points.filter((item) => item.news_count > 0).length,
      contactLinked: points.filter((item) => item.contact_count > 0).length,
      permitLinked: points.filter((item) => item.permit_count > 0).length,
    },
    notes: [
      "Mapped dots use public business coordinates enriched with linked organization, contact, news, and permit context where available.",
      "Unmapped address-backed signals still appear in the feed cards below.",
    ],
  };
}

function projectPoint(point, bbox) {
  const [minLat, minLon, maxLat, maxLon] = bbox;
  const lonSpan = Math.max(0.0001, maxLon - minLon);
  const latSpan = Math.max(0.0001, maxLat - minLat);
  const left = ((point.lon - minLon) / lonSpan) * 100;
  const top = 100 - ((point.lat - minLat) / latSpan) * 100;
  return {
    left: Math.max(2, Math.min(98, left)),
    top: Math.max(4, Math.min(96, top)),
  };
}

const INTEL_MAP_MODES = [
  { id: "all", label: "All mapped", predicate: () => true },
  { id: "priority", label: "Priority", predicate: (point) => point.score >= 60 },
  { id: "dense", label: "Dense signals", predicate: (point) => point.signal_count >= 3 },
  { id: "multi", label: "Multi-location", predicate: (point) => point.footprint_count > 1 },
  { id: "news", label: "News-backed", predicate: (point) => point.news_count > 0 },
  { id: "permits", label: "Permit-linked", predicate: (point) => point.permit_count > 0 },
  { id: "contacts", label: "Contact-backed", predicate: (point) => point.contact_count > 0 },
];

function intelMapFormatModeLabel(modeId) {
  return INTEL_MAP_MODES.find((mode) => mode.id === modeId)?.label || "All mapped";
}

function filterPointsForMode(points, modeId) {
  const mode = INTEL_MAP_MODES.find((item) => item.id === modeId) || INTEL_MAP_MODES[0];
  return points.filter(mode.predicate);
}

function buildSelectedPointHtml(point) {
  if (!point) {
    return `
      <div class="status-label">Point spotlight</div>
      <h3>No mapped entity selected</h3>
      <p class="subtle">Choose a dot or shortlist item to inspect why it matters, then jump into the full intel console if it warrants deeper review.</p>
    `;
  }
  return `
    <div class="status-label">Point spotlight</div>
    <h3>${intelMapEscapeHtml(point.title)}</h3>
    <p class="subtle">${intelMapEscapeHtml(point.subtitle)}</p>
    <div class="intel-tag-row">
      ${(point.tags || []).slice(0, 6).map((tag) => `<span class="intel-tag">${intelMapEscapeHtml(tag)}</span>`).join("")}
    </div>
    <div class="intel-map-facts">
      <div class="intel-map-fact">
        <span>Score</span>
        <strong>${intelMapEscapeHtml(point.score)}</strong>
      </div>
      <div class="intel-map-fact">
        <span>Signals</span>
        <strong>${intelMapEscapeHtml(point.signal_count)}</strong>
      </div>
      <div class="intel-map-fact">
        <span>News</span>
        <strong>${intelMapEscapeHtml(point.news_count)}</strong>
      </div>
      <div class="intel-map-fact">
        <span>Contacts</span>
        <strong>${intelMapEscapeHtml(point.contact_count)}</strong>
      </div>
      <div class="intel-map-fact">
        <span>Permits</span>
        <strong>${intelMapEscapeHtml(point.permit_count)}</strong>
      </div>
      <div class="intel-map-fact">
        <span>Footprint</span>
        <strong>${intelMapEscapeHtml(point.footprint_count)}</strong>
      </div>
    </div>
    <div class="client-feed-actions">
      <a class="ghost-button" href="${intelMapEscapeHtml(point.intel_url)}">Open in Intel</a>
      ${point.source_url ? `<a class="intel-link" href="${intelMapEscapeHtml(point.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
    </div>
  `;
}

function renderMap(config) {
  const canvas = config.canvas;
  const legend = config.legend;
  const topList = config.topList;
  const data = config.data;
  if (!canvas) {
    return;
  }
  if (!data?.region || !(data.points || []).length) {
    canvas.innerHTML = `<div class="empty-state">${intelMapEscapeHtml(config.emptyText || "No mappable intelligence points yet.")}</div>`;
    if (legend) {
      legend.innerHTML = `<div class="subtle">No mapped signal coverage yet.</div>`;
    }
    if (topList) {
      topList.innerHTML = `<div class="subtle">No mapped entities yet.</div>`;
    }
    return;
  }

  const state = {
    mode: config.initialMode || "all",
    selectedPointId: config.initialPointId || data.points[0]?.point_id || "",
  };

  function renderMode() {
    const availableModes = INTEL_MAP_MODES.filter((mode) => mode.id === "all" || filterPointsForMode(data.points, mode.id).length > 0);
    if (!availableModes.some((mode) => mode.id === state.mode)) {
      state.mode = "all";
    }
    const filteredPoints = filterPointsForMode(data.points, state.mode);
    const selectedPoint = filteredPoints.find((point) => point.point_id === state.selectedPointId) || filteredPoints[0] || null;
    state.selectedPointId = selectedPoint?.point_id || "";

    const dotsHtml = filteredPoints
      .map((point) => {
        const projected = projectPoint(point, data.region.bbox);
        const size = Math.max(10, Math.min(26, 8 + point.signal_count * 1.8 + point.score / 28));
        const title = `${point.title} | ${point.subtitle} | score ${point.score}`;
        return `
          <button
            class="intel-map-dot intel-map-dot-${intelMapEscapeHtml(point.kind)} ${point.point_id === state.selectedPointId ? "is-selected" : ""}"
            type="button"
            data-point-id="${intelMapEscapeHtml(point.point_id)}"
            data-intel-url="${intelMapEscapeHtml(point.intel_url)}"
            aria-label="${intelMapEscapeHtml(title)}"
            title="${intelMapEscapeHtml(title)}"
            style="left:${projected.left.toFixed(2)}%; top:${projected.top.toFixed(2)}%; --dot-size:${size.toFixed(1)}px"
          >
            <span class="intel-map-dot-core"></span>
          </button>
        `;
      })
      .join("");

    canvas.innerHTML = `
      <div class="intel-map-stage">
        <div class="intel-map-overlay intel-map-overlay-top-left">
          <div class="status-label">Map focus</div>
          <strong>${intelMapEscapeHtml(data.region.name)}</strong>
        </div>
        <div class="intel-map-overlay intel-map-overlay-top-right">
          <div class="status-label">Active mode</div>
          <strong>${intelMapEscapeHtml(intelMapFormatModeLabel(state.mode))}</strong>
        </div>
        <div class="intel-map-overlay intel-map-overlay-bottom-left">
          <div class="status-label">Visible points</div>
          <strong>${intelMapEscapeHtml(filteredPoints.length)}</strong>
        </div>
        <div class="intel-map-axis intel-map-axis-x"></div>
        <div class="intel-map-axis intel-map-axis-y"></div>
        <div class="intel-map-grid"></div>
        ${dotsHtml || `<div class="intel-map-empty-state"><div class="status-label">No mapped entities</div><strong>No points match this mode</strong></div>`}
      </div>
    `;

    if (legend) {
      legend.innerHTML = `
        <div class="status-label">Intelligence map</div>
        <h3>${intelMapEscapeHtml(data.region.name)}</h3>
        <p class="subtle">Mapped entity intelligence prioritized for operational use, not just visual density.</p>
        <div class="intel-tag-row">
          <span class="intel-tag">${intelMapEscapeHtml(data.counts.total)} mapped</span>
          <span class="intel-tag">${intelMapEscapeHtml(data.counts.orgLinked)} org-linked</span>
          <span class="intel-tag">${intelMapEscapeHtml(data.counts.newsLinked)} news-linked</span>
          <span class="intel-tag">${intelMapEscapeHtml(data.counts.contactLinked)} contact-linked</span>
          <span class="intel-tag">${intelMapEscapeHtml(data.counts.permitLinked)} permit-linked</span>
        </div>
        <div class="intel-map-mode-row">
          ${availableModes.map((mode) => `
            <button class="intel-map-mode-button ${mode.id === state.mode ? "is-active" : ""}" type="button" data-mode-id="${intelMapEscapeHtml(mode.id)}">
              ${intelMapEscapeHtml(mode.label)}
            </button>
          `).join("")}
        </div>
        <ul class="intel-list intel-map-note-list">
          ${(data.notes || []).map((note) => `<li class="intel-item"><div class="subtle">${intelMapEscapeHtml(note)}</div></li>`).join("")}
        </ul>
      `;
    }

    if (topList) {
      topList.innerHTML = `
        <article class="intel-map-selected">
          ${buildSelectedPointHtml(selectedPoint)}
        </article>
        <div class="intel-map-shortlist-header">
          <div>
            <div class="status-label">Top mapped entities</div>
            <h3>Map shortlist</h3>
          </div>
          <span class="intel-tag">${intelMapEscapeHtml(intelMapFormatModeLabel(state.mode))}</span>
        </div>
        <ul class="intel-list">
          ${
            filteredPoints.length
              ? filteredPoints
                  .slice(0, 8)
                  .map(
                    (point) => `
                      <li class="intel-item intel-map-top-item ${point.point_id === state.selectedPointId ? "is-selected" : ""}">
                        <div class="intel-item-head">
                          <strong>${intelMapEscapeHtml(point.title)}</strong>
                          <span class="intel-tag">${intelMapEscapeHtml(point.signal_count)} signals</span>
                        </div>
                        <div class="subtle">${intelMapEscapeHtml(point.subtitle)}</div>
                        <div class="subtle mono">score ${intelMapEscapeHtml(point.score)} | ${intelMapEscapeHtml(point.kind)}</div>
                        <div class="client-feed-actions">
                          <button class="ghost-button intel-map-select-button" type="button" data-point-id="${intelMapEscapeHtml(point.point_id)}">Inspect</button>
                          <a class="ghost-button" href="${intelMapEscapeHtml(point.intel_url)}">Open in Intel</a>
                          ${point.source_url ? `<a class="intel-link" href="${intelMapEscapeHtml(point.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
                        </div>
                      </li>
                    `
                  )
                  .join("")
              : `<li class="intel-item"><div class="subtle">No mapped entities matched this focus mode.</div></li>`
          }
        </ul>
      `;
    }

    legend?.querySelectorAll("[data-mode-id]").forEach((button) => {
      button.addEventListener("click", () => {
        state.mode = button.dataset.modeId || "all";
        renderMode();
      });
    });

    canvas.querySelectorAll("[data-point-id]").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedPointId = button.dataset.pointId || "";
        renderMode();
      });
    });

    topList?.querySelectorAll(".intel-map-select-button").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedPointId = button.dataset.pointId || "";
        renderMode();
      });
    });
  }

  renderMode();
}

window.IntelMap = {
  buildPointsFromSnapshot,
  renderMap,
};
