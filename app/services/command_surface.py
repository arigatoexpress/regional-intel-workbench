from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.intel_models import CommandSurfaceEntity
from app.intel_models import CommandSurfaceGuardrail
from app.intel_models import CommandSurfaceLayer
from app.intel_models import CommandSurfacePayload
from app.intel_models import CommandSurfaceViewport
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.utils import clean_text


DEFAULT_COMMAND_LAYERS = [
    "businesses",
    "organizations",
    "regional_news",
    "development_permits",
    "wildfire_watch",
    "source_health",
]

LAYER_DEFINITIONS: list[dict[str, Any]] = [
    {
        "layer_id": "regional_news",
        "label": "Live News",
        "category": "regional",
        "description": "Public-source regional news and civic signal layer.",
        "retrieval_mode": "public_rss_index",
        "rights": "derived_summary_with_source_links",
    },
    {
        "layer_id": "development_permits",
        "label": "Permits",
        "category": "regional",
        "description": "Official permit and development activity.",
        "retrieval_mode": "public_api_or_official_reports",
        "rights": "official_public_records_with_links",
    },
    {
        "layer_id": "businesses",
        "label": "Business Map",
        "category": "regional",
        "description": "Mapped public business and organization footprints.",
        "retrieval_mode": "open_licensed_api",
        "rights": "open_map_derived_records",
    },
    {
        "layer_id": "organizations",
        "label": "Organizations",
        "category": "regional",
        "description": "Cross-source organization profiles and linked evidence.",
        "retrieval_mode": "stored_snapshot_graph",
        "rights": "derived_profile_with_provenance",
    },
    {
        "layer_id": "public_contacts",
        "label": "Public Contacts",
        "category": "regional",
        "description": "Organization-level public professional contact points.",
        "retrieval_mode": "public_official_pages",
        "rights": "public_professional_contact_only",
    },
    {
        "layer_id": "wildfire_watch",
        "label": "Wildfire Watch",
        "category": "wildfire",
        "description": "Gunnison Valley wildfire-watch planning and AOR overlays.",
        "retrieval_mode": "local_wildfire_watch_planning_overlay",
        "rights": "operator_owned_planning_metadata",
        "caveats": [
            "No dispatch, alert send, flight authorization, or drone action is enabled.",
            "Live public fire perimeter ingestion is a pending adapter, not an implied feed.",
        ],
    },
    {
        "layer_id": "source_health",
        "label": "Source Health",
        "category": "readiness",
        "description": "Per-source freshness, empty-state, and manual-adapter posture.",
        "retrieval_mode": "stored_snapshot_source_health",
        "rights": "operational_metadata",
    },
    {
        "layer_id": "readiness_boundary",
        "label": "Boundaries",
        "category": "readiness",
        "description": "Read-only operating constraints for public and wildfire work.",
        "retrieval_mode": "policy_contract",
        "rights": "operator_owned_policy_metadata",
    },
]

ALLOWED_LAYER_IDS = {item["layer_id"] for item in LAYER_DEFINITIONS}


def _selected_layer_ids(layers: str | None) -> set[str]:
    if not layers:
        return set(DEFAULT_COMMAND_LAYERS)
    selected = {
        clean_text(value).lower()
        for value in layers.split(",")
        if clean_text(value).lower() in ALLOWED_LAYER_IDS
    }
    return selected or set(DEFAULT_COMMAND_LAYERS)


def _region_allowed(item_region: RegionId | None, region: RegionId | None) -> bool:
    return region is None or item_region == region


def _region_by_id(snapshot: RegionalIntelSnapshot, region: RegionId | None):
    if region is not None:
        return next((item for item in snapshot.regions if item.id == region), None)
    return next(
        (item for item in snapshot.regions if item.id == "gunnison_valley_co"), None
    ) or (snapshot.regions[0] if snapshot.regions else None)


def _center_from_bbox(bbox: list[float]) -> tuple[float, float]:
    if len(bbox) != 4:
        return 39.0, -98.0
    south, west, north, east = bbox
    return (south + north) / 2.0, (west + east) / 2.0


def _clamp_float(
    value: float | None, *, default: float, minimum: float, maximum: float
) -> float:
    if value is None or not math.isfinite(value):
        return default
    return max(minimum, min(maximum, value))


def _severity(score: float) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _intel_url(
    kind: str, item_id: str | None, region_id: RegionId | None
) -> str | None:
    if not item_id:
        return None
    params = [f"detail_kind={kind}", f"detail_id={item_id}"]
    if region_id:
        params.append(f"region={region_id}")
    return f"/intel?{'&'.join(params)}"


