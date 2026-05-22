from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


RegionId = Literal["austin_tx", "houston_tx", "gunnison_valley_co"]
IntelCategory = Literal["news", "permit", "business", "contacts"]


class EthicsRule(BaseModel):
    key: str
    title: str
    description: str


class IntelSource(BaseModel):
    source_key: str
    region_ids: list[RegionId] = Field(default_factory=list)
    category: IntelCategory
    name: str
    collection_mode: str
    access: str
    live_pull: bool = False
    url: str | None = None
    notes: str = ""


class RegionProfile(BaseModel):
    id: RegionId
    name: str
    summary: str
    bbox: list[float]
    focus_keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)


class NewsSignal(BaseModel):
    item_id: str
    region_id: RegionId
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: str
    publication: str | None = None
    signal_type: str
    address_hint: str | None = None
    actionable: bool = False
    organizations: list[str] = Field(default_factory=list)
    query: str = ""
    signal_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class PermitSignal(BaseModel):
    item_id: str
    region_id: RegionId
    county: str
    address: str
    permit_number: str
    permit_type: str
    status: str
    status_date: str
    source_name: str
    source_url: str
    signal_type: str
    actionable: bool = True
    signal_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class BusinessLead(BaseModel):
    item_id: str
    region_id: RegionId
    name: str
    category: str
    address: str
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    lat: float | None = None
    lon: float | None = None
    source_name: str
    source_url: str
    lead_score: float = 0.0
    tags: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class PublicContact(BaseModel):
    item_id: str
    region_id: RegionId
    name: str
    title: str | None = None
    organization: str
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    source_name: str
    source_url: str
    contact_type: str = "public_professional_contact"
    contact_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class OrganizationProfile(BaseModel):
    item_id: str
    region_id: RegionId
    name: str
    categories: list[str] = Field(default_factory=list)
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    business_lead_count: int = 0
    news_signal_count: int = 0
    contact_count: int = 0
    permit_signal_count: int = 0
    source_names: list[str] = Field(default_factory=list)
    latest_activity_at: str | None = None
    organization_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class SourceHealth(BaseModel):
    source_key: str
    name: str
    category: IntelCategory
    region_ids: list[RegionId] = Field(default_factory=list)
    live_pull: bool = False
    status: str
    item_count: int = 0
    last_seen_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class RegionBrief(BaseModel):
    region_id: RegionId
    headline: str
    summary: str
    top_news_ids: list[str] = Field(default_factory=list)
    top_permit_ids: list[str] = Field(default_factory=list)
    top_organization_ids: list[str] = Field(default_factory=list)
    top_contact_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelGraphNode(BaseModel):
    node_id: str
    kind: str
    region_id: RegionId | None = None
    label: str
    subtitle: str | None = None
    score: float = 0.0
    url: str | None = None
    address: str | None = None
    notes: list[str] = Field(default_factory=list)


class IntelGraphEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    notes: list[str] = Field(default_factory=list)


class IntelGraph(BaseModel):
    region: RegionId | None = None
    focus_node_id: str | None = None
    nodes: list[IntelGraphNode] = Field(default_factory=list)
    edges: list[IntelGraphEdge] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelTimelineEvent(BaseModel):
    event_id: str
    region_id: RegionId
    occurred_at: str
    kind: str
    title: str
    subtitle: str | None = None
    detail: str | None = None
    score: float = 0.0
    url: str | None = None
    notes: list[str] = Field(default_factory=list)


class IntelOpportunity(BaseModel):
    opportunity_id: str
    region_id: RegionId
    kind: str
    title: str
    summary: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelWatchlistEntry(BaseModel):
    entry_id: str
    created_at: str
    updated_at: str
    kind: str
    label: str
    region_id: RegionId | None = None
    item_id: str | None = None
    source_url: str | None = None
    note: str | None = None
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class IntelAnalystAnnotation(BaseModel):
    annotation_id: str
    target_kind: str
    target_id: str
    created_at: str
    updated_at: str
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelBriefingPack(BaseModel):
    item_id: str
    region_id: RegionId
    title: str
    summary: str
    reasons: list[str] = Field(default_factory=list)
    public_contacts: list[dict] = Field(default_factory=list)
    timeline: list[IntelTimelineEvent] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    markdown: str = ""
    notes: list[str] = Field(default_factory=list)


class IntelAlert(BaseModel):
    alert_id: str
    region_id: RegionId | None = None
    severity: str
    kind: str
    title: str
    summary: str
    score: float = 0.0
    item_ids: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelRegionBriefingPack(BaseModel):
    region_id: RegionId
    title: str
    summary: str
    top_opportunities: list[dict] = Field(default_factory=list)
    top_watchlist: list[dict] = Field(default_factory=list)
    top_contacts: list[dict] = Field(default_factory=list)
    source_alerts: list[IntelAlert] = Field(default_factory=list)
    markdown: str = ""
    notes: list[str] = Field(default_factory=list)


