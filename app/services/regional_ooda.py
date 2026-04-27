from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.services.foundry_export import build_export_plan


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _region_allowed(region_id: RegionId | str, region: RegionId | None) -> bool:
    return region is None or region_id == region


def _snapshot_counts(snapshot: RegionalIntelSnapshot, *, region: RegionId | None) -> dict[str, int]:
    return {
        "regions": len([item for item in snapshot.regions if _region_allowed(item.id, region)]),
        "news": len([item for item in snapshot.news if _region_allowed(item.region_id, region)]),
        "permits": len([item for item in snapshot.permits if _region_allowed(item.region_id, region)]),
        "businesses": len([item for item in snapshot.businesses if _region_allowed(item.region_id, region)]),
        "contacts": len([item for item in snapshot.contacts if _region_allowed(item.region_id, region)]),
        "organizations": len([item for item in snapshot.organizations if _region_allowed(item.region_id, region)]),
    }


def _source_health_orientation(summary: dict[str, Any]) -> dict[str, Any]:
    by_status = dict(summary.get("by_status") or {})
    non_live = {status: count for status, count in by_status.items() if status != "live"}
    return {
        "status": "attention_needed" if non_live else "nominal",
        "non_live_statuses": non_live,
        "live_sources": by_status.get("live", 0),
        "total_sources": summary.get("total_sources", 0),
    }


def _provenance_orientation(dropped_rows: dict[str, Any]) -> dict[str, Any]:
    total = int(dropped_rows.get("total") or 0)
    return {
        "status": "blocked_rows_dropped" if total else "clear",
        "dropped_rows": total,
        "by_reason": dict(dropped_rows.get("by_reason") or {}),
    }


def _safe_act_recommendations(*, source_orientation: dict[str, Any], provenance_orientation: dict[str, Any]) -> list[dict[str, str]]:
    recommendations = [
        {
            "title": "Review high-score public-source signals locally",
            "rationale": "Use the stored snapshot and source links to validate context before any human outreach.",
            "mode": "read_only_recommendation",
        }
    ]
    if provenance_orientation["dropped_rows"]:
        recommendations.append(
            {
                "title": "Resolve missing provenance before export promotion",
                "rationale": "Guarded rows were excluded because source_name and/or source_url was missing.",
                "mode": "read_only_recommendation",
            }
        )
    if source_orientation["non_live_statuses"]:
        recommendations.append(
            {
                "title": "Inspect non-live source health before acting on gaps",
                "rationale": "A missing or empty source can make the local snapshot incomplete without invalidating sourced rows.",
                "mode": "read_only_recommendation",
            }
        )
    recommendations.append(
        {
            "title": "Keep external systems untouched from this packet",
            "rationale": "This packet is evidence and recommendations only; it performs no refreshes and no Foundry, GCS, BQ, or messaging writes.",
            "mode": "read_only_recommendation",
        }
    )
    return recommendations


def build_regional_ooda_packet(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
) -> dict[str, Any]:
    """Build a read-only regional OODA packet from an already-stored snapshot."""
    _, export_manifest = build_export_plan(snapshot, region=region, log_drops=False)
    source_orientation = _source_health_orientation(export_manifest["source_health_summary"])
    provenance_orientation = _provenance_orientation(export_manifest["dropped_rows"])
    recommendations = _safe_act_recommendations(
        source_orientation=source_orientation,
        provenance_orientation=provenance_orientation,
    )
    return {
        "schema_version": 1,
        "packet_type": "regional_ooda",
        "generated_at": _now_iso(),
        "snapshot_updated_at": snapshot.updated_at,
        "region": region,
        "constraints": {
            "read_only": True,
            "external_refresh": False,
            "external_writes": False,
            "safe_act_recommendations_only": True,
        },
        "observe": {
            "snapshot_counts": _snapshot_counts(snapshot, region=region),
            "export_object_types": export_manifest["object_types"],
            "dropped_rows": export_manifest["dropped_rows"],
            "source_health_summary": export_manifest["source_health_summary"],
        },
        "orient": {
            "source_health": source_orientation,
            "provenance": provenance_orientation,
            "policy": export_manifest["policy"],
        },
        "decide": {
            "recommendation_count": len(recommendations),
            "recommended_mode": "manual_review",
        },
        "act": {
            "recommendations": recommendations,
            "writes": [],
            "external_calls": [],
        },
    }