def _source_ids_for_layer(snapshot: RegionalIntelSnapshot, layer_id: str) -> list[str]:
    category_by_layer = {
        "regional_news": "news",
        "development_permits": "permit",
        "businesses": "business",
        "public_contacts": "contacts",
    }
    category = category_by_layer.get(layer_id)
    if category is None:
        return []
    return [item.source_key for item in snapshot.sources if item.category == category]


def _entity(
    *,
    entity_id: str,
    layer_id: str,
    kind: str,
    title: str,
    region_id: RegionId | None,
    summary: str = "",
    lat: float | None = None,
    lon: float | None = None,
    score: float = 0.0,
    source_name: str = "",
    source_url: str | None = None,
    intel_url: str | None = None,
    tags: list[str] | None = None,
    facts: dict[str, str] | None = None,
    notes: list[str] | None = None,
) -> CommandSurfaceEntity:
    return CommandSurfaceEntity(
        entity_id=entity_id,
        layer_id=layer_id,
        kind=kind,
        region_id=region_id,
        title=title,
        summary=summary,
        lat=lat if lat is None or math.isfinite(lat) else None,
        lon=lon if lon is None or math.isfinite(lon) else None,
        score=round(float(score or 0), 2),
        severity=_severity(float(score or 0)),
        source_name=source_name,
        source_url=source_url,
        intel_url=intel_url,
        tags=[clean_text(item) for item in tags or [] if clean_text(item)],
        facts={key: clean_text(value) for key, value in (facts or {}).items()},
        notes=[clean_text(item) for item in notes or [] if clean_text(item)],
    )


def _business_coordinate_index(
    snapshot: RegionalIntelSnapshot,
) -> dict[tuple[RegionId, str], tuple[float, float]]:
    coords: dict[tuple[RegionId, str], tuple[float, float]] = {}
    for item in snapshot.businesses:
        if item.lat is None or item.lon is None:
            continue
        if not math.isfinite(item.lat) or not math.isfinite(item.lon):
            continue
        coords.setdefault(
            (item.region_id, clean_text(item.name).lower()), (item.lat, item.lon)
        )
    return coords


