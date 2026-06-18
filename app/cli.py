from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings, resolve_vote_powers
from app.intel_models import LogisticsDataSourceSpec
from app.intel_models import LogisticsForecastModel
from app.intel_models import LogisticsSignal
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.presenters.digest import build_digest_payload
from app.services.intel_insights import build_briefing_pack
from app.services.intel_insights import build_bundle_briefing_pack
from app.services.intel_insights import build_collection_briefing_pack
from app.services.intel_insights import build_entity_changes
from app.services.intel_insights import build_monitor_evaluations
from app.services.intel_insights import build_operational_alerts
from app.services.intel_insights import build_opportunities
from app.services.intel_insights import build_region_changes
from app.services.intel_insights import build_region_briefing_pack
from app.services.intel_insights import build_source_incidents
from app.services.intel_insights import resolve_collection_items
from app.services.intel_analyst_store import IntelAnalystStore
from app.services.intel_bundle_store import IntelBundleStore
from app.services.intel_collection_store import IntelCollectionStore
from app.services.intel_monitor_store import IntelMonitorStore
from app.services.foundry_client import FoundryClient
from app.services.foundry_client import FoundryConfigError
from app.services.foundry_client import FoundryError
from app.services.foundry_client import configured_summary
from app.services.foundry_export import export_snapshot
from app.services.foundry_upload import upload_foundry_packet
from app.services.intel_watchlist_store import IntelWatchlistStore
from app.services.regional_ooda import build_regional_ooda_packet
from app.services.regional_intel import RegionalIntelService
from app.services.regional_history_store import RegionalIntelHistoryStore
from app.services.strategy import build_strategy_snapshot


async def _build_snapshot(force: bool):
    from app.services.aggregator import DashboardService

    service = DashboardService()
    return await service.get_snapshot(force_refresh=force)


async def _build_intel_snapshot(force: bool):
    service = RegionalIntelService()
    return await service.get_snapshot(force_refresh=force)


async def _run_collect(force: bool) -> int:
    snapshot = await _build_snapshot(force=force)
    print(f"Refreshed snapshot at {snapshot.updated_at}")
    for protocol in snapshot.protocols:
        top_pool = protocol.pools[0].name if protocol.pools else "No pools"
        print(f"- {protocol.name}: {top_pool}")
    return 0


