from __future__ import annotations

import hashlib
import re

from app.intel_models import IntelGraph
from app.intel_models import IntelGraphEdge
from app.intel_models import IntelGraphNode
from app.intel_models import RegionId
from app.intel_models import RegionalIntelSnapshot
from app.utils import clean_text


ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[a-z0-9#.\- ]+?\s(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|ln|lane|way|pkwy|parkway|hwy|highway|trl|trail|rr)\b",
    re.IGNORECASE,
)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value or "").lower())


def _normalize_address(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value or "").lower())


def _permit_related_organizations(notes: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for note in notes:
        if ":" not in note:
            continue
        label, raw = note.split(":", 1)
        key = clean_text(label).lower()
        if key not in {"developer", "organization", "planning firm"}:
            continue
        value = clean_text(raw)
        normalized = _normalize_text(value)
        if not value or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value)
    return output


def build_intel_graph(
    snapshot: RegionalIntelSnapshot,
    *,
    region: RegionId | None = None,
    focus_node_id: str | None = None,
) -> IntelGraph:
    regions = [item for item in snapshot.regions if region is None or item.id == region]
    region_ids = {item.id for item in regions}

    organizations = [
        item for item in snapshot.organizations if not region_ids or item.region_id in region_ids
    ]
    organizations.sort(key=lambda item: item.organization_score, reverse=True)
    if focus_node_id:
        focus_org = next((item for item in organizations if item.item_id == focus_node_id), None)
        seed_orgs = [focus_org] if focus_org is not None else organizations[:10]
    else:
        seed_orgs = organizations[:18]

    seed_org_names = {_normalize_text(item.name): item.item_id for item in seed_orgs}

    nodes: dict[str, IntelGraphNode] = {}
    edges: dict[str, IntelGraphEdge] = {}

    def add_node(node: IntelGraphNode) -> None:
        if node.node_id not in nodes:
            nodes[node.node_id] = node

    def add_edge(source_id: str, target_id: str, relation: str, *, weight: float = 1.0, notes: list[str] | None = None) -> None:
        edge_id = _stable_id(source_id, target_id, relation)
        if edge_id not in edges:
            edges[edge_id] = IntelGraphEdge(
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                weight=weight,
                notes=notes or [],
            )

    for item in regions:
        add_node(
            IntelGraphNode(
                node_id=f"region:{item.id}",
                kind="region",
                region_id=item.id,
                label=item.name,
                subtitle=item.summary,
                notes=item.notes,
            )
        )

    for item in seed_orgs:
        add_node(
            IntelGraphNode(
                node_id=item.item_id,
                kind="organization",
                region_id=item.region_id,
                label=item.name,
                subtitle=", ".join(item.categories[:3]) or "Organization",
                score=item.organization_score,
                url=item.website,
                address=item.address,
                notes=item.notes,
            )
        )
        add_edge(f"region:{item.region_id}", item.item_id, "region_watch", weight=item.organization_score)

    for item in snapshot.businesses:
        if region_ids and item.region_id not in region_ids:
            continue
        org_id = seed_org_names.get(_normalize_text(item.name))
        if not org_id:
            continue
        add_node(
            IntelGraphNode(
                node_id=item.item_id,
                kind="business",
                region_id=item.region_id,
                label=item.name,
                subtitle=item.category,
                score=item.lead_score,
                url=item.website or item.source_url,
                address=item.address,
                notes=item.notes,
            )
        )
        add_edge(org_id, item.item_id, "open_map_business", weight=item.lead_score)

    for item in snapshot.contacts:
        if region_ids and item.region_id not in region_ids:
            continue
        org_id = seed_org_names.get(_normalize_text(item.organization))
        if not org_id:
            continue
        add_node(
            IntelGraphNode(
                node_id=item.item_id,
                kind="contact",
                region_id=item.region_id,
                label=item.name,
                subtitle=" | ".join(part for part in [item.title or "", item.organization] if part),
                score=item.contact_score,
                url=item.website or item.source_url,
                address=item.address,
                notes=item.notes,
            )
        )
        add_edge(org_id, item.item_id, "public_contact", weight=item.contact_score)

    for item in snapshot.news:
        if region_ids and item.region_id not in region_ids:
            continue
        related = [
            seed_org_names[_normalize_text(name)]
            for name in item.organizations
            if _normalize_text(name) in seed_org_names
        ]
        if not related:
            continue
        add_node(
            IntelGraphNode(
                node_id=item.item_id,
                kind="news",
                region_id=item.region_id,
                label=item.title,
                subtitle=item.source_name,
                score=item.signal_score,
                url=item.source_url,
                address=item.address_hint,
                notes=item.notes,
            )
        )
        for org_id in related:
            add_edge(item.item_id, org_id, "news_mentions_org", weight=item.signal_score)

    known_business_addresses = {
        _normalize_address(node.address)
        for node in nodes.values()
        if node.kind == "business" and node.address and node.address != "Address not provided"
    }

    for item in snapshot.permits:
        if region_ids and item.region_id not in region_ids:
            continue
        related_org_ids = [
            seed_org_names[name_key]
            for name_key in [_normalize_text(name) for name in _permit_related_organizations(item.notes)]
            if name_key in seed_org_names
        ]
        address_key = _normalize_address(item.address)
        if not related_org_ids and address_key not in known_business_addresses and item.signal_score < 70:
            continue
        add_node(
            IntelGraphNode(
                node_id=item.item_id,
                kind="permit",
                region_id=item.region_id,
                label=item.address,
                subtitle=f"{item.county} | {item.permit_type}",
                score=item.signal_score,
                url=item.source_url,
                address=item.address,
                notes=item.notes,
            )
        )
        for org_id in related_org_ids:
            add_edge(item.item_id, org_id, "permit_names_org", weight=item.signal_score)

    permit_nodes = [
        node for node in nodes.values() if node.kind == "permit" and node.address and node.address != "Address not provided"
    ]
    permit_by_address = {_normalize_address(node.address): node.node_id for node in permit_nodes}

    for node in list(nodes.values()):
        if node.kind == "business":
            permit_id = permit_by_address.get(_normalize_address(node.address))
            if permit_id:
                add_edge(node.node_id, permit_id, "same_address", weight=max(node.score, nodes[permit_id].score))
        elif node.kind == "news" and node.address:
            news_address = _normalize_address(node.address)
            if not news_address:
                continue
            for normalized_permit_address, permit_id in permit_by_address.items():
                if news_address and (news_address in normalized_permit_address or normalized_permit_address in news_address):
                    add_edge(node.node_id, permit_id, "same_address_hint", weight=max(node.score, nodes[permit_id].score))

    if focus_node_id and focus_node_id in nodes:
        neighbor_ids = {focus_node_id}
        for edge in list(edges.values()):
            if edge.source_id == focus_node_id or edge.target_id == focus_node_id:
                neighbor_ids.add(edge.source_id)
                neighbor_ids.add(edge.target_id)
        for edge in list(edges.values()):
            if edge.source_id in neighbor_ids and edge.target_id in neighbor_ids:
                continue
            edges.pop(edge.edge_id, None)
        nodes = {node_id: node for node_id, node in nodes.items() if node_id in neighbor_ids}

    graph = IntelGraph(
        region=region,
        focus_node_id=focus_node_id,
        nodes=sorted(nodes.values(), key=lambda item: (item.kind, -item.score, item.label.lower())),
        edges=sorted(edges.values(), key=lambda item: (-item.weight, item.relation, item.source_id, item.target_id)),
        notes=[
            "Graph edges are built from exact-name organization matches, public-contact associations, organization mentions in news, permit-linked organization notes, and address overlaps.",
            "This is an intelligence graph, not a truth graph. Human review is still required before action.",
        ],
    )
    return graph