def _snapshot_entities(
    snapshot: RegionalIntelSnapshot, region: RegionId | None
) -> list[CommandSurfaceEntity]:
    coords = _business_coordinate_index(snapshot)
    entities: list[CommandSurfaceEntity] = []

    for news_item in snapshot.news:
        if not _region_allowed(news_item.region_id, region):
            continue
        entities.append(
            _entity(
                entity_id=f"news:{news_item.item_id}",
                layer_id="regional_news",
                kind="news",
                title=news_item.title,
                region_id=news_item.region_id,
                summary=news_item.address_hint or news_item.summary,
                score=news_item.signal_score,
                source_name=news_item.source_name,
                source_url=news_item.source_url,
                intel_url=_intel_url("news", news_item.item_id, news_item.region_id),
                tags=[
                    news_item.signal_type,
                    "actionable" if news_item.actionable else "",
                ],
                facts={
                    "publication": news_item.publication or news_item.source_name,
                    "published": news_item.published_at,
                },
            )
        )

    for permit in snapshot.permits:
        if not _region_allowed(permit.region_id, region):
            continue
        entities.append(
            _entity(
                entity_id=f"permit:{permit.item_id}",
                layer_id="development_permits",
                kind="permit",
                title=permit.address,
                region_id=permit.region_id,
                summary=" | ".join(
                    part
                    for part in [
                        permit.county,
                        permit.permit_type,
                        permit.status,
                        permit.permit_number,
                    ]
                    if part
                ),
                score=permit.signal_score,
                source_name=permit.source_name,
                source_url=permit.source_url,
                intel_url=_intel_url("permit", permit.item_id, permit.region_id),
                tags=[permit.signal_type, permit.status],
                facts={
                    "permit": permit.permit_number,
                    "status_date": permit.status_date,
                },
            )
        )

    for business in snapshot.businesses:
        if not _region_allowed(business.region_id, region):
            continue
        entities.append(
            _entity(
                entity_id=f"business:{business.item_id}",
                layer_id="businesses",
                kind="business",
                title=business.name,
                region_id=business.region_id,
                summary=business.address or business.category,
                lat=business.lat,
                lon=business.lon,
                score=business.lead_score,
                source_name=business.source_name,
                source_url=business.website or business.source_url,
                intel_url=_intel_url("business", business.item_id, business.region_id),
                tags=[business.category],
                facts={
                    "address": business.address,
                    "website": business.website or "",
                },
            )
        )

    for org in snapshot.organizations:
        if not _region_allowed(org.region_id, region):
            continue
        lat_lon = coords.get((org.region_id, clean_text(org.name).lower()))
        entities.append(
            _entity(
                entity_id=f"organization:{org.item_id}",
                layer_id="organizations",
                kind="organization",
                title=org.name,
                region_id=org.region_id,
                summary=", ".join(org.categories[:3])
                or org.address
                or "Organization profile",
                lat=lat_lon[0] if lat_lon else None,
                lon=lat_lon[1] if lat_lon else None,
                score=org.organization_score,
                source_name=", ".join(org.source_names[:2]) or "Regional graph",
                source_url=org.website,
                intel_url=_intel_url("organization", org.item_id, org.region_id),
                tags=org.categories[:5],
                facts={
                    "signals": str(
                        org.business_lead_count
                        + org.news_signal_count
                        + org.contact_count
                        + org.permit_signal_count
                    ),
                    "contacts": str(org.contact_count),
                    "permits": str(org.permit_signal_count),
                },
            )
        )

    for contact in snapshot.contacts:
        if not _region_allowed(contact.region_id, region):
            continue
        lat_lon = coords.get(
            (contact.region_id, clean_text(contact.organization).lower())
        )
        entities.append(
            _entity(
                entity_id=f"contact:{contact.item_id}",
                layer_id="public_contacts",
                kind="contact",
                title=contact.name,
                region_id=contact.region_id,
                summary=" | ".join(
                    part for part in [contact.title, contact.organization] if part
                ),
                lat=lat_lon[0] if lat_lon else None,
                lon=lat_lon[1] if lat_lon else None,
                score=contact.contact_score,
                source_name=contact.source_name,
                source_url=contact.website or contact.source_url,
                intel_url=_intel_url("contact", contact.item_id, contact.region_id),
                tags=[contact.contact_type],
                facts={
                    "organization": contact.organization,
                    "contact": contact.email or contact.phone or contact.website or "",
                },
            )
        )

    for source in snapshot.source_health:
        if region is not None and source.region_ids and region not in source.region_ids:
            continue
        score_by_status = {"failed": 92, "empty": 66, "manual": 48, "live": 38}
        entities.append(
            _entity(
                entity_id=f"source:{source.source_key}",
                layer_id="source_health",
                kind="source",
                title=source.name,
                region_id=source.region_ids[0] if len(source.region_ids) == 1 else None,
                summary=f"{source.status} | {source.item_count} items",
                score=score_by_status.get(source.status, 50),
                source_name="Regional source catalog",
                source_url=None,
                tags=[source.category, source.status],
                facts={
                    "source_key": source.source_key,
                    "last_seen": source.last_seen_at or "not_seen",
                },
                notes=source.notes,
            )
        )

    return entities


def _wildfire_entities(
    snapshot: RegionalIntelSnapshot, region: RegionId | None
) -> list[CommandSurfaceEntity]:
    if region is not None and region != "gunnison_valley_co":
        return []
    gunnison = next(
        (item for item in snapshot.regions if item.id == "gunnison_valley_co"), None
    )
    if gunnison is None:
        return []

    lat, lon = _center_from_bbox(gunnison.bbox)
    gunnison_counts = {
        "news": len(
            [item for item in snapshot.news if item.region_id == "gunnison_valley_co"]
        ),
        "businesses": len(
            [
                item
                for item in snapshot.businesses
                if item.region_id == "gunnison_valley_co"
            ]
        ),
        "organizations": len(
            [
                item
                for item in snapshot.organizations
                if item.region_id == "gunnison_valley_co"
            ]
        ),
        "sources": len(
            [
                item
                for item in snapshot.source_health
                if "gunnison_valley_co" in item.region_ids
            ]
        ),
    }
    return [
        _entity(
            entity_id="wildfire:gunnison_valley_aor",
            layer_id="wildfire_watch",
            kind="wildfire_aor",
            title="Gunnison Valley Wildfire Watch AOR",
            region_id="gunnison_valley_co",
            summary="Operator-owned wildfire-watch planning overlay for the Gunnison / Crested Butte corridor.",
            lat=lat,
            lon=lon,
            score=82,
            source_name="wildfire-watch local planning layer",
            source_url=None,
            intel_url="/intel?region=gunnison_valley_co&layers=wildfire_watch,source_health,businesses,regional_news",
            tags=["aor", "planning", "read_only"],
            facts={key: str(value) for key, value in gunnison_counts.items()},
            notes=[
                "This is an integration overlay, not live incident command.",
                "Use sourced regional context before any field or partner action.",
            ],
        ),
        _entity(
            entity_id="wildfire:adapter_readiness",
            layer_id="wildfire_watch",
            kind="adapter_readiness",
            title="Wildfire Public Perimeter Adapter",
            region_id="gunnison_valley_co",
            summary="Adapter slot for official public fire perimeter and incident feeds.",
            score=64,
            source_name="wildfire-watch integration plan",
            source_url=None,
            tags=["adapter_pending", "official_sources_required"],
            facts={
                "output_policy": "derived_analysis_only",
                "side_effects": "none",
            },
            notes=[
                "Connect only official/public sources with license and output-policy metadata.",
                "Do not treat payment or access as permission to resell raw feeds.",
            ],
        ),
    ]


