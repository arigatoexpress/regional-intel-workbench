from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


CONTRACT_SCHEMA_ID = "regional_intel.route_readiness.v1"

AccessClass = Literal[
    "public_read",
    "public_preview",
    "local_read",
    "local_write",
    "admin_read",
    "health_read",
    "legacy_read",
]
AuthClass = Literal["none", "admin_token"]
SideEffectClass = Literal["none", "read_through_refresh", "local_store_write"]


class SourcePolicy(BaseModel):
    public_source_only: bool = True
    provenance_required: bool = True
    source_health_visible: bool = True
    login_gated_scraping_allowed: bool = False
    paywall_bypass_allowed: bool = False
    private_person_dossiering_allowed: bool = False
    external_writes_allowed: bool = False


class RouteContract(BaseModel):
    path: str
    methods: list[str]
    access_class: AccessClass
    auth: AuthClass = "none"
    side_effects: SideEffectClass = "none"
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)
    response_contract: str
    purpose: str
    integration_notes: list[str] = Field(default_factory=list)


class RuntimeRoute(BaseModel):
    path: str
    methods: list[str]
    name: str | None = None


class ReadinessSummary(BaseModel):
    status: Literal["ready", "needs_review"]
    route_count: int
    local_read_route_count: int
    local_write_route_count: int
    admin_route_count: int
    declared_paths_present: bool
    undeclared_app_paths: list[str] = Field(default_factory=list)
    missing_declared_paths: list[str] = Field(default_factory=list)


class RouteReadinessContract(BaseModel):
    schema_id: str = CONTRACT_SCHEMA_ID
    title: str = "Regional Intelligence Workbench Route Readiness Contract"
    version: str = "1.0.0"
    posture: SourcePolicy = Field(default_factory=SourcePolicy)
    openapi_path: str = "/openapi.json"
    human_surfaces: list[str]
    machine_surfaces: list[str]
    routes: list[RouteContract]
    runtime_routes: list[RuntimeRoute] = Field(default_factory=list)
    readiness: ReadinessSummary


def _route(
    path: str,
    methods: Sequence[str],
    *,
    access_class: AccessClass,
    response_contract: str,
    purpose: str,
    auth: AuthClass = "none",
    side_effects: SideEffectClass = "none",
    source_health_visible: bool = True,
    integration_notes: Sequence[str] = (),
) -> RouteContract:
    return RouteContract(
        path=path,
        methods=sorted({method.upper() for method in methods}),
        access_class=access_class,
        auth=auth,
        side_effects=side_effects,
        source_policy=SourcePolicy(source_health_visible=source_health_visible),
        response_contract=response_contract,
        purpose=purpose,
        integration_notes=list(integration_notes),
    )


