"""Smoke tests for the dedicated admin frontend (`/admin` + `/api/admin/*`).

These tests reuse the same fixture-snapshot pattern as
``tests/test_intel_app.py`` so we don't need a live network or a real
Playwright browser: we stub out ``regional_intel_service.get_snapshot``
with the latest record from ``data/regional_intel_history.jsonl``.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from app.intel_models import RegionalIntelSnapshot
from app.services.intel_analyst_store import IntelAnalystStore
from app.services.intel_bundle_store import IntelBundleStore
from app.services.intel_collection_store import IntelCollectionStore
from app.services.intel_monitor_store import IntelMonitorStore
from app.services.intel_watchlist_store import IntelWatchlistStore
from app.services.regional_history_store import RegionalIntelHistoryStore


class AdminAppTestCase(unittest.TestCase):
    fixture_snapshot: RegionalIntelSnapshot

    @classmethod
    def setUpClass(cls) -> None:
        history_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "regional_intel_history.jsonl"
        )
        latest = RegionalIntelHistoryStore(history_path).load_latest_record()
        if latest is None:
            raise RuntimeError(
                "Expected at least one stored intel snapshot for tests"
            )
        cls.fixture_snapshot = RegionalIntelSnapshot.model_validate(latest)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        temp_path = Path(self.tempdir.name)

        self._original_watchlist = main.intel_watchlist_store
        self._original_analyst = main.intel_analyst_store
        self._original_collection = main.intel_collection_store
        self._original_bundle = main.intel_bundle_store
        self._original_monitor = main.intel_monitor_store
        self._original_get_snapshot = main.regional_intel_service.get_snapshot
        self._original_cached = getattr(
            main.regional_intel_service, "_latest_snapshot", None
        )

        main.intel_watchlist_store = IntelWatchlistStore(
            temp_path / "intel_watchlist.json"
        )
        main.intel_analyst_store = IntelAnalystStore(
            temp_path / "intel_annotations.json"
        )
        main.intel_collection_store = IntelCollectionStore(
            temp_path / "intel_collections.json"
        )
        main.intel_bundle_store = IntelBundleStore(
            temp_path / "intel_briefing_bundles.json"
        )
        main.intel_monitor_store = IntelMonitorStore(
            temp_path / "intel_monitor_rules.json"
        )

        snapshot = self.fixture_snapshot

        async def fake_get_snapshot(force_refresh: bool = False):
            return snapshot

        main.regional_intel_service.get_snapshot = fake_get_snapshot
        main.regional_intel_service._latest_snapshot = snapshot

        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        main.intel_watchlist_store = self._original_watchlist
        main.intel_analyst_store = self._original_analyst
        main.intel_collection_store = self._original_collection
        main.intel_bundle_store = self._original_bundle
        main.intel_monitor_store = self._original_monitor
        main.regional_intel_service.get_snapshot = self._original_get_snapshot
        main.regional_intel_service._latest_snapshot = self._original_cached
        self.tempdir.cleanup()

    # ------------------------------------------------------------------
    # Health probe
    # ------------------------------------------------------------------

    def test_healthz_returns_ok_with_no_store_cache_header(self) -> None:
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    # ------------------------------------------------------------------
    # Admin shell HTML
    # ------------------------------------------------------------------

    def test_admin_page_renders_shell_with_required_markers(self) -> None:
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        body = response.text
        # Region selector + map + feed + source health + trends + rules
        for marker in (
            "id=\"admin-region\"",
            "id=\"admin-map\"",
            "id=\"admin-feed\"",
            "id=\"admin-source-health\"",
            "id=\"admin-trends\"",
            "id=\"admin-rules\"",
            "/static/admin.js",
            "/static/admin.css",
            "leaflet",
        ):
            self.assertIn(marker, body, f"missing marker: {marker}")

    # ------------------------------------------------------------------
    # Auth gate
    # ------------------------------------------------------------------

    def test_admin_api_open_when_admin_token_unset(self) -> None:
        # Default test environment has no ADMIN_TOKEN set; the gate is open.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_TOKEN", None)
            response = self.client.get("/api/admin/regions")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("regions", payload)
        self.assertGreater(len(payload["regions"]), 0)

    def test_admin_api_rejects_missing_token_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "s3cret"}, clear=False):
            response = self.client.get("/api/admin/regions")
            self.assertEqual(response.status_code, 401)
            self.assertIn("admin token", response.json()["detail"].lower())

    def test_admin_api_accepts_matching_token_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "s3cret"}, clear=False):
            response = self.client.get(
                "/api/admin/regions",
                headers={"X-Admin-Token": "s3cret"},
            )
            self.assertEqual(response.status_code, 200)

    def test_admin_api_rejects_wrong_token_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "s3cret"}, clear=False):
            response = self.client.get(
                "/api/admin/regions",
                headers={"X-Admin-Token": "nope"},
            )
            self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # Region catalog with bbox + map bounds
    # ------------------------------------------------------------------

    def test_admin_regions_endpoint_includes_bbox_center_and_bounds(self) -> None:
        response = self.client.get("/api/admin/regions")
        self.assertEqual(response.status_code, 200)
        regions = response.json()["regions"]
        self.assertGreater(len(regions), 0)
        for region in regions:
            self.assertIn("id", region)
            self.assertIn("bbox", region)
            self.assertIn("center", region)
            self.assertIn("bounds", region)
            # bbox-derived fields must be present (not null) for all
            # configured regions, since every region has a bbox today.
            self.assertEqual(len(region["bbox"]), 4)
            self.assertIsNotNone(region["center"])
            self.assertIsNotNone(region["bounds"])

    # ------------------------------------------------------------------
    # Overview bundle
    # ------------------------------------------------------------------

    def test_admin_overview_returns_grouped_feed_and_panels(self) -> None:
        response = self.client.get(
            "/api/admin/overview",
            params={"region": "austin_tx", "limit": 30},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in (
            "summary",
            "recent",
            "items_by_category",
            "source_health",
            "source_history",
            "trends",
            "monitor",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["summary"]["region"], "austin_tx")
        self.assertIsInstance(payload["items_by_category"], dict)
        # source_health is region-filtered, so the inner list is bounded.
        self.assertIn("source_health", payload["source_health"])
        self.assertIsInstance(payload["source_health"]["source_health"], list)

    def test_admin_search_returns_results_for_known_query(self) -> None:
        # Use a token from the fixture title to guarantee at least one hit.
        sample_news = next(
            item
            for item in self.fixture_snapshot.news
            if item.region_id == "austin_tx" and item.title
        )
        token = sample_news.title.split()[0]
        response = self.client.get(
            "/api/admin/search",
            params={"q": token, "region": "austin_tx"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertIsInstance(payload["results"], list)


if __name__ == "__main__":
    unittest.main()