class IntelCollectionItemRef(BaseModel):
    ref_id: str
    created_at: str
    updated_at: str
    kind: str
    label: str
    region_id: RegionId | None = None
    item_id: str | None = None
    source_url: str | None = None
    note: str | None = None
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class IntelCollection(BaseModel):
    collection_id: str
    created_at: str
    updated_at: str
    title: str
    region_id: RegionId | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    items: list[IntelCollectionItemRef] = Field(default_factory=list)
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class IntelCollectionBriefingPack(BaseModel):
    collection_id: str
    title: str
    region_id: RegionId | None = None
    summary: str
    items: list[dict] = Field(default_factory=list)
    linked_opportunities: list[dict] = Field(default_factory=list)
    public_contacts: list[dict] = Field(default_factory=list)
    source_alerts: list[IntelAlert] = Field(default_factory=list)
    markdown: str = ""
    notes: list[str] = Field(default_factory=list)


class IntelBriefingBundleRef(BaseModel):
    ref_id: str
    created_at: str
    updated_at: str
    collection_id: str
    label: str
    notes: list[str] = Field(default_factory=list)


class IntelBriefingBundle(BaseModel):
    bundle_id: str
    created_at: str
    updated_at: str
    title: str
    region_id: RegionId | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[IntelBriefingBundleRef] = Field(default_factory=list)
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class IntelBundleBriefingPack(BaseModel):
    bundle_id: str
    title: str
    region_id: RegionId | None = None
    summary: str
    collections: list[dict] = Field(default_factory=list)
    linked_opportunities: list[dict] = Field(default_factory=list)
    public_contacts: list[dict] = Field(default_factory=list)
    source_alerts: list[IntelAlert] = Field(default_factory=list)
    markdown: str = ""
    notes: list[str] = Field(default_factory=list)


class IntelSourceIncident(BaseModel):
    incident_id: str
    source_key: str
    name: str
    category: IntelCategory
    region_ids: list[RegionId] = Field(default_factory=list)
    severity: str
    incident_type: str
    started_at: str
    latest_at: str
    run_count: int = 0
    last_item_count: int = 0
    summary: str
    notes: list[str] = Field(default_factory=list)


class IntelRegionChange(BaseModel):
    change_id: str
    region_id: RegionId
    latest_at: str
    previous_at: str | None = None
    summary: str
    delta_news: int = 0
    delta_permits: int = 0
    delta_businesses: int = 0
    delta_contacts: int = 0
    delta_organizations: int = 0
    notable_lines: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntelEntityChange(BaseModel):
    change_id: str
    region_id: RegionId
    kind: str
    item_id: str
    title: str
    change_type: str
    latest_at: str
    previous_at: str | None = None
    summary: str
    score_before: float | None = None
    score_after: float | None = None
    notes: list[str] = Field(default_factory=list)


