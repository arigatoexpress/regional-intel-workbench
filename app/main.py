from __future__ import annotations

import math
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Literal

from fastapi import Depends, FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pydantic import Field

from app.admin import require_admin
from app.config import get_settings, resolve_vote_powers
from app.intel_models import IntelAnalystAnnotation
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.presenters.digest import build_digest_payload
from app.route_contracts import build_route_readiness_contract
from app.services.aggregator import DashboardService
from app.services.intel_graph import build_intel_graph
from app.services.intel_insights import build_operational_alerts
from app.services.intel_insights import build_region_briefing_pack
from app.services.intel_insights import build_briefing_pack
from app.services.intel_insights import build_bundle_briefing_pack
from app.services.intel_insights import build_collection_briefing_pack
from app.services.intel_insights import build_entity_changes
from app.services.intel_insights import build_entity_timeline
from app.services.intel_insights import build_monitor_evaluations
from app.services.intel_insights import build_opportunities
from app.services.intel_insights import build_region_changes
from app.services.intel_insights import build_source_incidents
from app.services.intel_insights import resolve_collection_items
from app.services.intel_insights import resolve_watchlist
from app.services.intel_analyst_store import IntelAnalystStore
from app.services.intel_bundle_store import IntelBundleStore
from app.services.client_views import available_client_views
from app.services.client_views import build_client_view
from app.services.intel_collection_store import IntelCollectionStore
from app.services.intel_monitor_store import IntelMonitorStore
from app.services.field_ops import build_field_ops_snapshot
from app.services.regional_ooda import build_regional_ooda_packet
from app.services.regional_intel import RegionalIntelService
from app.services.intel_watchlist_store import IntelWatchlistStore
from app.services.strategy import build_strategy_snapshot
from app.utils import clean_text


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Regional Intelligence Workbench")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
dashboard_service = DashboardService()
regional_intel_service = RegionalIntelService()
intel_watchlist_store = IntelWatchlistStore()
intel_analyst_store = IntelAnalystStore()
intel_bundle_store = IntelBundleStore()
intel_collection_store = IntelCollectionStore()
intel_monitor_store = IntelMonitorStore()
settings = get_settings()


class WatchlistSaveRequest(BaseModel):
    kind: str
    label: str | None = None
    region_id: RegionId | None = None
    item_id: str | None = None
    source_url: str | None = None
    note: str | None = None


class AnalystAnnotationRequest(BaseModel):
    target_kind: str
    target_id: str
    note: str = ""
    tags: list[str] = Field(default_factory=list)


class CollectionCreateRequest(BaseModel):
    title: str
    region_id: RegionId | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


class CollectionItemSaveRequest(BaseModel):
    kind: str
    label: str | None = None
    region_id: RegionId | None = None
    item_id: str | None = None
    source_url: str | None = None
    note: str | None = None


class BundleCreateRequest(BaseModel):
    title: str
    region_id: RegionId | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


class BundleCollectionSaveRequest(BaseModel):
    collection_id: str
    label: str | None = None


class MonitorRuleCreateRequest(BaseModel):
    title: str
    region_id: RegionId | None = None
    entity_kinds: list[str] = Field(default_factory=list)
    change_types: list[str] = Field(default_factory=list)
    incident_types: list[str] = Field(default_factory=list)
    keyword: str | None = None
    min_score_delta: float | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/vote-monitor", response_class=HTMLResponse)
async def vote_monitor_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "vote_monitor.html", {})


@app.get("/intel", response_class=HTMLResponse)
async def intel_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "intel.html", {})


@app.get("/field-ops", response_class=HTMLResponse)
async def field_ops_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "field_ops.html", {})


def _resolve_client_view_meta(view_id: str) -> dict:
    for item in available_client_views():
        if item["view_id"] == view_id:
            return item
    raise HTTPException(status_code=404, detail="Client view not found")


@app.get("/client-views/{view_id}", response_class=HTMLResponse)
async def client_view_page(request: Request, view_id: str) -> HTMLResponse:
    view_meta = _resolve_client_view_meta(view_id)
    return templates.TemplateResponse(
        request,
        "client_view.html",
        {
            "view_id": view_id,
            "view_meta": view_meta,
        },
    )


@app.get("/blanga/austin", response_class=HTMLResponse)
async def blanga_austin_page(request: Request) -> HTMLResponse:
    view_meta = _resolve_client_view_meta("blanga_austin")
    return templates.TemplateResponse(
        request,
        "client_view.html",
        {
            "view_id": "blanga_austin",
            "view_meta": view_meta,
        },
    )


@app.get("/api/snapshot")
async def api_snapshot(force: bool = False):
    snapshot = await dashboard_service.get_snapshot(force_refresh=force)
    return snapshot.model_dump()


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


@app.get("/api/intel/health")
async def api_intel_health():
    return {"status": "ok"}


def _runtime_route_inventory() -> list[dict[str, Any]]:
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(
            method
            for method in route.methods or []
            if method not in {"HEAD", "OPTIONS"}
        )
        routes.append({"path": route.path, "methods": methods, "name": route.name})
    return sorted(routes, key=lambda item: (item["path"], item["name"] or ""))


@app.get("/api/intel/contracts")
async def api_intel_contracts():
    return build_route_readiness_contract(_runtime_route_inventory()).model_dump()


@app.get("/api/intel/field-ops")
async def api_intel_field_ops(
    region: RegionId = "gunnison_valley_co",
    force: bool = False,
):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return build_field_ops_snapshot(snapshot, region_id=region).model_dump()


# ---------------------------------------------------------------------------
# Admin frontend (dedicated dashboard at /admin)
# ---------------------------------------------------------------------------


