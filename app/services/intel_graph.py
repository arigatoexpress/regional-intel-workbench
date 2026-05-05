from __future__ import annotations

import hashlib
import re

from app.intel_models import IntelGraph
from app.intel_models import IntelGraphEdge
from app.intel_models import IntelGraphNode
from app.intel_models import OrganizationProfile
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
    regions = [r for r in snapshot.regions if region is None or r.id == region]
    region_ids = {r.id for r in regions}

    organizations: list[OrganizationProfile] = [
        o for o in snapshot.organizations if not region_ids or o.region_id in region_ids
    ]
    organizations.sort(key=lambda o: o.organization_score, reverse=True)
    if focus_node_id:
        focus_org = next((o for o in organizations if o.item_id == focus_node_id), None)
        seed_orgs: list[OrganizationProfile] = (
            [focus_org] if focus_org is not None else organizations[:10]
        )
    else:
        seed_orgs = organizations[:18]

    seed_org_names = {_normalize_text(item.name): item.item_id for item in seed_orgs}

    nodes: dict[str, IntelGraphNode] = {}
    edges: dict[str, IntelGraphEdge] = {}

    def add_node(node: IntelGraphNode) -> None:
        if node.node_id not in nodes:
            nodes[node.node_id] = node

    def add_edge(
        source_id: str,
        target_id: str,
        relation: str,
        *,
        weight: float = 1.0,
        notes: list[str] | None = None,
    ) -> None:
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

    for reg in regions:
        add_node(
            IntelGraphNode(
                node_id=f"region:{reg.id}",
                kind="region",
                region_id=reg.id,
                label=reg.name,
                subtitle=reg.summary,
                notes=reg.notes,
            )
        )

    for org in seed_orgs:
        add_node(
            IntelGraphNode(
                node_id=org.item_id,
                kind="organization",
                region_id=org.region_id,
                label=org.name,
                subtitle=", ".join(org.categories[:3]) or "Organization",
                score=org.organization_score,
                url=org.website,
                address=org.address,
                notes=org.notes,
            )
        )
        add_edge(
            f"region:{org.region_id}",
            org.item_id,
            "region_watch",
            weight=org.organization_score,
        )

    for biz in snapshot.businesses:
        if region_ids and biz.region_id not in region_ids:
            continue
        org_id = seed_org_names.get(_normalize_text(biz.name))
        if not org_id:
            continue
        add_node(
            IntelGraphNode(
                node_id=biz.item_id,
                kind="business",
                region_id=biz.region_id,
                label=biz.name,
                subtitle=biz.category,
                score=biz.lead_score,
                url=biz.website or biz.source_url,
                address=biz.address,
                notes=biz.notes,
            )
        )
        add_edge(org_id, biz.item_id, "open_map_business", weight=biz.lead_score)

    for con in snapshot.contacts:
        if region_ids and con.region_id not in region_ids:
            continue
        org_id = seed_org_names.get(_normalize_text(con.organization))
        if not org_id:
            continue
        add_node(
            IntelGraphNode(
                node_id=con.item_id,
                kind="contact",
                region_id=con.region_id,
                label=con.name,
                subtitle=" | ".join(
                    part for part in [con.title or "", con.organization] if part
                ),
                score=con.contact_score,
                url=con.website or con.source_url,
                address=con.address,
                notes=con.notes,
            )
        )
        add_edge(org_id, con.item_id, "public_contact", weight=con.contact_score)

    for ns in snapshot.news:
        if region_ids and ns.region_id not in region_ids:
            continue
        related = [
            seed_org_names[_normalize_text(name)]
            for name in ns.organizations
            if _normalize_text(name) in seed_org_names
        ]
        if not related:
            continue
        add_node(
            IntelGraphNode(
                node_id=ns.item_id,
                kind="news",
                region_id=ns.region_id,
                label=ns.title,
                subtitle=ns.source_name,
                score=ns.signal_score,
                url=ns.source_url,
                address=ns.address_hint,
                notes=ns.notes,
            )
        )
        for org_id in related:
            add_edge(ns.item_id, org_id, "news_mentions_org", weight=ns.signal_score)

    known_business_addresses = {
        _normalize_address(node.address)
        for node in nodes.values()
        if node.kind == "business"
        and node.address
        and node.address != "Address not provided"
    }

    for ps in snapshot.permits:
        if region_ids and ps.region_id not in region_ids:
            continue
        related_org_ids = [
            seed_org_names[name_key]
            for name_key in [
                _normalize_text(name)
                for name in _permit_related_organizations(ps.notes)
            ]
            if name_key in seed_org_names
        ]
        address_key = _normalize_address(ps.address)
        if (
            not related_org_ids
            and address_key not in known_business_addresses
            and ps.signal_score < 70
        ):
            continue
        add_node(
            IntelGraphNode(
                node_id=ps.item_id,
                kind="permit",
                region_id=ps.region_id,
                label=ps.address,
                subtitle=f"{ps.county} | {ps.permit_type}",
                score=ps.signal_score,
                url=ps.source_url,
                address=ps.address,
                notes=ps.notes,
            )
        )
        for org_id in related_org_ids:
            add_edge(ps.item_id, org_id, "permit_names_org", weight=ps.signal_score)

    permit_nodes = [
        node
        for node in nodes.values()
        if node.kind == "permit"
        and node.address
        and node.address != "Address not provided"
    ]
    permit_by_address = {
        _normalize_address(node.address): node.node_id for node in permit_nodes
    }

    for node in list(nodes.values()):
        if node.kind == "business":
            permit_id = permit_by_address.get(_normalize_address(node.address))
            if permit_id:
                add_edge(
                    node.node_id,
                    permit_id,
                    "same_address",
                    weight=max(node.score, nodes[permit_id].score),
                )
        elif node.kind == "news" and node.address:
            news_address = _normalize_address(node.address)
            if not news_address:
                continue
            for normalized_permit_address, permit_id in permit_by_address.items():
                if news_address and (
                    news_address in normalized_permit_address
                    or normalized_permit_address in news_address
                ):
                    add_edge(
                        node.node_id,
                        permit_id,
                        "same_address_hint",
                        weight=max(node.score, nodes[permit_id].score),
                    )

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
        nodes = {
            node_id: node for node_id, node in nodes.items() if node_id in neighbor_ids
        }

    graph = IntelGraph(
        region=region,
        focus_node_id=focus_node_id,
        nodes=sorted(
            nodes.values(),
            key=lambda item: (item.kind, -item.score, item.label.lower()),
        ),
        edges=sorted(
            edges.values(),
            key=lambda item: (
                -item.weight,
                item.relation,
                item.source_id,
                item.target_id,
            ),
        ),
        notes=[
            "Graph edges are built from exact-name organization matches, public-contact associations, organization mentions in news, permit-linked organization notes, and address overlaps.",
            "This is an intelligence graph, not a truth graph. Human review is still required before action.",
        ],
    )
    return graph
