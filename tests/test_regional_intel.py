"""Tests for regional intel core logic and helpers."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from app.intel_models import BusinessLead
from app.intel_models import NewsSignal
from app.intel_models import OrganizationProfile
from app.intel_models import PermitSignal
from app.intel_models import PublicContact
from app.intel_models import RegionProfile
from app.intel_models import RegionalIntelSnapshot
from app.services.regional_intel import _austin_permit_signal_type
from app.services.regional_intel import _business_category
from app.services.regional_intel import _business_lead_score
from app.services.regional_intel import _build_organization_profiles
from app.services.regional_intel import _build_region_briefs
from app.services.regional_intel import _build_source_health
from app.services.regional_intel import _col_letters_to_index
from app.services.regional_intel import _contact_score
from app.services.regional_intel import _county_portal_datatables_payload
from app.services.regional_intel import _derive_org_keywords
from app.services.regional_intel import _excel_serial_to_iso
from app.services.regional_intel import _extract_address_hint
from app.services.regional_intel import _extract_first_email
from app.services.regional_intel import _extract_first_phone
from app.services.regional_intel import _extract_organizations_from_text
from app.services.regional_intel import _extract_source_label
from app.services.regional_intel import _hours_since
from app.services.regional_intel import _html_to_text
from app.services.regional_intel import _houston_development_signal_type
from app.services.regional_intel import _houston_location_label
from app.services.regional_intel import _is_useful_business
from app.services.regional_intel import _news_signal_score
from app.services.regional_intel import _normalize_entity_name
from app.services.regional_intel import _now_utc
from app.services.regional_intel import _organization_score
from app.services.regional_intel import _osm_object_url
from app.services.regional_intel import _parse_isoish
from app.services.regional_intel import _parse_pubdate
from app.services.regional_intel import _permit_signal_score
from app.services.regional_intel import _possible_orgs_from_title
from app.services.regional_intel import _signal_type_from_text
from app.services.regional_intel import _source_matches_name
from app.services.regional_intel import _stable_id
from app.services.regional_intel import RegionalIntelService


class RegionalIntelHelpersTestCase(unittest.TestCase):
    def test_stable_id_deterministic(self) -> None:
        self.assertEqual(_stable_id("a", "b"), _stable_id("a", "b"))

    def test_now_utc_returns_datetime(self) -> None:
        self.assertIsInstance(_now_utc(), datetime)

    def test_parse_isoish_with_z(self) -> None:
        result = _parse_isoish("2026-01-01T00:00:00Z")
        self.assertTrue(result.startswith("2026-01-01"))

    def test_parse_isoish_empty_fallback(self) -> None:
        result = _parse_isoish("")
        self.assertTrue(result)

    def test_parse_pubdate_rfc_format(self) -> None:
        result = _parse_pubdate("Mon, 01 Jan 2026 00:00:00 GMT")
        self.assertTrue(result.startswith("2026-01-01"))

    def test_parse_pubdate_empty_fallback(self) -> None:
        result = _parse_pubdate("")
        self.assertTrue(result)

    def test_extract_address_hint_finds_address(self) -> None:
        text = "A new store at 123 Main Street is opening"
        result = _extract_address_hint(text)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("123 Main Street", result)

    def test_extract_address_hint_no_match(self) -> None:
        self.assertIsNone(_extract_address_hint("No address here"))

    def test_signal_type_from_text_vacancy(self) -> None:
        self.assertEqual(
            _signal_type_from_text("Store closing soon"), "vacancy_or_closure"
        )

    def test_signal_type_from_text_opening(self) -> None:
        self.assertEqual(_signal_type_from_text("Grand opening this week"), "opening")

    def test_signal_type_from_text_construction(self) -> None:
        self.assertEqual(
            _signal_type_from_text("Building permit issued"), "construction"
        )

    def test_signal_type_from_text_general(self) -> None:
        self.assertEqual(_signal_type_from_text("Random news"), "general_business")

    def test_possible_orgs_from_title(self) -> None:
        result = _possible_orgs_from_title("Acme Corp opens new location")
        self.assertIn("Acme Corp", result)

    def test_possible_orgs_from_title_no_match(self) -> None:
        result = _possible_orgs_from_title("No verb match")
        self.assertEqual(result, [])

    def test_extract_source_label_from_source_tag(self) -> None:
        import xml.etree.ElementTree as ET

        item = ET.Element("item")
        source = ET.SubElement(item, "source")
        source.text = "Austin Monitor"
        self.assertEqual(_extract_source_label(item), "Austin Monitor")

    def test_austin_permit_signal_type_construction(self) -> None:
        self.assertEqual(
            _austin_permit_signal_type("Restaurant Build", ""), "construction"
        )

    def test_austin_permit_signal_type_ti(self) -> None:
        self.assertEqual(
            _austin_permit_signal_type("Tenant Improvement", ""), "tenant_improvement"
        )

    def test_county_portal_datatables_payload_structure(self) -> None:
        payload = _county_portal_datatables_payload(start=0, length=10)
        self.assertEqual(payload["draw"], "1")
        self.assertEqual(payload["start"], "0")
        self.assertEqual(payload["length"], "10")
        self.assertIn("columns[0][data]", payload)

    def test_col_letters_to_index_a(self) -> None:
        self.assertEqual(_col_letters_to_index("A"), 0)

    def test_col_letters_to_index_z(self) -> None:
        self.assertEqual(_col_letters_to_index("Z"), 25)

    def test_excel_serial_to_iso_valid(self) -> None:
        result = _excel_serial_to_iso("45000")
        self.assertTrue(result.startswith("2023"))

    def test_excel_serial_to_iso_empty(self) -> None:
        result = _excel_serial_to_iso("")
        self.assertTrue(result)

    def test_houston_development_signal_type_commercial(self) -> None:
        self.assertEqual(
            _houston_development_signal_type("Plat", "Commercial", "Test"),
            "commercial_development",
        )

    def test_houston_development_signal_type_residential(self) -> None:
        self.assertEqual(
            _houston_development_signal_type("Plat", "Single Family", "Test"),
            "residential_development",
        )

    def test_houston_location_label(self) -> None:
        row = {"App Location": "Main St", "Zipcode": "77001"}
        self.assertEqual(_houston_location_label(row), "Main St 77001")

    def test_business_category_shop(self) -> None:
        self.assertEqual(_business_category({"shop": "clothes"}), "shop:clothes")

    def test_business_category_office(self) -> None:
        self.assertEqual(_business_category({"office": "lawyer"}), "office:lawyer")

    def test_business_category_default(self) -> None:
        self.assertEqual(_business_category({}), "business")

    def test_osm_object_url_uses_stable_public_object_reference(self) -> None:
        self.assertEqual(
            _osm_object_url({"type": "way", "id": 12345}),
            "https://www.openstreetmap.org/way/12345",
        )
        self.assertIsNone(_osm_object_url({"type": "area", "id": 12345}))

    def test_html_to_text_strips_tags(self) -> None:
        self.assertEqual(_html_to_text("<p>Hello</p>"), "Hello")

    def test_html_to_text_strips_script(self) -> None:
        self.assertEqual(_html_to_text("<script>x</script><p>Hi</p>"), "Hi")

    def test_extract_first_email(self) -> None:
        self.assertEqual(
            _extract_first_email("Contact us at team@example.com today"),
            "team@example.com",
        )

    def test_extract_first_email_none(self) -> None:
        self.assertIsNone(_extract_first_email("No email"))

    def test_extract_first_phone(self) -> None:
        self.assertEqual(_extract_first_phone("Call 512-555-1234"), "512-555-1234")

    def test_extract_first_phone_none(self) -> None:
        self.assertIsNone(_extract_first_phone("No phone"))

    def test_normalize_entity_name(self) -> None:
        self.assertEqual(_normalize_entity_name("Acme Corp!"), "acmecorp")

    def test_derive_org_keywords(self) -> None:
        businesses = [
            BusinessLead(
                item_id="b1",
                region_id="austin_tx",
                name="Acme",
                category="shop",
                address="A",
                source_name="OSM",
                source_url="https://osm.org",
            )
        ]
        contacts = [
            PublicContact(
                item_id="c1",
                region_id="austin_tx",
                name="Alice",
                organization="Acme",
                source_name="OSM",
                source_url="https://osm.org",
            )
        ]
        permits: list[PermitSignal] = []
        result = _derive_org_keywords(businesses, contacts, permits)
        self.assertIn("Acme", result.get("austin_tx", []))

    def test_extract_organizations_from_text(self) -> None:
        result = _extract_organizations_from_text(
            "Acme Corp is hiring", ["Acme Corp", "Other Corp"]
        )
        self.assertIn("Acme Corp", result)

    def test_extract_organizations_from_text_limits_six(self) -> None:
        candidates = [f"Org{i}" for i in range(10)]
        text = " ".join(candidates)
        result = _extract_organizations_from_text(text, candidates)
        self.assertLessEqual(len(result), 6)

    def test_hours_since_valid(self) -> None:
        now = datetime.now(tz=UTC).isoformat()
        result = _hours_since(now)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result, 0.0)

    def test_hours_since_invalid(self) -> None:
        self.assertIsNone(_hours_since("not-a-date"))

    def test_news_signal_score_vacancy(self) -> None:
        news = NewsSignal(
            item_id="n1",
            region_id="austin_tx",
            title="Closing",
            summary="Closed",
            source_name="News",
            source_url="https://example.com",
            published_at=datetime.now(tz=UTC).isoformat(),
            signal_type="vacancy_or_closure",
            actionable=True,
            address_hint="123 Main St",
            organizations=["Acme"],
            signal_score=0.0,
        )
        score = _news_signal_score(news)
        self.assertGreater(score, 50.0)

    def test_permit_signal_score_construction_approved(self) -> None:
        permit = PermitSignal(
            item_id="p1",
            region_id="austin_tx",
            county="Travis",
            address="123 Main St",
            permit_number="P001",
            permit_type="Build",
            status="Approved",
            status_date=datetime.now(tz=UTC).isoformat(),
            source_name="City",
            source_url="https://example.com",
            signal_type="construction",
            signal_score=0.0,
        )
        score = _permit_signal_score(permit)
        self.assertGreater(score, 50.0)

    def test_business_lead_score_with_all_fields(self) -> None:
        lead = BusinessLead(
            item_id="b1",
            region_id="austin_tx",
            name="Acme",
            category="shop:retail",
            address="123 Main St",
            website="https://acme.com",
            phone="512-555-1234",
            email="a@acme.com",
            source_name="OSM",
            source_url="https://osm.org",
            lead_score=0.0,
        )
        score = _business_lead_score(lead)
        self.assertGreater(score, 50.0)

    def test_contact_score_with_email(self) -> None:
        contact = PublicContact(
            item_id="c1",
            region_id="austin_tx",
            name="Alice",
            organization="Acme",
            email="alice@acme.com",
            source_name="OSM",
            source_url="https://osm.org",
            contact_score=0.0,
        )
        score = _contact_score(contact)
        self.assertGreater(score, 50.0)

    def test_organization_score_with_signals(self) -> None:
        org = OrganizationProfile(
            item_id="org1",
            region_id="austin_tx",
            name="Acme",
            business_lead_count=2,
            news_signal_count=3,
            contact_count=1,
            permit_signal_count=1,
            website="https://acme.com",
            phone="512-555-1234",
            email="a@acme.com",
            organization_score=0.0,
        )
        score = _organization_score(org)
        self.assertGreater(score, 50.0)

    def test_source_matches_name_exact(self) -> None:
        from app.intel_models import IntelSource

        source = IntelSource(
            source_key="test",
            region_ids=[],
            category="news",
            name="Austin Monitor",
            collection_mode="rss",
            access="public",
        )
        self.assertTrue(_source_matches_name(source, "Austin Monitor"))

    def test_source_matches_name_false(self) -> None:
        from app.intel_models import IntelSource

        source = IntelSource(
            source_key="test",
            region_ids=[],
            category="news",
            name="Austin Monitor",
            collection_mode="rss",
            access="public",
        )
        self.assertFalse(_source_matches_name(source, "Houston Chronicle"))

    def test_is_useful_business_shop(self) -> None:
        self.assertTrue(_is_useful_business({"shop": "clothes"}, "Boutique"))

    def test_is_useful_business_noise_name(self) -> None:
        self.assertFalse(_is_useful_business({"leisure": "park"}, "Campground Trail"))

    def test_build_organization_profiles_empty(self) -> None:
        result = _build_organization_profiles(
            news=[], permits=[], businesses=[], contacts=[]
        )
        self.assertEqual(result, [])

    def test_build_organization_profiles_from_business(self) -> None:
        businesses = [
            BusinessLead(
                item_id="b1",
                region_id="austin_tx",
                name="Acme",
                category="shop:retail",
                address="123 Main St",
                source_name="OSM",
                source_url="https://osm.org",
            )
        ]
        result = _build_organization_profiles(
            news=[], permits=[], businesses=businesses, contacts=[]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Acme")
        self.assertEqual(result[0].source_names, ["OSM"])
        self.assertEqual(result[0].source_urls, ["https://osm.org"])

    def test_build_region_briefs(self) -> None:
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z",
            cache_ttl_seconds=900,
            regions=[
                RegionProfile(
                    id="austin_tx",
                    name="Austin",
                    summary="Test",
                    bbox=[30.0, -98.0, 31.0, -97.0],
                )
            ],
            news=[],
            permits=[],
            businesses=[],
            contacts=[],
            organizations=[],
        )
        briefs = _build_region_briefs(snapshot)
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0].region_id, "austin_tx")

    def test_build_source_health_empty(self) -> None:
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z",
            cache_ttl_seconds=900,
            sources=[],
        )
        health = _build_source_health(snapshot)
        self.assertEqual(health, [])


class RegionalIntelServiceTestCase(unittest.TestCase):
    def test_source_catalog_returns_sources(self) -> None:
        service = RegionalIntelService()
        self.assertTrue(service.source_catalog())

    def test_region_catalog_returns_regions(self) -> None:
        service = RegionalIntelService()
        self.assertTrue(service.region_catalog())

    def test_ethics_catalog_returns_rules(self) -> None:
        service = RegionalIntelService()
        self.assertTrue(service.ethics_catalog())

    def test_get_snapshot_returns_cached(self) -> None:
        service = RegionalIntelService(ttl_seconds=3600)
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z", cache_ttl_seconds=900
        )
        service._snapshot = snapshot
        service._expires_at = float("inf")
        result = asyncio.run(service.get_snapshot())
        self.assertEqual(result, snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