def _guardrails() -> list[CommandSurfaceGuardrail]:
    return [
        CommandSurfaceGuardrail(
            key="read_only",
            label="Read-only surface",
            status="enforced",
            detail="The command surface reads stored/public-source intelligence and performs no external writes.",
        ),
        CommandSurfaceGuardrail(
            key="public_sources",
            label="Public-source provenance",
            status="enforced",
            detail="Regional records retain source names and source URLs for analyst verification.",
        ),
        CommandSurfaceGuardrail(
            key="wildfire_boundary",
            label="Wildfire planning only",
            status="enforced",
            detail="No dispatch, drone authorization, alert send, or incident-command action is exposed.",
        ),
        CommandSurfaceGuardrail(
            key="external_sends",
            label="No external sends",
            status="enforced",
            detail="No Telegram, customer, market, or partner notifications are triggered by this view.",
        ),
    ]


def build_command_surface(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
    layers: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    zoom: float | None = None,
) -> CommandSurfacePayload:
    selected_layers = _selected_layer_ids(layers)
    viewport_region = _region_by_id(snapshot, region)
    default_lat, default_lon = (
        _center_from_bbox(viewport_region.bbox)
        if viewport_region is not None
        else (39.0, -98.0)
    )
    default_zoom = 8.0 if region else 4.0
    bbox = (
        viewport_region.bbox
        if viewport_region is not None
        else [24.0, -125.0, 49.5, -66.5]
    )

    all_entities = _snapshot_entities(snapshot, region) + _wildfire_entities(
        snapshot, region
    )
    layer_counts = Counter(item.layer_id for item in all_entities)
    visible_entities = [
        item for item in all_entities if item.layer_id in selected_layers
    ]
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    feed = sorted(
        visible_entities,
        key=lambda item: (
            -severity_rank.get(item.severity, 0),
            -item.score,
            item.layer_id,
            item.title.lower(),
        ),
    )[:40]

    layers_payload = [
        CommandSurfaceLayer(
            **definition,
            enabled=definition["layer_id"] in selected_layers,
            count=layer_counts.get(definition["layer_id"], 0),
            source_ids=_source_ids_for_layer(snapshot, definition["layer_id"]),
            status="available"
            if layer_counts.get(definition["layer_id"], 0) > 0
            else "pending",
        )
        for definition in LAYER_DEFINITIONS
    ]
    source_summary = Counter(item.status for item in snapshot.source_health)
    source_summary["total"] = len(snapshot.source_health)

    return CommandSurfacePayload(
        updated_at=snapshot.updated_at,
        region=region,
        viewport=CommandSurfaceViewport(
            center_lat=round(
                _clamp_float(lat, default=default_lat, minimum=-90, maximum=90), 6
            ),
            center_lon=round(
                _clamp_float(lon, default=default_lon, minimum=-180, maximum=180), 6
            ),
            zoom=round(
                _clamp_float(zoom, default=default_zoom, minimum=1, maximum=16), 2
            ),
            bbox=bbox,
        ),
        layers=layers_payload,
        entities=visible_entities,
        feed=feed,
        guardrails=_guardrails(),
        source_summary=dict(source_summary),
        notes=[
            "Inspired by layered OSINT map workbenches, but implemented as a rights-cleared Regional Intel command surface.",
            "Wildfire Watch appears as a read-only planning overlay until official live perimeter adapters are wired.",
        ],
    )
