from __future__ import annotations

import json
import re
from datetime import UTC
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from typing import Literal

from app.intel_models import FieldOpsAction
from app.intel_models import FieldOpsAsset
from app.intel_models import FieldOpsExternalReference
from app.intel_models import FieldOpsLayer
from app.intel_models import FieldOpsLandmark
from app.intel_models import FieldOpsMetric
from app.intel_models import FieldOpsPosture
from app.intel_models import FieldOpsSignal
from app.intel_models import FieldOpsSnapshot
from app.intel_models import FieldOpsSource
from app.intel_models import FieldOpsWeatherGate
from app.intel_models import FieldOpsZone
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot


REPO_ROOT = Path(__file__).resolve().parents[2]
FIELD_OPS_DATA_DIR = REPO_ROOT / "data" / "field_ops"
WILDFIRE_SIGNALS_PATH = FIELD_OPS_DATA_DIR / "wildfire_watch_signals.jsonl"
WILDFIRE_ZONES_PATH = FIELD_OPS_DATA_DIR / "wildfire_watch_zones.geojson"
KIMI_READINESS_PATH = FIELD_OPS_DATA_DIR / "kimi_uas_readiness.json"
AOR_LANDMARKS_PATH = FIELD_OPS_DATA_DIR / "aor_landmarks.json"
EXTERNAL_REFERENCES_PATH = FIELD_OPS_DATA_DIR / "external_references.json"
FIELD_OPS_SCHEMA_ID = "regional_intel.field_ops.v1"

FieldSeverity = Literal["low", "medium", "high", "critical"]
AssetStatus = Literal[
    "ready",
    "needs_live_check",
    "not_connected",
    "reference_only",
    "bench_verified",
    "field_verified",
    "offline",
]
WeatherGateStatus = Literal["requires_live_sensor", "ready", "blocked", "review"]
ZoneType = Literal["mission_zone", "exclusion", "coordination"]
HTML_TAG_RE = re.compile(r"<[^>]+>")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _coords_from_feature(feature: dict[str, Any]) -> list[tuple[float, float]]:
    geometry = feature.get("geometry") or {}
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        return []
    rings = geometry.get("coordinates") or []
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        return []
    coords: list[tuple[float, float]] = []
    for pair in rings[0]:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        lon = float(pair[0])
        lat = float(pair[1])
        coords.append((lat, lon))
    return coords


def _bbox(coords: list[tuple[float, float]]) -> list[float]:
    if not coords:
        return [0.0, 0.0, 0.0, 0.0]
    lats = [item[0] for item in coords]
    lons = [item[1] for item in coords]
    return [min(lats), min(lons), max(lats), max(lons)]


def _centroid(coords: list[tuple[float, float]]) -> list[float]:
    if not coords:
        return [0.0, 0.0]
    return [
        round(sum(item[0] for item in coords) / len(coords), 6),
        round(sum(item[1] for item in coords) / len(coords), 6),
    ]


def _label_from_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-"))


def _display_text(value: str | None) -> str:
    text = unescape(value or "")
    text = HTML_TAG_RE.sub(" ", text)
    return " ".join(text.split())


def _severity(risk_score: float) -> FieldSeverity:
    if risk_score >= 90:
        return "critical"
    if risk_score >= 65:
        return "high"
    if risk_score >= 35:
        return "medium"
    return "low"


def _asset_status(value: Any) -> AssetStatus:
    if value in {
        "ready",
        "needs_live_check",
        "not_connected",
        "reference_only",
        "bench_verified",
        "field_verified",
        "offline",
    }:
        return value
    return "reference_only"


def _weather_gate_status(value: Any) -> WeatherGateStatus:
    if value in {"requires_live_sensor", "ready", "blocked", "review"}:
        return value
    return "review"


