"""Tests for intel graph construction."""

from __future__ import annotations

import unittest

from app.intel_models import BusinessLead
from app.intel_models import NewsSignal
from app.intel_models import OrganizationProfile
from app.intel_models import PermitSignal
from app.intel_models import PublicContact
from app.intel_models import RegionProfile
from app.intel_models import RegionalIntelSnapshot
from app.services.intel_graph import _normalize_address
from app.services.intel_graph import _normalize_text
from app.services.intel_graph import _permit_related_organizations
from app.services.intel_graph import _stable_id
from app.services.intel_graph import build_intel_graph


class IntelGraphHelpersTestCase(unittest.TestCase):
    def test_stable_id_is_deterministic(self) -> None:
        self.assertEqual(_stable_id("a", "b"), _stable_id("a", "b"))

    def test_stable_id_changes_with_input(self) -> None:
        self.assertNotEqual(_stable_id("a", "b"), _stable_id("a", "c"))

    def test_normalize_text_lowercase_and_strips(self) -> None:
        self.assertEqual(_normalize_text("Hello World!"), "helloworld")

    def test_normalize_text_none_returns_empty(self) -> None:
        self.assertEqual(_normalize_text(None), "")

    def test_normalize_address_lowercase_and_strips(self) -> None:
        self.assertEqual(_normalize_address("123 Main St."), "123mainst")

    def test_permit_related_organizations_extracts_developer(self) -> None:
        notes = ["Developer: Acme Corp", "Organization: Builder Inc", "Other: note"]
        result = _permit_related_organizations(notes)
        self.assertIn("Acme Corp", result)
        self.assertIn("Builder Inc", result)

    def test_permit_related_organizations_dedupes(self) -> None:
        notes = ["Developer: Acme Corp", "Developer: Acme Corp"]
        result = _permit_related_organizations(notes)
        self.assertEqual(len(result), 1)

    def test_permit_related_organizations_skips_bad_labels(self) -> None:
        notes = ["Contact: Someone"]
        result = _permit_related_organizations(notes)
        self.assertEqual(result, [])


class IntelGraphBuildTestCase(unittest.TestCase):
    def _snapshot(self, **kwargs) -> RegionalIntelSnapshot:
        return RegionalIntelSnapshot(
            updated_at="2026-01-01T00:00:00Z",
            cache_ttl_seconds=900,
            regions=[
                RegionProfile(
                    id="austin_tx",
                    name="Austin, Texas",
                    summary="Test",
                    bbox=[30.05, -98.10, 30.65, -97.40],
                )
            ],
            organizations=[
                OrganizationProfile(
                    item_id="org1",
                    region_id="austin_tx",
                    name="Acme Corp",
                    organization_score=50.0,
                )
            ],
            news=[
                NewsSignal(
                    item_id="n1",
                    region_id="austin_tx",
                    title="Acme opens",
                    summary="Acme Corp opens a new location",
                    source_name="News",
                    source_url="https://example.com",
                    published_at="2026-01-01T00:00:00Z",
                    signal_type="opening",
                    organizations=["Acme Corp"],
                    signal_score=60.0,
                )
            ],
            permits=[
                PermitSignal(
                    item_id="p1",
                    region_id="austin_tx",
                    county="Travis",
                    address="123 Main St",
                    permit_number="P001",
                    permit_type="Build",
                    status="Issued",
                    status_date="2026-01-01T00:00:00Z",
                    source_name="City",
                    source_url="https://example.com",
                    signal_type="construction",
                    notes=["Developer: Acme Corp"],
                    signal_score=55.0,
                )
            ],
            businesses=[
                BusinessLead(
                    item_id="b1",
                    region_id="austin_tx",
                    name="Acme Corp",
                    category="shop:retail",
                    address="123 Main St",
                    source_name="OSM",
                    source_url="https://osm.org",
                    lead_score=40.0,
                )
            ],
            contacts=[
                PublicContact(
                    item_id="c1",
                    region_id="austin_tx",
                    name="Alice",
                    organization="Acme Corp",
                    source_name="OSM",
                    source_url="https://osm.org",
                    contact_score=30.0,
                )
            ],
            **kwargs,
        )

    def test_build_intel_graph_returns_nodes_and_edges(self) -> None:
        snapshot = self._snapshot()
        graph = build_intel_graph(snapshot)
        self.assertTrue(graph.nodes)
        self.assertTrue(graph.edges)
        node_ids = {n.node_id for n in graph.nodes}
        self.assertIn("org1", node_ids)

    def test_build_intel_graph_filters_by_region(self) -> None:
        snapshot = self._snapshot()
        graph = build_intel_graph(snapshot, region="austin_tx")
        self.assertTrue(
            all(n.region_id == "austin_tx" for n in graph.nodes if n.region_id)
        )

    def test_build_intel_graph_focus_node_id(self) -> None:
        snapshot = self._snapshot()
        graph = build_intel_graph(snapshot, focus_node_id="org1")
        self.assertTrue(
            all(
                n.node_id == "org1"
                or any(
                    e.source_id == n.node_id or e.target_id == n.node_id
                    for e in graph.edges
                )
                for n in graph.nodes
            )
        )

    def test_build_intel_graph_unknown_focus_returns_emptyish(self) -> None:
        snapshot = self._snapshot()
        graph = build_intel_graph(snapshot, focus_node_id="unknown")
        self.assertIn("region:austin_tx", {n.node_id for n in graph.nodes})

    def test_address_overlap_creates_same_address_edge(self) -> None:
        snapshot = self._snapshot()
        graph = build_intel_graph(snapshot, region="austin_tx")
        edge_relations = {e.relation for e in graph.edges}
        self.assertIn("same_address", edge_relations)


if __name__ == "__main__":
    unittest.main(verbosity=2)
