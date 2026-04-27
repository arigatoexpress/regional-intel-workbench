from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
from app.services.foundry_export import export_snapshot
from app.services.foundry_export import intel_item_objects
from app.services.foundry_export import region_objects
from app.services.foundry_export import source_health_objects


def _snapshot() -> RegionalIntelSnapshot:
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
        news=[
            NewsSignal(
                item_id="news-1",
                region_id="austin_tx",
                title="Retail corridor expansion",
                summary="New public coverage of a corridor expansion.",
                source_name="Public News",
                source_url="https://example.test/news",
                published_at="2026-04-27T10:00:00Z",
                signal_type="business_growth",
                actionable=True,
                signal_score=81.0,
            )
        ],
        permits=[
            PermitSignal(
                item_id="permit-1",
                region_id="austin_tx",
                county="Travis",
                address="100 Congress Ave",
                permit_number="P-1",
                permit_type="Building",
                status="issued",
                status_date="2026-04-27",
                source_name="Austin Permits",
                source_url="https://example.test/permit",
                signal_type="construction",
                signal_score=74.0,
            )
        ],
        businesses=[
            BusinessLead(
                item_id="business-1",
                region_id="austin_tx",
                name="Example Coffee",
                category="retail",
                address="200 Main St",
                source_name="OpenStreetMap",
                source_url="https://example.test/osm",
                lead_score=52.0,
            )
        ],
        contacts=[
            PublicContact(
                item_id="contact-1",
                region_id="austin_tx",
                name="Public Desk",
                title="Economic Development",
                organization="City Office",
                source_name="City Directory",
                source_url="https://example.test/contact",
                contact_score=66.0,
            )
        ],
        organizations=[
            OrganizationProfile(
                item_id="org-1",
                region_id="austin_tx",
                name="Example Coffee",
                categories=["retail"],
                website="https://example.test/org",
                business_lead_count=1,
                news_signal_count=1,
                contact_count=1,
                permit_signal_count=1,
                source_names=["OpenStreetMap", "Public News"],
                latest_activity_at="2026-04-27T10:00:00Z",
                organization_score=88.0,
            )
        ],
        source_health=[
            SourceHealth(
                source_key="austin_open_data_permits",
                name="City of Austin Open Data Permits",
                category="permit",
                region_ids=["austin_tx"],
                live_pull=True,
                status="live",
                item_count=1,
                last_seen_at="2026-04-27T10:00:00Z",
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


def _read_ndjson(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class FoundryExportTestCase(unittest.TestCase):
    def test_builds_region_source_and_item_objects(self) -> None:
        snapshot = _snapshot()

        regions = region_objects(snapshot)
        items = intel_item_objects(snapshot)
        sources = source_health_objects(snapshot)

        self.assertEqual([row["region_id"] for row in regions], ["austin_tx", "houston_tx"])
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["object_id"], "regional-intel:item:business:business-1")
        self.assertTrue(items[0]["provenance"]["public_sources_only"])
        self.assertEqual(sources[0]["object_id"], "regional-intel:source:austin_open_data_permits")

    def test_region_filter_limits_all_object_types(self) -> None:
        snapshot = _snapshot()

        self.assertEqual(len(region_objects(snapshot, region="houston_tx")), 1)
        self.assertEqual(intel_item_objects(snapshot, region="houston_tx"), [])
        self.assertEqual(source_health_objects(snapshot, region="houston_tx"), [])

    def test_export_snapshot_writes_ndjson_and_manifest(self) -> None:
        snapshot = _snapshot()
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "foundry"
            manifest = export_snapshot(snapshot, output_dir, region="austin_tx")

            self.assertEqual(manifest["region"], "austin_tx")
            self.assertEqual(manifest["object_types"]["Region"]["rows"], 1)
            self.assertEqual(manifest["object_types"]["IntelItem"]["rows"], 5)
            self.assertEqual(manifest["object_types"]["IntelSourceHealth"]["rows"], 1)
            self.assertTrue((output_dir / "manifest.json").is_file())

            items = _read_ndjson(output_dir / "IntelItem.ndjson")
            self.assertEqual({item["kind"] for item in items}, {"business", "contact", "news", "organization", "permit"})
            self.assertEqual(items[0]["snapshot_updated_at"], "2026-04-27T16:00:00Z")


class FoundryExportDeterminismTestCase(unittest.TestCase):
    """Same snapshot + region must yield byte-identical NDJSON across runs."""

    def test_intel_item_ndjson_is_byte_identical_across_runs(self) -> None:
        snapshot = _snapshot()
        with TemporaryDirectory() as tmp_a, TemporaryDirectory() as tmp_b:
            export_snapshot(snapshot, Path(tmp_a), region="austin_tx")
            export_snapshot(snapshot, Path(tmp_b), region="austin_tx")

            for filename in ("Region.ndjson", "IntelItem.ndjson", "IntelSourceHealth.ndjson"):
                bytes_a = (Path(tmp_a) / filename).read_bytes()
                bytes_b = (Path(tmp_b) / filename).read_bytes()
                self.assertEqual(
                    bytes_a,
                    bytes_b,
                    f"{filename} differed across runs",
                )

    def test_duplicate_kind_and_item_id_still_sort_stably(self) -> None:
        # Two news rows that share (region_id, kind, item_id) — primary key
        # collision. Without a tie-break the sort is non-deterministic; with
        # the content-hash secondary key, two runs must agree.
        snapshot = _snapshot()
        snapshot.news.append(
            NewsSignal(
                item_id="news-1",  # duplicate id
                region_id="austin_tx",
                title="Distinct downstream coverage",
                summary="Different body, same item id collision case.",
                source_name="Public News Two",
                source_url="https://example.test/news-2",
                published_at="2026-04-27T11:00:00Z",
                signal_type="business_growth",
                actionable=True,
                signal_score=42.0,
            )
        )

        items_first = intel_item_objects(snapshot)
        items_second = intel_item_objects(snapshot)
        self.assertEqual(items_first, items_second)
        self.assertEqual(
            json.dumps(items_first, sort_keys=True),
            json.dumps(items_second, sort_keys=True),
        )


class FoundryExportProvenanceGuardTestCase(unittest.TestCase):
    """News/permit/org rows lacking source_name + source_url must be dropped."""

    def _snapshot_with_missing_provenance(self) -> RegionalIntelSnapshot:
        snap = _snapshot()
        snap.news.append(
            NewsSignal(
                item_id="news-no-prov",
                region_id="austin_tx",
                title="Unverified rumor",
                summary="No source attribution.",
                source_name="",  # blank source name
                source_url="",  # blank source url
                published_at="2026-04-27T12:00:00Z",
                signal_type="rumor",
                actionable=False,
                signal_score=10.0,
            )
        )
        snap.permits.append(
            PermitSignal(
                item_id="permit-no-prov",
                region_id="austin_tx",
                county="Travis",
                address="999 Unknown Way",
                permit_number="P-X",
                permit_type="Building",
                status="filed",
                status_date="2026-04-27",
                source_name="",  # blank — dropped
                source_url="",
                signal_type="construction",
                signal_score=22.0,
            )
        )
        snap.organizations.append(
            OrganizationProfile(
                item_id="org-no-prov",
                region_id="austin_tx",
                name="Mystery LLC",
                categories=["unknown"],
                # source_names empty list → org row has source_name=None in export
                source_names=[],
                latest_activity_at="2026-04-27T09:00:00Z",
                organization_score=33.0,
            )
        )
        return snap

    def test_rows_without_provenance_are_dropped_and_logged(self) -> None:
        snapshot = self._snapshot_with_missing_provenance()
        with self.assertLogs("app.services.foundry_export", level="WARNING") as captured:
            items = intel_item_objects(snapshot, region="austin_tx")

        item_ids = {row["item_id"] for row in items}
        self.assertNotIn("news-no-prov", item_ids)
        self.assertNotIn("permit-no-prov", item_ids)
        self.assertNotIn("org-no-prov", item_ids)
        # The original well-attributed news row still emits.
        self.assertIn("news-1", item_ids)

        joined_logs = "\n".join(captured.output)
        self.assertIn("news-no-prov", joined_logs)
        self.assertIn("permit-no-prov", joined_logs)
        self.assertIn("org-no-prov", joined_logs)
        self.assertIn("missing provenance", joined_logs)

    def test_business_and_contact_rows_are_not_provenance_guarded(self) -> None:
        # Pydantic already enforces source_name/source_url for those models
        # at ingestion. The guard should be a no-op for them.
        snapshot = _snapshot()
        items = intel_item_objects(snapshot, region="austin_tx")
        kinds = {row["kind"] for row in items}
        self.assertIn("business", kinds)
        self.assertIn("contact", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
