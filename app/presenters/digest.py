from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import DashboardSnapshot, PoolOpportunity, ProtocolSnapshot, ProtocolStrategy, StrategyAllocation, StrategySnapshot
from app.utils import format_number_compact, format_usd_compact


def build_digest_payload(
    snapshot: DashboardSnapshot,
    strategy: StrategySnapshot,
    *,
    timezone: str = "UTC",
    style: str = "text",
) -> dict[str, object]:
    strategy_index = {item.protocol_id: item for item in strategy.protocols}
    sections = [
        _build_protocol_section(protocol, strategy_index.get(protocol.id))
        for protocol in snapshot.protocols
    ]
    as_of = _format_as_of(snapshot.updated_at, timezone)
    message = _render_digest_text(sections, as_of=as_of, compact=style == "telegram")
    return {
        "updated_at": snapshot.updated_at,
        "as_of": as_of,
        "style": style,
        "sections": sections,
        "message": message,
    }


def _build_protocol_section(
    protocol: ProtocolSnapshot,
    strategy: ProtocolStrategy | None,
) -> dict[str, object]:
    leader = protocol.pools[0] if protocol.pools else None
    headline = f"{protocol.name} ({protocol.chain})"

    if protocol.error:
        return {
            "protocol_id": protocol.id,
            "headline": headline,
            "epoch_label": protocol.epoch_label,
            "countdown": protocol.countdown,
            "action": "Refresh failed",
            "details": [protocol.error],
        }

    if strategy and strategy.vote_power > 0 and strategy.allocations:
        if strategy.strategy_mode == "prediction":
            return _build_prediction_section(protocol, strategy, leader, headline)
        return _build_allocation_section(protocol, strategy, leader, headline)

    return _build_watch_section(protocol, leader, headline)


def _build_allocation_section(
    protocol: ProtocolSnapshot,
    strategy: ProtocolStrategy,
    leader: PoolOpportunity | None,
    headline: str,
) -> dict[str, object]:
    allocations = strategy.allocations
    action = f"Vote {_format_split(allocations)}"
    details = [
        f"Expected payout {format_usd_compact(strategy.expected_weekly_payout_usd)} per epoch at {format_number_compact(strategy.vote_power, 1)} {protocol.vote_power_symbol}.",
    ]
    if leader:
        details.append(
            f"Current leader {leader.name} at {_format_percent(leader.expected_apr or leader.apr)} model APR."
        )
    if strategy.improvement_vs_best_single_pct is not None:
        details.append(
            f"Lift vs best single {_format_signed_percent(strategy.improvement_vs_best_single_pct)}."
        )
    return {
        "protocol_id": protocol.id,
        "headline": headline,
        "epoch_label": protocol.epoch_label,
        "countdown": protocol.countdown,
        "action": action,
        "details": details,
    }


def _build_prediction_section(
    protocol: ProtocolSnapshot,
    strategy: ProtocolStrategy,
    leader: PoolOpportunity | None,
    headline: str,
) -> dict[str, object]:
    allocation = strategy.allocations[0]
    prediction = format_usd_compact(allocation.suggested_prediction_usd)
    action = f"Predict {allocation.name} next-epoch volume at {prediction}"
    details = [
        f"Forecast band {format_usd_compact(allocation.prediction_range_low_usd)} to {format_usd_compact(allocation.prediction_range_high_usd)}.",
        f"Expected capture {format_usd_compact(strategy.expected_weekly_payout_usd)} per epoch at {format_number_compact(strategy.vote_power, 1)} {protocol.vote_power_symbol}.",
    ]
    if strategy.best_single_pool_name and strategy.best_single_pool_name != allocation.name:
        details.append(f"Unrestricted leader {strategy.best_single_pool_name}.")
    elif leader:
        details.append(f"Current leader {leader.name}.")
    return {
        "protocol_id": protocol.id,
        "headline": headline,
        "epoch_label": protocol.epoch_label,
        "countdown": protocol.countdown,
        "action": action,
        "details": details,
    }


def _build_watch_section(
    protocol: ProtocolSnapshot,
    leader: PoolOpportunity | None,
    headline: str,
) -> dict[str, object]:
    if protocol.id == "fullsail":
        preferred = _preferred_fullsail_watch(protocol.pools) or leader
        if preferred:
            action = (
                f"Watch {preferred.name} at {format_usd_compact(preferred.forecast_volume_usd or preferred.predicted_volume_usd)} "
                "next-epoch volume."
            )
            details = [
                f"Forecast band {format_usd_compact(preferred.forecast_volume_low_usd)} to {format_usd_compact(preferred.forecast_volume_high_usd)}.",
                "Set veSAIL vote power to turn the watchlist into a prediction plan.",
            ]
        else:
            action = "No Full Sail watchlist available."
            details = ["Refresh the snapshot once the source API is reachable."]
    else:
        top_names = ", ".join(pool.name for pool in protocol.pools[:3]) if protocol.pools else "No pools"
        if leader:
            action = f"Watch {leader.name}."
            details = [
                f"Top pools: {top_names}.",
                f"Set {protocol.vote_power_symbol} to size the split.",
            ]
        else:
            action = "No watchlist available."
            details = ["Refresh the snapshot once the source is reachable."]

    return {
        "protocol_id": protocol.id,
        "headline": headline,
        "epoch_label": protocol.epoch_label,
        "countdown": protocol.countdown,
        "action": action,
        "details": details,
    }


def _preferred_fullsail_watch(pools: list[PoolOpportunity]) -> PoolOpportunity | None:
    for pool in pools:
        if "IKA" in (pool.name or "").upper():
            return pool
    return None


def _format_split(allocations: list[StrategyAllocation]) -> str:
    return ", ".join(f"{allocation.allocation_pct:.1f}% {allocation.name}" for allocation in allocations)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}%"


def _format_signed_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _format_as_of(updated_at: str, timezone: str) -> str:
    timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    try:
        localized = timestamp.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        localized = timestamp
    return localized.strftime("%B %d, %Y %I:%M %p %Z")


def _render_digest_text(
    sections: list[dict[str, object]],
    *,
    as_of: str,
    compact: bool,
) -> str:
    lines = ["ve Vote Digest", f"As of {as_of}"]
    for section in sections:
        lines.append("")
        heading = str(section["headline"])
        if section.get("epoch_label"):
            heading = f"{heading} | {section['epoch_label']}"
        if section.get("countdown"):
            heading = f"{heading} | {section['countdown']}"
        lines.append(heading)
        lines.append(f"- {section['action']}")
        details = section.get("details", [])
        if not isinstance(details, list):
            details = []
        if compact:
            if details:
                lines.append(f"- {details[0]}")
            continue
        for detail in details:
            lines.append(f"- {detail}")
    return "\n".join(lines)