def _safe_action_label(action: str) -> str:
    labels = {
        "notify_fire_dept": "Human review only: fire-dept notification not sent",
        "notify_operator": "Queue for operator review, no external notification sent",
        "loiter_and_capture": "Planning-only recommendation, no loiter command sent",
        "rtl": "Planning-only recommendation, no return-to-launch command sent",
        "log_only": "Log and retain for trend review",
    }
    return labels.get(action, "Human review only, no external action sent")


def _build_sources() -> list[FieldOpsSource]:
    return [
        FieldOpsSource(
            source_id="regional_intel_snapshot",
            owner="Regional Intelligence Workbench",
            title="Public-source regional intelligence snapshot",
            source_url="/api/intel/snapshot?region=gunnison_valley_co",
            retrieval_mode="local_snapshot_read",
            retrieved_at=_now_iso(),
            license_or_rights=(
                "Derived from public-source catalog with source URLs retained per item."
            ),
            freshness_ttl=(
                "Cache governed by RegionalIntelSnapshot.cache_ttl_seconds."
            ),
            output_policy="Expose derived summaries, counts, links, and provenance only.",
            caveats=[
                "Some public-source adapters are manual-reference pending.",
                "Human verification is required before outreach, publication, or operational use.",
            ],
        ),
        FieldOpsSource(
            source_id="wildfire_watch_fixture",
            owner="wildfire-watch",
            title="Wildfire-watch signal fixture and schema-derived sample events",
            source_url="local://wildfire-watch/frontend/fixtures/signals.jsonl",
            retrieval_mode="local_reference_fixture",
            retrieved_at="2026-05-20T00:00:00Z",
            license_or_rights=(
                "Workspace-owned reference material; preserve schema provenance "
                "and do not resell raw fixture payloads."
            ),
            freshness_ttl="Static fixture until a live adapter is explicitly authorized.",
            output_policy=(
                "Expose derived planning signals and source IDs; no dispatch or command fan-out."
            ),
            caveats=[
                "Fixture timestamps are historical demo data.",
                "recommended_action values are deliberately converted to safe review labels.",
            ],
        ),
        FieldOpsSource(
            source_id="wildfire_watch_aor",
            owner="wildfire-watch",
            title="Gunnison-Crested Butte wildfire-watch AOR zones",
            source_url=(
                "local://wildfire-watch/missions/zones/"
                "gunnison_crested_butte_corridor.geojson"
            ),
            retrieval_mode="local_reference_geojson",
            retrieved_at="2026-05-20T00:00:00Z",
            license_or_rights=(
                "Workspace-owned planning reference; authoritative legal boundaries "
                "must come from agencies before flight."
            ),
            freshness_ttl="Static reference until replaced by authoritative GIS.",
            output_policy="Expose simplified zones as planning overlays with caveats.",
            caveats=[
                "Wilderness exclusion polygon is a simplified bounding box.",
                "FAA/TFR/LAANC status is not live in this payload.",
            ],
        ),
        FieldOpsSource(
            source_id="kimi_uas_readiness",
            owner="Ari / Kimi research packet",
            title="Kimi UAS architecture, weather-station, and shopping-list research",
            source_url="local://Kimi_Agent_Amazon Shopping List.zip",
            retrieval_mode="uploaded_zip_summary",
            retrieved_at="2026-05-20T00:00:00Z",
            license_or_rights=(
                "User-provided research packet; output is a derived readiness model, "
                "not a reproduced raw report."
            ),
            freshness_ttl=(
                "Static research packet; hardware prices and legal details require "
                "current verification."
            ),
            output_policy=(
                "Expose derived readiness gates, architecture boundaries, and operator TODOs."
            ),
            caveats=[
                "No root, DJI SDK, LoRa, or virtual-stick commands are exposed by this workbench.",
                (
                    "Hardware availability, pricing, FAA/TFR/LAANC, and RF compliance "
                    "must be checked live by the operator."
                ),
            ],
        ),
        FieldOpsSource(
            source_id="wildfire_watch_aor_landmarks",
            owner="wildfire-watch",
            title="Gunnison / Crested Butte AOR orientation landmarks",
            source_url="local://regional-intel-workbench/data/field_ops/aor_landmarks.json",
            retrieval_mode="local_reference_landmarks",
            retrieved_at="2026-05-20T00:00:00Z",
            license_or_rights=(
                "Workspace-owned derived planning markers; coordinates are approximate "
                "orientation anchors and not surveyed operational positions."
            ),
            freshness_ttl="Static reference until replaced by authoritative GIS/geocoding.",
            output_policy=(
                "Expose labels, approximate coordinates, orientation summaries, and caveats."
            ),
            caveats=[
                "Do not use landmark coordinates as flight-control or dispatch coordinates.",
                "Public-safety markers do not imply permission to notify or contact agencies.",
            ],
        ),
        FieldOpsSource(
            source_id="osiris_and_onchain_reference",
            owner="Public web / block explorers",
            title="OSIRIS public app pattern and provided on-chain address context",
            source_url="https://www.osirisai.live/?lat=46.2030&lon=24.5298&zoom=6.50&layers=cctv%2Clive_news%2Cearthquakes%2Cglobal_incidents%2Cday_night",
            retrieval_mode="public_reference_review",
            retrieved_at="2026-05-20T21:17:53Z",
            license_or_rights=(
                "External public reference material; local system stores derived pattern "
                "notes and explorer summaries only."
            ),
            freshness_ttl="Verify live before relying on external app or explorer state.",
            output_policy=(
                "Expose reference URL, layer taxonomy, and cautious explorer facts; no "
                "private data, credentials, or external writes."
            ),
            caveats=[
                "OSIRIS is a design/source-pattern reference, not a dependency for this API.",
                (
                    "The provided address is treated as an unverified EOA context marker, "
                    "not as authority or ownership evidence."
                ),
            ],
        ),
    ]