class IntelMonitorRule(BaseModel):
    rule_id: str
    created_at: str
    updated_at: str
    title: str
    region_id: RegionId | None = None
    entity_kinds: list[str] = Field(default_factory=list)
    change_types: list[str] = Field(default_factory=list)
    incident_types: list[str] = Field(default_factory=list)
    keyword: str | None = None
    min_score_delta: float | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class IntelMonitorMatch(BaseModel):
    match_id: str
    rule_id: str
    source_kind: str
    region_id: RegionId | None = None
    title: str
    summary: str
    occurred_at: str
    severity: str = "info"
    kind: str | None = None
    item_id: str | None = None
    url: str | None = None
    score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class IntelMonitorEvaluation(BaseModel):
    rule: IntelMonitorRule
    summary: str
    matches: list[IntelMonitorMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClientViewMetric(BaseModel):
    label: str
    value: str
    detail: str | None = None


class ClientFeedItem(BaseModel):
    item_id: str
    item_kind: str
    region_id: RegionId | None = None
    title: str
    subtitle: str | None = None
    summary: str
    why_it_matters: str | None = None
    recommended_action: str | None = None
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    source_name: str | None = None
    source_url: str | None = None
    intel_url: str | None = None
    notes: list[str] = Field(default_factory=list)


class ClientFeedSection(BaseModel):
    section_id: str
    title: str
    summary: str
    items: list[ClientFeedItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClientView(BaseModel):
    view_id: str
    client_name: str
    title: str
    summary: str
    region_id: RegionId | None = None
    audience: str | None = None
    playbook: list[str] = Field(default_factory=list)
    hero_metrics: list[ClientViewMetric] = Field(default_factory=list)
    sections: list[ClientFeedSection] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FieldOpsPosture(BaseModel):
    mode: Literal["read_only_planning"] = "read_only_planning"
    public_source_only: bool = True
    external_actions_allowed: bool = False
    drone_command_allowed: bool = False
    dispatch_allowed: bool = False
    live_flight_authorization_required: bool = True
    notes: list[str] = Field(default_factory=list)


class FieldOpsSource(BaseModel):
    source_id: str
    owner: str
    title: str
    source_url: str | None = None
    retrieval_mode: str
    retrieved_at: str
    license_or_rights: str
    freshness_ttl: str
    output_policy: str
    caveats: list[str] = Field(default_factory=list)


class FieldOpsMetric(BaseModel):
    label: str
    value: str
    detail: str
    status: Literal["ready", "review", "blocked", "safe"] = "review"


class FieldOpsLayer(BaseModel):
    layer_id: str
    label: str
    description: str
    item_count: int = 0
    enabled_default: bool = True
    source_ids: list[str] = Field(default_factory=list)


class FieldOpsZone(BaseModel):
    zone_id: str
    label: str
    region_id: RegionId
    zone_type: Literal["mission_zone", "exclusion", "coordination"]
    bbox: list[float]
    centroid: list[float]
    geometry: dict[str, Any] = Field(default_factory=dict)
    fuel_load_class: str | None = None
    primary_risk: str | None = None
    phase: int | None = None
    regulatory_basis: str | None = None
    source_id: str
    notes: list[str] = Field(default_factory=list)


class FieldOpsSignal(BaseModel):
    signal_id: str
    region_id: RegionId
    zone_id: str
    signal_type: str
    title: str
    summary: str
    timestamp: str
    lat: float
    lon: float
    target_lat: float | None = None
    target_lon: float | None = None
    confidence: float
    risk_score: float
    severity: Literal["low", "medium", "high", "critical"]
    recommended_action: str
    safe_action_label: str
    source_id: str
    source_url: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FieldOpsAsset(BaseModel):
    asset_id: str
    label: str
    layer: str
    status: Literal[
        "ready",
        "needs_live_check",
        "not_connected",
        "reference_only",
        "bench_verified",
        "field_verified",
        "offline",
    ]
    summary: str
    lat: float | None = None
    lon: float | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    comms_link: str | None = None
    last_update_utc: str | None = None
    readiness: dict[str, Any] = Field(default_factory=dict)
    source_id: str
    notes: list[str] = Field(default_factory=list)


class FieldOpsWeatherGate(BaseModel):
    gate_id: str
    label: str
    status: Literal["requires_live_sensor", "ready", "blocked", "review"]
    threshold: str
    summary: str
    source_id: str
    notes: list[str] = Field(default_factory=list)


class FieldOpsLandmark(BaseModel):
    landmark_id: str
    label: str
    kind: str
    lat: float
    lon: float
    elevation_m: int | None = None
    summary: str
    source_id: str
    notes: list[str] = Field(default_factory=list)


class FieldOpsExternalReference(BaseModel):
    reference_id: str
    label: str
    kind: str
    status: str
    summary: str
    source_id: str
    source_url: str | None = None
    lat: float | None = None
    lon: float | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class FieldOpsAction(BaseModel):
    action_id: str
    label: str
    status: Literal["safe_next_step", "blocked_until_human", "reference_only"]
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FieldOpsSnapshot(BaseModel):
    schema_id: str = "regional_intel.field_ops.v1"
    generated_at: str
    region_id: RegionId
    region_name: str
    posture: FieldOpsPosture
    metrics: list[FieldOpsMetric] = Field(default_factory=list)
    layers: list[FieldOpsLayer] = Field(default_factory=list)
    zones: list[FieldOpsZone] = Field(default_factory=list)
    signals: list[FieldOpsSignal] = Field(default_factory=list)
    assets: list[FieldOpsAsset] = Field(default_factory=list)
    landmarks: list[FieldOpsLandmark] = Field(default_factory=list)
    weather_gates: list[FieldOpsWeatherGate] = Field(default_factory=list)
    external_references: list[FieldOpsExternalReference] = Field(default_factory=list)
    regional_context: list[dict[str, Any]] = Field(default_factory=list)
    action_queue: list[FieldOpsAction] = Field(default_factory=list)
    sources: list[FieldOpsSource] = Field(default_factory=list)
    provenance_summary: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RegionalIntelSnapshot(BaseModel):
    updated_at: str
    cache_ttl_seconds: int
    regions: list[RegionProfile] = Field(default_factory=list)
    ethics_rules: list[EthicsRule] = Field(default_factory=list)
    sources: list[IntelSource] = Field(default_factory=list)
    news: list[NewsSignal] = Field(default_factory=list)
    permits: list[PermitSignal] = Field(default_factory=list)
    businesses: list[BusinessLead] = Field(default_factory=list)
    contacts: list[PublicContact] = Field(default_factory=list)
    organizations: list[OrganizationProfile] = Field(default_factory=list)
    source_health: list[SourceHealth] = Field(default_factory=list)
    briefs: list[RegionBrief] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