ROUTE_CONTRACTS: tuple[RouteContract, ...] = (
    _route(
        "/",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Workbench launch surface with guardrails and route entrypoints.",
        source_health_visible=False,
    ),
    _route(
        "/intel",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Analyst console for map, search, provenance, and briefing workflows.",
    ),
    _route(
        "/field-ops",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Unified read-only regional, wildfire-watch, and UAS readiness workbench.",
        integration_notes=[
            "No dispatch, drone command, LoRa command, or external notification control is exposed.",
        ],
    ),
    _route(
        "/client-views/{view_id}",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Client-specific read-only regional intelligence page.",
    ),
    _route(
        "/blanga/austin",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Stable Austin client-view alias for brokerage review.",
    ),
    _route(
        "/admin",
        ["GET"],
        access_class="public_preview",
        response_contract="text/html",
        purpose="Admin shell; every /api/admin/* data call remains token-gated.",
        source_health_visible=False,
    ),
    _route(
        "/api/intel/contracts",
        ["GET"],
        access_class="public_read",
        response_contract=CONTRACT_SCHEMA_ID,
        purpose="Machine-readable route, provenance, and readiness contract.",
        integration_notes=["Preferred integration discovery endpoint."],
    ),
    _route(
        "/api/intel/field-ops",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.field_ops.v1",
        purpose="Unified derived field-ops payload for regional context, wildfire-watch overlays, and UAS readiness state.",
        integration_notes=[
            "Derived analysis only; no raw payload resale.",
            "No drone commands, dispatch sends, fire-dept notifications, Telegram sends, or external writes are allowed.",
        ],
    ),
    _route(
        "/api/snapshot",
        ["GET"],
        access_class="legacy_read",
        side_effects="read_through_refresh",
        response_contract="regional_vote.snapshot.v1",
        purpose="Legacy vote-monitor snapshot API retained for compatibility.",
        source_health_visible=False,
    ),
    _route(
        "/api/client-views",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.client_views.index.v1",
        purpose="List available client views and canonical page/API URLs.",
    ),
    _route(
        "/api/client-views/{view_id}",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.client_view.v1",
        purpose="Client-specific feed with sectioned items, metrics, and provenance.",
        integration_notes=["Use without force=true for stored-read behavior."],
    ),
    _route(
        "/api/intel/recent",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.recent_feed.v1",
        purpose="Bounded recent-item feed for downstream dashboards and proxies.",
        integration_notes=["Limit is capped server-side at 50 items."],
    ),
    _route(
        "/api/intel/source-health",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.source_health.v1",
        purpose="Source freshness, drop, and health state by region.",
    ),
    _route(
        "/api/intel/source-history",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.source_history.v1",
        purpose="Historical source-health trajectory from local stored snapshots.",
    ),
    _route(
        "/api/intel/ooda-packet",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.ooda_packet.v1",
        purpose="Read-only OODA packet built from the latest stored snapshot.",
        integration_notes=["No source refresh, external call, or write is allowed."],
    ),
    _route(
        "/api/intel/regions",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.regions.v1",
        purpose="Configured region catalog for frontend filters and routing.",
    ),
    _route(
        "/api/intel/sources",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.sources.v1",
        purpose="Ethics rules and public-source catalog.",
    ),
    _route(
        "/api/intel/snapshot",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.snapshot.v1",
        purpose="Full or region-filtered regional intelligence snapshot.",
    ),
    _route(
        "/api/intel/search",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.search.v1",
        purpose="Public-source full-text search over the current snapshot.",
    ),
    _route(
        "/api/intel/briefs",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.briefs.v1",
        purpose="Region-filtered public-source brief collection.",
    ),
    _route(
        "/api/intel/organizations/{item_id}",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.organization_detail.v1",
        purpose="Organization detail with provenance-bearing fields.",
    ),
    _route(
        "/api/intel/items/{kind}/{item_id}",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.item_detail.v1",
        purpose="Generic public-source item detail endpoint.",
    ),
    _route(
        "/api/intel/graph",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.graph.v1",
        purpose="Relationship graph for regional intel maps.",
    ),
    _route(
        "/api/intel/opportunities",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.opportunities.v1",
        purpose="Public-source opportunity queue derived from the snapshot.",
    ),
    _route(
        "/api/intel/alerts",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.alerts.v1",
        purpose="Operational alerts derived from public-source signal density.",
    ),
    _route(
        "/api/intel/source-incidents",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.source_incidents.v1",
        purpose="Source-health incident list from stored history.",
    ),
    _route(
        "/api/intel/region-changes",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.region_changes.v1",
        purpose="Region-level change events from stored history.",
    ),
    _route(
        "/api/intel/entity-changes",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.entity_changes.v1",
        purpose="Entity-level change events from stored history.",
    ),
    _route(
        "/api/intel/region-briefing/{region_id}",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.region_briefing.v1",
        purpose="Structured regional briefing pack.",
    ),
    _route(
        "/api/intel/region-briefing/{region_id}/markdown",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="text/markdown",
        purpose="Markdown regional briefing export.",
    ),
    _route(
        "/api/intel/briefing/{item_id}",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.entity_briefing.v1",
        purpose="Structured briefing pack, optionally enriched with local notes.",
    ),
    _route(
        "/api/intel/briefing/{item_id}/markdown",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="text/markdown",
        purpose="Markdown briefing export, optionally enriched with local notes.",
    ),
    _route(
        "/api/intel/timeline/{item_id}",
        ["GET"],
        access_class="public_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.timeline.v1",
        purpose="Public-source entity timeline.",
    ),
    _route(
        "/api/intel/annotations/{target_kind}/{target_id}",
        ["GET"],
        access_class="local_read",
        response_contract="regional_intel.annotation.v1",
        purpose="Local analyst annotation lookup.",
    ),
    _route(
        "/api/intel/annotations",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.annotation.v1",
        purpose="Local analyst annotation write endpoint.",
    ),
    _route(
        "/api/intel/annotations/{target_kind}/{target_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.annotation.v1",
        purpose="Local analyst annotation delete endpoint.",
    ),
    _route(
        "/api/intel/watchlist-items",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.watchlist_items.v1",
        purpose="Local analyst watchlist with live public-source resolution.",
    ),
    _route(
        "/api/intel/watchlist-items",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.watchlist_item.v1",
        purpose="Local analyst watchlist write endpoint.",
        integration_notes=["Writes only to the local analyst store."],
    ),
    _route(
        "/api/intel/watchlist-items/{entry_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.watchlist_item_delete.v1",
        purpose="Local analyst watchlist delete endpoint.",
    ),
    _route(
        "/api/intel/watchlist",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.watchlist.v1",
        purpose="Resolved local watchlist view for analyst workflows.",
    ),
    _route(
        "/api/intel/collections",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.collections.v1",
        purpose="Local briefing collection index with live item resolution.",
    ),
    _route(
        "/api/intel/collections",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.collection.v1",
        purpose="Local briefing collection create endpoint.",
    ),
    _route(
        "/api/intel/collections/{collection_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.collection_delete.v1",
        purpose="Local briefing collection delete endpoint.",
    ),
    _route(
        "/api/intel/collections/{collection_id}/items",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.collection_item.v1",
        purpose="Local briefing collection item save endpoint.",
    ),
    _route(
        "/api/intel/collections/{collection_id}/items/{ref_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.collection_item_delete.v1",
        purpose="Local briefing collection item delete endpoint.",
    ),
    _route(
        "/api/intel/collections/{collection_id}/briefing",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.collection_briefing.v1",
        purpose="Structured briefing pack for a local collection.",
    ),
    _route(
        "/api/intel/collections/{collection_id}/briefing/markdown",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="text/markdown",
        purpose="Markdown briefing export for a local collection.",
    ),
    _route(
        "/api/intel/bundles",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.briefing_bundles.v1",
        purpose="Local briefing bundle index with live collection resolution.",
    ),
    _route(
        "/api/intel/bundles",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.briefing_bundle.v1",
        purpose="Local briefing bundle create endpoint.",
    ),
    _route(
        "/api/intel/bundles/{bundle_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.briefing_bundle_delete.v1",
        purpose="Local briefing bundle delete endpoint.",
    ),
    _route(
        "/api/intel/bundles/{bundle_id}/collections",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.briefing_bundle_collection.v1",
        purpose="Local briefing bundle collection attach endpoint.",
    ),
    _route(
        "/api/intel/bundles/{bundle_id}/collections/{ref_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.briefing_bundle_collection_delete.v1",
        purpose="Local briefing bundle collection detach endpoint.",
    ),
    _route(
        "/api/intel/bundles/{bundle_id}/briefing",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.briefing_bundle_pack.v1",
        purpose="Structured briefing pack for a local bundle.",
    ),
    _route(
        "/api/intel/bundles/{bundle_id}/briefing/markdown",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="text/markdown",
        purpose="Markdown briefing export for a local bundle.",
    ),
    _route(
        "/api/intel/monitor-rules",
        ["GET"],
        access_class="local_read",
        side_effects="read_through_refresh",
        response_contract="regional_intel.monitor_rules.v1",
        purpose="Local monitor-rule state with public-source match context.",
    ),
    _route(
        "/api/intel/monitor-rules",
        ["POST"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.monitor_rule.v1",
        purpose="Local monitor-rule create endpoint.",
    ),
    _route(
        "/api/intel/monitor-rules/{rule_id}",
        ["DELETE"],
        access_class="local_write",
        side_effects="local_store_write",
        response_contract="regional_intel.monitor_rule_delete.v1",
        purpose="Local monitor-rule delete endpoint.",
    ),
    _route(
        "/api/intel/trends",
        ["GET"],
        access_class="public_read",
        response_contract="regional_intel.trends.v1",
        purpose="Stored-history regional trend payload.",
    ),
    _route(
        "/api/admin/overview",
        ["GET"],
        access_class="admin_read",
        auth="admin_token",
        side_effects="read_through_refresh",
        response_contract="regional_intel.admin_overview.v1",
        purpose="Operator-only source health, trends, monitor, and feed overview.",
    ),
    _route(
        "/api/admin/regions",
        ["GET"],
        access_class="admin_read",
        auth="admin_token",
        response_contract="regional_intel.admin_regions.v1",
        purpose="Operator-only region catalog with map bounds.",
    ),
    _route(
        "/api/admin/search",
        ["GET"],
        access_class="admin_read",
        auth="admin_token",
        side_effects="read_through_refresh",
        response_contract="regional_intel.admin_search.v1",
        purpose="Operator-only full-text search over current snapshot.",
    ),
    _route(
        "/api/intel/health",
        ["GET"],
        access_class="health_read",
        response_contract="regional_intel.health.v1",
        purpose="Regional intel service health check.",
        source_health_visible=False,
    ),
    _route(
        "/api/health",
        ["GET"],
        access_class="health_read",
        response_contract="regional_intel.health.v1",
        purpose="Simple local health check.",
        source_health_visible=False,
    ),
    _route(
        "/healthz/",
        ["GET"],
        access_class="health_read",
        response_contract="regional_intel.health.v1",
        purpose="Cloud Run and Kubernetes style health probe.",
        source_health_visible=False,
    ),
    _route(
        "/api/strategy",
        ["GET"],
        access_class="legacy_read",
        side_effects="read_through_refresh",
        response_contract="regional_vote.strategy.v1",
        purpose="Legacy strategy snapshot API retained for vote-monitor compatibility.",
        source_health_visible=False,
    ),
    _route(
        "/api/digest",
        ["GET"],
        access_class="legacy_read",
        side_effects="read_through_refresh",
        response_contract="regional_vote.digest.v1",
        purpose="Legacy digest API retained for vote-monitor compatibility.",
        source_health_visible=False,
    ),
    _route(
        "/vote-monitor",
        ["GET"],
        access_class="legacy_read",
        response_contract="text/html",
        purpose="Legacy vote-monitor compatibility surface.",
        source_health_visible=False,
    ),
)


def build_route_readiness_contract(
    runtime_routes: Sequence[Mapping[str, Any]] | None = None,
) -> RouteReadinessContract:
    declared_routes = list(ROUTE_CONTRACTS)
    declared_paths = {item.path for item in declared_routes}
    runtime = [
        RuntimeRoute(
            path=str(route.get("path")),
            methods=sorted(str(method).upper() for method in route.get("methods", [])),
            name=str(route.get("name")) if route.get("name") else None,
        )
        for route in runtime_routes or []
    ]
    runtime_paths = {item.path for item in runtime}
    undeclared_app_paths = sorted(
        path
        for path in runtime_paths - declared_paths
        if not path.startswith("/static") and path != "/openapi.json"
    )
    missing_declared_paths = sorted(declared_paths - runtime_paths) if runtime else []
    readiness = ReadinessSummary(
        status=(
            "ready"
            if not missing_declared_paths
            and all(route.source_policy.public_source_only for route in declared_routes)
            else "needs_review"
        ),
        route_count=len(declared_routes),
        local_read_route_count=sum(
            route.access_class == "local_read" for route in declared_routes
        ),
        local_write_route_count=sum(
            route.access_class == "local_write" for route in declared_routes
        ),
        admin_route_count=sum(
            route.access_class == "admin_read" for route in declared_routes
        ),
        declared_paths_present=not missing_declared_paths,
        undeclared_app_paths=undeclared_app_paths,
        missing_declared_paths=missing_declared_paths,
    )
    return RouteReadinessContract(
        human_surfaces=[
            "/",
            "/intel",
            "/field-ops",
            "/client-views/{view_id}",
            "/admin",
        ],
        machine_surfaces=[
            "/api/intel/contracts",
            "/api/intel/field-ops",
            "/api/client-views",
            "/api/client-views/{view_id}",
            "/api/intel/recent",
            "/api/intel/source-health",
            "/api/intel/ooda-packet",
        ],
        routes=declared_routes,
        runtime_routes=runtime,
        readiness=readiness,
    )
