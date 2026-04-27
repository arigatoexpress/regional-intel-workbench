from __future__ import annotations

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.intel_models import BusinessLead
from app.intel_models import EthicsRule
from app.intel_models import IntelSource
from app.intel_models import NewsSignal
from app.intel_models import OrganizationProfile
from app.intel_models import PermitSignal
from app.intel_models import PublicContact
from app.intel_models import RegionBrief
from app.intel_models import RegionProfile
from app.intel_models import RegionalIntelSnapshot
from app.intel_models import SourceHealth
from app.services.intel_analyst_store import IntelAnalystStore
from app.services.intel_bundle_store import IntelBundleStore
from app.services.intel_collection_store import IntelCollectionStore
from app.services.intel_monitor_store import IntelMonitorStore
from app.services.intel_watchlist_store import IntelWatchlistStore
from app.services.regional_history_store import RegionalIntelHistoryStore


class IntelAppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        history_path = Path(__file__).resolve().parents[1] / "data" / "regional_intel_history.jsonl"
        latest_record = RegionalIntelHistoryStore(history_path).load_latest_record()
        if latest_record is None:
            raise RuntimeError("Expected at least one stored intel snapshot for tests")
        cls.fixture_snapshot = RegionalIntelSnapshot.model_validate(latest_record)
        cls.sample_org = next(item for item in cls.fixture_snapshot.organizations if item.region_id == "austin_tx")
        cls.sample_business = next(item for item in cls.fixture_snapshot.businesses if item.region_id == "austin_tx")
        cls.sample_news = next(item for item in cls.fixture_snapshot.news if item.region_id == "austin_tx")
        cls.sample_permit = next(item for item in cls.fixture_snapshot.permits if item.region_id == "austin_tx")

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        temp_path = Path(self.tempdir.name)

        self.original_watchlist_store = main.intel_watchlist_store
        self.original_analyst_store = main.intel_analyst_store
        self.original_collection_store = main.intel_collection_store
        self.original_bundle_store = main.intel_bundle_store
        self.original_monitor_store = main.intel_monitor_store
        self.original_get_snapshot = main.regional_intel_service.get_snapshot
        self.original_cached_snapshot = getattr(main.regional_intel_service, "_latest_snapshot", None)

        main.intel_watchlist_store = IntelWatchlistStore(temp_path / "intel_watchlist.json")
        main.intel_analyst_store = IntelAnalystStore(temp_path / "intel_annotations.json")
        main.intel_collection_store = IntelCollectionStore(temp_path / "intel_collections.json")
        main.intel_bundle_store = IntelBundleStore(temp_path / "intel_briefing_bundles.json")
        main.intel_monitor_store = IntelMonitorStore(temp_path / "intel_monitor_rules.json")

        fixture_snapshot = self.fixture_snapshot

        async def fake_get_snapshot(force_refresh: bool = False):
            return fixture_snapshot

        main.regional_intel_service.get_snapshot = fake_get_snapshot
        main.regional_intel_service._latest_snapshot = fixture_snapshot

        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        main.intel_watchlist_store = self.original_watchlist_store
        main.intel_analyst_store = self.original_analyst_store
        main.intel_collection_store = self.original_collection_store
        main.intel_bundle_store = self.original_bundle_store
        main.intel_monitor_store = self.original_monitor_store
        main.regional_intel_service.get_snapshot = self.original_get_snapshot
        main.regional_intel_service._latest_snapshot = self.original_cached_snapshot
        self.tempdir.cleanup()

    def test_html_shells_include_map_and_core_markers(self) -> None:
        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn("Regional Intelligence Workbench", landing.text)
        self.assertIn("/blanga/austin", landing.text)
        self.assertIn("/vote-monitor", landing.text)

        vote_monitor = self.client.get("/vote-monitor")
        self.assertEqual(vote_monitor.status_code, 200)
        self.assertIn("Vote Escrow Monitor", vote_monitor.text)

        intel = self.client.get("/intel")
        self.assertEqual(intel.status_code, 200)
        self.assertIn("Intelligence Map", intel.text)
        self.assertIn("intel-map-canvas", intel.text)
        self.assertIn("/static/intel_map.js", intel.text)

        client_view = self.client.get("/blanga/austin")
        self.assertEqual(client_view.status_code, 200)
        self.assertIn("Austin Intelligence Map", client_view.text)
        self.assertIn("client-view-map-canvas", client_view.text)
        self.assertIn("How To Use It", client_view.text)

    def test_snapshot_region_filter_and_client_view_shape(self) -> None:
        snapshot = self.client.get("/api/intel/snapshot", params={"region": "austin_tx"})
        self.assertEqual(snapshot.status_code, 200)
        payload = snapshot.json()
        self.assertEqual(len(payload["regions"]), 1)
        self.assertEqual(payload["regions"][0]["id"], "austin_tx")
        self.assertTrue(all(item["region_id"] == "austin_tx" for item in payload["businesses"]))

        view = self.client.get("/api/client-views/blanga_austin")
        self.assertEqual(view.status_code, 200)
        view_payload = view.json()
        self.assertEqual(view_payload["view_id"], "blanga_austin")
        self.assertGreaterEqual(len(view_payload["hero_metrics"]), 4)
        self.assertGreaterEqual(len(view_payload["sections"]), 6)
        self.assertTrue(any(section["section_id"] == "what_changed" for section in view_payload["sections"]))

    def test_recent_feed_contract_for_sapphire_proxy(self) -> None:
        recent = self.client.get("/api/intel/recent", params={"region": "austin_tx", "limit": 5})
        self.assertEqual(recent.status_code, 200)
        payload = recent.json()
        self.assertEqual(payload["region"], "austin_tx")
        self.assertEqual(payload["limit"], 5)
        self.assertLessEqual(len(payload["items"]), 5)
        self.assertGreater(payload["item_count"], 5)

        timestamps = [item["timestamp"] or "" for item in payload["items"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        self.assertTrue(all(item["region_id"] == "austin_tx" for item in payload["items"]))
        self.assertTrue(all(item["region"] == "austin_tx" for item in payload["items"]))
        self.assertTrue(all(item["source_name"] for item in payload["items"]))
        self.assertTrue(any(item["source_url"] for item in payload["items"]))
        self.assertTrue(all(item["severity"] in {"high", "medium", "low"} for item in payload["items"]))
        self.assertTrue(all(item["intel_url"].startswith("/intel?") for item in payload["items"]))
        self.assertTrue({"id", "kind", "title", "timestamp", "tags"} <= set(payload["items"][0]))

        capped = self.client.get("/api/intel/recent", params={"limit": 500})
        self.assertEqual(capped.status_code, 200)
        self.assertEqual(capped.json()["limit"], 50)
        self.assertLessEqual(len(capped.json()["items"]), 50)

    def test_search_detail_and_briefing_endpoints(self) -> None:
        search = self.client.get("/api/intel/search", params={"q": "Amy", "region": "austin_tx"})
        self.assertEqual(search.status_code, 200)
        results = search.json()["results"]
        self.assertTrue(results)

        org_detail = self.client.get(f"/api/intel/organizations/{self.sample_org.item_id}")
        self.assertEqual(org_detail.status_code, 200)
        self.assertEqual(org_detail.json()["organization"]["item_id"], self.sample_org.item_id)

        generic_detail = self.client.get(f"/api/intel/items/business/{self.sample_business.item_id}")
        self.assertEqual(generic_detail.status_code, 200)
        self.assertEqual(generic_detail.json()["item"]["item_id"], self.sample_business.item_id)

        briefing = self.client.get(f"/api/intel/briefing/{self.sample_org.item_id}")
        self.assertEqual(briefing.status_code, 200)
        self.assertIn(self.sample_org.name, briefing.json()["title"])

        timeline = self.client.get(f"/api/intel/timeline/{self.sample_org.item_id}")
        self.assertEqual(timeline.status_code, 200)
        self.assertIn("timeline", timeline.json())

    def test_annotations_watchlist_collections_and_bundle_roundtrip(self) -> None:
        annotation = self.client.post(
            "/api/intel/annotations",
            json={
                "target_kind": "organization",
                "target_id": self.sample_org.item_id,
                "note": "Priority Austin operator",
                "tags": ["Austin", "Retail", "Austin"],
            },
        )
        self.assertEqual(annotation.status_code, 200)
        self.assertEqual(annotation.json()["annotation"]["tags"], ["austin", "retail"])

        watchlist = self.client.post(
            "/api/intel/watchlist-items",
            json={
                "kind": "organization",
                "item_id": self.sample_org.item_id,
                "region_id": "austin_tx",
                "note": "Track for demo",
            },
        )
        self.assertEqual(watchlist.status_code, 200)
        watchlist_again = self.client.post(
            "/api/intel/watchlist-items",
            json={
                "kind": "organization",
                "item_id": self.sample_org.item_id,
                "region_id": "austin_tx",
                "note": "Updated note",
            },
        )
        self.assertEqual(watchlist_again.status_code, 200)
        listed_watchlist = self.client.get("/api/intel/watchlist-items").json()["items"]
        self.assertEqual(len(listed_watchlist), 1)
        self.assertEqual(listed_watchlist[0]["entry"]["note"], "Updated note")

        collection = self.client.post(
            "/api/intel/collections",
            json={"title": "Austin Demo Dossier", "region_id": "austin_tx", "note": "QA collection"},
        )
        self.assertEqual(collection.status_code, 200)
        collection_id = collection.json()["collection"]["collection_id"]

        collection_item = self.client.post(
            f"/api/intel/collections/{collection_id}/items",
            json={"kind": "organization", "item_id": self.sample_org.item_id, "region_id": "austin_tx"},
        )
        self.assertEqual(collection_item.status_code, 200)

        collection_briefing = self.client.get(f"/api/intel/collections/{collection_id}/briefing")
        self.assertEqual(collection_briefing.status_code, 200)
        self.assertIn("Austin Demo Dossier", collection_briefing.json()["title"])

        bundle = self.client.post(
            "/api/intel/bundles",
            json={"title": "Austin Weekly Bundle", "region_id": "austin_tx", "note": "QA bundle"},
        )
        self.assertEqual(bundle.status_code, 200)
        bundle_id = bundle.json()["bundle"]["bundle_id"]

        bundle_ref = self.client.post(
            f"/api/intel/bundles/{bundle_id}/collections",
            json={"collection_id": collection_id},
        )
        self.assertEqual(bundle_ref.status_code, 200)

        bundle_briefing = self.client.get(f"/api/intel/bundles/{bundle_id}/briefing")
        self.assertEqual(bundle_briefing.status_code, 200)
        self.assertIn("Austin Weekly Bundle", bundle_briefing.json()["title"])

    def test_monitor_rules_and_history_endpoints(self) -> None:
        created = self.client.post(
            "/api/intel/monitor-rules",
            json={
                "title": " Austin Permit Changes ",
                "region_id": "austin_tx",
                "entity_kinds": ["Permit", "permit"],
                "change_types": ["Added", "removed"],
                "incident_types": ["empty_source"],
                "keyword": "  Austin airport ",
                "tags": ["Demo", "Austin", "Demo"],
            },
        )
        self.assertEqual(created.status_code, 200)
        rule = created.json()["rule"]
        self.assertEqual(rule["title"], "Austin Permit Changes")
        self.assertEqual(rule["entity_kinds"], ["permit"])
        self.assertEqual(rule["tags"], ["demo", "austin"])

        listed = self.client.get("/api/intel/monitor-rules", params={"region": "austin_tx"})
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(listed.json()["rules"])

        source_history = self.client.get("/api/intel/source-history", params={"region": "austin_tx"})
        self.assertEqual(source_history.status_code, 200)
        self.assertIn("sources", source_history.json())

        source_incidents = self.client.get("/api/intel/source-incidents", params={"region": "austin_tx"})
        self.assertEqual(source_incidents.status_code, 200)
        self.assertIn("incidents", source_incidents.json())

        region_changes = self.client.get("/api/intel/region-changes", params={"region": "austin_tx"})
        self.assertEqual(region_changes.status_code, 200)
        self.assertIn("changes", region_changes.json())

        entity_changes = self.client.get("/api/intel/entity-changes", params={"region": "austin_tx", "kind": "permit"})
        self.assertEqual(entity_changes.status_code, 200)
        self.assertIn("changes", entity_changes.json())

    def test_ooda_packet_endpoint_is_read_only_and_uses_stored_snapshot(self) -> None:
        async def fail_if_refreshed(force_refresh: bool = False):
            raise AssertionError("OODA packet endpoint must not refresh sources")

        main.regional_intel_service.get_snapshot = fail_if_refreshed
        response = self.client.get("/api/intel/ooda-packet", params={"region": "austin_tx"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["packet_type"], "regional_ooda")
        self.assertEqual(payload["region"], "austin_tx")
        self.assertTrue(payload["constraints"]["read_only"])
        self.assertFalse(payload["constraints"]["external_refresh"])
        self.assertFalse(payload["constraints"]["external_writes"])
        self.assertIn("source_health_summary", payload["observe"])
        self.assertIn("dropped_rows", payload["observe"])
        self.assertIn("IntelItem", payload["observe"]["export_object_types"])
        self.assertEqual(payload["act"]["writes"], [])
        self.assertEqual(payload["act"]["external_calls"], [])

    def test_invalid_resources_return_404(self) -> None:
        self.assertEqual(self.client.get("/api/client-views/does_not_exist").status_code, 404)
        self.assertEqual(self.client.get("/api/intel/items/unknown/abc").status_code, 404)
        self.assertEqual(self.client.get("/api/intel/organizations/not-real").status_code, 404)
        self.assertEqual(self.client.delete("/api/intel/watchlist-items/not-real").status_code, 404)
        self.assertEqual(self.client.delete("/api/intel/annotations/organization/not-real").status_code, 404)


class IntelOodaCliTestCase(unittest.TestCase):
    def test_ooda_packet_cli_reads_latest_snapshot_without_refresh_flag(self) -> None:
        from app.cli import main as cli_main

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli_main(["intel-ooda-packet", "--region", "austin_tx", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["packet_type"], "regional_ooda")
        self.assertEqual(payload["region"], "austin_tx")
        self.assertTrue(payload["constraints"]["read_only"])
        self.assertFalse(payload["constraints"]["external_refresh"])
        self.assertFalse(payload["constraints"]["external_writes"])
        self.assertEqual(payload["act"]["writes"], [])
        self.assertEqual(payload["act"]["external_calls"], [])


def _build_controlled_snapshot(
    *,
    news: list[NewsSignal] | None = None,
    permits: list[PermitSignal] | None = None,
    businesses: list[BusinessLead] | None = None,
    contacts: list[PublicContact] | None = None,
    organizations: list[OrganizationProfile] | None = None,
) -> RegionalIntelSnapshot:
    """Construct a deterministic snapshot for /api/intel/recent unit tests."""
    return RegionalIntelSnapshot(
        updated_at="2026-04-27T16:00:00Z",
        cache_ttl_seconds=900,
        ethics_rules=[
            EthicsRule(
                key="public_sources_only",
                title="Public Sources Only",
                description="Use public data only.",
            )
        ],
        regions=[
            RegionProfile(
                id="austin_tx",
                name="Austin, Texas",
                summary="Central Texas growth intelligence.",
                bbox=[30.05, -98.10, 30.65, -97.40],
                source_keys=["austin_open_data_permits"],
            ),
            RegionProfile(
                id="houston_tx",
                name="Houston, Texas",
                summary="Houston metro intelligence.",
                bbox=[29.50, -95.90, 30.20, -95.00],
                source_keys=["houston_plat_activity_reports"],
            ),
        ],
        sources=[
            IntelSource(
                source_key="austin_open_data_permits",
                region_ids=["austin_tx"],
                category="permit",
                name="City of Austin Open Data Permits",
                collection_mode="public_api",
                access="public",
                live_pull=True,
                url="https://data.austintexas.gov",
            )
        ],
        news=news or [],
        permits=permits or [],
        businesses=businesses or [],
        contacts=contacts or [],
        organizations=organizations or [],
        source_health=[
            SourceHealth(
                source_key="austin_open_data_permits",
                name="City of Austin Open Data Permits",
                category="permit",
                region_ids=["austin_tx"],
                live_pull=True,
                status="live",
                item_count=0,
            )
        ],
        briefs=[
            RegionBrief(
                region_id="austin_tx",
                headline="Austin public-source snapshot",
                summary="Austin is active.",
            )
        ],
        notes=["Public sources only."],
    )


def _news(item_id: str, *, region: str = "austin_tx", score: float, ts: str = "2026-04-27T10:00:00Z") -> NewsSignal:
    return NewsSignal(
        item_id=item_id,
        region_id=region,
        title=f"News {item_id}",
        summary="Public coverage.",
        source_name="Public News",
        source_url=f"https://example.test/{item_id}",
        published_at=ts,
        signal_type="business_growth",
        actionable=True,
        signal_score=score,
    )


class IntelRecentEndpointTestCase(unittest.TestCase):
    """Direct unit tests for /api/intel/recent feed semantics."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        temp_path = Path(self.tempdir.name)

        self._original_get_snapshot = main.regional_intel_service.get_snapshot
        self._original_cached = getattr(main.regional_intel_service, "_latest_snapshot", None)
        self._original_watchlist_store = main.intel_watchlist_store
        self._original_analyst_store = main.intel_analyst_store
        self._original_collection_store = main.intel_collection_store
        self._original_bundle_store = main.intel_bundle_store
        self._original_monitor_store = main.intel_monitor_store

        main.intel_watchlist_store = IntelWatchlistStore(temp_path / "wl.json")
        main.intel_analyst_store = IntelAnalystStore(temp_path / "ann.json")
        main.intel_collection_store = IntelCollectionStore(temp_path / "col.json")
        main.intel_bundle_store = IntelBundleStore(temp_path / "bun.json")
        main.intel_monitor_store = IntelMonitorStore(temp_path / "mon.json")

        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        main.regional_intel_service.get_snapshot = self._original_get_snapshot
        main.regional_intel_service._latest_snapshot = self._original_cached
        main.intel_watchlist_store = self._original_watchlist_store
        main.intel_analyst_store = self._original_analyst_store
        main.intel_collection_store = self._original_collection_store
        main.intel_bundle_store = self._original_bundle_store
        main.intel_monitor_store = self._original_monitor_store
        self.tempdir.cleanup()

    def _install_snapshot(self, snapshot: RegionalIntelSnapshot) -> None:
        async def fake(force_refresh: bool = False):
            return snapshot
        main.regional_intel_service.get_snapshot = fake
        main.regional_intel_service._latest_snapshot = snapshot

    # --- score normalization -----------------------------------------------

    def test_score_is_rounded_to_two_decimals(self) -> None:
        self._install_snapshot(_build_controlled_snapshot(news=[_news("n1", score=72.34567)]))
        payload = self.client.get("/api/intel/recent").json()
        item = next(it for it in payload["items"] if it["item_id"] == "n1")
        self.assertEqual(item["score"], 72.35)

    def test_nan_and_inf_scores_normalize_to_zero(self) -> None:
        self._install_snapshot(
            _build_controlled_snapshot(
                news=[
                    _news("n_nan", score=float("nan")),
                    _news("n_inf", score=float("inf")),
                    _news("n_neg_inf", score=float("-inf")),
                ]
            )
        )
        payload = self.client.get("/api/intel/recent").json()
        for item_id in ("n_nan", "n_inf", "n_neg_inf"):
            item = next(it for it in payload["items"] if it["item_id"] == item_id)
            self.assertEqual(item["score"], 0.0)
            self.assertTrue(math.isfinite(item["score"]))
            self.assertEqual(item["severity"], "low")

    def test_null_score_falls_back_to_zero(self) -> None:
        # signal_score has a default of 0.0; constructing with None blows up
        # at pydantic, so we exercise the helper directly to confirm the
        # null-score code path normalizes to 0.
        from app.main import _recent_item

        row = _recent_item(
            kind="news",
            item_id="n0",
            region_id="austin_tx",
            title="t",
            summary="s",
            score=None,  # type: ignore[arg-type]
            timestamp=None,
            source_name="Public News",
            source_url="https://example.test/n0",
            tags=None,
        )
        self.assertEqual(row["score"], 0.0)
        self.assertEqual(row["severity"], "low")

    # --- severity bucket boundaries ---------------------------------------

    def test_severity_boundaries_low_medium_high(self) -> None:
        self._install_snapshot(
            _build_controlled_snapshot(
                news=[
                    _news("low_top", score=59.99, ts="2026-04-27T01:00:00Z"),
                    _news("med_low", score=60.00, ts="2026-04-27T02:00:00Z"),
                    _news("med_top", score=84.99, ts="2026-04-27T03:00:00Z"),
                    _news("high_low", score=85.00, ts="2026-04-27T04:00:00Z"),
                    _news("high_hi", score=100.0, ts="2026-04-27T05:00:00Z"),
                    _news("zero", score=0.0, ts="2026-04-27T06:00:00Z"),
                ]
            )
        )
        payload = self.client.get("/api/intel/recent", params={"limit": 50}).json()
        sev = {it["item_id"]: it["severity"] for it in payload["items"]}
        self.assertEqual(sev["low_top"], "low")
        self.assertEqual(sev["med_low"], "medium")
        self.assertEqual(sev["med_top"], "medium")
        self.assertEqual(sev["high_low"], "high")
        self.assertEqual(sev["high_hi"], "high")
        self.assertEqual(sev["zero"], "low")

    # --- pagination / limit clamping --------------------------------------

    def test_limit_default_is_ten(self) -> None:
        items = [_news(f"n{i}", score=10.0 + i, ts=f"2026-04-27T{i:02d}:00:00Z") for i in range(20)]
        self._install_snapshot(_build_controlled_snapshot(news=items))
        payload = self.client.get("/api/intel/recent").json()
        self.assertEqual(payload["limit"], 10)
        self.assertEqual(len(payload["items"]), 10)
        self.assertEqual(payload["item_count"], 20)

    def test_limit_clamps_to_max_fifty(self) -> None:
        items = [_news(f"n{i}", score=10.0, ts=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z") for i in range(120)]
        self._install_snapshot(_build_controlled_snapshot(news=items))
        payload = self.client.get("/api/intel/recent", params={"limit": 9999}).json()
        self.assertEqual(payload["limit"], 50)
        self.assertLessEqual(len(payload["items"]), 50)

    def test_limit_clamps_below_one_to_one(self) -> None:
        self._install_snapshot(_build_controlled_snapshot(news=[_news("n1", score=50.0)]))
        for raw in (0, -5):
            payload = self.client.get("/api/intel/recent", params={"limit": raw}).json()
            self.assertEqual(payload["limit"], 1, f"limit={raw} should clamp to 1")
            self.assertLessEqual(len(payload["items"]), 1)

    # --- edge cases --------------------------------------------------------

    def test_empty_snapshot_returns_empty_items_with_envelope_intact(self) -> None:
        self._install_snapshot(_build_controlled_snapshot())
        payload = self.client.get("/api/intel/recent").json()
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["item_count"], 0)
        self.assertEqual(payload["limit"], 10)
        self.assertIsNone(payload["region"])
        self.assertIn("notes", payload)

    def test_malformed_timestamp_does_not_crash_sort(self) -> None:
        self._install_snapshot(
            _build_controlled_snapshot(
                news=[
                    _news("good", score=70.0, ts="2026-04-27T10:00:00Z"),
                    _news("bad", score=70.0, ts="not-a-date"),
                ]
            )
        )
        resp = self.client.get("/api/intel/recent")
        self.assertEqual(resp.status_code, 200)
        ids = {it["item_id"] for it in resp.json()["items"]}
        self.assertEqual(ids, {"good", "bad"})

    def test_missing_optional_fields_use_safe_fallbacks(self) -> None:
        # News with no publication and no address_hint still
        # falls back to a non-empty string and summary survives.
        news = _news("n_min", score=42.0)
        news.publication = None
        news.address_hint = None
        news.summary = ""
        self._install_snapshot(_build_controlled_snapshot(news=[news]))
        payload = self.client.get("/api/intel/recent").json()
        item = next(it for it in payload["items"] if it["item_id"] == "n_min")
        self.assertTrue(item["source_name"])
        self.assertEqual(item["summary"], "")
        self.assertTrue(item["intel_url"].startswith("/intel?detail_kind=news"))

    # --- region filter -----------------------------------------------------

    def test_region_filter_excludes_other_regions(self) -> None:
        self._install_snapshot(
            _build_controlled_snapshot(
                news=[
                    _news("austin_a", region="austin_tx", score=70.0),
                    _news("austin_b", region="austin_tx", score=80.0),
                    _news("houston_a", region="houston_tx", score=90.0),
                ]
            )
        )
        payload = self.client.get("/api/intel/recent", params={"region": "austin_tx"}).json()
        self.assertEqual(payload["region"], "austin_tx")
        ids = {it["item_id"] for it in payload["items"]}
        self.assertEqual(ids, {"austin_a", "austin_b"})
        for it in payload["items"]:
            self.assertEqual(it["region_id"], "austin_tx")
            self.assertEqual(it["region"], "austin_tx")

    def test_region_filter_none_returns_all_regions(self) -> None:
        self._install_snapshot(
            _build_controlled_snapshot(
                news=[
                    _news("austin_a", region="austin_tx", score=70.0),
                    _news("houston_a", region="houston_tx", score=90.0),
                ]
            )
        )
        payload = self.client.get("/api/intel/recent").json()
        ids = {it["item_id"] for it in payload["items"]}
        self.assertIn("austin_a", ids)
        self.assertIn("houston_a", ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
