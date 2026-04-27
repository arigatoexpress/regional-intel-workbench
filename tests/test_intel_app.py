from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.intel_models import RegionalIntelSnapshot
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

    def test_invalid_resources_return_404(self) -> None:
        self.assertEqual(self.client.get("/api/client-views/does_not_exist").status_code, 404)
        self.assertEqual(self.client.get("/api/intel/items/unknown/abc").status_code, 404)
        self.assertEqual(self.client.get("/api/intel/organizations/not-real").status_code, 404)
        self.assertEqual(self.client.delete("/api/intel/watchlist-items/not-real").status_code, 404)
        self.assertEqual(self.client.delete("/api/intel/annotations/organization/not-real").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
