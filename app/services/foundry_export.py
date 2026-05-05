from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.intel_models import BusinessLead
from app.intel_models import NewsSignal
from app.intel_models import OrganizationProfile
from app.intel_models import PermitSignal
from app.intel_models import PublicContact
from app.intel_models import RegionId
from app.intel_models import RegionProfile
from app.intel_models import RegionalIntelSnapshot
from app.intel_models import SourceHealth

logger = logging.getLogger(__name__)

OBJECT_FILES = {
    "Region": "Region.ndjson",
    "IntelItem": "IntelItem.ndjson",
    "IntelSourceHealth": "IntelSourceHealth.ndjson",
}

# Item kinds that MUST carry both source_name and source_url. Business and
# contact rows are validated by pydantic at ingestion (str fields, not Optional);
# news, permits, and organizations can slip through with empty/None provenance
# from upstream aggregators, so we guard them here before emission.
PROVENANCE_REQUIRED_KINDS = {"news", "permit", "organization"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(row))
            handle.write("\n")


def _region_allowed(region_id: RegionId | str, region: RegionId | None) -> bool:
    return region is None or region_id == region


def _source_policy(snapshot: RegionalIntelSnapshot) -> dict[str, Any]:
    return {
        "public_sources_only": True,
        "ethics_rules": [item.key for item in snapshot.ethics_rules],
        "notes": snapshot.notes,
    }


def region_objects(
    snapshot: RegionalIntelSnapshot, *, region: RegionId | None = None
) -> list[dict[str, Any]]:
    rows = []
    for item in snapshot.regions:
        if not _region_allowed(item.id, region):
            continue
        rows.append(_region_object(item, snapshot))
    return rows


