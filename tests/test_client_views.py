"""Tests for client view composition and helpers."""

from __future__ import annotations

import unittest

from app.intel_models import ClientFeedItem
from app.intel_models import ClientViewMetric
from app.intel_models import IntelMonitorRule
from app.intel_models import NewsSignal
from app.intel_models import PermitSignal
from app.intel_models import RegionalIntelSnapshot
from app.services.client_views import _feed_item
from app.services.client_views import _intel_url
from app.services.client_views import _is_commercial_permit
from app.services.client_views import _is_retail_business
from app.services.client_views import _looks_commercial_signal
from app.services.client_views import available_client_views
from app.services.client_views import build_client_view


class ClientViewsHelpersTestCase(unittest.TestCase):
    def test_available_client_views_returns_list_with_blanga_austin(self) -> None:
        views = available_client_views()
        self.assertIsInstance(views, list)
        self.assertTrue(any(v["view_id"] == "blanga_austin" for v in views))

    def test_intel_url_with_region(self) -> None:
        url = _intel_url("news", "n1", region_id="austin_tx")
        self.assertIn("detail_kind=news", url)
        self.assertIn("detail_id=n1", url)
        self.assertIn("region=austin_tx", url)
        self.assertTrue(url.startswith("/intel?"))

    def test_intel_url_without_region(self) -> None:
        url = _intel_url("permit", "p1")
        self.assertIn("detail_kind=permit", url)
        self.assertIn("detail_id=p1", url)
        self.assertNotIn("region", url)

    def test_feed_item_defaults(self) -> None:
        item = _feed_item(
            item_id="x1",
            item_kind="news",
            region_id="austin_tx",
            title="Test",
            subtitle=None,
            summary="Summary",
            why_it_matters=None,
            recommended_action=None,
            score=42.0,
        )
        self.assertIsInstance(item, ClientFeedItem)
        self.assertEqual(item.item_id, "x1")
        self.assertEqual(item.tags, [])
        self.assertEqual(item.notes, [])
        self.assertEqual(item.score, 42.0)

    def test_is_retail_business_with_restaurant(self) -> None:
        self.assertTrue(_is_retail_business("restaurant", {}))

    def test_is_retail_business_with_shop_tag(self) -> None:
        self.assertTrue(_is_retail_business("store", {"shop": "clothes"}))

    def test_is_retail_business_negative(self) -> None:
        self.assertFalse(_is_retail_business("warehouse", {}))

    def test_looks_commercial_signal_positive(self) -> None:
        self.assertTrue(_looks_commercial_signal("Commercial retail building"))

    def test_looks_commercial_signal_negative_residential(self) -> None:
        self.assertFalse(_looks_commercial_signal("Single family residential"))

    def test_looks_commercial_signal_empty(self) -> None:
        self.assertFalse(_looks_commercial_signal(""))

    def test_is_commercial_permit_commercial(self) -> None:
        permit = PermitSignal(
            item_id="p1",
            region_id="austin_tx",
            county="Travis",
            address="123 Main St",
            permit_number="P001",
            permit_type="Commercial Build",
            status="Issued",
            status_date="2026-01-01T00:00:00Z",
            source_name="City",
            source_url="https://example.com",
            signal_type="construction",
            notes=["Tenant improvement"],
        )
        self.assertTrue(_is_commercial_permit(permit))

    def test_is_commercial_permit_residential_negative(self) -> None:
        permit = PermitSignal(
            item_id="p2",
            region_id="austin_tx",
            county="Travis",
            address="456 Oak St",
            permit_number="P002",
            permit_type="Residential",
            status="Issued",
            status_date="2026-01-01T00:00:00Z",
            source_name="City",
            source_url="https://example.com",
            signal_type="construction",
            notes=["Pool construction"],
        )
        self.assertFalse(_is_commercial_permit(permit))


class ClientViewsBuildTestCase(unittest.TestCase):
    def test_build_client_view_unknown_raises_keyerror(self) -> None:
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z", cache_ttl_seconds=900
        )
        with self.assertRaises(KeyError):
            build_client_view(
                view_id="unknown",
                snapshot=snapshot,
                history_records=[],
                source_history=[],
                monitor_rules=[],
            )

    def test_build_client_view_blanga_austin_returns_view(self) -> None:
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z",
            cache_ttl_seconds=900,
            regions=[],
            news=[
                NewsSignal(
                    item_id="n1",
                    region_id="austin_tx",
                    title="Vacancy at 123 Main St",
                    summary="Store closed",
                    source_name="News",
                    source_url="https://example.com",
                    published_at="2026-01-01T00:00:00Z",
                    signal_type="vacancy_or_closure",
                    address_hint="123 Main St",
                    actionable=True,
                    signal_score=80.0,
                )
            ],
            permits=[
                PermitSignal(
                    item_id="p1",
                    region_id="austin_tx",
                    county="Travis",
                    address="123 Main St",
                    permit_number="P001",
                    permit_type="Commercial Build",
                    status="Issued",
                    status_date="2026-01-01T00:00:00Z",
                    source_name="City",
                    source_url="https://example.com",
                    signal_type="construction",
                    notes=["Retail shell"],
                    signal_score=75.0,
                )
            ],
            businesses=[],
            contacts=[],
            organizations=[],
        )
        view = build_client_view(
            view_id="blanga_austin",
            snapshot=snapshot,
            history_records=[],
            source_history=[],
            monitor_rules=[
                IntelMonitorRule(
                    rule_id="r1",
                    created_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z",
                    title="Test rule",
                    region_id="austin_tx",
                )
            ],
        )
        self.assertEqual(view.view_id, "blanga_austin")
        self.assertTrue(view.hero_metrics)
        self.assertTrue(view.sections)
        section_ids = {s.section_id for s in view.sections}
        self.assertIn("deal_radar", section_ids)
        self.assertIn("vacancy_feed", section_ids)

    def test_client_view_metric_model(self) -> None:
        metric = ClientViewMetric(label="Test", value="1", detail="detail")
        self.assertEqual(metric.label, "Test")
        self.assertEqual(metric.value, "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
