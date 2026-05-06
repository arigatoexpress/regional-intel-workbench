from __future__ import annotations

import asyncio

import httpx

from app.models import KeyStat, PoolOpportunity, ProtocolSnapshot
from app.utils import (
    confidence_from_history,
    forecast_volume_from_history,
    format_number_compact,
    format_usd_compact,
    make_pool_key,
    normalize_fullsail_prediction_usd,
    normalize_fullsail_vote_power,
    parse_metric_or_zero,
)

BASE_URL = "https://app.fullsail.finance"


async def fetch_fullsail_snapshot() -> ProtocolSnapshot:
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        pools_response, config_response, stats_response = await asyncio.gather(
            client.get(
                "/api/pools/voting",
                params={"page": 0, "page_size": 250, "account_address": ""},
            ),
            client.get("/api/config"),
            client.get("/api/stats/overview"),
        )
        pools_response.raise_for_status()
        config_response.raise_for_status()
        stats_response.raise_for_status()

    pools_payload = pools_response.json()
    config = config_response.json().get("config", {})
    stats = stats_response.json()
    current_epoch = config.get("current_epoch", {})
    overview = stats.get("overview", {})
    statistics = stats.get("statistics", {})
    supply = stats.get("supply", {})

    total_vote_power = normalize_fullsail_vote_power(config.get("global_voting_power"))
    pools: list[PoolOpportunity] = []

    for raw_pool in pools_payload.get("pools", []):
        pool_meta = raw_pool.get("pool", {})
        dynamic_stats = pool_meta.get("dinamic_stats", {})
        weekly_volume = parse_metric_or_zero(
            str(
                raw_pool.get("weekly_volume_usd")
                or dynamic_stats.get("volume_usd_7d")
                or "0"
            )
        )
        predicted_volume = normalize_fullsail_prediction_usd(
            raw_pool.get("predicted_volume_usd"), weekly_volume
        )
        confidence = confidence_from_history(raw_pool.get("volume_history", []))
        forecast_volume, forecast_low, forecast_high = forecast_volume_from_history(
            raw_pool.get("volume_history", []),
            weekly_volume,
            predicted_volume,
        )
        apr = float(raw_pool.get("estimated_apr") or 0)
        current_votes = (
            normalize_fullsail_vote_power(raw_pool.get("total_voting_power")) or 0.0
        )
        total_rewards = parse_metric_or_zero(
            str(raw_pool.get("voting_fees_usd") or "0")
        )
        vote_share = (
            (current_votes / total_vote_power * 100) if total_vote_power else None
        )
        ranking_score = apr * (confidence if confidence is not None else 1.0)

        pools.append(
            PoolOpportunity(
                rank=0,
                pool_key=make_pool_key(pool_meta.get("name"), pool_meta.get("fee")),
                name=pool_meta.get("name") or "Unknown pool",
                fee_tier=str(pool_meta.get("fee") or ""),
                tvl_usd=parse_metric_or_zero(str(dynamic_stats.get("tvl") or "0")),
                fees_usd=total_rewards,
                incentives_usd=0.0,
                total_rewards_usd=total_rewards,
                apr=apr,
                current_votes=current_votes,
                vote_share_pct=vote_share,
                weekly_volume_usd=weekly_volume,
                predicted_volume_usd=predicted_volume,
                forecast_volume_usd=forecast_volume,
                forecast_volume_low_usd=forecast_low,
                forecast_volume_high_usd=forecast_high,
                prediction_confidence=confidence,
                ranking_score=ranking_score,
            )
        )

    pools.sort(
        key=lambda pool: (pool.ranking_score, pool.total_rewards_usd or 0.0),
        reverse=True,
    )
    for index, pool in enumerate(pools, start=1):
        pool.rank = index

    avg_voting_apr = float(statistics.get("avg_voting_apr") or 0.0)
    ve_sail_supply = normalize_fullsail_vote_power(supply.get("vesail_supply"))
    key_stats = [
        KeyStat(label="Epoch", value=str(current_epoch.get("epoch_count") or "--")),
        KeyStat(
            label="Voting power",
            value=f"{format_number_compact(total_vote_power)} veSAIL",
        ),
        KeyStat(label="Avg voting APR", value=f"{avg_voting_apr:.2f}%"),
        KeyStat(
            label="Fee rewards",
            value=format_usd_compact(
                parse_metric_or_zero(str(overview.get("fee_rewards_usd") or "0"))
            ),
        ),
        KeyStat(
            label="Daily volume",
            value=format_usd_compact(
                parse_metric_or_zero(str(overview.get("daily_volume_usd") or "0"))
            ),
        ),
        KeyStat(
            label="TVL",
            value=format_usd_compact(
                parse_metric_or_zero(str(statistics.get("tvl_usd") or "0"))
            ),
        ),
        KeyStat(label="veSAIL supply", value=format_number_compact(ve_sail_supply)),
        KeyStat(
            label="Passive fee APR",
            value=f"{float(current_epoch.get('passive_fee_apr') or 0):.2f}%",
        ),
    ]

    notes = [
        "Full Sail uses its public /api/pools/voting endpoint.",
        "Unlike Blackhole and Supernova, Full Sail is prediction-based: you choose a pool and forecast the next epoch's volume.",
        "Prediction confidence is estimated from recent predicted-vs-actual volume history when enough history is available.",
    ]
    if pools:
        notes.append(f"Top pool right now: {pools[0].name}.")

    return ProtocolSnapshot(
        id="fullsail",
        name="Full Sail",
        chain="Sui",
        vote_power_symbol="veSAIL",
        ranking_basis="Ranked by estimated APR, with an added confidence penalty when recent volume predictions have been inaccurate.",
        source="Full Sail public API",
        epoch_label=f"Epoch #{current_epoch.get('epoch_count')}"
        if current_epoch.get("epoch_count") is not None
        else None,
        countdown=None,
        ends_at_ms=current_epoch.get("end_time"),
        key_stats=key_stats,
        notes=notes,
        pools=pools,
    )