def _region_object(
    item: RegionProfile, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    return {
        "object_id": f"regional-intel:region:{item.id}",
        "region_id": item.id,
        "name": item.name,
        "summary": item.summary,
        "bbox": item.bbox,
        "focus_keywords": item.focus_keywords,
        "source_keys": item.source_keys,
        "snapshot_updated_at": snapshot.updated_at,
        "notes": item.notes,
        "provenance": _source_policy(snapshot),
    }


def source_health_objects(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for item in snapshot.source_health:
        if region is not None and region not in item.region_ids:
            continue
        rows.append(_source_health_object(item, snapshot))
    return rows


def _source_health_object(
    item: SourceHealth, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    return {
        "object_id": f"regional-intel:source:{item.source_key}",
        "source_key": item.source_key,
        "name": item.name,
        "category": item.category,
        "region_ids": item.region_ids,
        "live_pull": item.live_pull,
        "status": item.status,
        "item_count": item.item_count,
        "last_seen_at": item.last_seen_at,
        "snapshot_updated_at": snapshot.updated_at,
        "notes": item.notes,
        "provenance": _source_policy(snapshot),
    }


def _has_provenance(row: dict[str, Any]) -> bool:
    """Return True iff the row carries a non-empty source_name and source_url."""
    name = row.get("source_name")
    url = row.get("source_url")
    return bool(name and str(name).strip()) and bool(url and str(url).strip())


def _empty_drop_report() -> dict[str, Any]:
    return {"total": 0, "by_reason": {}, "details": []}


def _record_drop(
    report: dict[str, Any],
    *,
    reason: str,
    row: dict[str, Any],
    missing_fields: list[str],
) -> None:
    report["total"] += 1
    report["by_reason"][reason] = report["by_reason"].get(reason, 0) + 1
    report["details"].append(
        {
            "reason": reason,
            "object_type": "IntelItem",
            "kind": row.get("kind"),
            "item_id": row.get("item_id"),
            "region_id": row.get("region_id"),
            "missing_fields": missing_fields,
        }
    )


def _drop_missing_provenance_with_report(
    rows: list[dict[str, Any]],
    *,
    log_drops: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop guarded item kinds without source_name + source_url; log/report each drop."""
    kept: list[dict[str, Any]] = []
    report = _empty_drop_report()
    for row in rows:
        kind = row.get("kind")
        if kind in PROVENANCE_REQUIRED_KINDS and not _has_provenance(row):
            missing_fields = [
                field
                for field in ("source_name", "source_url")
                if not (row.get(field) and str(row.get(field)).strip())
            ]
            _record_drop(
                report,
                reason="missing_provenance",
                row=row,
                missing_fields=missing_fields,
            )
            if log_drops:
                logger.warning(
                    "foundry_export: dropping %s item %s (region=%s) - missing provenance "
                    "(source_name=%r, source_url=%r)",
                    kind,
                    row.get("item_id"),
                    row.get("region_id"),
                    row.get("source_name"),
                    row.get("source_url"),
                )
            continue
        kept.append(row)
    return kept, report


def _drop_missing_provenance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _drop_missing_provenance_with_report(rows)[0]


def _canonical_json(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def _ndjson_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(f"{_canonical_json(row)}\n" for row in rows).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _row_hash(row: dict[str, Any]) -> str:
    """Stable secondary sort key for byte-identical NDJSON across runs.

    Same content => same hash, so two equal rows from different Python runs
    sort identically. Salts the hash with the canonical JSON representation
    used at write time.
    """
    return _sha256_bytes(_canonical_json(row).encode("utf-8"))


def _row_hash_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "object_id": row.get("object_id"),
            "sha256": _row_hash(row),
        }
        for row in rows
    ]


def _source_health_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_region: dict[str, int] = {}
    live_pull_sources = 0
    total_item_count = 0
    for row in rows:
        status = str(row.get("status") or "unknown")
        category = str(row.get("category") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
        if row.get("live_pull"):
            live_pull_sources += 1
        total_item_count += int(row.get("item_count") or 0)
        for region_id in row.get("region_ids") or []:
            key = str(region_id)
            by_region[key] = by_region.get(key, 0) + 1
    return {
        "total_sources": len(rows),
        "live_pull_sources": live_pull_sources,
        "total_item_count": total_item_count,
        "by_status": dict(sorted(by_status.items())),
        "by_category": dict(sorted(by_category.items())),
        "by_region": dict(sorted(by_region.items())),
    }


def _object_type_manifest_info(
    *,
    object_type: str,
    rows: list[dict[str, Any]],
    output_dir: Path | None,
) -> dict[str, Any]:
    filename = OBJECT_FILES[object_type]
    info: dict[str, Any] = {
        "filename": filename,
        "rows": len(rows),
        "file_sha256": _sha256_bytes(_ndjson_bytes(rows)),
        "row_hashes": _row_hash_entries(rows),
    }
    if output_dir is not None:
        info["path"] = str(output_dir / filename)
    return info


def _intel_item_objects_with_drop_report(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
    log_drops: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(
        _news_object(item, snapshot)
        for item in snapshot.news
        if _region_allowed(item.region_id, region)
    )
    rows.extend(
        _permit_object(item, snapshot)
        for item in snapshot.permits
        if _region_allowed(item.region_id, region)
    )
    rows.extend(
        _business_object(item, snapshot)
        for item in snapshot.businesses
        if _region_allowed(item.region_id, region)
    )
    rows.extend(
        _contact_object(item, snapshot)
        for item in snapshot.contacts
        if _region_allowed(item.region_id, region)
    )
    rows.extend(
        _organization_object(item, snapshot)
        for item in snapshot.organizations
        if _region_allowed(item.region_id, region)
    )
    rows, drop_report = _drop_missing_provenance_with_report(rows, log_drops=log_drops)
    # Deterministic ordering: primary tuple is (region_id, kind, item_id);
    # tie-break with a content hash so duplicate-id rows still sort stably
    # and runs produce byte-identical NDJSON.
    rows.sort(
        key=lambda item: (
            item["region_id"],
            item["kind"],
            item["item_id"],
            _row_hash(item),
        )
    )
    return rows, drop_report


def intel_item_objects(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
) -> list[dict[str, Any]]:
    return _intel_item_objects_with_drop_report(snapshot, region=region)[0]


def _base_item(
    *,
    kind: str,
    item_id: str,
    region_id: RegionId,
    title: str,
    summary: str,
    score: float,
    source_name: str | None,
    source_url: str | None,
    observed_at: str | None,
    snapshot: RegionalIntelSnapshot,
    attributes: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "object_id": f"regional-intel:item:{kind}:{item_id}",
        "item_id": item_id,
        "kind": kind,
        "region_id": region_id,
        "title": title,
        "summary": summary,
        "score": score,
        "source_name": source_name,
        "source_url": source_url,
        "observed_at": observed_at,
        "snapshot_updated_at": snapshot.updated_at,
        "attributes": attributes or {},
        "notes": notes or [],
        "provenance": _source_policy(snapshot),
    }


def _news_object(item: NewsSignal, snapshot: RegionalIntelSnapshot) -> dict[str, Any]:
    return _base_item(
        kind="news",
        item_id=item.item_id,
        region_id=item.region_id,
        title=item.title,
        summary=item.summary,
        score=item.signal_score,
        source_name=item.source_name,
        source_url=item.source_url,
        observed_at=item.published_at,
        snapshot=snapshot,
        attributes={
            "publication": item.publication,
            "signal_type": item.signal_type,
            "address_hint": item.address_hint,
            "actionable": item.actionable,
            "organizations": item.organizations,
            "query": item.query,
        },
        notes=item.notes,
    )


def _permit_object(
    item: PermitSignal, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    return _base_item(
        kind="permit",
        item_id=item.item_id,
        region_id=item.region_id,
        title=item.address,
        summary=f"{item.permit_type} - {item.status}",
        score=item.signal_score,
        source_name=item.source_name,
        source_url=item.source_url,
        observed_at=item.status_date,
        snapshot=snapshot,
        attributes={
            "county": item.county,
            "permit_number": item.permit_number,
            "permit_type": item.permit_type,
            "status": item.status,
            "signal_type": item.signal_type,
            "actionable": item.actionable,
        },
        notes=item.notes,
    )


def _business_object(
    item: BusinessLead, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    return _base_item(
        kind="business",
        item_id=item.item_id,
        region_id=item.region_id,
        title=item.name,
        summary=f"{item.category} - {item.address}",
        score=item.lead_score,
        source_name=item.source_name,
        source_url=item.source_url,
        observed_at=None,
        snapshot=snapshot,
        attributes={
            "category": item.category,
            "address": item.address,
            "website": item.website,
            "phone": item.phone,
            "email": item.email,
            "lat": item.lat,
            "lon": item.lon,
            "tags": item.tags,
        },
        notes=item.notes,
    )


def _contact_object(
    item: PublicContact, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    subtitle = " - ".join(part for part in (item.title, item.organization) if part)
    return _base_item(
        kind="contact",
        item_id=item.item_id,
        region_id=item.region_id,
        title=item.name,
        summary=subtitle or item.organization,
        score=item.contact_score,
        source_name=item.source_name,
        source_url=item.source_url,
        observed_at=None,
        snapshot=snapshot,
        attributes={
            "title": item.title,
            "organization": item.organization,
            "address": item.address,
            "website": item.website,
            "phone": item.phone,
            "email": item.email,
            "contact_type": item.contact_type,
        },
        notes=item.notes,
    )


def _organization_object(
    item: OrganizationProfile, snapshot: RegionalIntelSnapshot
) -> dict[str, Any]:
    summary = (
        f"{len(item.categories)} categories; "
        f"{item.news_signal_count} news, {item.permit_signal_count} permits, "
        f"{item.business_lead_count} business leads, {item.contact_count} contacts"
    )
    return _base_item(
        kind="organization",
        item_id=item.item_id,
        region_id=item.region_id,
        title=item.name,
        summary=summary,
        score=item.organization_score,
        source_name=", ".join(item.source_names) if item.source_names else None,
        source_url=item.website,
        observed_at=item.latest_activity_at,
        snapshot=snapshot,
        attributes={
            "categories": item.categories,
            "address": item.address,
            "website": item.website,
            "phone": item.phone,
            "email": item.email,
            "source_names": item.source_names,
        },
        notes=item.notes,
    )


def build_export_plan(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
    output_dir: Path | None = None,
    log_drops: bool = True,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build deterministic export rows plus manifest metadata without writing files."""
    intel_items, drop_report = _intel_item_objects_with_drop_report(
        snapshot,
        region=region,
        log_drops=log_drops,
    )
    rows_by_type = {
        "Region": region_objects(snapshot, region=region),
        "IntelItem": intel_items,
        "IntelSourceHealth": source_health_objects(snapshot, region=region),
    }
    files = {
        object_type: _object_type_manifest_info(
            object_type=object_type,
            rows=rows,
            output_dir=output_dir,
        )
        for object_type, rows in rows_by_type.items()
    }
    manifest = {
        "schema_version": 2,
        "generated_at": _now_iso(),
        "snapshot_updated_at": snapshot.updated_at,
        "region": region,
        "object_types": files,
        "dropped_rows": drop_report,
        "source_health_summary": _source_health_summary(
            rows_by_type["IntelSourceHealth"]
        ),
        "policy": _source_policy(snapshot),
    }
    return rows_by_type, manifest


def export_snapshot(
    snapshot: RegionalIntelSnapshot,
    output_dir: Path,
    *,
    region: RegionId | None = None,
) -> dict[str, Any]:
    """Write Foundry-ready NDJSON exports and return a manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_by_type, manifest = build_export_plan(
        snapshot, region=region, output_dir=output_dir
    )
    for object_type, rows in rows_by_type.items():
        path = Path(manifest["object_types"][object_type]["path"])
        _write_ndjson(path, rows)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest
