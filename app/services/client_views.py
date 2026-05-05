from __future__ import annotations

from urllib.parse import urlencode

from app.intel_models import ClientFeedItem
from app.intel_models import ClientFeedSection
from app.intel_models import ClientView
from app.intel_models import ClientViewMetric
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.intel_models import IntelMonitorRule
from app.services.intel_insights import build_entity_changes
from app.services.intel_insights import build_monitor_evaluations
from app.services.intel_insights import build_opportunities
from app.services.intel_insights import build_source_incidents
from app.utils import clean_text


SUPPORTED_CLIENT_VIEWS = {
    "blanga_austin": {
        "client_name": "Blanga Intelligence System",
        "title": "Austin STNL + Redevelopment Feed",
        "summary": "Austin-focused retail, redevelopment, vacancy, permit, and contact intelligence for brokerage work.",
        "region_id": "austin_tx",
        "audience": "Single-tenant retail and redevelopment brokerage in the Austin MSA.",
    }
}


def available_client_views() -> list[dict]:
    return [
        {
            "view_id": key,
            **value,
        }
        for key, value in SUPPORTED_CLIENT_VIEWS.items()
    ]


def build_client_view(
    *,
    view_id: str,
    snapshot: RegionalIntelSnapshot,
    history_records: list[dict],
    source_history: list[dict],
    monitor_rules: list[IntelMonitorRule],
) -> ClientView:
    if view_id != "blanga_austin":
        raise KeyError(view_id)
    return _build_blanga_austin_view(
        snapshot=snapshot,
        history_records=history_records,
        source_history=source_history,
        monitor_rules=monitor_rules,
    )


def _intel_url(kind: str, item_id: str, *, region_id: RegionId | None = None) -> str:
    params: dict[str, str] = {}
    if region_id:
        params["region"] = region_id
    params["detail_kind"] = kind
    params["detail_id"] = item_id
    return f"/intel?{urlencode(params)}"


def _feed_item(
    *,
    item_id: str,
    item_kind: str,
    region_id: RegionId | None,
    title: str,
    subtitle: str | None,
    summary: str,
    why_it_matters: str | None,
    recommended_action: str | None,
    score: float,
    tags: list[str] | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    intel_url: str | None = None,
    notes: list[str] | None = None,
) -> ClientFeedItem:
    return ClientFeedItem(
        item_id=item_id,
        item_kind=item_kind,
        region_id=region_id,
        title=title,
        subtitle=subtitle,
        summary=summary,
        why_it_matters=why_it_matters,
        recommended_action=recommended_action,
        score=round(score, 2),
        tags=tags or [],
        source_name=source_name,
        source_url=source_url,
        intel_url=intel_url,
        notes=notes or [],
    )


def _is_retail_business(category: str, tags: dict[str, str]) -> bool:
    haystack = " ".join(
        [
            clean_text(category),
            " ".join(f"{clean_text(k)}:{clean_text(v)}" for k, v in tags.items()),
        ]
    ).lower()
    retail_terms = [
        "restaurant",
        "fast_food",
        "cafe",
        "ice_cream",
        "pharmacy",
        "dentist",
        "clinic",
        "medical",
        "fuel",
        "convenience",
        "retail",
        "shop:",
    ]
    return any(term in haystack for term in retail_terms)


def _looks_commercial_signal(*parts: str | None) -> bool:
    haystack = " ".join(clean_text(part) for part in parts if part).lower()
    if not haystack:
        return False
    negative_terms = [
        "residential",
        "single family",
        "single-family",
        "multifamily",
        "patio",
        "driveway",
        "septic",
        "irrigation",
        "fence",
        "solar",
        "roof replacement",
        "roofing only",
        "pool",
    ]
    if any(term in haystack for term in negative_terms):
        return False
    positive_terms = [
        "commercial",
        "retail",
        "restaurant",
        "qsr",
        "tenant",
        "improvement",
        "fit out",
        "fit-out",
        "office",
        "bank",
        "liquor",
        "business",
        "center",
        "medical",
        "clinic",
        "pharmacy",
        "warehouse",
        "shell",
        "site",
        "plat",
        "building",
        "suite",
        "ste ",
        "ste,",
        "ste.",
        "bldg",
        "unit",
        "hotel",
        "storage",
        "drive thru",
        "drive-thru",
        "fire alarm",
        "fire sprinkler",
        "underground fire",
    ]
    return any(term in haystack for term in positive_terms)


def _is_commercial_permit(item) -> bool:
    return _looks_commercial_signal(
        item.permit_type, item.address, " ".join(item.notes)
    )


def _build_blanga_austin_view(
    *,
    snapshot: RegionalIntelSnapshot,
    history_records: list[dict],
    source_history: list[dict],
    monitor_rules: list[IntelMonitorRule],
) -> ClientView:
    region_id: RegionId = "austin_tx"
    opportunities = build_opportunities(snapshot, region=region_id)
    entity_changes = build_entity_changes(history_records, region=region_id)
    incidents = build_source_incidents(source_history, region=region_id)
    evaluations = build_monitor_evaluations(
        snapshot,
        rules=[rule for rule in monitor_rules if rule.region_id in {None, region_id}],
        history_records=history_records,
        source_history=source_history,
    )

    austin_news = [item for item in snapshot.news if item.region_id == region_id]
    austin_permits = [item for item in snapshot.permits if item.region_id == region_id]
    austin_businesses = [
        item for item in snapshot.businesses if item.region_id == region_id
    ]
    austin_contacts = [
        item for item in snapshot.contacts if item.region_id == region_id
    ]
    austin_orgs = [
        item for item in snapshot.organizations if item.region_id == region_id
    ]
    permit_lookup = {item.item_id: item for item in austin_permits}

    vacancy_news = [
        item
        for item in austin_news
        if item.signal_type == "vacancy_or_closure"
        and (item.address_hint or item.actionable)
        and _looks_commercial_signal(
            item.title, item.summary, item.address_hint, " ".join(item.notes)
        )
    ]
    vacancy_news.sort(
        key=lambda item: (item.signal_score, item.published_at), reverse=True
    )

    construction_permits = [
        item
        for item in austin_permits
        if item.signal_type
        in {"construction", "commercial_development", "tenant_improvement"}
        and _is_commercial_permit(item)
    ]
    construction_permits.sort(
        key=lambda item: (item.signal_score, item.status_date), reverse=True
    )

    redevelopment_permits = [
        item
        for item in austin_permits
        if item.signal_type in {"commercial_development", "tenant_improvement"}
        and item.status.lower() in {"under review", "on hold", "approved", "active"}
        and _is_commercial_permit(item)
    ]
    redevelopment_permits.sort(
        key=lambda item: (item.signal_score, item.status_date), reverse=True
    )

    redevelopment_orgs = [
        item
        for item in austin_orgs
        if any(
            term in clean_text(",".join(item.categories)).lower()
            for term in ["commercial_development", "vacancy_or_closure"]
        )
    ]
    redevelopment_orgs.sort(key=lambda item: item.organization_score, reverse=True)

    retail_businesses = [
        item
        for item in austin_businesses
        if _is_retail_business(item.category, item.tags)
    ]
    retail_businesses.sort(key=lambda item: item.lead_score, reverse=True)

    contact_rows = sorted(
        austin_contacts, key=lambda item: item.contact_score, reverse=True
    )

    vacancy_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind="news",
            region_id=item.region_id,
            title=item.title,
            subtitle=item.address_hint or item.publication or item.source_name,
            summary=item.summary
            or "Vacancy or closure signal from public local media.",
            why_it_matters="Vacancy signals can create landlord motivation, repositioning angles, or near-term leasing/listing opportunities.",
            recommended_action="Verify the address, link ownership, and check for follow-on permits or listing activity.",
            score=item.signal_score,
            tags=[item.signal_type, "vacancy"],
            source_name=item.source_name,
            source_url=item.source_url,
            intel_url=_intel_url("news", item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in vacancy_news[:10]
    ]

    construction_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind="permit",
            region_id=item.region_id,
            title=item.address,
            subtitle=f"{item.county} | {item.permit_type}",
            summary=f"{item.status} permit from {item.source_name}.",
            why_it_matters="Retail/QSR/restaurant construction and TI work often signal tenant expansion, new competition, or nearby value movement.",
            recommended_action="Review the address, map nearby retail ownership, and decide whether this is an expansion comp, tenant lead, or adjacency signal.",
            score=item.signal_score,
            tags=[item.signal_type, item.status],
            source_name=item.source_name,
            source_url=item.source_url,
            intel_url=_intel_url("permit", item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in construction_permits[:12]
    ]

    redevelopment_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind="permit",
            region_id=item.region_id,
            title=item.address,
            subtitle=f"{item.status} | {item.permit_type}",
            summary=f"{item.county} {item.signal_type.replace('_', ' ')} signal.",
            why_it_matters="Commercial development or TI permits in non-final statuses can signal site repositioning, redevelopment friction, or a future ownership decision point.",
            recommended_action="Review the site, compare current use versus highest-and-best use, and watch for additional permit or vacancy activity.",
            score=item.signal_score,
            tags=[item.signal_type, item.status, "redevelopment"],
            source_name=item.source_name,
            source_url=item.source_url,
            intel_url=_intel_url("permit", item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in redevelopment_permits[:8]
    ] + [
        _feed_item(
            item_id=item.item_id,
            item_kind="organization",
            region_id=item.region_id,
            title=item.name,
            subtitle=item.address
            or ", ".join(item.categories[:2])
            or "organization watch",
            summary="Organization profile with development- or vacancy-linked signal density.",
            why_it_matters="Repeated business/news/permit linkage can point to owners, operators, or properties worth underwriting for repositioning.",
            recommended_action="Open the entity detail, inspect linked signals, and decide whether it belongs in an Austin redevelopment collection.",
            score=item.organization_score,
            tags=item.categories[:3] + ["redevelopment_watch"],
            source_name=", ".join(item.source_names[:2]) if item.source_names else None,
            source_url=item.website,
            intel_url=_intel_url(
                "organization", item.item_id, region_id=item.region_id
            ),
            notes=item.notes,
        )
        for item in redevelopment_orgs[:4]
    ]
    redevelopment_items.sort(key=lambda item: item.score, reverse=True)

    opportunity_items = [
        _feed_item(
            item_id=item.item_ids[0] if item.item_ids else item.opportunity_id,
            item_kind="organization"
            if item.kind == "organization"
            else "permit"
            if item.kind == "permit_signal"
            else "news",
            region_id=item.region_id,
            title=item.title,
            subtitle=item.kind.replace("_", " "),
            summary=item.summary,
            why_it_matters="This is the system’s highest-ranked Austin signal blend across permits, news, organizations, and contacts.",
            recommended_action="Use this as the top of the daily call/research queue.",
            score=item.score,
            tags=item.reasons[:3],
            source_url=item.urls[0] if item.urls else None,
            intel_url=_intel_url(
                "organization"
                if item.kind == "organization"
                else "permit"
                if item.kind == "permit_signal"
                else "news",
                item.item_ids[0] if item.item_ids else item.opportunity_id,
                region_id=item.region_id,
            )
            if item.item_ids
            else None,
            notes=item.notes,
        )
        for item in opportunities[:20]
        if item.kind != "permit_signal"
        or (
            item.item_ids
            and item.item_ids[0] in permit_lookup
            and _is_commercial_permit(permit_lookup[item.item_ids[0]])
        )
    ]

    business_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind="business",
            region_id=item.region_id,
            title=item.name,
            subtitle=item.address or item.category,
            summary=item.website or item.phone or "Public business lead",
            why_it_matters="Retail and service operators can become tenant, buyer, or market-color leads tied to specific corridors and nodes.",
            recommended_action="Review the address and public contact path, then save strong operator leads into a collection for outreach or market mapping.",
            score=item.lead_score,
            tags=[item.category],
            source_name=item.source_name,
            source_url=item.website or item.source_url,
            intel_url=_intel_url("business", item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in retail_businesses[:12]
    ]

    contact_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind="contact",
            region_id=item.region_id,
            title=item.name,
            subtitle=" | ".join(
                part for part in [item.title or "", item.organization] if part
            ),
            summary=" | ".join(
                part
                for part in [item.email or "", item.phone or "", item.address or ""]
                if part
            )
            or "Public contact path",
            why_it_matters="Public professional contacts help with economic-development context, permitting follow-up, and market validation.",
            recommended_action="Use for context gathering and public-side research, not private outreach assumptions.",
            score=item.contact_score,
            tags=["public_contact"],
            source_name=item.source_name,
            source_url=item.website or item.source_url,
            intel_url=_intel_url("contact", item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in contact_rows[:8]
    ]

    change_items = [
        _feed_item(
            item_id=item.item_id,
            item_kind=item.kind,
            region_id=item.region_id,
            title=item.title,
            subtitle=item.change_type.replace("_", " "),
            summary=item.summary,
            why_it_matters="This is the direct answer to what changed, not just how counts moved.",
            recommended_action="Open detail if it is relevant to current Austin coverage, then decide whether to save it into a dossier or monitor rule.",
            score=abs((item.score_after or 0.0) - (item.score_before or 0.0))
            or float(item.score_after or item.score_before or 0.0),
            tags=[item.kind, item.change_type],
            intel_url=_intel_url(item.kind, item.item_id, region_id=item.region_id),
            notes=item.notes,
        )
        for item in entity_changes[:24]
        if item.kind != "permit" or _looks_commercial_signal(item.title, item.summary)
    ]

    monitor_items = []
    for evaluation in evaluations[:6]:
        for match in evaluation.matches[:3]:
            if match.kind == "permit" and not _looks_commercial_signal(
                match.title, match.summary
            ):
                continue
            monitor_items.append(
                _feed_item(
                    item_id=match.item_id or match.match_id,
                    item_kind=match.kind or match.source_kind,
                    region_id=match.region_id,
                    title=f"{evaluation.rule.title}: {match.title}",
                    subtitle=match.source_kind.replace("_", " "),
                    summary=match.summary,
                    why_it_matters="Saved monitor rules let this client view act like a standing intelligence inbox, not just a dashboard.",
                    recommended_action="Adjust or add monitor rules when the client’s focus changes.",
                    score=match.score,
                    tags=[match.severity, evaluation.rule.title],
                    source_url=match.url,
                    intel_url=_intel_url(
                        match.kind, match.item_id, region_id=match.region_id
                    )
                    if match.item_id
                    and match.kind
                    in {"news", "permit", "business", "contact", "organization"}
                    else None,
                    notes=match.notes,
                )
            )

    hero_metrics = [
        ClientViewMetric(
            label="Vacancy signals",
            value=str(len(vacancy_news)),
            detail="Address-backed closure or move-out coverage",
        ),
        ClientViewMetric(
            label="Construction + TI",
            value=str(len(construction_permits)),
            detail="Retail development and tenant work",
        ),
        ClientViewMetric(
            label="Retail leads",
            value=str(len(retail_businesses)),
            detail="Operators and tenant-style business leads",
        ),
        ClientViewMetric(
            label="Today changes",
            value=str(len(change_items)),
            detail="Brokerage-relevant entity changes surfaced in this feed",
        ),
        ClientViewMetric(
            label="Public contacts",
            value=str(len(contact_rows)),
            detail="Official or public professional contact paths",
        ),
    ]

    sections = [
        ClientFeedSection(
            section_id="deal_radar",
            title="Austin Deal Radar",
            summary="The highest-ranked Austin opportunities across vacancy, development, organizations, and public signals.",
            items=opportunity_items,
            notes=["Start here each day if you only have ten minutes."],
        ),
        ClientFeedSection(
            section_id="vacancy_feed",
            title="Vacancy + Closure Feed",
            summary="Public local-news items that suggest a space may be vacant or a tenant may be leaving.",
            items=vacancy_items,
            notes=[
                "Address-bearing vacancy signals are the highest-confidence items here."
            ],
        ),
        ClientFeedSection(
            section_id="construction_feed",
            title="Retail Construction + TI Feed",
            summary="Austin-area construction, TI, and commercial development permits relevant to retail and tenant movement.",
            items=construction_items,
            notes=[
                "This is best used to spot tenant expansion, new competition, and adjacent ownership opportunities."
            ],
        ),
        ClientFeedSection(
            section_id="redevelopment_watch",
            title="Redevelopment + Repositioning Watch",
            summary="A blended view of permits and entities that look more like repositioning or redevelopment candidates than simple stabilized retail.",
            items=redevelopment_items[:12],
            notes=[
                "This section intentionally prioritizes friction, vacancy, and development transitions over stabilized assets."
            ],
        ),
        ClientFeedSection(
            section_id="operator_leads",
            title="Retail Operator + Tenant Leads",
            summary="Public operator and tenant-style businesses in Austin that can be used for market mapping, outreach prep, and tenant intelligence.",
            items=business_items,
        ),
        ClientFeedSection(
            section_id="contact_paths",
            title="Public Contact Paths",
            summary="Public economic-development and business-facing contacts that help with context and verification.",
            items=contact_items,
        ),
        ClientFeedSection(
            section_id="what_changed",
            title="What Changed Recently",
            summary="Direct entity-level diffs in Austin so the brokerage workflow starts from change, not static records.",
            items=change_items,
        ),
        ClientFeedSection(
            section_id="monitor_hits",
            title="Saved Monitor Hits",
            summary="Matches from saved Austin monitor rules so repeat filters turn into a standing client inbox.",
            items=monitor_items[:12],
            notes=[
                "Monitor rules are reusable across client views, which is the core extensibility pattern here."
            ],
        ),
    ]

    return ClientView(
        view_id="blanga_austin",
        client_name="Blanga Intelligence System",
        title="Austin STNL + Redevelopment Feed",
        summary="A client-specific Austin feed for brokerage work: vacancies, construction, repositioning signals, retail leads, public contacts, and recent changes.",
        region_id=region_id,
        audience="Single-tenant retail and redevelopment brokerage in Travis, Williamson, Hays, Bastrop, and nearby Austin MSA submarkets.",
        playbook=[
            "Start with Deal Radar and Vacancy + Closure Feed.",
            "Use Retail Construction + TI to spot tenant expansion, new competition, and adjacency opportunities.",
            "Use Redevelopment + Repositioning Watch for underutilized-site thinking, not just stabilized retail.",
            "Save anything worth pursuing into Collections, then package into Bundles for client-ready delivery.",
        ],
        hero_metrics=hero_metrics,
        sections=sections,
        notes=[
            "This is a custom client view built on top of the shared regional-intel framework.",
            "The feed is tailored to brokerage use cases, but still keeps public-source provenance and the broader graph available underneath.",
            f"Source incidents in scope right now: {len(incidents)} Austin-relevant reliability events.",
        ],
    )