def _build_zones(region_id: RegionId) -> list[FieldOpsZone]:
    payload = _read_json(WILDFIRE_ZONES_PATH)
    zones: list[FieldOpsZone] = []
    for feature in payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        zone_id = str(props.get("zone_id") or "unknown-zone")
        coords = _coords_from_feature(feature)
        regulatory_basis = props.get("regulatory_basis")
        zone_type: ZoneType = "mission_zone"
        if props.get("exclusion"):
            zone_type = "exclusion"
        elif regulatory_basis and "LAANC" in str(regulatory_basis).upper():
            zone_type = "coordination"
        zones.append(
            FieldOpsZone(
                zone_id=zone_id,
                label=_label_from_id(zone_id),
                region_id=region_id,
                zone_type=zone_type,
                bbox=_bbox(coords),
                centroid=_centroid(coords),
                geometry=dict(feature.get("geometry") or {}),
                fuel_load_class=props.get("fuel_load_class"),
                primary_risk=props.get("primary_risk"),
                phase=props.get("phase"),
                regulatory_basis=regulatory_basis,
                source_id="wildfire_watch_aor",
                notes=[
                    str(value)
                    for value in [props.get("note"), payload.get("description")]
                    if value
                ],
            )
        )
    return zones


def _build_signals(region_id: RegionId) -> list[FieldOpsSignal]:
    rows = _read_jsonl(WILDFIRE_SIGNALS_PATH)
    signals: list[FieldOpsSignal] = []
    for row in rows:
        coords = row.get("coords") or {}
        target = row.get("target_coords") or {}
        if not isinstance(coords, dict):
            coords = {}
        if not isinstance(target, dict):
            target = {}
        signal_type = str(row.get("signal_type") or "unknown")
        risk_score = float(row.get("risk_score") or 0)
        action = str(row.get("recommended_action") or "log_only")
        zone_id = str(row.get("zone_id") or "unknown-zone")
        title = f"{signal_type.replace('_', ' ').title()} in {_label_from_id(zone_id)}"
        evidence = row.get("evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}
        frame_uris = [
            str(value)
            for value in evidence.get("frame_uris", [])
            if isinstance(value, str)
        ]
        notes = [
            "This is wildfire-watch fixture/demo data, not a live incident feed.",
            "No operational alert or drone command is sent from this workbench.",
        ]
        if action == "notify_fire_dept":
            notes.append(
                "Original fixture recommended fire-dept notification; this API "
                "downgrades it to human review only."
            )
        signals.append(
            FieldOpsSignal(
                signal_id=str(row.get("signal_id")),
                region_id=region_id,
                zone_id=zone_id,
                signal_type=signal_type,
                title=title,
                summary=(
                    f"Risk {risk_score:.1f}, "
                    f"confidence {float(row.get('confidence') or 0):.2f}, "
                    f"drone {row.get('drone_id') or 'unknown'}."
                ),
                timestamp=str(row.get("timestamp") or ""),
                lat=float(target.get("lat") or coords.get("lat") or 0),
                lon=float(target.get("lon") or coords.get("lon") or 0),
                target_lat=(
                    float(target["lat"]) if target.get("lat") is not None else None
                ),
                target_lon=(
                    float(target["lon"]) if target.get("lon") is not None else None
                ),
                confidence=float(row.get("confidence") or 0),
                risk_score=risk_score,
                severity=_severity(risk_score),
                recommended_action=action,
                safe_action_label=_safe_action_label(action),
                source_id="wildfire_watch_fixture",
                source_url="local://wildfire-watch/frontend/fixtures/signals.jsonl",
                evidence_refs=frame_uris,
                notes=notes,
            )
        )
    return sorted(
        signals, key=lambda item: (item.timestamp, item.risk_score), reverse=True
    )


def _build_kimi_assets() -> tuple[list[FieldOpsAsset], list[FieldOpsWeatherGate]]:
    payload = _read_json(KIMI_READINESS_PATH)
    architecture = payload.get("architecture") or {}
    if not isinstance(architecture, dict):
        architecture = {}
    assets: list[FieldOpsAsset] = []
    for item in payload.get("assets", []):
        if not isinstance(item, dict):
            continue
        props = item.get("properties") if item.get("type") == "Feature" else item
        if not isinstance(props, dict):
            props = {}
        geometry = item.get("geometry") if item.get("type") == "Feature" else {}
        if not isinstance(geometry, dict):
            geometry = {}
        point_coords = (
            geometry.get("coordinates") if geometry.get("type") == "Point" else None
        )
        lon = props.get("lon")
        lat = props.get("lat")
        if isinstance(point_coords, list) and len(point_coords) >= 2:
            lon = point_coords[0]
            lat = point_coords[1]
        assets.append(
            FieldOpsAsset(
                asset_id=str(props.get("asset_id")),
                label=str(props.get("label") or props.get("asset_id")),
                layer=str(props.get("layer") or "uas_readiness"),
                status=_asset_status(props.get("status")),
                summary=str(props.get("summary") or ""),
                lat=lat,
                lon=lon,
                geometry=geometry,
                comms_link=props.get("comms_link"),
                last_update_utc=props.get("last_update_utc"),
                readiness=dict(props.get("readiness") or {}),
                source_id="kimi_uas_readiness",
                notes=[
                    str(architecture.get("control_boundary") or ""),
                    "Reference-only until hardware is connected and separately authorized.",
                ],
            )
        )

    weather_gates: list[FieldOpsWeatherGate] = []
    for item in payload.get("weather_gates", []):
        if not isinstance(item, dict):
            continue
        weather_gates.append(
            FieldOpsWeatherGate(
                gate_id=str(item.get("gate_id")),
                label=str(item.get("label")),
                status=_weather_gate_status(item.get("status")),
                threshold=str(item.get("threshold")),
                summary=str(item.get("summary")),
                source_id="kimi_uas_readiness",
                notes=[
                    "Displayed as a readiness gate, not a live sensor reading.",
                    "Connect and verify hardware before treating this as operational.",
                ],
            )
        )
    return assets, weather_gates


def _build_landmarks() -> list[FieldOpsLandmark]:
    payload = _read_json(AOR_LANDMARKS_PATH)
    landmarks: list[FieldOpsLandmark] = []
    for item in payload.get("landmarks", []):
        if not isinstance(item, dict):
            continue
        notes = [
            str(payload.get("description") or ""),
            "Approximate planning marker; not an authoritative operational coordinate.",
        ]
        landmarks.append(
            FieldOpsLandmark(
                landmark_id=str(item.get("landmark_id")),
                label=str(item.get("label")),
                kind=str(item.get("kind")),
                lat=float(item.get("lat") or 0),
                lon=float(item.get("lon") or 0),
                elevation_m=(
                    int(item["elevation_m"])
                    if item.get("elevation_m") is not None
                    else None
                ),
                summary=str(item.get("summary") or ""),
                source_id="wildfire_watch_aor_landmarks",
                notes=notes,
            )
        )
    return landmarks


def _build_external_references() -> list[FieldOpsExternalReference]:
    payload = _read_json(EXTERNAL_REFERENCES_PATH)
    references: list[FieldOpsExternalReference] = []
    for item in payload.get("references", []):
        if not isinstance(item, dict):
            continue
        references.append(
            FieldOpsExternalReference(
                reference_id=str(item.get("reference_id")),
                label=str(item.get("label")),
                kind=str(item.get("kind")),
                status=str(item.get("status")),
                summary=str(item.get("summary") or ""),
                source_id="osiris_and_onchain_reference",
                source_url=item.get("source_url"),
                lat=item.get("lat"),
                lon=item.get("lon"),
                facts=dict(item.get("facts") or {}),
                notes=[str(note) for note in item.get("notes", [])],
            )
        )
    return references


def _regional_context(
    snapshot: RegionalIntelSnapshot, region_id: RegionId
) -> list[dict[str, Any]]:
    region = next((item for item in snapshot.regions if item.id == region_id), None)
    briefs = [item for item in snapshot.briefs if item.region_id == region_id]
    sources = [
        item
        for item in snapshot.source_health
        if not item.region_ids or region_id in item.region_ids
    ]
    news = [item for item in snapshot.news if item.region_id == region_id]
    permits = [item for item in snapshot.permits if item.region_id == region_id]
    organizations = [
        item for item in snapshot.organizations if item.region_id == region_id
    ]
    items: list[dict[str, Any]] = [
        {
            "context_id": "regional_summary",
            "title": region.name if region else "Selected region",
            "summary": (
                region.summary
                if region
                else "Regional context was not found in the current snapshot."
            ),
            "kind": "region",
            "score": None,
            "source_url": "/api/intel/snapshot?region=gunnison_valley_co",
        },
        {
            "context_id": "source_health",
            "title": "Regional source-health coverage",
            "summary": (
                f"{sum(item.item_count for item in sources)} source items across "
                f"{len(sources)} configured public sources."
            ),
            "kind": "source_health",
            "score": None,
            "source_url": "/api/intel/source-health?region=gunnison_valley_co",
        },
    ]
    if briefs:
        items.append(
            {
                "context_id": "region_brief",
                "title": briefs[0].headline,
                "summary": briefs[0].summary,
                "kind": "brief",
                "score": None,
                "source_url": "/api/intel/briefs?region=gunnison_valley_co",
            }
        )
    for news_item in sorted(
        news, key=lambda news_item: news_item.signal_score, reverse=True
    )[:2]:
        items.append(
            {
                "context_id": news_item.item_id,
                "title": _display_text(news_item.title),
                "summary": _display_text(news_item.summary),
                "kind": "news",
                "score": news_item.signal_score,
                "source_url": news_item.source_url,
            }
        )
    for permit_item in sorted(
        permits, key=lambda permit: permit.signal_score, reverse=True
    )[:1]:
        items.append(
            {
                "context_id": permit_item.item_id,
                "title": permit_item.address,
                "summary": (
                    f"{permit_item.county} {permit_item.permit_type} "
                    f"{permit_item.status}"
                ),
                "kind": "permit",
                "score": permit_item.signal_score,
                "source_url": permit_item.source_url,
            }
        )
    for org_item in sorted(
        organizations, key=lambda org: org.organization_score, reverse=True
    )[:2]:
        items.append(
            {
                "context_id": org_item.item_id,
                "title": org_item.name,
                "summary": ", ".join(org_item.categories[:3])
                or "Regional organization profile",
                "kind": "organization",
                "score": org_item.organization_score,
                "source_url": org_item.website,
            }
        )
    return items


def _build_metrics(
    *,
    zones: list[FieldOpsZone],
    signals: list[FieldOpsSignal],
    assets: list[FieldOpsAsset],
    landmarks: list[FieldOpsLandmark],
    weather_gates: list[FieldOpsWeatherGate],
) -> list[FieldOpsMetric]:
    non_heartbeat = [item for item in signals if item.signal_type != "system_event"]
    critical = [item for item in signals if item.severity in {"high", "critical"}]
    exclusions = [item for item in zones if item.zone_type == "exclusion"]
    return [
        FieldOpsMetric(
            label="Wildfire signals",
            value=str(len(non_heartbeat)),
            detail=f"{len(critical)} high/critical fixture signals require review.",
            status="review" if critical else "safe",
        ),
        FieldOpsMetric(
            label="Mission zones",
            value=str(sum(item.zone_type == "mission_zone" for item in zones)),
            detail=f"{len(exclusions)} hard exclusion overlay retained.",
            status="ready",
        ),
        FieldOpsMetric(
            label="UAS assets",
            value=str(len(assets)),
            detail="Hardware is readiness state only; no command path exists here.",
            status="safe",
        ),
        FieldOpsMetric(
            label="Map anchors",
            value=str(len(landmarks)),
            detail="AOR landmarks now orient the basemap, zones, and signal layer.",
            status="ready",
        ),
        FieldOpsMetric(
            label="Weather gates",
            value=str(len(weather_gates)),
            detail="All gates require live sensor verification before flight use.",
            status="review",
        ),
        FieldOpsMetric(
            label="External sends",
            value="0",
            detail="No fire-dept, Telegram, DJI, LoRa, or dispatch call is wired.",
            status="safe",
        ),
    ]


def _build_layers(
    *,
    zones: list[FieldOpsZone],
    signals: list[FieldOpsSignal],
    assets: list[FieldOpsAsset],
    landmarks: list[FieldOpsLandmark],
    regional_context: list[dict[str, Any]],
) -> list[FieldOpsLayer]:
    return [
        FieldOpsLayer(
            layer_id="regional-context",
            label="Regional graph",
            description=(
                "Public-source business, permitting, source-health, and brief context."
            ),
            item_count=len(regional_context),
            source_ids=["regional_intel_snapshot"],
        ),
        FieldOpsLayer(
            layer_id="wildfire-zones",
            label="Wildfire zones",
            description="Mission, exclusion, and coordination overlays from wildfire-watch.",
            item_count=len(zones),
            source_ids=["wildfire_watch_aor"],
        ),
        FieldOpsLayer(
            layer_id="wildfire-signals",
            label="Wildfire signals",
            description=(
                "Fixture wildfire-watch signal events converted into review-only intelligence."
            ),
            item_count=len(signals),
            source_ids=["wildfire_watch_fixture"],
        ),
        FieldOpsLayer(
            layer_id="uas-readiness",
            label="UAS readiness",
            description=(
                "Kimi-derived ground-station, LoRa, Starlink, payload, and weather model."
            ),
            item_count=len(assets),
            source_ids=["kimi_uas_readiness"],
        ),
        FieldOpsLayer(
            layer_id="aor-landmarks",
            label="AOR landmarks",
            description="Named towns, drainages, airport, and no-fly reference anchors.",
            item_count=len(landmarks),
            source_ids=["wildfire_watch_aor_landmarks"],
        ),
        FieldOpsLayer(
            layer_id="osiris-reference",
            label="OSIRIS reference",
            description=(
                "External public map pattern plus provided on-chain address context."
            ),
            item_count=2,
            source_ids=["osiris_and_onchain_reference"],
        ),
    ]


def _build_action_queue() -> list[FieldOpsAction]:
    return [
        FieldOpsAction(
            action_id="verify-live-weather",
            label="Wire live weather station into the readiness rail",
            status="safe_next_step",
            summary=(
                "BME280, rain, anemometer, DS18B20, and MCP3008 become useful "
                "after a live sensor readback route exists."
            ),
            source_ids=["kimi_uas_readiness"],
        ),
        FieldOpsAction(
            action_id="preserve-no-fly-boundaries",
            label="Replace simplified exclusion boxes with authoritative GIS",
            status="blocked_until_human",
            summary=(
                "The West Elk and airspace overlays are references until USFS/FAA "
                "sources are fetched and verified."
            ),
            source_ids=["wildfire_watch_aor"],
        ),
        FieldOpsAction(
            action_id="review-fire-signal",
            label="Review high-risk wildfire fixture signal",
            status="reference_only",
            summary=(
                "The demo fire signal stays in analyst review; this surface will not "
                "notify a fire department or command a drone."
            ),
            source_ids=["wildfire_watch_fixture"],
        ),
        FieldOpsAction(
            action_id="regional-public-context",
            label="Use Gunnison public-source context beside wildfire layers",
            status="safe_next_step",
            summary=(
                "Regional public-source briefs and source health explain where the "
                "wildfire layer is thin or stale."
            ),
            source_ids=["regional_intel_snapshot"],
        ),
    ]


def build_field_ops_snapshot(
    snapshot: RegionalIntelSnapshot,
    *,
    region_id: RegionId = "gunnison_valley_co",
) -> FieldOpsSnapshot:
    zones = _build_zones(region_id)
    signals = _build_signals(region_id)
    assets, weather_gates = _build_kimi_assets()
    landmarks = _build_landmarks()
    external_references = _build_external_references()
    regional_context = _regional_context(snapshot, region_id)
    region_name = next(
        (item.name for item in snapshot.regions if item.id == region_id),
        "Gunnison / Crested Butte Valley, Colorado",
    )
    sources = _build_sources()
    return FieldOpsSnapshot(
        generated_at=_now_iso(),
        region_id=region_id,
        region_name=region_name,
        posture=FieldOpsPosture(
            notes=[
                (
                    "This is a unified analyst workbench, not an incident-command, "
                    "dispatch, or flight-control system."
                ),
                (
                    "Wildfire/drone content is read-only planning intelligence until "
                    "explicit operator authorization and live compliance checks exist."
                ),
            ]
        ),
        metrics=_build_metrics(
            zones=zones,
            signals=signals,
            assets=assets,
            landmarks=landmarks,
            weather_gates=weather_gates,
        ),
        layers=_build_layers(
            zones=zones,
            signals=signals,
            assets=assets,
            landmarks=landmarks,
            regional_context=regional_context,
        ),
        zones=zones,
        signals=signals,
        assets=assets,
        landmarks=landmarks,
        weather_gates=weather_gates,
        external_references=external_references,
        regional_context=regional_context,
        action_queue=_build_action_queue(),
        sources=sources,
        provenance_summary={
            "schema_id": FIELD_OPS_SCHEMA_ID,
            "source_count": len(sources),
            "source_ids": [item.source_id for item in sources],
            "rights_posture": "derived_analysis_only",
            "source_url_required": True,
            "external_writes_allowed": False,
            "raw_payload_resale_allowed": False,
        },
        notes=[
            (
                "Built from current regional-intel snapshot data plus local Kimi and "
                "wildfire-watch reference materials."
            ),
            (
                "Hardware prices, FAA/TFR/LAANC state, RF compliance, and live source "
                "freshness are intentionally not guessed."
            ),
        ],
    )