@app.get("/healthz/")
async def healthz():
    """Cloud Run / k8s style health probe.

    Explicit JSONResponse + Cache-Control:no-store so probes never get a
    stale 200 from a CDN or browser cache.
    """

    return JSONResponse(
        {"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    """Render the admin dashboard shell.

    The HTML page itself is unauthenticated so the operator can land on the
    page and supply the ``X-Admin-Token`` header (stored in localStorage)
    via the in-page prompt. Every ``/api/admin/*`` call is gated.
    """

    return templates.TemplateResponse(request, "admin.html", {})


@app.get("/api/admin/regions", dependencies=[Depends(require_admin)])
async def api_admin_regions():
    """Return the configured region catalog with bbox + center for the map."""

    catalog = [item.model_dump() for item in regional_intel_service.region_catalog()]
    for region in catalog:
        bbox = region.get("bbox") or []
        if len(bbox) == 4:
            south, west, north, east = bbox
            region["center"] = [(south + north) / 2.0, (west + east) / 2.0]
            region["bounds"] = [[south, west], [north, east]]
        else:
            region["center"] = None
            region["bounds"] = None
    return {"regions": catalog}


@app.get("/api/admin/overview", dependencies=[Depends(require_admin)])
async def api_admin_overview(
    region: RegionId | None = None,
    days: int = 14,
    limit: int = 40,
    force: bool = False,
):
    """One-shot fetch the admin UI uses to populate every panel.

    Returns recent items grouped by category, source health for the region,
    trends, monitor rules, and a summary. Bundling avoids the N+1
    request waterfall a naive frontend would create.
    """

    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    lookback = max(1, min(int(days or 14), 30))
    effective_limit = max(1, min(int(limit or 40), 200))

    recent = _build_recent_items(snapshot, region=region, limit=effective_limit)
    items_by_category: dict[str, list] = {}
    for item in recent.get("items", []):
        kind = item.get("kind") or "other"
        items_by_category.setdefault(kind, []).append(item)

    source_health = {
        "source_health": _filter_region_snapshot(snapshot, region)["source_health"],
    }
    trends = _build_trends(
        regional_intel_service, lookback_days=lookback, region=region
    )
    source_history = _build_source_history(
        regional_intel_service, lookback_days=lookback, region=region
    )
    monitor = _build_monitor_rules(snapshot, region=region)

    payload = _filter_region_snapshot(snapshot, region)
    summary = {
        "region": region,
        "updated_at": payload.get("updated_at"),
        "regions": payload.get("regions", []),
        "counts": {
            "news": len(payload.get("news", [])),
            "permits": len(payload.get("permits", [])),
            "businesses": len(payload.get("businesses", [])),
            "contacts": len(payload.get("contacts", [])),
            "organizations": len(payload.get("organizations", [])),
            "sources": len(payload.get("sources", [])),
        },
    }
    return {
        "summary": summary,
        "recent": recent,
        "items_by_category": items_by_category,
        "source_health": source_health,
        "source_history": source_history,
        "trends": trends,
        "monitor": monitor,
    }


@app.get("/api/admin/search", dependencies=[Depends(require_admin)])
async def api_admin_search(q: str, region: RegionId | None = None, force: bool = False):
    """Full-text search across the snapshot. Reuses /api/intel/search."""

    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _search_snapshot(snapshot, q, region)


def _filter_region_snapshot(snapshot, region: RegionId | None):
    payload = snapshot.model_dump()
    if region is None:
        return payload
    payload["regions"] = [item for item in payload["regions"] if item["id"] == region]
    payload["sources"] = [
        item
        for item in payload["sources"]
        if not item["region_ids"] or region in item["region_ids"]
    ]
    payload["news"] = [item for item in payload["news"] if item["region_id"] == region]
    payload["permits"] = [
        item for item in payload["permits"] if item["region_id"] == region
    ]
    payload["businesses"] = [
        item for item in payload["businesses"] if item["region_id"] == region
    ]
    payload["contacts"] = [
        item for item in payload["contacts"] if item["region_id"] == region
    ]
    payload["organizations"] = [
        item for item in payload["organizations"] if item["region_id"] == region
    ]
    payload["source_health"] = [
        item
        for item in payload["source_health"]
        if not item["region_ids"] or region in item["region_ids"]
    ]
    payload["briefs"] = [
        item for item in payload["briefs"] if item["region_id"] == region
    ]
    return payload


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _severity(score: float) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _normalize_score(score) -> float:
    """Coerce a score-like value to a finite float rounded to 2 decimals.

    Rejects NaN and infinities (returns 0.0) so downstream JSON/JS consumers
    never receive non-finite numbers.
    """
    try:
        value = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return round(value, 2)


def _intel_url(
    kind: str, item_id: str | None, *, region_id: str | None = None
) -> str | None:
    if not item_id:
        return None
    region_qs = f"&region={region_id}" if region_id else ""
    return f"/intel?detail_kind={kind}&detail_id={item_id}{region_qs}"


def _recent_item(
    *,
    kind: str,
    item_id: str,
    region_id: str,
    title: str,
    summary: str,
    score: float,
    timestamp: str | None,
    source_name: str,
    source_url: str | None,
    tags: list[str] | None = None,
) -> dict:
    normalized_score = _normalize_score(score)
    return {
        "id": f"{kind}:{item_id}",
        "item_id": item_id,
        "kind": kind,
        "region": region_id,
        "region_id": region_id,
        "title": title,
        "summary": summary,
        "detail": summary,
        "score": normalized_score,
        "severity": _severity(normalized_score),
        "timestamp": timestamp,
        "source_name": source_name,
        "source_url": source_url,
        "url": source_url,
        "intel_url": _intel_url(kind, item_id, region_id=region_id),
        "tags": [item for item in tags or [] if item],
    }


def _build_recent_items(snapshot, *, region: RegionId | None, limit: int) -> dict:
    payload = _filter_region_snapshot(snapshot, region)
    try:
        raw_limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raw_limit = 10
    effective_limit = max(1, min(raw_limit, 50))
    items: list[dict] = []

    for item in payload.get("news", []):
        items.append(
            _recent_item(
                kind="news",
                item_id=item["item_id"],
                region_id=item["region_id"],
                title=item["title"],
                summary=item.get("address_hint") or item.get("summary") or "",
                score=float(item.get("signal_score") or 0),
                timestamp=item.get("published_at"),
                source_name=item.get("source_name")
                or item.get("publication")
                or "Public news",
                source_url=item.get("source_url"),
                tags=[
                    item.get("signal_type", ""),
                    "actionable" if item.get("actionable") else "",
                ],
            )
        )

    for item in payload.get("permits", []):
        items.append(
            _recent_item(
                kind="permit",
                item_id=item["item_id"],
                region_id=item["region_id"],
                title=item["address"],
                summary=" | ".join(
                    part
                    for part in [
                        item.get("county"),
                        item.get("permit_type"),
                        item.get("status"),
                        item.get("permit_number"),
                    ]
                    if part
                ),
                score=float(item.get("signal_score") or 0),
                timestamp=item.get("status_date"),
                source_name=item.get("source_name") or "Public permit source",
                source_url=item.get("source_url"),
                tags=[item.get("signal_type", ""), item.get("status", "")],
            )
        )

    for item in payload.get("organizations", []):
        items.append(
            _recent_item(
                kind="organization",
                item_id=item["item_id"],
                region_id=item["region_id"],
                title=item["name"],
                summary=" | ".join(
                    part
                    for part in [
                        ", ".join(item.get("categories", [])[:3]),
                        item.get("address"),
                        f"{item.get('permit_signal_count', 0)} permits",
                        f"{item.get('news_signal_count', 0)} news",
                    ]
                    if part
                ),
                score=float(item.get("organization_score") or 0),
                timestamp=item.get("latest_activity_at"),
                source_name=", ".join(item.get("source_names", [])[:2])
                or "Regional graph",
                source_url=item.get("website"),
                tags=list(item.get("categories", [])[:4]),
            )
        )

    for item in payload.get("businesses", []):
        items.append(
            _recent_item(
                kind="business",
                item_id=item["item_id"],
                region_id=item["region_id"],
                title=item["name"],
                summary=item.get("address")
                or item.get("category")
                or "Public business lead",
                score=float(item.get("lead_score") or 0),
                timestamp=None,
                source_name=item.get("source_name") or "Public business source",
                source_url=item.get("website") or item.get("source_url"),
                tags=[item.get("category", "")],
            )
        )

    for item in payload.get("contacts", []):
        items.append(
            _recent_item(
                kind="contact",
                item_id=item["item_id"],
                region_id=item["region_id"],
                title=item["name"],
                summary=" | ".join(
                    part
                    for part in [
                        item.get("title"),
                        item.get("organization"),
                        item.get("email") or item.get("phone"),
                    ]
                    if part
                ),
                score=float(item.get("contact_score") or 0),
                timestamp=None,
                source_name=item.get("source_name") or "Public contact source",
                source_url=item.get("website") or item.get("source_url"),
                tags=[item.get("contact_type", "public_professional_contact")],
            )
        )

    items.sort(
        key=lambda item: (
            _parse_timestamp(item.get("timestamp")),
            float(item.get("score") or 0),
            str(item.get("title") or "").lower(),
        ),
        reverse=True,
    )
    return {
        "region": region,
        "limit": effective_limit,
        "items": items[:effective_limit],
        "item_count": len(items),
        "notes": [
            "Recent feed is assembled from public-source regional intelligence snapshots.",
            "Undated business/contact rows sort after dated news, permit, and organization rows.",
        ],
    }


def _organization_detail(snapshot, item_id: str):
    payload = snapshot.model_dump()
    target = next(
        (item for item in payload["organizations"] if item["item_id"] == item_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    annotation = intel_analyst_store.get_annotation(
        target_kind="organization", target_id=item_id
    )
    region_id = target["region_id"]
    normalized_name = target["name"].lower()
    related_businesses = [
        item
        for item in payload["businesses"]
        if item["region_id"] == region_id and item["name"].lower() == normalized_name
    ]
    related_contacts = [
        item
        for item in payload["contacts"]
        if item["region_id"] == region_id
        and item["organization"].lower() == normalized_name
    ]
    related_news = [
        item
        for item in payload["news"]
        if item["region_id"] == region_id
        and normalized_name in [org.lower() for org in item.get("organizations", [])]
    ]
    related_permits = [
        item
        for item in payload["permits"]
        if item["region_id"] == region_id
        and any(normalized_name in note.lower() for note in item.get("notes", []))
    ]
    return {
        "organization": target,
        "businesses": related_businesses,
        "contacts": related_contacts,
        "news": related_news,
        "permits": related_permits,
        "annotation": annotation.model_dump() if annotation else None,
        "notes": [
            "Entity detail is assembled from the current public-source snapshot.",
            "Matches are exact-name for businesses/contacts and name-in-signal for news/permit notes.",
        ],
    }


def _item_detail(snapshot, kind: str, item_id: str):
    payload = snapshot.model_dump()
    normalized_kind = clean_text(kind).lower()
    kind_map = {
        "organization": "organizations",
        "news": "news",
        "permit": "permits",
        "business": "businesses",
        "contact": "contacts",
    }
    collection_name = kind_map.get(normalized_kind)
    if not collection_name:
        raise HTTPException(status_code=404, detail="Unsupported item kind")
    if normalized_kind == "organization":
        return _organization_detail(snapshot, item_id)

    target = next(
        (item for item in payload[collection_name] if item["item_id"] == item_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Item not found")

    region_id = target["region_id"]
    target_text = " ".join(
        str(value)
        for value in [
            target.get("title"),
            target.get("summary"),
            target.get("address"),
            target.get("permit_type"),
            target.get("organization"),
            " ".join(target.get("organizations", [])),
            " ".join(target.get("notes", [])),
        ]
        if value
    ).lower()
    target_address = clean_text(
        target.get("address") or target.get("address_hint") or ""
    ).lower()

    related_organizations = [
        item
        for item in payload["organizations"]
        if item["region_id"] == region_id
        and (
            item["name"].lower() in target_text
            or (
                target_address
                and clean_text(item.get("address") or "").lower() == target_address
            )
            or (
                normalized_kind == "business"
                and item["name"].lower() == clean_text(target.get("name")).lower()
            )
            or (
                normalized_kind == "contact"
                and item["name"].lower()
                == clean_text(target.get("organization")).lower()
            )
        )
    ][:8]

    related_contacts = [
        item
        for item in payload["contacts"]
        if item["region_id"] == region_id
        and (
            item["organization"].lower() in target_text
            or (
                normalized_kind == "business"
                and item["organization"].lower()
                == clean_text(target.get("name")).lower()
            )
        )
    ][:8]

    related_businesses = [
        item
        for item in payload["businesses"]
        if item["region_id"] == region_id
        and (
            item["name"].lower() in target_text
            or (
                target_address
                and clean_text(item.get("address") or "").lower() == target_address
            )
            or (
                normalized_kind == "contact"
                and item["name"].lower()
                == clean_text(target.get("organization")).lower()
            )
        )
    ][:8]

    related_news = [
        item
        for item in payload["news"]
        if item["region_id"] == region_id
        and item["item_id"] != item_id
        and (
            target.get("name", "").lower()
            in " ".join(item.get("organizations", [])).lower()
            or target.get("organization", "").lower()
            in " ".join(item.get("organizations", [])).lower()
            or (
                target_address
                and clean_text(item.get("address_hint") or "").lower() == target_address
            )
        )
    ][:8]

    related_permits = [
        item
        for item in payload["permits"]
        if item["region_id"] == region_id
        and item["item_id"] != item_id
        and (
            target.get("name", "").lower() in " ".join(item.get("notes", [])).lower()
            or target.get("organization", "").lower()
            in " ".join(item.get("notes", [])).lower()
            or (
                target_address
                and clean_text(item.get("address") or "").lower() == target_address
            )
        )
    ][:8]

    return {
        "kind": normalized_kind,
        "item": target,
        "related_organizations": related_organizations,
        "related_contacts": related_contacts,
        "related_businesses": related_businesses,
        "related_news": related_news,
        "related_permits": related_permits,
        "notes": [
            "Generic item detail is assembled from current public-source records and simple relationship heuristics.",
            "Use linked organizations, contacts, and addresses as research accelerators, not as final truth.",
        ],
    }


def _match_score(text: str, query: str) -> int:
    haystack = str(text or "").lower()
    needle = query.lower()
    if not needle or needle not in haystack:
        return 0
    if haystack == needle:
        return 120
    if haystack.startswith(needle):
        return 90
    return 50


def _search_snapshot(snapshot, query: str, region: RegionId | None):
    trimmed = query.strip()
    if not trimmed:
        return {"query": trimmed, "region": region, "results": []}
    payload = _filter_region_snapshot(snapshot, region)
    results = []

    for item in payload.get("news", []):
        score = max(
            _match_score(item["title"], trimmed),
            _match_score(item.get("summary", ""), trimmed),
            _match_score(" ".join(item.get("organizations", [])), trimmed),
            _match_score(item.get("address_hint", ""), trimmed),
        )
        if score <= 0:
            continue
        results.append(
            {
                "kind": "news",
                "score": score,
                "item_id": item.get("item_id"),
                "region_id": item["region_id"],
                "title": item["title"],
                "subtitle": item.get("source_name") or item.get("publication"),
                "detail": item.get("summary") or item.get("address_hint") or "",
                "url": item.get("source_url"),
            }
        )

    for item in payload.get("permits", []):
        score = max(
            _match_score(item["address"], trimmed),
            _match_score(item.get("permit_type", ""), trimmed),
            _match_score(" ".join(item.get("notes", [])), trimmed),
        )
        if score <= 0:
            continue
        results.append(
            {
                "kind": "permit",
                "score": score,
                "item_id": item.get("item_id"),
                "region_id": item["region_id"],
                "title": item["address"],
                "subtitle": f"{item.get('county', '')} | {item.get('permit_type', '')}",
                "detail": " | ".join(
                    part
                    for part in [item.get("permit_number", ""), item.get("status", "")]
                    if part
                ),
                "url": item.get("source_url"),
            }
        )

    for item in payload.get("businesses", []):
        score = max(
            _match_score(item["name"], trimmed),
            _match_score(item.get("address", ""), trimmed),
            _match_score(item.get("category", ""), trimmed),
        )
        if score <= 0:
            continue
        results.append(
            {
                "kind": "business",
                "score": score,
                "item_id": item.get("item_id"),
                "region_id": item["region_id"],
                "title": item["name"],
                "subtitle": item.get("category", ""),
                "detail": item.get("address")
                or item.get("website")
                or item.get("phone")
                or "",
                "url": item.get("website") or item.get("source_url"),
            }
        )

    for item in payload.get("contacts", []):
        score = max(
            _match_score(item["name"], trimmed),
            _match_score(item.get("organization", ""), trimmed),
            _match_score(item.get("title", ""), trimmed),
            _match_score(item.get("email", ""), trimmed),
        )
        if score <= 0:
            continue
        results.append(
            {
                "kind": "contact",
                "score": score,
                "item_id": item.get("item_id"),
                "region_id": item["region_id"],
                "title": item["name"],
                "subtitle": " | ".join(
                    part
                    for part in [item.get("title", ""), item.get("organization", "")]
                    if part
                ),
                "detail": " | ".join(
                    part
                    for part in [
                        item.get("email", ""),
                        item.get("phone", ""),
                        item.get("address", ""),
                    ]
                    if part
                ),
                "url": item.get("website") or item.get("source_url"),
            }
        )

    for item in payload.get("organizations", []):
        score = max(
            _match_score(item["name"], trimmed),
            _match_score(" ".join(item.get("categories", [])), trimmed),
            _match_score(item.get("address", ""), trimmed),
        )
        if score <= 0:
            continue
        results.append(
            {
                "kind": "organization",
                "score": score,
                "item_id": item.get("item_id"),
                "region_id": item["region_id"],
                "title": item["name"],
                "subtitle": ", ".join(item.get("categories", [])[:3]),
                "detail": " | ".join(
                    part
                    for part in [
                        item.get("address", ""),
                        item.get("website", ""),
                        item.get("phone", ""),
                        item.get("email", ""),
                    ]
                    if part
                ),
                "url": item.get("website"),
            }
        )

    results.sort(
        key=lambda item: (
            -item["score"],
            item["region_id"],
            item["kind"],
            item["title"].lower(),
        )
    )
    return {"query": trimmed, "region": region, "results": results[:60]}


def _build_watchlist(snapshot, region: RegionId | None):
    payload = _filter_region_snapshot(snapshot, region)
    items = []
    for item in payload.get("news", []):
        items.append(
            {
                "kind": "news",
                "item_id": item["item_id"],
                "region_id": item["region_id"],
                "score": item.get("signal_score", 0),
                "title": item["title"],
                "subtitle": item.get("source_name", ""),
                "detail": item.get("address_hint") or item.get("summary") or "",
                "reason": "High-signal news item with public source provenance.",
                "url": item.get("source_url"),
            }
        )
    for item in payload.get("permits", []):
        items.append(
            {
                "kind": "permit",
                "item_id": item["item_id"],
                "region_id": item["region_id"],
                "score": item.get("signal_score", 0),
                "title": item["address"],
                "subtitle": f"{item.get('county', '')} | {item.get('permit_type', '')}",
                "detail": item.get("status", ""),
                "reason": "Permit activity with an address and recent status.",
                "url": item.get("source_url"),
            }
        )
    for item in payload.get("organizations", []):
        items.append(
            {
                "kind": "organization",
                "item_id": item["item_id"],
                "region_id": item["region_id"],
                "score": item.get("organization_score", 0),
                "title": item["name"],
                "subtitle": ", ".join(item.get("categories", [])[:3]),
                "detail": item.get("address") or item.get("website") or "",
                "reason": "Organization with multiple linked signals or public contacts.",
                "url": item.get("website"),
            }
        )
    for item in payload.get("contacts", []):
        items.append(
            {
                "kind": "contact",
                "item_id": item["item_id"],
                "region_id": item["region_id"],
                "score": item.get("contact_score", 0),
                "title": item["name"],
                "subtitle": item.get("organization", ""),
                "detail": item.get("title")
                or item.get("email")
                or item.get("phone")
                or "",
                "reason": "Public professional contact with verifiable source.",
                "url": item.get("website") or item.get("source_url"),
            }
        )
    items.sort(
        key=lambda item: (
            -item["score"],
            item["region_id"],
            item["kind"],
            item["title"].lower(),
        )
    )
    return {"region": region, "watchlist": items[:20]}


def _build_trends(
    regional_intel_service: RegionalIntelService,
    lookback_days: int,
    region: RegionId | None,
):
    records = regional_intel_service.history_store.load_records(
        lookback_days=lookback_days
    )
    series = []
    for record in records:
        row: dict[str, Any] = {
            "updated_at": record.get("updated_at"),
            "regions": [],
        }
        for item in record.get("regions", []):
            region_id = item.get("id")
            if region is not None and region_id != region:
                continue
            row["regions"].append(
                {
                    "region_id": region_id,
                    "news": len(
                        [
                            x
                            for x in record.get("news", [])
                            if x.get("region_id") == region_id
                        ]
                    ),
                    "permits": len(
                        [
                            x
                            for x in record.get("permits", [])
                            if x.get("region_id") == region_id
                        ]
                    ),
                    "businesses": len(
                        [
                            x
                            for x in record.get("businesses", [])
                            if x.get("region_id") == region_id
                        ]
                    ),
                    "contacts": len(
                        [
                            x
                            for x in record.get("contacts", [])
                            if x.get("region_id") == region_id
                        ]
                    ),
                    "organizations": len(
                        [
                            x
                            for x in record.get("organizations", [])
                            if x.get("region_id") == region_id
                        ]
                    ),
                }
            )
        if row["regions"]:
            series.append(row)
    return {"region": region, "series": series}


def _build_source_history(
    regional_intel_service: RegionalIntelService,
    lookback_days: int,
    region: RegionId | None,
    *,
    records: list[dict] | None = None,
):
    if records is None:
        records = regional_intel_service.history_store.load_records(
            lookback_days=lookback_days
        )
    sources: dict[str, dict] = {}
    for record in records:
        updated_at = record.get("updated_at")
        if not updated_at:
            continue
        for item in record.get("source_health", []):
            if not isinstance(item, dict):
                continue
            region_ids = item.get("region_ids") or []
            if region is not None and region_ids and region not in region_ids:
                continue
            key = str(item.get("source_key"))
            if not key:
                continue
            bucket = sources.setdefault(
                key,
                {
                    "source_key": key,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "region_ids": region_ids,
                    "last_status": None,
                    "last_item_count": 0,
                    "non_empty_runs": 0,
                    "empty_runs": 0,
                    "manual_runs": 0,
                    "points": [],
                },
            )
            status = str(item.get("status") or "unknown")
            item_count = int(item.get("item_count") or 0)
            bucket["last_status"] = status
            bucket["last_item_count"] = item_count
            if status == "live" and item_count > 0:
                bucket["non_empty_runs"] += 1
            elif status == "empty":
                bucket["empty_runs"] += 1
            elif status == "manual":
                bucket["manual_runs"] += 1
            bucket["points"].append(
                {
                    "updated_at": updated_at,
                    "status": status,
                    "item_count": item_count,
                }
            )
    output = list(sources.values())
    output.sort(
        key=lambda item: (
            item["category"],
            -(item["non_empty_runs"] + item["last_item_count"]),
            item["name"] or "",
        )
    )
    return {"region": region, "sources": output}


def _build_operational_alerts(snapshot, region: RegionId | None):
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=region
    )["sources"]
    return {
        "region": region,
        "alerts": [
            item.model_dump()
            for item in build_operational_alerts(
                snapshot, source_history=source_history, region=region
            )
        ],
    }


def _build_source_incidents(region: RegionId | None):
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=region
    )["sources"]
    return {
        "region": region,
        "incidents": [
            item.model_dump()
            for item in build_source_incidents(source_history, region=region)
        ],
    }


def _build_region_changes(lookback_days: int, region: RegionId | None):
    records = regional_intel_service.history_store.load_records(
        lookback_days=lookback_days
    )
    return {
        "region": region,
        "changes": [
            item.model_dump() for item in build_region_changes(records, region=region)
        ],
    }


def _build_entity_changes(
    lookback_days: int, region: RegionId | None, kind: str | None, item_id: str | None
):
    records = regional_intel_service.history_store.load_records(
        lookback_days=lookback_days
    )
    return {
        "region": region,
        "kind": kind,
        "item_id": item_id,
        "changes": [
            item.model_dump()
            for item in build_entity_changes(
                records, region=region, kind=kind, item_id=item_id
            )
        ],
    }


def _build_region_briefing(snapshot, region: RegionId):
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=region
    )["sources"]
    alerts = build_operational_alerts(
        snapshot, source_history=source_history, region=region
    )
    watchlist_items = resolve_watchlist(snapshot, intel_watchlist_store.list_entries())
    pack = build_region_briefing_pack(
        snapshot,
        region=region,
        opportunities=build_opportunities(snapshot, region=region),
        alerts=alerts,
        watchlist_items=watchlist_items,
    )
    return pack


def _build_collection_briefing(snapshot, collection_id: str):
    collection = intel_collection_store.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=collection.region_id
    )["sources"]
    annotation_lookup = {
        item.get("resolved", {}).get("item_id"): intel_analyst_store.get_annotation(
            target_kind="organization",
            target_id=item.get("resolved", {}).get("item_id"),
        )
        for item in resolve_collection_items(snapshot, collection)
        if item.get("ref", {}).get("kind") == "organization"
        and item.get("resolved", {}).get("item_id")
    }
    return build_collection_briefing_pack(
        snapshot,
        collection=collection,
        source_history=source_history,
        annotation_lookup={
            key: value for key, value in annotation_lookup.items() if value is not None
        },
    )


def _build_bundle_briefing(snapshot, bundle_id: str):
    bundle = intel_bundle_store.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    collections = []
    for ref in bundle.collections:
        collection = intel_collection_store.get_collection(ref.collection_id)
        if collection is not None:
            collections.append(collection)
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=bundle.region_id
    )["sources"]
    annotation_lookup: dict[str, IntelAnalystAnnotation] = {}
    for collection in collections:
        for item in resolve_collection_items(snapshot, collection):
            if item.get("ref", {}).get("kind") != "organization" or not item.get(
                "resolved", {}
            ).get("item_id"):
                continue
            target_id = item["resolved"]["item_id"]
            annotation = intel_analyst_store.get_annotation(
                target_kind="organization", target_id=target_id
            )
            if annotation is not None:
                annotation_lookup[target_id] = annotation
    return build_bundle_briefing_pack(
        snapshot,
        bundle=bundle,
        collections=collections,
        source_history=source_history,
        annotation_lookup=annotation_lookup,
    )


def _build_monitor_rules(snapshot, region: RegionId | None):
    records = regional_intel_service.history_store.load_records(lookback_days=14)
    source_history = _build_source_history(
        regional_intel_service, lookback_days=14, region=region
    )["sources"]
    rules = [
        rule
        for rule in intel_monitor_store.list_rules()
        if region is None or rule.region_id in {None, region}
    ]
    return {
        "region": region,
        "rules": [
            item.model_dump()
            for item in build_monitor_evaluations(
                snapshot,
                rules=rules,
                history_records=records,
                source_history=source_history,
            )
        ],
    }


def _build_client_view_payload(snapshot, view_id: str):
    _resolve_client_view_meta(view_id)
    history_records = regional_intel_service.history_store.load_records(
        lookback_days=14
    )
    source_history = _build_source_history(
        regional_intel_service,
        lookback_days=14,
        region=None,
        records=history_records,
    )["sources"]
    try:
        view = build_client_view(
            view_id=view_id,
            snapshot=snapshot,
            history_records=history_records,
            source_history=source_history,
            monitor_rules=intel_monitor_store.list_rules(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Client view not found") from exc
    return view


@app.get("/api/client-views")
async def api_client_views():
    views = []
    for item in available_client_views():
        alias_url = "/blanga/austin" if item["view_id"] == "blanga_austin" else None
        views.append(
            {
                **item,
                "page_url": f"/client-views/{item['view_id']}",
                "api_url": f"/api/client-views/{item['view_id']}",
                "alias_url": alias_url,
                "intel_url": f"/intel?region={item.get('region_id')}"
                if item.get("region_id")
                else "/intel",
            }
        )
    return {"views": views}


@app.get("/api/client-views/{view_id}")
async def api_client_view(view_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    view = _build_client_view_payload(snapshot, view_id)
    return view.model_dump()


@app.get("/api/intel/snapshot")
async def api_intel_snapshot(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _filter_region_snapshot(snapshot, region)


@app.get("/api/intel/recent")
async def api_intel_recent(
    force: bool = False, region: RegionId | None = None, limit: int = 10
):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_recent_items(snapshot, region=region, limit=limit)


@app.get("/api/intel/search")
async def api_intel_search(q: str, force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _search_snapshot(snapshot, q, region)


@app.get("/api/intel/source-health")
async def api_intel_source_health(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    payload = _filter_region_snapshot(snapshot, region)
    return {"source_health": payload["source_health"]}


@app.get("/api/intel/ooda-packet")
async def api_intel_ooda_packet(region: RegionId | None = None):
    latest_record = regional_intel_service.history_store.load_latest_record()
    if latest_record is None:
        raise HTTPException(
            status_code=404, detail="No stored regional intel snapshot found"
        )
    snapshot = RegionalIntelSnapshot.model_validate(latest_record)
    return build_regional_ooda_packet(snapshot, region=region)


@app.get("/api/intel/briefs")
async def api_intel_briefs(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    payload = _filter_region_snapshot(snapshot, region)
    return {"briefs": payload["briefs"]}


@app.get("/api/intel/organizations/{item_id}")
async def api_intel_organization_detail(item_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _organization_detail(snapshot, item_id)


@app.get("/api/intel/items/{kind}/{item_id}")
async def api_intel_item_detail(kind: str, item_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _item_detail(snapshot, kind, item_id)


@app.get("/api/intel/graph")
async def api_intel_graph(
    force: bool = False,
    region: RegionId | None = None,
    focus_node_id: str | None = None,
):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return build_intel_graph(
        snapshot, region=region, focus_node_id=focus_node_id
    ).model_dump()


@app.get("/api/intel/opportunities")
async def api_intel_opportunities(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return {
        "opportunities": [
            item.model_dump() for item in build_opportunities(snapshot, region=region)
        ]
    }


@app.get("/api/intel/alerts")
async def api_intel_alerts(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_operational_alerts(snapshot, region=region)


@app.get("/api/intel/source-incidents")
async def api_intel_source_incidents(days: int = 14, region: RegionId | None = None):
    return (
        _build_source_incidents(region=region if region is not None else None)
        if days == 14
        else {
            "region": region,
            "incidents": [
                item.model_dump()
                for item in build_source_incidents(
                    _build_source_history(
                        regional_intel_service,
                        lookback_days=max(1, min(days, 30)),
                        region=region,
                    )["sources"],
                    region=region,
                )
            ],
        }
    )


@app.get("/api/intel/region-changes")
async def api_intel_region_changes(days: int = 14, region: RegionId | None = None):
    return _build_region_changes(lookback_days=max(2, min(days, 30)), region=region)


@app.get("/api/intel/entity-changes")
async def api_intel_entity_changes(
    days: int = 14,
    region: RegionId | None = None,
    kind: str | None = None,
    item_id: str | None = None,
):
    return _build_entity_changes(
        lookback_days=max(2, min(days, 30)), region=region, kind=kind, item_id=item_id
    )


@app.get("/api/intel/region-briefing/{region_id}")
async def api_intel_region_briefing(region_id: RegionId, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_region_briefing(snapshot, region=region_id).model_dump()


@app.get("/api/intel/region-briefing/{region_id}/markdown")
async def api_intel_region_briefing_markdown(region_id: RegionId, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    pack = _build_region_briefing(snapshot, region=region_id)
    return PlainTextResponse(pack.markdown)


@app.get("/api/intel/monitor-rules")
async def api_intel_monitor_rules(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_monitor_rules(snapshot, region=region)


@app.post("/api/intel/monitor-rules")
async def api_intel_monitor_rule_create(payload: MonitorRuleCreateRequest):
    rule = intel_monitor_store.save_rule(
        title=payload.title,
        region_id=payload.region_id,
        entity_kinds=payload.entity_kinds,
        change_types=payload.change_types,
        incident_types=payload.incident_types,
        keyword=payload.keyword,
        min_score_delta=payload.min_score_delta,
        note=payload.note,
        tags=payload.tags,
    )
    return {"rule": rule.model_dump()}


@app.delete("/api/intel/monitor-rules/{rule_id}")
async def api_intel_monitor_rule_delete(rule_id: str):
    if not intel_monitor_store.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    return {"status": "deleted", "rule_id": rule_id}


@app.get("/api/intel/briefing/{item_id}")
async def api_intel_briefing(item_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    annotation = intel_analyst_store.get_annotation(
        target_kind="organization", target_id=item_id
    )
    briefing = build_briefing_pack(snapshot, item_id, annotation=annotation)
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing target not found")
    return briefing.model_dump()


@app.get("/api/intel/briefing/{item_id}/markdown")
async def api_intel_briefing_markdown(item_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    annotation = intel_analyst_store.get_annotation(
        target_kind="organization", target_id=item_id
    )
    briefing = build_briefing_pack(snapshot, item_id, annotation=annotation)
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing target not found")
    return PlainTextResponse(briefing.markdown)


@app.get("/api/intel/timeline/{item_id}")
async def api_intel_timeline(item_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    timeline = build_entity_timeline(snapshot, item_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return {"item_id": item_id, "timeline": [item.model_dump() for item in timeline]}


@app.get("/api/intel/annotations/{target_kind}/{target_id}")
async def api_intel_annotation_get(target_kind: str, target_id: str):
    annotation = intel_analyst_store.get_annotation(
        target_kind=target_kind, target_id=target_id
    )
    if annotation is None:
        return {"annotation": None}
    return {"annotation": annotation.model_dump()}


@app.post("/api/intel/annotations")
async def api_intel_annotation_save(payload: AnalystAnnotationRequest):
    annotation = intel_analyst_store.save_annotation(
        target_kind=payload.target_kind,
        target_id=payload.target_id,
        note=payload.note,
        tags=payload.tags,
    )
    return {"annotation": annotation.model_dump()}


@app.delete("/api/intel/annotations/{target_kind}/{target_id}")
async def api_intel_annotation_delete(target_kind: str, target_id: str):
    if not intel_analyst_store.delete_annotation(
        target_kind=target_kind, target_id=target_id
    ):
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"status": "deleted", "target_kind": target_kind, "target_id": target_id}


@app.get("/api/intel/watchlist-items")
async def api_intel_watchlist_items(force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    entries = intel_watchlist_store.list_entries()
    items = resolve_watchlist(snapshot, entries)
    for item in items:
        entry = item.get("entry", {})
        target_kind = entry.get("kind")
        target_id = entry.get("item_id")
        annotation = (
            intel_analyst_store.get_annotation(
                target_kind=target_kind, target_id=target_id
            )
            if target_kind and target_id
            else None
        )
        item["annotation"] = annotation.model_dump() if annotation else None
    return {"items": items}


@app.post("/api/intel/watchlist-items")
async def api_intel_watchlist_save(payload: WatchlistSaveRequest, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    resolved_label = payload.label
    resolved_url = payload.source_url
    if payload.item_id:
        for collection_name in [
            "organizations",
            "businesses",
            "contacts",
            "news",
            "permits",
        ]:
            for item in getattr(snapshot, collection_name):
                if item.item_id != payload.item_id:
                    continue
                resolved_label = (
                    resolved_label
                    or getattr(item, "name", None)
                    or getattr(item, "title", None)
                    or getattr(item, "address", None)
                )
                resolved_url = (
                    resolved_url
                    or getattr(item, "website", None)
                    or getattr(item, "source_url", None)
                )
                break
            if resolved_label:
                break
    entry = intel_watchlist_store.save_entry(
        kind=payload.kind,
        label=resolved_label or "Saved item",
        region_id=payload.region_id,
        item_id=payload.item_id,
        source_url=resolved_url,
        note=payload.note,
    )
    return {"entry": entry.model_dump()}


@app.delete("/api/intel/watchlist-items/{entry_id}")
async def api_intel_watchlist_delete(entry_id: str):
    if not intel_watchlist_store.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return {"status": "deleted", "entry_id": entry_id}


@app.get("/api/intel/watchlist")
async def api_intel_watchlist(force: bool = False, region: RegionId | None = None):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_watchlist(snapshot, region)


@app.get("/api/intel/collections")
async def api_intel_collections(force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    collections = intel_collection_store.list_collections()
    items = []
    for collection in collections:
        resolved_items = resolve_collection_items(snapshot, collection)
        items.append(
            {
                "collection": collection.model_dump(),
                "items": resolved_items,
                "live_count": len(
                    [item for item in resolved_items if item.get("is_live")]
                ),
            }
        )
    return {"collections": items}


@app.post("/api/intel/collections")
async def api_intel_collection_create(payload: CollectionCreateRequest):
    collection = intel_collection_store.save_collection(
        title=payload.title,
        region_id=payload.region_id,
        note=payload.note,
        tags=payload.tags,
    )
    return {"collection": collection.model_dump()}


@app.delete("/api/intel/collections/{collection_id}")
async def api_intel_collection_delete(collection_id: str):
    if not intel_collection_store.delete_collection(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "deleted", "collection_id": collection_id}


@app.post("/api/intel/collections/{collection_id}/items")
async def api_intel_collection_item_save(
    collection_id: str, payload: CollectionItemSaveRequest, force: bool = False
):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    resolved_label = payload.label
    resolved_url = payload.source_url
    if payload.item_id:
        for collection_name in [
            "organizations",
            "businesses",
            "contacts",
            "news",
            "permits",
        ]:
            for item in getattr(snapshot, collection_name):
                if item.item_id != payload.item_id:
                    continue
                resolved_label = (
                    resolved_label
                    or getattr(item, "name", None)
                    or getattr(item, "title", None)
                    or getattr(item, "address", None)
                )
                resolved_url = (
                    resolved_url
                    or getattr(item, "website", None)
                    or getattr(item, "source_url", None)
                )
                break
            if resolved_label:
                break
    try:
        item_ref = intel_collection_store.save_item(
            collection_id=collection_id,
            kind=payload.kind,
            label=resolved_label or "Saved item",
            region_id=payload.region_id,
            item_id=payload.item_id,
            source_url=resolved_url,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Collection not found") from exc
    return {"item": item_ref.model_dump()}


@app.delete("/api/intel/collections/{collection_id}/items/{ref_id}")
async def api_intel_collection_item_delete(collection_id: str, ref_id: str):
    if not intel_collection_store.delete_item(collection_id, ref_id):
        raise HTTPException(status_code=404, detail="Collection item not found")
    return {"status": "deleted", "collection_id": collection_id, "ref_id": ref_id}


@app.get("/api/intel/collections/{collection_id}/briefing")
async def api_intel_collection_briefing(collection_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_collection_briefing(snapshot, collection_id).model_dump()


@app.get("/api/intel/collections/{collection_id}/briefing/markdown")
async def api_intel_collection_briefing_markdown(
    collection_id: str, force: bool = False
):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return PlainTextResponse(
        _build_collection_briefing(snapshot, collection_id).markdown
    )


@app.get("/api/intel/bundles")
async def api_intel_bundles(force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    bundles = []
    for bundle in intel_bundle_store.list_bundles():
        resolved_collections: list[dict[str, Any]] = []
        live_count = 0
        for ref in bundle.collections:
            collection = intel_collection_store.get_collection(ref.collection_id)
            if collection is None:
                resolved_collections.append(
                    {"ref": ref.model_dump(), "collection": None, "is_live": False}
                )
                continue
            resolved_items = resolve_collection_items(snapshot, collection)
            live_count += len([item for item in resolved_items if item.get("is_live")])
            resolved_collections.append(
                {
                    "ref": ref.model_dump(),
                    "collection": collection.model_dump(),
                    "is_live": True,
                    "item_count": len(collection.items),
                    "live_count": len(
                        [item for item in resolved_items if item.get("is_live")]
                    ),
                }  # type: ignore[dict-item]
            )
        bundles.append(
            {
                "bundle": bundle.model_dump(),
                "collections": resolved_collections,
                "live_count": live_count,
            }
        )
    return {"bundles": bundles}


@app.post("/api/intel/bundles")
async def api_intel_bundle_create(payload: BundleCreateRequest):
    bundle = intel_bundle_store.save_bundle(
        title=payload.title,
        region_id=payload.region_id,
        note=payload.note,
        tags=payload.tags,
    )
    return {"bundle": bundle.model_dump()}


@app.delete("/api/intel/bundles/{bundle_id}")
async def api_intel_bundle_delete(bundle_id: str):
    if not intel_bundle_store.delete_bundle(bundle_id):
        raise HTTPException(status_code=404, detail="Bundle not found")
    return {"status": "deleted", "bundle_id": bundle_id}


@app.post("/api/intel/bundles/{bundle_id}/collections")
async def api_intel_bundle_collection_save(
    bundle_id: str, payload: BundleCollectionSaveRequest
):
    collection = intel_collection_store.get_collection(payload.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    try:
        ref = intel_bundle_store.save_collection_ref(
            bundle_id=bundle_id,
            collection_id=payload.collection_id,
            label=payload.label or collection.title,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bundle not found") from exc
    return {"ref": ref.model_dump()}


@app.delete("/api/intel/bundles/{bundle_id}/collections/{ref_id}")
async def api_intel_bundle_collection_delete(bundle_id: str, ref_id: str):
    if not intel_bundle_store.delete_collection_ref(bundle_id, ref_id):
        raise HTTPException(status_code=404, detail="Bundle collection ref not found")
    return {"status": "deleted", "bundle_id": bundle_id, "ref_id": ref_id}


@app.get("/api/intel/bundles/{bundle_id}/briefing")
async def api_intel_bundle_briefing(bundle_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return _build_bundle_briefing(snapshot, bundle_id).model_dump()


@app.get("/api/intel/bundles/{bundle_id}/briefing/markdown")
async def api_intel_bundle_briefing_markdown(bundle_id: str, force: bool = False):
    snapshot = await regional_intel_service.get_snapshot(force_refresh=force)
    return PlainTextResponse(_build_bundle_briefing(snapshot, bundle_id).markdown)


@app.get("/api/intel/trends")
async def api_intel_trends(days: int = 7, region: RegionId | None = None):
    return _build_trends(
        regional_intel_service, lookback_days=max(1, min(days, 30)), region=region
    )


@app.get("/api/intel/source-history")
async def api_intel_source_history(days: int = 14, region: RegionId | None = None):
    return _build_source_history(
        regional_intel_service, lookback_days=max(1, min(days, 30)), region=region
    )


@app.get("/api/intel/regions")
async def api_intel_regions():
    return {
        "regions": [
            item.model_dump() for item in regional_intel_service.region_catalog()
        ]
    }


@app.get("/api/intel/sources")
async def api_intel_sources():
    return {
        "ethics_rules": [
            item.model_dump() for item in regional_intel_service.ethics_catalog()
        ],
        "sources": [
            item.model_dump() for item in regional_intel_service.source_catalog()
        ],
    }


@app.get("/api/strategy")
async def api_strategy(
    blackhole: float | None = None,
    supernova: float | None = None,
    fullsail: float | None = None,
    force: bool = False,
):
    snapshot = await dashboard_service.get_snapshot(force_refresh=force)
    strategy = build_strategy_snapshot(
        snapshot,
        vote_powers=resolve_vote_powers(
            blackhole=blackhole,
            supernova=supernova,
            fullsail=fullsail,
            settings=settings,
        ),
    )
    return strategy.model_dump()


@app.get("/api/digest")
async def api_digest(
    blackhole: float | None = None,
    supernova: float | None = None,
    fullsail: float | None = None,
    force: bool = False,
    format: Literal["json", "text", "telegram"] = "json",
):
    snapshot = await dashboard_service.get_snapshot(force_refresh=force)
    strategy = build_strategy_snapshot(
        snapshot,
        vote_powers=resolve_vote_powers(
            blackhole=blackhole,
            supernova=supernova,
            fullsail=fullsail,
            settings=settings,
        ),
    )
    payload = build_digest_payload(
        snapshot, strategy, timezone=settings.timezone, style=format
    )
    if format in {"text", "telegram"}:
        return PlainTextResponse(str(payload["message"]))
    return payload