async def _run_snapshot(force: bool, as_json: bool) -> int:
    snapshot = await _build_snapshot(force=force)
    if as_json:
        json.dump(snapshot.model_dump(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Snapshot updated at {snapshot.updated_at}")
        for protocol in snapshot.protocols:
            top_pool = protocol.pools[0].name if protocol.pools else "No pools"
            print(f"- {protocol.name}: {top_pool}")
    return 0


async def _run_digest(
    *,
    force: bool,
    output_format: str,
    blackhole: float | None,
    supernova: float | None,
    fullsail: float | None,
) -> int:
    settings = get_settings()
    vote_powers = resolve_vote_powers(
        blackhole=blackhole,
        supernova=supernova,
        fullsail=fullsail,
        settings=settings,
    )
    snapshot = await _build_snapshot(force=force)
    strategy = build_strategy_snapshot(snapshot, vote_powers=vote_powers)
    payload = build_digest_payload(
        snapshot, strategy, timezone=settings.timezone, style=output_format
    )

    if output_format == "json":
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(payload["message"])
    return 0


async def _run_intel_collect(force: bool) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    print(f"Regional intel refreshed at {snapshot.updated_at}")
    print(f"- Regions: {len(snapshot.regions)}")
    print(f"- News items: {len(snapshot.news)}")
    print(f"- Permit items: {len(snapshot.permits)}")
    print(f"- Business leads: {len(snapshot.businesses)}")
    print(f"- Public contacts: {len(snapshot.contacts)}")
    print(f"- Organizations: {len(snapshot.organizations)}")
    return 0


async def _run_intel_snapshot(
    force: bool, as_json: bool, region: RegionId | None
) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    payload = snapshot.model_dump()
    if region is not None:
        payload["regions"] = [
            item for item in payload["regions"] if item["id"] == region
        ]
        payload["sources"] = [
            item for item in payload["sources"] if region in item["region_ids"]
        ]
        payload["news"] = [
            item for item in payload["news"] if item["region_id"] == region
        ]
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
    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Regional intel updated at {payload['updated_at']}")
        for item in payload["regions"]:
            region_id = item["id"]
            news_count = len(
                [row for row in payload["news"] if row["region_id"] == region_id]
            )
            permit_count = len(
                [row for row in payload["permits"] if row["region_id"] == region_id]
            )
            business_count = len(
                [row for row in payload["businesses"] if row["region_id"] == region_id]
            )
            contact_count = len(
                [row for row in payload["contacts"] if row["region_id"] == region_id]
            )
            org_count = len(
                [
                    row
                    for row in payload["organizations"]
                    if row["region_id"] == region_id
                ]
            )
            print(
                f"- {item['name']}: news={news_count}, permits={permit_count}, businesses={business_count}, contacts={contact_count}, organizations={org_count}"
            )
    return 0


async def _run_intel_search(force: bool, region: RegionId | None, query: str) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    payload = snapshot.model_dump()
    if region is not None:
        payload["news"] = [
            item for item in payload["news"] if item["region_id"] == region
        ]
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

    needle = query.strip().lower()
    results: list[tuple[str, str, str]] = []
    if not needle:
        print("Query is required.")
        return 2
    for kind, items, fields in [
        ("news", payload["news"], ("title", "summary")),
        ("permit", payload["permits"], ("address", "permit_type")),
        ("business", payload["businesses"], ("name", "category", "address")),
        ("contact", payload["contacts"], ("name", "organization", "title", "email")),
        ("organization", payload["organizations"], ("name", "address")),
    ]:
        for item in items:
            haystack = " ".join(str(item.get(field, "")) for field in fields).lower()
            if needle in haystack:
                title = str(
                    item.get("name") or item.get("title") or item.get("address") or ""
                )
                subtitle = str(
                    item.get("organization")
                    or item.get("category")
                    or item.get("permit_type")
                    or item.get("source_name")
                    or ""
                )
                results.append((kind, title, subtitle))
    for kind, title, subtitle in results[:40]:
        print(f"- [{kind}] {title} {f'| {subtitle}' if subtitle else ''}")
    return 0


async def _run_intel_opportunities(
    force: bool, region: RegionId | None, as_json: bool
) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    opportunities = [
        item.model_dump() for item in build_opportunities(snapshot, region=region)
    ]
    if as_json:
        json.dump({"opportunities": opportunities}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in opportunities[:20]:
        print(
            f"- [{item['kind']}] {item['title']} | score={item['score']} | {'; '.join(item.get('reasons', [])[:3])}"
        )
    return 0


async def _run_intel_briefing(force: bool, item_id: str, as_json: bool) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    briefing = build_briefing_pack(snapshot, item_id=item_id)
    if briefing is None:
        print("Briefing target not found.", file=sys.stderr)
        return 2
    if as_json:
        json.dump(briefing.model_dump(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(briefing.markdown)
    return 0


async def _run_intel_alerts(force: bool, region: RegionId | None, as_json: bool) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    source_history = _build_source_history_local(lookback_days=14, region=region)
    alerts = [
        item.model_dump()
        for item in build_operational_alerts(
            snapshot, source_history=source_history, region=region
        )
    ]
    if as_json:
        json.dump({"alerts": alerts}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in alerts[:20]:
        print(
            f"- [{item['severity']}] {item['title']} | score={item['score']} | {item['summary']}"
        )
    return 0


async def _run_intel_region_briefing(
    force: bool, region: RegionId, as_json: bool
) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    source_history = _build_source_history_local(lookback_days=14, region=region)
    alerts = build_operational_alerts(
        snapshot, source_history=source_history, region=region
    )
    watchlist_items = _resolve_watchlist_local(snapshot)
    pack = build_region_briefing_pack(
        snapshot,
        region=region,
        opportunities=build_opportunities(snapshot, region=region),
        alerts=alerts,
        watchlist_items=watchlist_items,
    )
    if as_json:
        json.dump(pack.model_dump(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(pack.markdown)
    return 0


async def _run_intel_collections(as_json: bool) -> int:
    snapshot = await _build_intel_snapshot(force=False)
    store = IntelCollectionStore()
    collections: list[dict[str, object]] = []
    for coll in store.list_collections():
        resolved = resolve_collection_items(snapshot, coll)
        collections.append(
            {
                "collection": coll.model_dump(),
                "item_count": len(coll.items),
                "live_count": len([item for item in resolved if item.get("is_live")]),
            }
        )
    if as_json:
        json.dump({"collections": collections}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for col in collections:
        collection = dict(col["collection"])  # type: ignore[call-overload]
        print(
            f"- {collection['title']} | region={collection.get('region_id') or 'multi_region'} | items={col['item_count']} | live={col['live_count']}"
        )
    return 0


async def _run_intel_collection_briefing(
    collection_id: str, force: bool, as_json: bool
) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    collection_store = IntelCollectionStore()
    analyst_store = IntelAnalystStore()
    collection = collection_store.get_collection(collection_id)
    if collection is None:
        print("Collection not found.", file=sys.stderr)
        return 2
    source_history = _build_source_history_local(
        lookback_days=14, region=collection.region_id
    )
    annotation_lookup = {}
    for item in resolve_collection_items(snapshot, collection):
        if item.get("ref", {}).get("kind") != "organization" or not item.get(
            "ref", {}
        ).get("item_id"):
            continue
        target_id = item["ref"]["item_id"]
        annotation = analyst_store.get_annotation(
            target_kind="organization", target_id=target_id
        )
        if annotation is not None:
            annotation_lookup[target_id] = annotation
    pack = build_collection_briefing_pack(
        snapshot,
        collection=collection,
        source_history=source_history,
        annotation_lookup=annotation_lookup,
    )
    if as_json:
        json.dump(pack.model_dump(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(pack.markdown)
    return 0


async def _run_intel_bundles(as_json: bool) -> int:
    snapshot = await _build_intel_snapshot(force=False)
    bundle_store = IntelBundleStore()
    collection_store = IntelCollectionStore()
    bundles: list[dict[str, object]] = []
    for b in bundle_store.list_bundles():
        live_count = 0
        resolved_collections = []
        for ref in b.collections:
            collection = collection_store.get_collection(ref.collection_id)
            if collection is None:
                resolved_collections.append(
                    {"ref": ref.model_dump(), "collection": None, "is_live": False}
                )
                continue
            resolved = resolve_collection_items(snapshot, collection)
            live_count += len([item for item in resolved if item.get("is_live")])
            resolved_collections.append(
                {
                    "ref": ref.model_dump(),
                    "collection": collection.model_dump(),
                    "is_live": True,
                }
            )
        bundles.append(
            {
                "bundle": b.model_dump(),
                "collection_count": len(b.collections),
                "live_count": live_count,
                "collections": resolved_collections,
            }
        )
    if as_json:
        json.dump({"bundles": bundles}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for bun in bundles:  # type: ignore[assignment]
        bdict = dict(bun["bundle"])  # type: ignore[call-overload]
        print(  # type: ignore[index]
            f"- {bdict['title']} | region={bdict.get('region_id') or 'multi_region'} | collections={bun['collection_count']} | live_items={bun['live_count']}"
        )
    return 0


async def _run_intel_bundle_briefing(bundle_id: str, force: bool, as_json: bool) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    bundle_store = IntelBundleStore()
    collection_store = IntelCollectionStore()
    analyst_store = IntelAnalystStore()
    bundle = bundle_store.get_bundle(bundle_id)
    if bundle is None:
        print("Bundle not found.", file=sys.stderr)
        return 2
    collections = []
    for ref in bundle.collections:
        collection = collection_store.get_collection(ref.collection_id)
        if collection is not None:
            collections.append(collection)
    source_history = _build_source_history_local(
        lookback_days=14, region=bundle.region_id
    )
    annotation_lookup = {}
    for collection in collections:
        for item in resolve_collection_items(snapshot, collection):
            if item.get("ref", {}).get("kind") != "organization" or not item.get(
                "resolved", {}
            ).get("item_id"):
                continue
            target_id = item["resolved"]["item_id"]
            annotation = analyst_store.get_annotation(
                target_kind="organization", target_id=target_id
            )
            if annotation is not None:
                annotation_lookup[target_id] = annotation
    pack = build_bundle_briefing_pack(
        snapshot,
        bundle=bundle,
        collections=collections,
        source_history=source_history,
        annotation_lookup=annotation_lookup,
    )
    if as_json:
        json.dump(pack.model_dump(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(pack.markdown)
    return 0


async def _run_intel_source_incidents(region: RegionId | None, as_json: bool) -> int:
    incidents = build_source_incidents(
        _build_source_history_local(lookback_days=14, region=region), region=region
    )
    payload = [item.model_dump() for item in incidents]
    if as_json:
        json.dump({"incidents": payload}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in payload[:20]:
        print(
            f"- [{item['severity']}] {item['name']} | {item['incident_type']} | {item['summary']}"
        )
    return 0


async def _run_intel_region_changes(region: RegionId | None, as_json: bool) -> int:
    records = RegionalIntelHistoryStore().load_records(lookback_days=14)
    changes = [
        item.model_dump() for item in build_region_changes(records, region=region)
    ]
    if as_json:
        json.dump({"changes": changes}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in changes[:20]:
        print(f"- [{item['region_id']}] {item['latest_at']} | {item['summary']}")
    return 0


async def _run_intel_entity_changes(
    region: RegionId | None, kind: str | None, item_id: str | None, as_json: bool
) -> int:
    records = RegionalIntelHistoryStore().load_records(lookback_days=14)
    changes = [
        item.model_dump()
        for item in build_entity_changes(
            records, region=region, kind=kind, item_id=item_id
        )
    ]
    if as_json:
        json.dump({"changes": changes}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in changes[:20]:
        print(
            f"- [{item['region_id']}] [{item['kind']}] {item['title']} | {item['change_type']} | {item['summary']}"
        )
    return 0


async def _run_intel_monitor_rules(
    force: bool, region: RegionId | None, as_json: bool
) -> int:
    snapshot = await _build_intel_snapshot(force=force)
    rules = [
        rule
        for rule in IntelMonitorStore().list_rules()
        if region is None or rule.region_id in {None, region}
    ]
    source_history = _build_source_history_local(lookback_days=14, region=region)
    history_records = RegionalIntelHistoryStore().load_records(lookback_days=14)
    evaluations = [
        item.model_dump()
        for item in build_monitor_evaluations(
            snapshot,
            rules=rules,
            history_records=history_records,
            source_history=source_history,
        )
    ]
    if as_json:
        json.dump({"rules": evaluations}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for item in evaluations[:20]:
        print(
            f"- {item['rule']['title']} | matches={len(item['matches'])} | {item['summary']}"
        )
    return 0


async def _run_intel_foundry_export(
    *,
    output_dir: Path,
    refresh: bool,
    region: RegionId | None,
    as_json: bool,
    include_logistics_fixture: bool,
) -> int:
    if refresh:
        snapshot = await _build_intel_snapshot(force=True)
    else:
        latest_record = RegionalIntelHistoryStore().load_latest_record()
        if latest_record is None:
            print(
                "No stored regional intel snapshot found. Run `regional-intel intel-collect` first.",
                file=sys.stderr,
            )
            return 2
        snapshot = RegionalIntelSnapshot.model_validate(latest_record)

    if include_logistics_fixture:
        manifest = export_snapshot(
            snapshot,
            output_dir,
            region=region,
            logistics_sources=_logistics_fixture_sources(),
            logistics_signals=_logistics_fixture_signals(),
            logistics_models=_logistics_fixture_models(),
        )
    else:
        manifest = export_snapshot(snapshot, output_dir, region=region)
    if as_json:
        json.dump(manifest, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"Foundry export written to {manifest['manifest_path']}")
    for object_type, info in manifest["object_types"].items():
        print(f"- {object_type}: {info['rows']} rows -> {info['path']}")
    return 0


def _run_intel_foundry_status(*, as_json: bool) -> int:
    config = configured_summary()
    try:
        client = FoundryClient.from_env()
        health = client.health()
        status_code = 0 if health.get("ok") else 2
        payload = {"configured": config, "health": health}
    except FoundryConfigError as exc:
        payload = {
            "configured": config,
            "health": {"ok": False, "kind": "configuration", "error": str(exc)},
        }
        status_code = 2

    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return status_code

    print("Foundry target")
    print(f"- base_url: {payload['configured'].get('base_url') or 'not configured'}")
    print(
        "- credentials: "
        + (
            "configured"
            if payload["configured"].get("credential_configured")
            else "missing"
        )
    )
    dataset_types = ", ".join(
        payload["configured"].get("configured_dataset_types") or []
    )
    print(
        f"- default ontology: {payload['configured'].get('default_ontology') or 'none'}"
    )
    print("- dataset mappings: " + (dataset_types or "none"))
    print(f"- health: {'ok' if payload['health'].get('ok') else 'not ready'}")
    if payload["health"].get("error"):
        print(f"- note: {payload['health']['error']}")
    return status_code


def _foundry_name(item: dict[str, object]) -> str:
    return str(item.get("apiName") or item.get("rid") or item.get("displayName") or "")


def _run_intel_foundry_discover(
    *,
    ontology: str | None,
    as_json: bool,
) -> int:
    try:
        client = FoundryClient.from_env()
        ontologies = client.list_ontologies().get("data") or []
        ontology_names = [
            _foundry_name(item) for item in ontologies if isinstance(item, dict)
        ]
        selected = (
            ontology
            or client.default_ontology
            or (ontology_names[0] if ontology_names else None)
        )
        payload: dict[str, object] = {
            "ok": True,
            "base_url": client.auth.base_url,
            "ontologies": ontology_names,
            "selected_ontology": selected,
            "object_types": [],
            "action_types": [],
        }
        if selected:
            object_types = client.list_object_types(selected).get("data") or []
            action_types = client.list_action_types(selected).get("data") or []
            payload["object_types"] = [
                {
                    "apiName": item.get("apiName"),
                    "displayName": item.get("displayName"),
                    "primaryKey": item.get("primaryKey"),
                    "status": item.get("status"),
                }
                for item in object_types
                if isinstance(item, dict)
            ]
            payload["action_types"] = [
                {
                    "apiName": item.get("apiName"),
                    "displayName": item.get("displayName"),
                    "rid": item.get("rid"),
                }
                for item in action_types
                if isinstance(item, dict)
            ]
        status_code = 0
    except FoundryError as exc:
        payload = {"ok": False, "error": str(exc)}
        status_code = 2

    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return status_code

    print("Foundry discovery")
    print(f"- base_url: {payload.get('base_url') or 'not configured'}")
    ontology_names_for_print = payload.get("ontologies")
    if not isinstance(ontology_names_for_print, list):
        ontology_names_for_print = []
    print("- ontologies: " + ", ".join(str(item) for item in ontology_names_for_print))
    print(f"- selected ontology: {payload.get('selected_ontology') or 'none'}")
    print("- object types:")
    object_types_for_print = payload.get("object_types")
    if not isinstance(object_types_for_print, list):
        object_types_for_print = []
    for item in object_types_for_print:
        if not isinstance(item, dict):
            continue
        print(
            f"  - {item.get('apiName')} "
            f"(pk={item.get('primaryKey')}, display={item.get('displayName')})"
        )
    print("- action types:")
    action_types_for_print = payload.get("action_types")
    if not isinstance(action_types_for_print, list):
        action_types_for_print = []
    for item in action_types_for_print:
        if not isinstance(item, dict):
            continue
        print(f"  - {item.get('apiName')}")
    return status_code


def _run_intel_foundry_upload(
    *,
    input_dir: Path,
    object_types: list[str] | None,
    branch: str,
    prefix: str,
    apply: bool,
    as_json: bool,
) -> int:
    try:
        client = FoundryClient.from_env()
        payload = upload_foundry_packet(
            input_dir,
            client=client,
            object_types=object_types,
            branch=branch,
            prefix=prefix,
            apply=apply,
        )
        status_code = 0 if payload.get("ready", True) or payload.get("applied") else 2
    except FoundryError as exc:
        payload = {"ok": False, "error": str(exc)}
        status_code = 2

    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return status_code

    if payload.get("applied"):
        print("Foundry upload complete")
        for object_type, rows in (payload.get("uploaded_types") or {}).items():
            print(f"- {object_type}: {rows} rows")
    else:
        print("Foundry upload plan")
        for object_type, info in (payload.get("object_types") or {}).items():
            marker = "mapped" if info.get("dataset_configured") else "missing dataset"
            print(f"- {object_type}: {info.get('rows')} rows, {marker}")
        if payload.get("missing_files"):
            print("- missing files: " + ", ".join(payload["missing_files"]))
        if payload.get("missing_datasets"):
            print("- missing datasets: " + ", ".join(payload["missing_datasets"]))
        if not apply:
            print("Dry run only. Re-run with --apply to upload.")
    return status_code


def _logistics_fixture_sources() -> list[LogisticsDataSourceSpec]:
    return [
        LogisticsDataSourceSpec(
            source_id="nws_alerts",
            name="National Weather Service Alerts",
            owner="NOAA/National Weather Service",
            source_url="https://www.weather.gov/documentation/services-web-api",
            retrieval_mode="public_api",
            rights="U.S. government public weather data; cite NOAA/NWS.",
            freshness_ttl="15 minutes",
            output_policy="Store derived alert summaries, source URLs, and hashes.",
            caveats=["Weather context requires human operations review."],
        ),
        LogisticsDataSourceSpec(
            source_id="bts_faf",
            name="BTS Freight Analysis Framework",
            owner="Bureau of Transportation Statistics and FHWA",
            source_url="https://www.bts.gov/faf",
            retrieval_mode="public_download",
            rights="Public DOT freight-flow dataset; cite BTS/FHWA.",
            freshness_ttl="annual",
            output_policy="Store derived freight context and links.",
            caveats=["Long-run freight flow data is not live station volume."],
        ),
        LogisticsDataSourceSpec(
            source_id="synthetic_station_baseline",
            name="Synthetic Station Baseline",
            owner="AI Efficiency Team",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            retrieval_mode="synthetic_fixture",
            rights="Synthetic demo data only.",
            freshness_ttl="manual",
            output_policy="Use for demos and tests only.",
            caveats=["Not real FedEx volume, staffing, dispatch, or route data."],
        ),
    ]


def _logistics_fixture_signals() -> list[LogisticsSignal]:
    return [
        LogisticsSignal(
            signal_id="gunnison-weather-watch",
            region_id="gunnison_valley_co",
            signal_type="weather_alert",
            title="Gunnison Valley public weather watch",
            summary="Public weather context for manager verification before shift.",
            source_id="nws_alerts",
            source_name="National Weather Service",
            source_url="https://api.weather.gov/alerts/active",
            observed_at="2026-05-22T12:00:00Z",
            data_classification="public",
            confidence=0.9,
            attributes={"verification": "Check current alert before use."},
        ),
        LogisticsSignal(
            signal_id="western-co-freight-baseline",
            region_id="gunnison_valley_co",
            signal_type="freight_context",
            title="Western Colorado freight-flow context",
            summary="Long-run public freight context for synthetic baseline work.",
            source_id="bts_faf",
            source_name="BTS Freight Analysis Framework",
            source_url="https://www.bts.gov/faf",
            observed_at="2026-05-22T12:00:00Z",
            data_classification="derived_public",
            confidence=0.65,
            attributes={"use": "Regional context only, not real station volume."},
        ),
        LogisticsSignal(
            signal_id="synthetic-pm-sort-baseline",
            region_id="gunnison_valley_co",
            signal_type="synthetic_baseline",
            title="Synthetic PM sort baseline",
            summary="Demo-only baseline for load-estimation packet testing.",
            source_id="synthetic_station_baseline",
            source_name="Synthetic demo baseline",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            observed_at="2026-05-22T12:00:00Z",
            data_classification="synthetic",
            confidence=1.0,
            attributes={"baseline_packages": 1000, "real_fedex_data": False},
        ),
    ]


def _logistics_fixture_models() -> list[LogisticsForecastModel]:
    return [
        LogisticsForecastModel(
            model_id="seasonal-baseline-v0",
            name="Seasonal Baseline V0",
            purpose="Synthetic load-estimation baseline for public-data demos.",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            license_or_rights="Synthetic methodology; no real FedEx data.",
            input_policy="Public, synthetic, or derived-public inputs only.",
            output_policy="Label outputs as estimates requiring human verification.",
            supported_horizons=["same_shift", "next_day"],
            caveats=["Not calibrated on production FedEx volume."],
        )
    ]


async def _run_intel_ooda_packet(
    *,
    region: RegionId | None,
    as_json: bool,
) -> int:
    latest_record = RegionalIntelHistoryStore().load_latest_record()
    if latest_record is None:
        print(
            "No stored regional intel snapshot found. Run `regional-intel intel-collect` first.",
            file=sys.stderr,
        )
        return 2
    snapshot = RegionalIntelSnapshot.model_validate(latest_record)
    packet = build_regional_ooda_packet(snapshot, region=region)
    if as_json:
        json.dump(packet, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    observe = packet["observe"]
    orient = packet["orient"]
    print(f"Regional OODA packet for {packet['region'] or 'all regions'}")
    print(f"- Snapshot: {packet['snapshot_updated_at']}")
    print(
        f"- Rows dropped: {observe['dropped_rows']['total']} {observe['dropped_rows']['by_reason']}"
    )
    print(f"- Source health: {orient['source_health']['status']}")
    for object_type, info in observe["export_object_types"].items():
        print(
            f"- {object_type}: {info['rows']} rows | file_sha256={info['file_sha256']}"
        )
    print("Safe act recommendations:")
    for item in packet["act"]["recommendations"]:
        print(f"- {item['title']}: {item['rationale']}")
    return 0


def _build_source_history_local(lookback_days: int, region: RegionId | None):
    records = RegionalIntelHistoryStore().load_records(lookback_days=lookback_days)
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
                {"updated_at": updated_at, "status": status, "item_count": item_count}
            )
    output = list(sources.values())
    output.sort(
        key=lambda item: (
            item["category"],
            -(item["non_empty_runs"] + item["last_item_count"]),
            item["name"] or "",
        )
    )
    return output


def _resolve_watchlist_local(snapshot):
    entries = IntelWatchlistStore().list_entries()
    by_id = {}
    for collection_name in [
        "organizations",
        "businesses",
        "contacts",
        "news",
        "permits",
    ]:
        for item in getattr(snapshot, collection_name):
            by_id[item.item_id] = item.model_dump()
    items = []
    for entry in entries:
        resolved = by_id.get(entry.item_id or "", {})
        items.append(
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
    return items


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="regional-intel")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the local FastAPI service.")
    serve_parser.add_argument("--host", default=settings.host)
    serve_parser.add_argument("--port", type=int, default=settings.port)

    collect_parser = subparsers.add_parser(
        "collect", help="Refresh and persist the latest snapshot."
    )
    collect_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )

    snapshot_parser = subparsers.add_parser(
        "snapshot", help="Print the latest snapshot summary or JSON."
    )
    snapshot_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    snapshot_parser.add_argument(
        "--json", action="store_true", help="Print the raw snapshot JSON."
    )

    digest_parser = subparsers.add_parser(
        "digest", help="Print a bot-friendly digest for the current week."
    )
    digest_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    digest_parser.add_argument(
        "--format",
        choices=("text", "telegram", "json"),
        default="text",
        help="Choose plain text, Telegram-friendly text, or JSON.",
    )
    digest_parser.add_argument("--blackhole", type=float, default=None)
    digest_parser.add_argument("--supernova", type=float, default=None)
    digest_parser.add_argument("--fullsail", type=float, default=None)

    intel_collect_parser = subparsers.add_parser(
        "intel-collect", help="Refresh the regional intelligence snapshot."
    )
    intel_collect_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )

    intel_snapshot_parser = subparsers.add_parser(
        "intel-snapshot",
        help="Print the regional intelligence snapshot summary or JSON.",
    )
    intel_snapshot_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_snapshot_parser.add_argument(
        "--json", action="store_true", help="Print the raw snapshot JSON."
    )
    intel_snapshot_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_search_parser = subparsers.add_parser(
        "intel-search", help="Search the current regional intelligence snapshot."
    )
    intel_search_parser.add_argument("query", help="Search query text.")
    intel_search_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_search_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_opportunities_parser = subparsers.add_parser(
        "intel-opportunities", help="Print ranked intelligence opportunities."
    )
    intel_opportunities_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_opportunities_parser.add_argument(
        "--json", action="store_true", help="Print the raw opportunity JSON."
    )
    intel_opportunities_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_briefing_parser = subparsers.add_parser(
        "intel-briefing",
        help="Print an analyst-ready briefing pack for one organization.",
    )
    intel_briefing_parser.add_argument(
        "item_id", help="Organization item_id from the intel graph/search output."
    )
    intel_briefing_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_briefing_parser.add_argument(
        "--json", action="store_true", help="Print the raw briefing JSON."
    )
    intel_alerts_parser = subparsers.add_parser(
        "intel-alerts", help="Print operational alerts for the regional intel system."
    )
    intel_alerts_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_alerts_parser.add_argument(
        "--json", action="store_true", help="Print the raw alerts JSON."
    )
    intel_alerts_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_region_briefing_parser = subparsers.add_parser(
        "intel-region-briefing", help="Print a regional briefing pack."
    )
    intel_region_briefing_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        required=True,
        help="Region to brief.",
    )
    intel_region_briefing_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_region_briefing_parser.add_argument(
        "--json", action="store_true", help="Print the raw briefing JSON."
    )
    intel_collections_parser = subparsers.add_parser(
        "intel-collections", help="List saved intelligence collections."
    )
    intel_collections_parser.add_argument(
        "--json", action="store_true", help="Print the raw collection JSON."
    )
    intel_collection_briefing_parser = subparsers.add_parser(
        "intel-collection-briefing", help="Print a saved collection briefing pack."
    )
    intel_collection_briefing_parser.add_argument(
        "collection_id", help="Collection id from the saved collection shelf."
    )
    intel_collection_briefing_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_collection_briefing_parser.add_argument(
        "--json", action="store_true", help="Print the raw briefing JSON."
    )
    intel_bundles_parser = subparsers.add_parser(
        "intel-bundles", help="List saved briefing bundles."
    )
    intel_bundles_parser.add_argument(
        "--json", action="store_true", help="Print the raw bundle JSON."
    )
    intel_bundle_briefing_parser = subparsers.add_parser(
        "intel-bundle-briefing", help="Print a saved bundle briefing pack."
    )
    intel_bundle_briefing_parser.add_argument(
        "bundle_id", help="Bundle id from the bundle shelf."
    )
    intel_bundle_briefing_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_bundle_briefing_parser.add_argument(
        "--json", action="store_true", help="Print the raw briefing JSON."
    )
    intel_source_incidents_parser = subparsers.add_parser(
        "intel-source-incidents",
        help="Print source incident diagnostics from source history.",
    )
    intel_source_incidents_parser.add_argument(
        "--json", action="store_true", help="Print the raw source incident JSON."
    )
    intel_source_incidents_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_region_changes_parser = subparsers.add_parser(
        "intel-region-changes", help="Print regional snapshot count deltas over time."
    )
    intel_region_changes_parser.add_argument(
        "--json", action="store_true", help="Print the raw region change JSON."
    )
    intel_region_changes_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_entity_changes_parser = subparsers.add_parser(
        "intel-entity-changes", help="Print entity-level snapshot diffs."
    )
    intel_entity_changes_parser.add_argument(
        "--json", action="store_true", help="Print the raw entity change JSON."
    )
    intel_entity_changes_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_entity_changes_parser.add_argument(
        "--kind",
        choices=("news", "permit", "business", "contact", "organization"),
        default=None,
        help="Filter output to a single kind.",
    )
    intel_entity_changes_parser.add_argument(
        "--item-id", default=None, help="Filter output to a single item_id."
    )
    intel_monitor_rules_parser = subparsers.add_parser(
        "intel-monitor-rules", help="List saved monitor rules with current matches."
    )
    intel_monitor_rules_parser.add_argument(
        "--force", action="store_true", help="Bypass the in-process TTL cache."
    )
    intel_monitor_rules_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw monitor-rule evaluation JSON.",
    )
    intel_monitor_rules_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_foundry_export_parser = subparsers.add_parser(
        "intel-foundry-export",
        help="Write Foundry-ready regional intelligence NDJSON files.",
    )
    intel_foundry_export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/foundry/regional-intel"),
        help="Directory for Region/IntelItem/IntelSourceHealth NDJSON files.",
    )
    intel_foundry_export_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh from public sources before exporting; default uses latest stored snapshot.",
    )
    intel_foundry_export_parser.add_argument(
        "--json", action="store_true", help="Print the export manifest JSON."
    )
    intel_foundry_export_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )
    intel_foundry_export_parser.add_argument(
        "--include-logistics-fixture",
        action="store_true",
        help="Include public/synthetic station-ops logistics object files.",
    )
    intel_foundry_status_parser = subparsers.add_parser(
        "intel-foundry-status",
        help="Check configured Kadima/Foundry target without exposing credentials.",
    )
    intel_foundry_status_parser.add_argument(
        "--json", action="store_true", help="Print the status as JSON."
    )
    intel_foundry_discover_parser = subparsers.add_parser(
        "intel-foundry-discover",
        help="List visible Kadima/Foundry ontologies, object types, and actions.",
    )
    intel_foundry_discover_parser.add_argument(
        "--ontology",
        default=None,
        help="Ontology API name or RID to inspect; default uses configured ontology, then first visible ontology.",
    )
    intel_foundry_discover_parser.add_argument(
        "--json", action="store_true", help="Print discovery as JSON."
    )
    intel_foundry_upload_parser = subparsers.add_parser(
        "intel-foundry-upload",
        help="Upload a local intel-foundry-export packet to configured Foundry datasets.",
    )
    intel_foundry_upload_parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/foundry/regional-intel"),
        help="Directory containing manifest.json and Foundry NDJSON files.",
    )
    intel_foundry_upload_parser.add_argument(
        "--object-type",
        action="append",
        default=None,
        help="Object type to upload. Repeat to limit upload; default uploads all files.",
    )
    intel_foundry_upload_parser.add_argument(
        "--branch",
        default="master",
        help="Foundry dataset branch to write.",
    )
    intel_foundry_upload_parser.add_argument(
        "--prefix",
        default="regional_intel",
        help="Path prefix inside each Foundry dataset.",
    )
    intel_foundry_upload_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually upload. Omit for a dry-run plan.",
    )
    intel_foundry_upload_parser.add_argument(
        "--json", action="store_true", help="Print the upload result as JSON."
    )
    intel_ooda_packet_parser = subparsers.add_parser(
        "intel-ooda-packet",
        help="Print a read-only regional OODA packet from the latest stored snapshot.",
    )
    intel_ooda_packet_parser.add_argument(
        "--json", action="store_true", help="Print the raw OODA packet JSON."
    )
    intel_ooda_packet_parser.add_argument(
        "--region",
        choices=("austin_tx", "houston_tx", "gunnison_valley_co"),
        default=None,
        help="Filter output to a single region.",
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
        return 0
    if args.command == "collect":
        return asyncio.run(_run_collect(force=args.force))
    if args.command == "snapshot":
        return asyncio.run(_run_snapshot(force=args.force, as_json=args.json))
    if args.command == "digest":
        return asyncio.run(
            _run_digest(
                force=args.force,
                output_format=args.format,
                blackhole=args.blackhole,
                supernova=args.supernova,
                fullsail=args.fullsail,
            )
        )
    if args.command == "intel-collect":
        return asyncio.run(_run_intel_collect(force=args.force))
    if args.command == "intel-snapshot":
        return asyncio.run(
            _run_intel_snapshot(force=args.force, as_json=args.json, region=args.region)
        )
    if args.command == "intel-search":
        return asyncio.run(
            _run_intel_search(force=args.force, region=args.region, query=args.query)
        )
    if args.command == "intel-opportunities":
        return asyncio.run(
            _run_intel_opportunities(
                force=args.force, region=args.region, as_json=args.json
            )
        )
    if args.command == "intel-briefing":
        return asyncio.run(
            _run_intel_briefing(
                force=args.force, item_id=args.item_id, as_json=args.json
            )
        )
    if args.command == "intel-alerts":
        return asyncio.run(
            _run_intel_alerts(force=args.force, region=args.region, as_json=args.json)
        )
    if args.command == "intel-region-briefing":
        return asyncio.run(
            _run_intel_region_briefing(
                force=args.force, region=args.region, as_json=args.json
            )
        )
    if args.command == "intel-collections":
        return asyncio.run(_run_intel_collections(as_json=args.json))
    if args.command == "intel-collection-briefing":
        return asyncio.run(
            _run_intel_collection_briefing(
                collection_id=args.collection_id, force=args.force, as_json=args.json
            )
        )
    if args.command == "intel-bundles":
        return asyncio.run(_run_intel_bundles(as_json=args.json))
    if args.command == "intel-bundle-briefing":
        return asyncio.run(
            _run_intel_bundle_briefing(
                bundle_id=args.bundle_id, force=args.force, as_json=args.json
            )
        )
    if args.command == "intel-source-incidents":
        return asyncio.run(
            _run_intel_source_incidents(region=args.region, as_json=args.json)
        )
    if args.command == "intel-region-changes":
        return asyncio.run(
            _run_intel_region_changes(region=args.region, as_json=args.json)
        )
    if args.command == "intel-entity-changes":
        return asyncio.run(
            _run_intel_entity_changes(
                region=args.region,
                kind=args.kind,
                item_id=args.item_id,
                as_json=args.json,
            )
        )
    if args.command == "intel-monitor-rules":
        return asyncio.run(
            _run_intel_monitor_rules(
                force=args.force, region=args.region, as_json=args.json
            )
        )
    if args.command == "intel-foundry-export":
        return asyncio.run(
            _run_intel_foundry_export(
                output_dir=args.output_dir,
                refresh=args.refresh,
                region=args.region,
                as_json=args.json,
                include_logistics_fixture=args.include_logistics_fixture,
            )
        )
    if args.command == "intel-foundry-status":
        return _run_intel_foundry_status(as_json=args.json)
    if args.command == "intel-foundry-discover":
        return _run_intel_foundry_discover(ontology=args.ontology, as_json=args.json)
    if args.command == "intel-foundry-upload":
        return _run_intel_foundry_upload(
            input_dir=args.input_dir,
            object_types=args.object_type,
            branch=args.branch,
            prefix=args.prefix,
            apply=args.apply,
            as_json=args.json,
        )
    if args.command == "intel-ooda-packet":
        return asyncio.run(
            _run_intel_ooda_packet(region=args.region, as_json=args.json)
        )

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
