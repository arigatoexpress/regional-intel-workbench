from __future__ import annotations

import hashlib
from typing import Any

from app.intel_models import IntelOpportunity
from app.intel_models import IntelAlert
from app.intel_models import IntelBriefingPack
from app.intel_models import IntelAnalystAnnotation
from app.intel_models import IntelRegionBriefingPack
from app.intel_models import IntelCollection
from app.intel_models import IntelCollectionBriefingPack
from app.intel_models import IntelBriefingBundle
from app.intel_models import IntelBundleBriefingPack
from app.intel_models import IntelSourceIncident
from app.intel_models import IntelRegionChange
from app.intel_models import IntelEntityChange
from app.intel_models import IntelMonitorEvaluation
from app.intel_models import IntelMonitorMatch
from app.intel_models import IntelMonitorRule
from app.intel_models import IntelTimelineEvent
from app.intel_models import IntelWatchlistEntry
from app.intel_models import OrganizationProfile
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.utils import clean_text


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _normalize(value: str | None) -> str:
    return "".join(ch for ch in clean_text(value or "").lower() if ch.isalnum())


def _hours_since(iso_string: str | None) -> float | None:
    if not iso_string:
        return None
    from datetime import UTC, datetime

    try:
        delta = datetime.now(tz=UTC) - datetime.fromisoformat(
            iso_string.replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError:
        return None
    return max(delta.total_seconds() / 3600, 0.0)


def _parse_iso(iso_string: str | None):
    from datetime import UTC, datetime

    if not iso_string:
        return None
    try:
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _organization_lookup(
    snapshot: RegionalIntelSnapshot,
) -> dict[str, OrganizationProfile]:
    return {item.item_id: item for item in snapshot.organizations}


def _organization_detail_payload(
    snapshot: RegionalIntelSnapshot, org_id: str
) -> dict[str, Any] | None:
    org = _organization_lookup(snapshot).get(org_id)
    if org is None:
        return None
    normalized_name = _normalize(org.name)
    businesses = [
        item
        for item in snapshot.businesses
        if item.region_id == org.region_id and _normalize(item.name) == normalized_name
    ]
    contacts = [
        item
        for item in snapshot.contacts
        if item.region_id == org.region_id
        and _normalize(item.organization) == normalized_name
    ]
    news = [
        item
        for item in snapshot.news
        if item.region_id == org.region_id
        and normalized_name in {_normalize(name) for name in item.organizations}
    ]
    permits = [
        item
        for item in snapshot.permits
        if item.region_id == org.region_id
        and any(
            normalized_name == _normalize(note.split(":", 1)[1])
            for note in item.notes
            if ":" in note
        )
    ]
    return {
        "organization": org,
        "businesses": businesses,
        "contacts": contacts,
        "news": news,
        "permits": permits,
    }


def build_entity_timeline(
    snapshot: RegionalIntelSnapshot, item_id: str
) -> list[IntelTimelineEvent]:
    detail = _organization_detail_payload(snapshot, item_id)
    if detail is None:
        return []

    timeline: list[IntelTimelineEvent] = []

    for item in detail["news"]:
        timeline.append(
            IntelTimelineEvent(
                event_id=_stable_id(item.item_id, "timeline"),
                region_id=item.region_id,
                occurred_at=item.published_at,
                kind="news",
                title=item.title,
                subtitle=item.source_name,
                detail=item.address_hint or item.summary,
                score=item.signal_score,
                url=item.source_url,
                notes=item.notes,
            )
        )

    for item in detail["permits"]:
        timeline.append(
            IntelTimelineEvent(
                event_id=_stable_id(item.item_id, "timeline"),
                region_id=item.region_id,
                occurred_at=item.status_date,
                kind="permit",
                title=item.address,
                subtitle=f"{item.county} | {item.permit_type}",
                detail=" | ".join(
                    part for part in [item.permit_number, item.signal_type] if part
                ),
                score=item.signal_score,
                url=item.source_url,
                notes=item.notes,
            )
        )

    for item in detail["contacts"]:
        timeline.append(
            IntelTimelineEvent(
                event_id=_stable_id(item.item_id, "timeline"),
                region_id=item.region_id,
                occurred_at=snapshot.updated_at,
                kind="contact",
                title=item.name,
                subtitle=" | ".join(
                    part for part in [item.title or "", item.organization] if part
                ),
                detail=" | ".join(
                    part
                    for part in [item.email or "", item.phone or "", item.address or ""]
                    if part
                ),
                score=item.contact_score,
                url=item.website or item.source_url,
                notes=item.notes,
            )
        )

    for item in detail["businesses"]:
        timeline.append(
            IntelTimelineEvent(
                event_id=_stable_id(item.item_id, "timeline"),
                region_id=item.region_id,
                occurred_at=snapshot.updated_at,
                kind="business",
                title=item.name,
                subtitle=item.category,
                detail=item.address,
                score=item.lead_score,
                url=item.website or item.source_url,
                notes=item.notes,
            )
        )

    timeline.sort(key=lambda item: (item.occurred_at, item.score), reverse=True)
    return timeline[:40]


def build_opportunities(
    snapshot: RegionalIntelSnapshot, region: RegionId | None = None
) -> list[IntelOpportunity]:
    opportunities: list[IntelOpportunity] = []

    for org in snapshot.organizations:
        if region is not None and org.region_id != region:
            continue
        score = org.organization_score
        reasons: list[str] = []
        if org.news_signal_count:
            reasons.append(f"{org.news_signal_count} news-linked signals")
            score += org.news_signal_count * 6
        if org.permit_signal_count:
            reasons.append(f"{org.permit_signal_count} permit/development links")
            score += org.permit_signal_count * 10
        if org.contact_count:
            reasons.append(f"{org.contact_count} public contact paths")
            score += org.contact_count * 8
        if org.business_lead_count:
            reasons.append(
                f"{org.business_lead_count} mapped public business locations"
            )
            score += org.business_lead_count * 4
        if any(
            term in clean_text(",".join(org.categories)).lower()
            for term in ["vacancy_or_closure", "commercial_development", "construction"]
        ):
            reasons.append("high-signal category activity")
            score += 18
        recency_hours = _hours_since(org.latest_activity_at)
        if recency_hours is not None and recency_hours <= 168:
            reasons.append("fresh activity in the last 7 days")
            score += 12
        if not reasons:
            continue
        opportunities.append(
            IntelOpportunity(
                opportunity_id=_stable_id("opportunity", org.item_id),
                region_id=org.region_id,
                kind="organization",
                title=org.name,
                summary=f"{org.name} has a multi-source signal footprint worth review.",
                score=round(score, 2),
                reasons=reasons[:4],
                item_ids=[org.item_id],
                urls=[org.website] if org.website else [],
                notes=org.notes,
            )
        )

    for ns in snapshot.news:
        if region is not None and ns.region_id != region:
            continue
        if not ns.actionable:
            continue
        reasons = [f"Actionable {ns.signal_type} signal", ns.source_name]
        if ns.address_hint:
            reasons.append(f"Address: {ns.address_hint}")
        opportunities.append(
            IntelOpportunity(
                opportunity_id=_stable_id("opportunity", ns.item_id),
                region_id=ns.region_id,
                kind="news_signal",
                title=ns.title,
                summary=ns.summary or "Public local-news signal with an address hint.",
                score=round(ns.signal_score + 16, 2),
                reasons=reasons[:4],
                item_ids=[ns.item_id],
                urls=[ns.source_url],
                notes=ns.notes,
            )
        )

    for ps in snapshot.permits:
        if region is not None and ps.region_id != region:
            continue
        if ps.signal_type not in {
            "commercial_development",
            "construction",
            "tenant_improvement",
        }:
            continue
        reasons = [f"{ps.signal_type.replace('_', ' ')} signal", ps.county]
        if any(note.startswith("Developer:") for note in ps.notes):
            reasons.append(
                next(note for note in ps.notes if note.startswith("Developer:"))
            )
        if any(note.startswith("Organization:") for note in ps.notes):
            reasons.append(
                next(note for note in ps.notes if note.startswith("Organization:"))
            )
        opportunities.append(
            IntelOpportunity(
                opportunity_id=_stable_id("opportunity", ps.item_id),
                region_id=ps.region_id,
                kind="permit_signal",
                title=ps.address,
                summary=f"{ps.permit_type} from an official public source.",
                score=round(ps.signal_score + 10, 2),
                reasons=reasons[:4],
                item_ids=[ps.item_id],
                urls=[ps.source_url],
                notes=ps.notes,
            )
        )

    opportunities.sort(
        key=lambda item: (item.region_id, -item.score, item.title.lower())
    )
    return opportunities[:40]


def resolve_watchlist(
    snapshot: RegionalIntelSnapshot, entries: list[IntelWatchlistEntry]
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for collection_name in [
        "organizations",
        "businesses",
        "contacts",
        "news",
        "permits",
    ]:
        for item in getattr(snapshot, collection_name):
            by_id[item.item_id] = item.model_dump()

    output: list[dict[str, Any]] = []
    for entry in entries:
        resolved = by_id.get(entry.item_id or "", {})
        output.append(
            {
                "entry": entry.model_dump(),
                "resolved": resolved,
                "is_live": bool(resolved),
                "summary": resolved.get("summary")
                or resolved.get("address")
                or resolved.get("organization")
                or resolved.get("category")
                or resolved.get("permit_type")
                or "",
            }
        )
    return output


def resolve_collection_items(
    snapshot: RegionalIntelSnapshot, collection: IntelCollection
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for collection_name in [
        "organizations",
        "businesses",
        "contacts",
        "news",
        "permits",
    ]:
        for item in getattr(snapshot, collection_name):
            by_id[item.item_id] = item.model_dump()

    output: list[dict[str, Any]] = []
    for ref in collection.items:
        resolved = by_id.get(ref.item_id or "", {})
        output.append(
            {
                "ref": ref.model_dump(),
                "resolved": resolved,
                "is_live": bool(resolved),
                "summary": resolved.get("summary")
                or resolved.get("address")
                or resolved.get("organization")
                or resolved.get("category")
                or resolved.get("permit_type")
                or ref.note
                or "",
            }
        )
    return output


def build_briefing_pack(
    snapshot: RegionalIntelSnapshot,
    item_id: str,
    *,
    annotation: IntelAnalystAnnotation | None = None,
) -> IntelBriefingPack | None:
    detail = _organization_detail_payload(snapshot, item_id)
    if detail is None:
        return None

    org = detail["organization"]
    timeline = build_entity_timeline(snapshot, item_id)[:12]
    reasons: list[str] = []
    if org.permit_signal_count:
        reasons.append(
            f"{org.permit_signal_count} permit/development signals are linked to this organization."
        )
    if org.news_signal_count:
        reasons.append(
            f"{org.news_signal_count} public news signals mention this organization."
        )
    if org.contact_count:
        reasons.append(
            f"{org.contact_count} public professional contacts are available."
        )
    if org.business_lead_count:
        reasons.append(
            f"{org.business_lead_count} mapped public-facing business locations were found."
        )
    if not reasons:
        reasons.append(
            "Organization exists in the current public-source graph but has limited linked evidence."
        )
    if annotation and annotation.note:
        reasons.insert(0, "Analyst note is attached to this organization.")

    public_contacts = [
        {
            "name": item.name,
            "title": item.title,
            "organization": item.organization,
            "email": item.email,
            "phone": item.phone,
            "website": item.website or item.source_url,
        }
        for item in detail["contacts"][:8]
    ]

    source_index: dict[str, dict[str, str]] = {}
    for collection_name in ["news", "permits", "contacts", "businesses"]:
        for item in detail[collection_name]:
            label = (
                getattr(item, "source_name", None)
                or getattr(item, "publication", None)
                or "Public source"
            )
            url = (
                getattr(item, "source_url", None)
                or getattr(item, "website", None)
                or ""
            )
            key = f"{label}|{url}"
            if key not in source_index:
                source_index[key] = {"name": label, "url": url}

    summary = (
        f"{org.name} is a {org.region_id} organization with {org.permit_signal_count} permit/development links, "
        f"{org.news_signal_count} news mentions, {org.contact_count} public contacts, and {org.business_lead_count} mapped business leads."
    )
    if annotation and annotation.note:
        summary += f" Analyst note: {annotation.note}"

    markdown_lines = [
        f"# {org.name}",
        "",
        f"- Region: `{org.region_id}`",
        f"- Categories: {', '.join(org.categories) if org.categories else 'n/a'}",
        f"- Address: {org.address or 'n/a'}",
        f"- Website: {org.website or 'n/a'}",
        "",
        "## Analyst Notes",
        f"- Note: {annotation.note if annotation and annotation.note else 'n/a'}",
        f"- Tags: {', '.join(annotation.tags) if annotation and annotation.tags else 'n/a'}",
        "",
        "## Why It Matters",
        *[f"- {reason}" for reason in reasons],
        "",
        "## Public Contacts",
    ]
    if public_contacts:
        markdown_lines.extend(
            [
                f"- {item['name']} | {item.get('title') or 'Public contact'} | {item.get('email') or item.get('phone') or item.get('website') or 'No direct contact field'}"
                for item in public_contacts
            ]
        )
    else:
        markdown_lines.append("- No public professional contacts linked yet.")
    markdown_lines.extend(["", "## Recent Evidence"])
    if timeline:
        markdown_lines.extend(
            [
                f"- [{item.kind}] {item.title} | {item.subtitle or item.detail or ''} | {item.occurred_at}"
                for item in timeline[:8]
            ]
        )
    else:
        markdown_lines.append("- No timeline events linked yet.")
    markdown_lines.extend(["", "## Sources"])
    markdown_lines.extend(
        [f"- {item['name']} | {item['url']}" for item in source_index.values()]
        or ["- No sources linked yet."]
    )

    return IntelBriefingPack(
        item_id=item_id,
        region_id=org.region_id,
        title=org.name,
        summary=summary,
        reasons=reasons,
        public_contacts=public_contacts,
        timeline=timeline,
        sources=list(source_index.values()),
        markdown="\n".join(markdown_lines),
        notes=[
            "Briefing pack is synthesized from currently linked public-source evidence.",
            "Use it as a starting brief, not as a final due-diligence document.",
        ],
    )


def build_operational_alerts(
    snapshot: RegionalIntelSnapshot,
    *,
    source_history: list[dict],
    region: RegionId | None = None,
) -> list[IntelAlert]:
    alerts: list[IntelAlert] = []

    for item in source_history:
        region_ids = item.get("region_ids") or []
        if region is not None and region_ids and region not in region_ids:
            continue
        last_status = str(item.get("last_status") or "unknown")
        empty_runs = int(item.get("empty_runs") or 0)
        last_item_count = int(item.get("last_item_count") or 0)
        if last_status == "empty":
            severity = "high" if empty_runs >= 2 else "medium"
            alerts.append(
                IntelAlert(
                    alert_id=_stable_id(
                        "alert",
                        item.get("source_key", ""),
                        last_status,
                        str(empty_runs),
                    ),
                    region_id=region_ids[0] if len(region_ids) == 1 else region,
                    severity=severity,
                    kind="source_gap",
                    title=f"{item.get('name') or item.get('source_key')} returned empty",
                    summary=f"Recent run is empty. non-empty runs={item.get('non_empty_runs', 0)}, empty runs={empty_runs}.",
                    score=90.0 if severity == "high" else 72.0,
                    source_keys=[str(item.get("source_key"))],
                    urls=[],
                    notes=[
                        "Source reliability alert generated from stored source-history data."
                    ],
                )
            )
        elif last_status == "live" and last_item_count > 40:
            alerts.append(
                IntelAlert(
                    alert_id=_stable_id(
                        "alert",
                        item.get("source_key", ""),
                        "surge",
                        str(last_item_count),
                    ),
                    region_id=region_ids[0] if len(region_ids) == 1 else region,
                    severity="info",
                    kind="source_surge",
                    title=f"{item.get('name') or item.get('source_key')} has high current volume",
                    summary=f"Latest run produced {last_item_count} items.",
                    score=55.0,
                    source_keys=[str(item.get("source_key"))],
                    notes=[
                        "High-volume source run; review for new intelligence density."
                    ],
                )
            )

    for ns in snapshot.news:
        if region is not None and ns.region_id != region:
            continue
        if ns.actionable and ns.signal_score >= 90:
            alerts.append(
                IntelAlert(
                    alert_id=_stable_id("alert", ns.item_id, "actionable_news"),
                    region_id=ns.region_id,
                    severity="high",
                    kind="actionable_news",
                    title=ns.title,
                    summary=ns.address_hint
                    or ns.summary
                    or "Actionable public news signal.",
                    score=ns.signal_score,
                    item_ids=[ns.item_id],
                    urls=[ns.source_url],
                    notes=ns.notes,
                )
            )

    for ps in snapshot.permits:
        if region is not None and ps.region_id != region:
            continue
        if (
            ps.signal_type
            in {"commercial_development", "construction", "tenant_improvement"}
            and ps.signal_score >= 78
        ):
            alerts.append(
                IntelAlert(
                    alert_id=_stable_id("alert", ps.item_id, "permit_signal"),
                    region_id=ps.region_id,
                    severity="medium",
                    kind="permit_signal",
                    title=ps.address,
                    summary=f"{ps.permit_type} | {ps.county}",
                    score=ps.signal_score,
                    item_ids=[ps.item_id],
                    urls=[ps.source_url],
                    notes=ps.notes,
                )
            )

    alerts.sort(key=lambda a: (-a.score, a.severity, a.title.lower()))
    return alerts[:30]


def build_region_briefing_pack(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId,
    opportunities: list[IntelOpportunity],
    alerts: list[IntelAlert],
    watchlist_items: list[dict],
) -> IntelRegionBriefingPack:
    region_profile = next(
        (item for item in snapshot.regions if item.id == region), None
    )
    if region_profile is None:
        raise ValueError(f"Unknown region: {region}")

    region_contacts = sorted(
        [item for item in snapshot.contacts if item.region_id == region],
        key=lambda item: item.contact_score,
        reverse=True,
    )[:5]
    region_watchlist = [
        item
        for item in watchlist_items
        if (item.get("entry", {}).get("region_id") == region)
        or (item.get("resolved", {}).get("region_id") == region)
    ][:6]
    top_opportunities = [
        item.model_dump() if hasattr(item, "model_dump") else item
        for item in opportunities[:6]
    ]
    top_contacts = [
        {
            "name": item.name,
            "title": item.title,
            "organization": item.organization,
            "email": item.email,
            "phone": item.phone,
            "website": item.website or item.source_url,
            "score": item.contact_score,
        }
        for item in region_contacts
    ]
    source_alerts = [item for item in alerts if item.region_id in {None, region}][:8]
    summary = (
        f"{region_profile.name} currently has {len(top_opportunities)} high-priority opportunities, "
        f"{len(source_alerts)} operational alerts, and {len(top_contacts)} high-signal public contacts."
    )

    markdown_lines = [
        f"# {region_profile.name} Briefing",
        "",
        summary,
        "",
        "## Top Opportunities",
    ]
    for opp in top_opportunities:
        if isinstance(opp, dict):
            title = opp.get("title", "")
            score = opp.get("score", 0.0)
            reasons = opp.get("reasons", [])
        else:
            title = opp.title
            score = opp.score
            reasons = opp.reasons
        markdown_lines.append(f"- {title} | score {score} | {'; '.join(reasons[:3])}")
    else:
        markdown_lines.append("- No opportunities ranked yet.")

    markdown_lines.extend(["", "## Operational Alerts"])
    if source_alerts:
        markdown_lines.extend(
            [
                f"- [{item.severity}] {item.title} | {item.summary}"
                for item in source_alerts
            ]
        )
    else:
        markdown_lines.append("- No current alerts.")

    markdown_lines.extend(["", "## Public Contacts"])
    if top_contacts:
        markdown_lines.extend(
            [
                f"- {item['name']} | {item.get('title') or 'Public contact'} | {item.get('email') or item.get('phone') or item.get('website') or 'No direct field'}"
                for item in top_contacts
            ]
        )
    else:
        markdown_lines.append("- No public contacts linked yet.")

    markdown_lines.extend(["", "## Saved Watchlist Context"])
    if region_watchlist:
        markdown_lines.extend(
            [
                f"- {item.get('entry', {}).get('label')} | {item.get('summary') or item.get('entry', {}).get('note') or 'Saved watchlist item'}"
                for item in region_watchlist
            ]
        )
    else:
        markdown_lines.append("- No saved watchlist items for this region.")

    return IntelRegionBriefingPack(
        region_id=region,
        title=f"{region_profile.name} Briefing",
        summary=summary,
        top_opportunities=top_opportunities,
        top_watchlist=region_watchlist,
        top_contacts=top_contacts,
        source_alerts=source_alerts,
        markdown="\n".join(markdown_lines),
        notes=[
            "Regional briefing pack is synthesized from the current public-source snapshot and stored source history.",
            "Operational alerts combine source reliability issues and high-signal actionable intelligence.",
        ],
    )


def build_collection_briefing_pack(
    snapshot: RegionalIntelSnapshot,
    *,
    collection: IntelCollection,
    source_history: list[dict],
    annotation_lookup: dict[str, IntelAnalystAnnotation] | None = None,
) -> IntelCollectionBriefingPack:
    resolved_items = resolve_collection_items(snapshot, collection)
    collection_regions = {
        item.get("resolved", {}).get("region_id")
        or item.get("ref", {}).get("region_id")
        for item in resolved_items
        if item.get("resolved", {}).get("region_id")
        or item.get("ref", {}).get("region_id")
    }
    effective_region = collection.region_id or (
        sorted(collection_regions)[0] if len(collection_regions) == 1 else None
    )
    item_ids = {
        item.get("resolved", {}).get("item_id") or item.get("ref", {}).get("item_id")
        for item in resolved_items
    }
    item_ids.discard(None)
    annotation_lookup = annotation_lookup or {}

    linked_opportunities = [
        item.model_dump()
        for item in build_opportunities(snapshot, region=effective_region)
        if item_ids.intersection(item.item_ids)
    ][:8]

    contact_rows: list[dict] = []
    seen_contacts: set[str] = set()
    for item in resolved_items:
        resolved = item.get("resolved", {})
        if not resolved:
            continue
        kind = item.get("ref", {}).get("kind")
        if kind == "contact":
            key = str(
                resolved.get("item_id") or resolved.get("email") or resolved.get("name")
            )
            if key in seen_contacts:
                continue
            seen_contacts.add(key)
            contact_rows.append(
                {
                    "name": resolved.get("name"),
                    "title": resolved.get("title"),
                    "organization": resolved.get("organization"),
                    "email": resolved.get("email"),
                    "phone": resolved.get("phone"),
                    "website": resolved.get("website") or resolved.get("source_url"),
                }
            )
        elif kind == "organization" and resolved.get("item_id"):
            org_briefing = build_briefing_pack(
                snapshot,
                item_id=str(resolved.get("item_id")),
                annotation=annotation_lookup.get(str(resolved.get("item_id"))),
            )
            if org_briefing is None:
                continue
            for contact in org_briefing.public_contacts:
                key = str(
                    contact.get("email")
                    or contact.get("name")
                    or contact.get("website")
                )
                if not key or key in seen_contacts:
                    continue
                seen_contacts.add(key)
                contact_rows.append(contact)
    source_alerts = build_operational_alerts(
        snapshot, source_history=source_history, region=effective_region
    )[:8]

    item_lines: list[str] = []
    markdown_lines = [
        f"# {collection.title}",
        "",
        f"- Region: `{effective_region or 'multi_region'}`",
        f"- Tags: {', '.join(collection.tags) if collection.tags else 'n/a'}",
        f"- Note: {collection.note or 'n/a'}",
        "",
        "## Collection Items",
    ]
    for item in resolved_items:
        ref = item.get("ref", {})
        resolved = item.get("resolved", {})
        title = (
            resolved.get("name")
            or resolved.get("title")
            or resolved.get("address")
            or ref.get("label")
            or "Saved item"
        )
        descriptor = (
            resolved.get("summary")
            or resolved.get("address")
            or resolved.get("organization")
            or resolved.get("category")
            or resolved.get("permit_type")
            or ref.get("note")
            or "No additional summary."
        )
        live_state = "live" if item.get("is_live") else "saved_only"
        line = f"- [{ref.get('kind')}] {title} | {live_state} | {descriptor}"
        if ref.get("note"):
            line += f" | note: {ref.get('note')}"
        item_lines.append(line)
    markdown_lines.extend(item_lines or ["- No collection items saved yet."])

    markdown_lines.extend(["", "## Linked Opportunities"])
    if linked_opportunities:
        markdown_lines.extend(
            [
                f"- {item['title']} | score {item['score']} | {'; '.join(item.get('reasons', [])[:3])}"
                for item in linked_opportunities
            ]
        )
    else:
        markdown_lines.append(
            "- No linked opportunities were detected from the current collection items."
        )

    markdown_lines.extend(["", "## Public Contacts"])
    if contact_rows:
        markdown_lines.extend(
            [
                f"- {item.get('name')} | {item.get('title') or 'Public contact'} | {item.get('email') or item.get('phone') or item.get('website') or 'No direct field'}"
                for item in contact_rows[:10]
            ]
        )
    else:
        markdown_lines.append(
            "- No public contacts linked from current collection items."
        )

    markdown_lines.extend(["", "## Operational Alerts"])
    if source_alerts:
        markdown_lines.extend(
            [
                f"- [{item.severity}] {item.title} | {item.summary}"
                for item in source_alerts
            ]
        )
    else:
        markdown_lines.append("- No current alerts for this collection scope.")

    summary = (
        f"{collection.title} contains {len(resolved_items)} saved items, "
        f"{len(linked_opportunities)} linked opportunities, and {len(contact_rows)} public contacts."
    )
    if collection.note:
        summary += f" Collection note: {collection.note}"

    return IntelCollectionBriefingPack(
        collection_id=collection.collection_id,
        title=collection.title,
        region_id=effective_region,
        summary=summary,
        items=resolved_items,
        linked_opportunities=linked_opportunities,
        public_contacts=contact_rows[:10],
        source_alerts=source_alerts,
        markdown="\n".join(markdown_lines),
        notes=[
            "Collection briefing packs synthesize only the items explicitly saved into the collection plus current source health.",
            "Collections are operator-curated dossiers, not automatic truth sets.",
        ],
    )


def build_bundle_briefing_pack(
    snapshot: RegionalIntelSnapshot,
    *,
    bundle: IntelBriefingBundle,
    collections: list[IntelCollection],
    source_history: list[dict],
    annotation_lookup: dict[str, IntelAnalystAnnotation] | None = None,
) -> IntelBundleBriefingPack:
    annotation_lookup = annotation_lookup or {}
    packs = [
        build_collection_briefing_pack(
            snapshot,
            collection=collection,
            source_history=source_history,
            annotation_lookup=annotation_lookup,
        )
        for collection in collections
    ]
    linked_opportunities: list[dict] = []
    contacts: list[dict] = []
    seen_opportunity_titles: set[str] = set()
    seen_contact_keys: set[str] = set()
    for pack in packs:
        for item in pack.linked_opportunities:
            key = str(item.get("title"))
            if key in seen_opportunity_titles:
                continue
            seen_opportunity_titles.add(key)
            linked_opportunities.append(item)
        for item in pack.public_contacts:
            key = str(item.get("email") or item.get("name") or item.get("website"))
            if not key or key in seen_contact_keys:
                continue
            seen_contact_keys.add(key)
            contacts.append(item)
    effective_region = bundle.region_id
    alerts = build_operational_alerts(
        snapshot, source_history=source_history, region=effective_region
    )[:10]
    summary = (
        f"{bundle.title} combines {len(collections)} collections, "
        f"{sum(len(collection.items) for collection in collections)} saved items, "
        f"{len(linked_opportunities)} linked opportunities, and {len(contacts)} public contacts."
    )
    if bundle.note:
        summary += f" Bundle note: {bundle.note}"

    markdown_lines = [
        f"# {bundle.title}",
        "",
        f"- Region: `{effective_region or 'multi_region'}`",
        f"- Tags: {', '.join(bundle.tags) if bundle.tags else 'n/a'}",
        f"- Note: {bundle.note or 'n/a'}",
        "",
        "## Included Collections",
    ]
    markdown_lines.extend(
        [
            f"- {pack.title} | {len(pack.items)} items | {len(pack.linked_opportunities)} linked opportunities"
            for pack in packs
        ]
        or ["- No collections attached yet."]
    )
    markdown_lines.extend(["", "## Linked Opportunities"])
    markdown_lines.extend(
        [
            f"- {item['title']} | score {item['score']} | {'; '.join(item.get('reasons', [])[:3])}"
            for item in linked_opportunities[:12]
        ]
        or ["- No linked opportunities yet."]
    )
    markdown_lines.extend(["", "## Public Contacts"])
    markdown_lines.extend(
        [
            f"- {item.get('name')} | {item.get('title') or 'Public contact'} | {item.get('email') or item.get('phone') or item.get('website') or 'No direct field'}"
            for item in contacts[:12]
        ]
        or ["- No public contacts linked yet."]
    )
    markdown_lines.extend(["", "## Operational Alerts"])
    markdown_lines.extend(
        [f"- [{item.severity}] {item.title} | {item.summary}" for item in alerts]
        or ["- No current alerts."]
    )
    markdown_lines.extend(["", "## Collection Briefs"])
    for pack in packs:
        markdown_lines.extend(
            [
                f"### {pack.title}",
                pack.summary,
                "",
            ]
        )

    return IntelBundleBriefingPack(
        bundle_id=bundle.bundle_id,
        title=bundle.title,
        region_id=effective_region,
        summary=summary,
        collections=[
            {
                "collection_id": pack.collection_id,
                "title": pack.title,
                "summary": pack.summary,
                "item_count": len(pack.items),
            }
            for pack in packs
        ],
        linked_opportunities=linked_opportunities[:12],
        public_contacts=contacts[:12],
        source_alerts=alerts,
        markdown="\n".join(markdown_lines),
        notes=[
            "Bundle briefing packs aggregate multiple saved collection dossiers into one export surface.",
            "Bundles are packaging layers on top of collections; they do not create new intelligence on their own.",
        ],
    )


def build_source_incidents(
    source_history: list[dict],
    *,
    region: RegionId | None = None,
) -> list[IntelSourceIncident]:
    incidents: list[IntelSourceIncident] = []

    for item in source_history:
        region_ids = item.get("region_ids") or []
        if region is not None and region_ids and region not in region_ids:
            continue
        points = sorted(
            item.get("points") or [],
            key=lambda point: str(point.get("updated_at") or ""),
        )
        if not points:
            continue
        latest = points[-1]
        latest_status = str(latest.get("status") or "unknown")
        latest_count = int(latest.get("item_count") or 0)

        trailing_empty: list[dict] = []
        for point in reversed(points):
            if str(point.get("status") or "unknown") != "empty":
                break
            trailing_empty.append(point)
        trailing_empty.reverse()
        if trailing_empty:
            severity = "high" if len(trailing_empty) >= 2 else "medium"
            incidents.append(
                IntelSourceIncident(
                    incident_id=_stable_id(
                        "source_incident",
                        str(item.get("source_key")),
                        "empty",
                        str(len(trailing_empty)),
                    ),
                    source_key=str(item.get("source_key")),
                    name=str(item.get("name") or item.get("source_key")),
                    category=str(item.get("category") or "news"),
                    region_ids=region_ids,
                    severity=severity,
                    incident_type="repeated_empty"
                    if len(trailing_empty) >= 2
                    else "single_empty",
                    started_at=str(trailing_empty[0].get("updated_at")),
                    latest_at=str(trailing_empty[-1].get("updated_at")),
                    run_count=len(trailing_empty),
                    last_item_count=latest_count,
                    summary=(
                        f"Latest {len(trailing_empty)} run(s) returned empty. "
                        f"non-empty runs={int(item.get('non_empty_runs') or 0)}, empty runs={int(item.get('empty_runs') or 0)}."
                    ),
                    notes=["Derived from the stored source-history trail."],
                )
            )

        previous_non_empty = [
            int(point.get("item_count") or 0)
            for point in points[:-1]
            if str(point.get("status") or "unknown") == "live"
            and int(point.get("item_count") or 0) > 0
        ]
        if latest_status == "live" and latest_count > 0 and previous_non_empty:
            baseline = sum(previous_non_empty) / max(len(previous_non_empty), 1)
            if baseline > 0 and latest_count >= max(int(round(baseline * 1.75)), 20):
                incidents.append(
                    IntelSourceIncident(
                        incident_id=_stable_id(
                            "source_incident",
                            str(item.get("source_key")),
                            "surge",
                            str(latest_count),
                        ),
                        source_key=str(item.get("source_key")),
                        name=str(item.get("name") or item.get("source_key")),
                        category=str(item.get("category") or "news"),
                        region_ids=region_ids,
                        severity="info",
                        incident_type="volume_surge",
                        started_at=str(latest.get("updated_at")),
                        latest_at=str(latest.get("updated_at")),
                        run_count=1,
                        last_item_count=latest_count,
                        summary=f"Latest run produced {latest_count} items against a trailing baseline of {round(baseline, 1)}.",
                        notes=[
                            "Use this to review sudden density spikes from an otherwise stable source."
                        ],
                    )
                )

        if latest_status == "live" and trailing_empty:
            pass
        elif latest_status == "live":
            previous_points = points[:-1]
            recovery_streak: list[dict] = []
            for point in reversed(previous_points):
                if str(point.get("status") or "unknown") != "empty":
                    break
                recovery_streak.append(point)
            if len(recovery_streak) >= 2:
                incidents.append(
                    IntelSourceIncident(
                        incident_id=_stable_id(
                            "source_incident",
                            str(item.get("source_key")),
                            "recovery",
                            str(latest_count),
                        ),
                        source_key=str(item.get("source_key")),
                        name=str(item.get("name") or item.get("source_key")),
                        category=str(item.get("category") or "news"),
                        region_ids=region_ids,
                        severity="info",
                        incident_type="recovery",
                        started_at=str(recovery_streak[-1].get("updated_at")),
                        latest_at=str(latest.get("updated_at")),
                        run_count=len(recovery_streak) + 1,
                        last_item_count=latest_count,
                        summary=f"Source recovered after {len(recovery_streak)} empty run(s); latest run returned {latest_count} items.",
                        notes=[
                            "Useful for distinguishing temporary outages from chronic source failures."
                        ],
                    )
                )

        age_hours = _hours_since(str(latest.get("updated_at") or ""))
        if age_hours is not None and age_hours >= 36:
            incidents.append(
                IntelSourceIncident(
                    incident_id=_stable_id(
                        "source_incident",
                        str(item.get("source_key")),
                        "stale",
                        str(int(age_hours)),
                    ),
                    source_key=str(item.get("source_key")),
                    name=str(item.get("name") or item.get("source_key")),
                    category=str(item.get("category") or "news"),
                    region_ids=region_ids,
                    severity="medium" if age_hours < 72 else "high",
                    incident_type="stale_source",
                    started_at=str(latest.get("updated_at")),
                    latest_at=str(latest.get("updated_at")),
                    run_count=1,
                    last_item_count=latest_count,
                    summary=f"Latest recorded run is {round(age_hours, 1)} hours old.",
                    notes=[
                        "Staleness is measured from the latest history point, not from feed metadata."
                    ],
                )
            )

    incidents.sort(
        key=lambda item: (-item.run_count, -item.last_item_count, item.latest_at),
        reverse=True,
    )
    return incidents[:40]


def build_region_changes(
    history_records: list[dict],
    *,
    region: RegionId | None = None,
) -> list[IntelRegionChange]:
    changes: list[IntelRegionChange] = []
    if len(history_records) < 2:
        return changes

    for previous, latest in zip(history_records[:-1], history_records[1:]):
        latest_at = str(latest.get("updated_at") or "")
        previous_at = str(previous.get("updated_at") or "")
        for region_item in latest.get("regions") or []:
            region_id = region_item.get("id")
            if region_id is None or (region is not None and region_id != region):
                continue

            def _count(record: dict, collection_name: str) -> int:
                return len(
                    [
                        item
                        for item in record.get(collection_name, [])
                        if item.get("region_id") == region_id
                    ]
                )

            delta_news = _count(latest, "news") - _count(previous, "news")
            delta_permits = _count(latest, "permits") - _count(previous, "permits")
            delta_businesses = _count(latest, "businesses") - _count(
                previous, "businesses"
            )
            delta_contacts = _count(latest, "contacts") - _count(previous, "contacts")
            delta_organizations = _count(latest, "organizations") - _count(
                previous, "organizations"
            )
            if not any(
                [
                    delta_news,
                    delta_permits,
                    delta_businesses,
                    delta_contacts,
                    delta_organizations,
                ]
            ):
                continue

            lines: list[str] = []
            if delta_news:
                lines.append(f"news {delta_news:+d}")
            if delta_permits:
                lines.append(f"permits {delta_permits:+d}")
            if delta_businesses:
                lines.append(f"businesses {delta_businesses:+d}")
            if delta_contacts:
                lines.append(f"contacts {delta_contacts:+d}")
            if delta_organizations:
                lines.append(f"orgs {delta_organizations:+d}")

            changes.append(
                IntelRegionChange(
                    change_id=_stable_id(
                        "region_change", str(region_id), previous_at, latest_at
                    ),
                    region_id=region_id,
                    latest_at=latest_at,
                    previous_at=previous_at,
                    summary=f"Snapshot delta from {previous_at} to {latest_at}: {', '.join(lines)}.",
                    delta_news=delta_news,
                    delta_permits=delta_permits,
                    delta_businesses=delta_businesses,
                    delta_contacts=delta_contacts,
                    delta_organizations=delta_organizations,
                    notable_lines=lines,
                    notes=[
                        "Counts are derived from stored snapshots, not from entity-level diffs."
                    ],
                )
            )

    changes.sort(key=lambda item: item.latest_at, reverse=True)
    return changes[:30]


def build_entity_changes(
    history_records: list[dict],
    *,
    region: RegionId | None = None,
    kind: str | None = None,
    item_id: str | None = None,
) -> list[IntelEntityChange]:
    changes: list[IntelEntityChange] = []
    if len(history_records) < 2:
        return changes

    collection_map = {
        "news": ("news", "signal_score"),
        "permit": ("permits", "signal_score"),
        "business": ("businesses", "lead_score"),
        "contact": ("contacts", "contact_score"),
        "organization": ("organizations", "organization_score"),
    }
    normalized_kind = clean_text(kind or "").lower() or None
    if normalized_kind and normalized_kind not in collection_map:
        return changes

    def _title_for(entity_kind: str, row: dict) -> str:
        if entity_kind == "news":
            return str(
                row.get("title")
                or row.get("summary")
                or row.get("item_id")
                or "news item"
            )
        if entity_kind == "permit":
            return str(
                row.get("address")
                or row.get("permit_number")
                or row.get("item_id")
                or "permit"
            )
        if entity_kind == "business":
            return str(
                row.get("name")
                or row.get("address")
                or row.get("item_id")
                or "business"
            )
        if entity_kind == "contact":
            return str(
                row.get("name")
                or row.get("organization")
                or row.get("item_id")
                or "contact"
            )
        return str(row.get("name") or row.get("item_id") or "organization")

    def _summary_for(entity_kind: str, row: dict) -> str:
        if entity_kind == "news":
            return str(row.get("summary") or row.get("source_name") or "")
        if entity_kind == "permit":
            return " | ".join(
                part
                for part in [
                    row.get("permit_type"),
                    row.get("status"),
                    row.get("county"),
                ]
                if part
            )
        if entity_kind == "business":
            return " | ".join(
                part for part in [row.get("category"), row.get("address")] if part
            )
        if entity_kind == "contact":
            return " | ".join(
                part
                for part in [
                    row.get("organization"),
                    row.get("title"),
                    row.get("email"),
                ]
                if part
            )
        return " | ".join(
            part
            for part in [", ".join(row.get("categories") or []), row.get("address")]
            if part
        )

    for previous, latest in zip(history_records[:-1], history_records[1:]):
        latest_at = str(latest.get("updated_at") or "")
        previous_at = str(previous.get("updated_at") or "")
        kinds_to_process = (
            [normalized_kind] if normalized_kind else list(collection_map.keys())
        )

        for entity_kind in kinds_to_process:
            collection_name, score_field = collection_map[entity_kind]
            previous_rows = {
                str(row.get("item_id")): row
                for row in previous.get(collection_name, [])
                if row.get("item_id")
                and (region is None or row.get("region_id") == region)
            }
            latest_rows = {
                str(row.get("item_id")): row
                for row in latest.get(collection_name, [])
                if row.get("item_id")
                and (region is None or row.get("region_id") == region)
            }
            candidate_ids = set(previous_rows) | set(latest_rows)
            if item_id:
                candidate_ids &= {item_id}

            for current_item_id in candidate_ids:
                previous_row = previous_rows.get(current_item_id)
                latest_row = latest_rows.get(current_item_id)
                reference = latest_row or previous_row or {}
                region_id = reference.get("region_id")
                if region_id is None:
                    continue
                title = _title_for(entity_kind, reference)
                notes = [
                    f"{entity_kind} diff derived from consecutive stored snapshots."
                ]

                if previous_row is None and latest_row is not None:
                    changes.append(
                        IntelEntityChange(
                            change_id=_stable_id(
                                "entity_change",
                                entity_kind,
                                current_item_id,
                                "added",
                                latest_at,
                            ),
                            region_id=region_id,
                            kind=entity_kind,
                            item_id=current_item_id,
                            title=title,
                            change_type="added",
                            latest_at=latest_at,
                            previous_at=previous_at,
                            summary=f"{title} appeared in the latest snapshot. {_summary_for(entity_kind, latest_row)}".strip(),
                            score_before=None,
                            score_after=float(latest_row.get(score_field) or 0.0),
                            notes=notes,
                        )
                    )
                    continue

                if previous_row is not None and latest_row is None:
                    changes.append(
                        IntelEntityChange(
                            change_id=_stable_id(
                                "entity_change",
                                entity_kind,
                                current_item_id,
                                "removed",
                                latest_at,
                            ),
                            region_id=region_id,
                            kind=entity_kind,
                            item_id=current_item_id,
                            title=title,
                            change_type="removed",
                            latest_at=latest_at,
                            previous_at=previous_at,
                            summary=f"{title} dropped out of the latest snapshot after appearing previously. {_summary_for(entity_kind, previous_row)}".strip(),
                            score_before=float(previous_row.get(score_field) or 0.0),
                            score_after=None,
                            notes=notes,
                        )
                    )
                    continue

                if previous_row is None or latest_row is None:
                    continue

                score_before = float(previous_row.get(score_field) or 0.0)
                score_after = float(latest_row.get(score_field) or 0.0)
                score_delta = round(score_after - score_before, 2)
                if abs(score_delta) >= 5:
                    direction = "increased" if score_delta > 0 else "decreased"
                    changes.append(
                        IntelEntityChange(
                            change_id=_stable_id(
                                "entity_change",
                                entity_kind,
                                current_item_id,
                                "score",
                                latest_at,
                            ),
                            region_id=region_id,
                            kind=entity_kind,
                            item_id=current_item_id,
                            title=title,
                            change_type="score_shift",
                            latest_at=latest_at,
                            previous_at=previous_at,
                            summary=f"{title} score {direction} by {abs(score_delta):.1f} points ({score_before:.1f} -> {score_after:.1f}).",
                            score_before=score_before,
                            score_after=score_after,
                            notes=notes,
                        )
                    )

                if entity_kind == "permit":
                    previous_status = str(previous_row.get("status") or "").strip()
                    latest_status = str(latest_row.get("status") or "").strip()
                    if (
                        previous_status
                        and latest_status
                        and previous_status != latest_status
                    ):
                        changes.append(
                            IntelEntityChange(
                                change_id=_stable_id(
                                    "entity_change",
                                    entity_kind,
                                    current_item_id,
                                    "status",
                                    latest_at,
                                ),
                                region_id=region_id,
                                kind=entity_kind,
                                item_id=current_item_id,
                                title=title,
                                change_type="status_change",
                                latest_at=latest_at,
                                previous_at=previous_at,
                                summary=f"{title} permit status changed from {previous_status} to {latest_status}.",
                                score_before=score_before,
                                score_after=score_after,
                                notes=notes,
                            )
                        )

    changes.sort(
        key=lambda current: (current.latest_at, current.kind, current.change_type),
        reverse=True,
    )
    return changes[:80]


def build_monitor_evaluations(
    snapshot: RegionalIntelSnapshot,
    *,
    rules: list[IntelMonitorRule],
    history_records: list[dict],
    source_history: list[dict],
) -> list[IntelMonitorEvaluation]:
    evaluations: list[IntelMonitorEvaluation] = []

    def _keyword_match(keyword: str | None, values: list[str]) -> bool:
        if not keyword:
            return True
        needle = clean_text(keyword).lower()
        haystack = " ".join(clean_text(value or "").lower() for value in values)
        return needle in haystack

    def _severity_rank(value: str) -> int:
        return {"high": 3, "medium": 2, "info": 1}.get(value, 0)

    for rule in rules:
        entity_changes = build_entity_changes(
            history_records, region=rule.region_id, kind=None, item_id=None
        )
        incidents = build_source_incidents(source_history, region=rule.region_id)
        matches: list[IntelMonitorMatch] = []
        has_entity_filters = bool(
            rule.entity_kinds or rule.change_types or rule.min_score_delta is not None
        )
        has_incident_filters = bool(rule.incident_types)
        include_entity_changes = has_entity_filters or not has_incident_filters
        include_incidents = has_incident_filters or not has_entity_filters

        if include_entity_changes:
            for ec in entity_changes:
                if rule.entity_kinds and ec.kind not in rule.entity_kinds:
                    continue
                if rule.change_types and ec.change_type not in rule.change_types:
                    continue
                score_delta = abs((ec.score_after or 0.0) - (ec.score_before or 0.0))
                if (
                    rule.min_score_delta is not None
                    and score_delta < rule.min_score_delta
                ):
                    continue
                if not _keyword_match(
                    rule.keyword, [ec.title, ec.summary, " ".join(ec.notes)]
                ):
                    continue
                severity = (
                    "high"
                    if ec.change_type in {"removed", "status_change"}
                    else "medium"
                    if ec.change_type == "score_shift"
                    else "info"
                )
                matches.append(
                    IntelMonitorMatch(
                        match_id=_stable_id(
                            "monitor_match", rule.rule_id, ec.change_id
                        ),
                        rule_id=rule.rule_id,
                        source_kind="entity_change",
                        region_id=ec.region_id,
                        title=ec.title,
                        summary=ec.summary,
                        occurred_at=ec.latest_at,
                        severity=severity,
                        kind=ec.kind,
                        item_id=ec.item_id,
                        score=score_delta
                        or float(ec.score_after or ec.score_before or 0.0),
                        notes=ec.notes,
                    )
                )

        if include_incidents:
            for inc in incidents:
                if rule.incident_types and inc.incident_type not in rule.incident_types:
                    continue
                if not _keyword_match(
                    rule.keyword, [inc.name, inc.summary, " ".join(inc.notes)]
                ):
                    continue
                matches.append(
                    IntelMonitorMatch(
                        match_id=_stable_id(
                            "monitor_match", rule.rule_id, inc.incident_id
                        ),
                        rule_id=rule.rule_id,
                        source_kind="source_incident",
                        region_id=inc.region_ids[0]
                        if len(inc.region_ids) == 1
                        else None,
                        title=inc.name,
                        summary=inc.summary,
                        occurred_at=inc.latest_at,
                        severity=inc.severity,
                        kind=inc.incident_type,
                        item_id=None,
                        score=float(inc.run_count or inc.last_item_count or 0.0),
                        notes=inc.notes,
                    )
                )

        matches.sort(
            key=lambda item: (
                _severity_rank(item.severity),
                item.occurred_at,
                item.score,
            ),
            reverse=True,
        )
        summary = (
            f"{rule.title} matched {len(matches)} item(s)"
            + (f" in {rule.region_id}" if rule.region_id else "")
            + "."
        )
        if rule.keyword:
            summary += f" Keyword: {rule.keyword}."
        evaluations.append(
            IntelMonitorEvaluation(
                rule=rule,
                summary=summary,
                matches=matches[:12],
                notes=[
                    "Monitor rules evaluate entity changes and source incidents against saved filters.",
                    "Rules are deterministic filters over stored public-source evidence, not model-generated guesses.",
                ],
            )
        )

    evaluations.sort(
        key=lambda item: (
            len(item.matches),
            item.rule.updated_at,
            item.rule.title.lower(),
        ),
        reverse=True,
    )
    return evaluations
