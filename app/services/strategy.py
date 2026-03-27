from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from app.models import (
    DashboardSnapshot,
    KeyStat,
    PoolOpportunity,
    ProtocolSnapshot,
    ProtocolStrategy,
    StrategyAllocation,
    StrategySnapshot,
)
from app.utils import clamp, coefficient_of_variation, format_number_compact


LOOKBACK_DAYS = 30
SHORT_WINDOW = 3
LONG_WINDOW = 8
MAX_RECOMMENDED_POOLS = 5
FULLSAIL_PREFERRED_KEYWORDS = ("IKA",)


@dataclass(frozen=True)
class PoolObservation:
    timestamp: datetime
    apr: float | None
    total_rewards_usd: float | None
    current_votes: float | None
    weekly_volume_usd: float | None
    predicted_volume_usd: float | None
    prediction_confidence: float | None


@dataclass(frozen=True)
class CandidatePool:
    pool: PoolOpportunity
    expected_rewards_usd: float
    effective_votes: float


def enrich_dashboard_snapshot(
    snapshot: DashboardSnapshot,
    history_records: list[dict[str, Any]],
    lookback_days: int = LOOKBACK_DAYS,
) -> DashboardSnapshot:
    history_index, protocol_samples = _build_history_index(history_records)
    snapshot.global_notes.append(
        f"Historical model uses the last {lookback_days} days of locally stored snapshots. Confidence improves as more history accumulates."
    )

    for protocol in snapshot.protocols:
        protocol.history_window_days = lookback_days
        protocol.history_samples = protocol_samples.get(protocol.id, 0)
        if protocol.id == "fullsail":
            protocol.analysis_basis = (
                "Full Sail is modeled as a prediction market. Expected rewards blend live rewards with "
                "prediction accuracy, volume trend, and a next-epoch volume forecast."
            )
        else:
            protocol.analysis_basis = (
                "Expected rewards blend live rewards with trailing local history, short-term momentum, "
                "and confidence penalties for unstable pools."
            )
        if not protocol.error:
            protocol.key_stats.append(
                KeyStat(label="History window", value=f"{protocol.history_samples} snaps / {lookback_days}d")
            )

        protocol_history = history_index.get(protocol.id, {})
        for pool in protocol.pools:
            observations = protocol_history.get(pool.pool_key, [])
            _apply_pool_history(pool, observations)

        if protocol.history_samples < 3:
            protocol.notes.append("Historical model is still warming up locally for this protocol.")
        else:
            protocol.notes.append(
                f"Historical model currently uses {protocol.history_samples} stored snapshots from the last {lookback_days} days."
            )

    return snapshot


def build_strategy_snapshot(
    snapshot: DashboardSnapshot,
    vote_powers: dict[str, float],
    lookback_days: int = LOOKBACK_DAYS,
) -> StrategySnapshot:
    strategies = [
        recommend_protocol_strategy(
            protocol=protocol,
            vote_power=vote_powers.get(protocol.id, 0.0),
            lookback_days=lookback_days,
        )
        for protocol in snapshot.protocols
        if not protocol.error
    ]
    return StrategySnapshot(updated_at=snapshot.updated_at, protocols=strategies)


def recommend_protocol_strategy(
    protocol: ProtocolSnapshot,
    vote_power: float,
    lookback_days: int = LOOKBACK_DAYS,
) -> ProtocolStrategy:
    if protocol.id == "fullsail":
        return recommend_fullsail_strategy(protocol=protocol, vote_power=vote_power, lookback_days=lookback_days)

    base_notes = [
        "Objective: maximize expected weekly payout from your vote power using adjusted rewards and current vote depth.",
        "Zero-vote pools receive a conservative vote-depth floor so the optimizer does not overfit dust allocations.",
    ]

    if vote_power <= 0:
        return ProtocolStrategy(
            protocol_id=protocol.id,
            protocol_name=protocol.name,
            vote_power=0.0,
            lookback_days=lookback_days,
            history_samples=protocol.history_samples,
            max_recommended_pools=MAX_RECOMMENDED_POOLS,
            notes=["Enter your vote power to generate a sized weekly strategy.", *base_notes],
        )

    candidates = _build_candidates(protocol, vote_power)
    if not candidates:
        return ProtocolStrategy(
            protocol_id=protocol.id,
            protocol_name=protocol.name,
            vote_power=vote_power,
            lookback_days=lookback_days,
            history_samples=protocol.history_samples,
            max_recommended_pools=MAX_RECOMMENDED_POOLS,
            notes=["No eligible pools had enough reward and vote data to size a strategy.", *base_notes],
        )

    best_single = max(
        candidates,
        key=lambda item: _expected_payout(item.expected_rewards_usd, item.effective_votes, vote_power),
    )
    best_single_payout = _expected_payout(best_single.expected_rewards_usd, best_single.effective_votes, vote_power)

    allocations = _optimize_allocations(candidates, vote_power)
    min_allocation = max(vote_power * 0.03, 1.0)
    kept = [item for item in allocations if item[1] >= min_allocation]
    if not kept:
        kept = [max(allocations, key=lambda item: item[1])]
    if len(kept) > MAX_RECOMMENDED_POOLS:
        kept = sorted(kept, key=lambda item: item[1], reverse=True)[:MAX_RECOMMENDED_POOLS]
    if len(kept) != len(allocations):
        allocations = _optimize_allocations([item[0] for item in kept], vote_power)
    else:
        allocations = kept

    strategy_allocations: list[StrategyAllocation] = []
    expected_total_payout = 0.0
    for rank, (candidate, allocation_votes) in enumerate(
        sorted(allocations, key=lambda item: item[1], reverse=True),
        start=1,
    ):
        payout = _expected_payout(candidate.expected_rewards_usd, candidate.effective_votes, allocation_votes)
        expected_total_payout += payout
        strategy_allocations.append(
            StrategyAllocation(
                rank=rank,
                pool_key=candidate.pool.pool_key,
                name=candidate.pool.name,
                fee_tier=candidate.pool.fee_tier,
                allocation_votes=allocation_votes,
                allocation_pct=(allocation_votes / vote_power * 100) if vote_power else 0.0,
                expected_weekly_payout_usd=payout,
                expected_capture_pct=(
                    payout / candidate.expected_rewards_usd * 100
                    if candidate.expected_rewards_usd > 0
                    else None
                ),
                current_apr=candidate.pool.apr,
                expected_apr=candidate.pool.expected_apr,
                history_points=candidate.pool.history_points,
                stability_score=candidate.pool.stability_score,
                model_confidence=candidate.pool.model_confidence,
            )
        )

    improvement = None
    if best_single_payout > 0:
        improvement = (expected_total_payout - best_single_payout) / best_single_payout * 100

    if expected_total_payout <= best_single_payout:
        strategy_allocations = [
            StrategyAllocation(
                rank=1,
                pool_key=best_single.pool.pool_key,
                name=best_single.pool.name,
                fee_tier=best_single.pool.fee_tier,
                allocation_votes=vote_power,
                allocation_pct=100.0,
                expected_weekly_payout_usd=best_single_payout,
                expected_capture_pct=(
                    best_single_payout / best_single.expected_rewards_usd * 100
                    if best_single.expected_rewards_usd > 0
                    else None
                ),
                current_apr=best_single.pool.apr,
                expected_apr=best_single.pool.expected_apr,
                history_points=best_single.pool.history_points,
                stability_score=best_single.pool.stability_score,
                model_confidence=best_single.pool.model_confidence,
            )
        ]
        expected_total_payout = best_single_payout
        improvement = 0.0

    notes = [
        f"Using {protocol.history_samples} stored snapshots from the last {lookback_days} days.",
        f"Best single-pool fallback is {best_single.pool.name}.",
        f"Recommended split uses {len(strategy_allocations)} pool(s) and {format_number_compact(vote_power)} {protocol.vote_power_symbol}.",
        *base_notes,
    ]

    return ProtocolStrategy(
        protocol_id=protocol.id,
        protocol_name=protocol.name,
        strategy_mode="allocation",
        vote_power=vote_power,
        lookback_days=lookback_days,
        history_samples=protocol.history_samples,
        expected_weekly_payout_usd=expected_total_payout,
        best_single_pool_name=best_single.pool.name,
        best_single_pool_payout_usd=best_single_payout,
        improvement_vs_best_single_pct=improvement,
        max_recommended_pools=MAX_RECOMMENDED_POOLS,
        allocations=strategy_allocations,
        notes=notes,
    )


def recommend_fullsail_strategy(
    protocol: ProtocolSnapshot,
    vote_power: float,
    lookback_days: int = LOOKBACK_DAYS,
) -> ProtocolStrategy:
    preference_label = "IKA-only hold preference"
    base_notes = [
        "Full Sail is modeled as a prediction market, so the main output is the next-epoch volume forecast for the chosen pool.",
        f"Current preference restricts Full Sail to pools containing {', '.join(FULLSAIL_PREFERRED_KEYWORDS)} when available.",
    ]

    if vote_power <= 0:
        return ProtocolStrategy(
            protocol_id=protocol.id,
            protocol_name=protocol.name,
            strategy_mode="prediction",
            preference_label=preference_label,
            vote_power=0.0,
            lookback_days=lookback_days,
            history_samples=protocol.history_samples,
            max_recommended_pools=1,
            notes=["Enter your veSAIL balance to generate a prediction plan.", *base_notes],
        )

    candidates = _build_candidates(protocol, vote_power)
    if not candidates:
        return ProtocolStrategy(
            protocol_id=protocol.id,
            protocol_name=protocol.name,
            strategy_mode="prediction",
            preference_label=preference_label,
            vote_power=vote_power,
            lookback_days=lookback_days,
            history_samples=protocol.history_samples,
            max_recommended_pools=1,
            notes=["No eligible Full Sail pools had enough data to build a prediction plan.", *base_notes],
        )

    unrestricted_best = max(candidates, key=lambda item: _fullsail_candidate_score(item, vote_power))
    preferred_candidates = [item for item in candidates if _is_fullsail_preferred_pool(item.pool)]
    chosen = max(
        preferred_candidates or candidates,
        key=lambda item: _fullsail_candidate_score(item, vote_power),
    )

    payout = _expected_payout(chosen.expected_rewards_usd, chosen.effective_votes, vote_power)
    suggested_prediction = (
        chosen.pool.forecast_volume_usd
        or chosen.pool.predicted_volume_usd
        or chosen.pool.weekly_volume_usd
    )
    prediction_low = chosen.pool.forecast_volume_low_usd
    prediction_high = chosen.pool.forecast_volume_high_usd

    notes = [
        f"Using {protocol.history_samples} stored snapshots from the last {lookback_days} days.",
        f"Recommended Full Sail pool: {chosen.pool.name}.",
        (
            f"Suggested next-epoch volume prediction is {format_number_compact(suggested_prediction)} USD"
            if suggested_prediction
            else "Suggested next-epoch volume prediction is unavailable because the pool lacks enough history."
        ),
        *base_notes,
    ]
    if preferred_candidates:
        notes.append("The unrestricted model may rank another pool higher, but the strategy stays inside your IKA-only constraint.")
    if unrestricted_best.pool.pool_key != chosen.pool.pool_key:
        notes.append(f"Unrestricted model leader is {unrestricted_best.pool.name}.")

    allocation = StrategyAllocation(
        rank=1,
        pool_key=chosen.pool.pool_key,
        name=chosen.pool.name,
        fee_tier=chosen.pool.fee_tier,
        allocation_votes=vote_power,
        allocation_pct=100.0,
        expected_weekly_payout_usd=payout,
        expected_capture_pct=(payout / chosen.expected_rewards_usd * 100) if chosen.expected_rewards_usd > 0 else None,
        suggested_prediction_usd=suggested_prediction,
        prediction_range_low_usd=prediction_low,
        prediction_range_high_usd=prediction_high,
        current_apr=chosen.pool.apr,
        expected_apr=chosen.pool.expected_apr,
        history_points=chosen.pool.history_points,
        stability_score=chosen.pool.stability_score,
        model_confidence=chosen.pool.model_confidence,
    )

    unrestricted_best_payout = _expected_payout(
        unrestricted_best.expected_rewards_usd,
        unrestricted_best.effective_votes,
        vote_power,
    )
    improvement = None
    if unrestricted_best_payout > 0:
        improvement = (payout - unrestricted_best_payout) / unrestricted_best_payout * 100

    return ProtocolStrategy(
        protocol_id=protocol.id,
        protocol_name=protocol.name,
        strategy_mode="prediction",
        preference_label=preference_label,
        vote_power=vote_power,
        lookback_days=lookback_days,
        history_samples=protocol.history_samples,
        expected_weekly_payout_usd=payout,
        best_single_pool_name=unrestricted_best.pool.name,
        best_single_pool_payout_usd=unrestricted_best_payout,
        improvement_vs_best_single_pct=improvement,
        max_recommended_pools=1,
        allocations=[allocation],
        notes=notes,
    )


def _build_history_index(
    history_records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, list[PoolObservation]]], dict[str, int]]:
    pool_history: dict[str, dict[str, list[PoolObservation]]] = {}
    protocol_samples: dict[str, int] = {}

    for record in history_records:
        updated_at = record.get("updated_at")
        if not updated_at:
            continue
        timestamp = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")).astimezone(UTC)
        for protocol in record.get("protocols", []):
            protocol_id = protocol.get("id")
            if not protocol_id:
                continue
            pool_bucket = pool_history.setdefault(protocol_id, {})
            raw_pools = protocol.get("pools", [])
            if not raw_pools:
                continue
            protocol_samples[protocol_id] = protocol_samples.get(protocol_id, 0) + 1
            for raw_pool in raw_pools:
                pool_key = raw_pool.get("pool_key")
                if not pool_key:
                    continue
                pool_bucket.setdefault(pool_key, []).append(
                    PoolObservation(
                        timestamp=timestamp,
                        apr=_positive_or_none(raw_pool.get("apr")),
                        total_rewards_usd=_positive_or_none(raw_pool.get("total_rewards_usd")),
                        current_votes=_positive_or_none(raw_pool.get("current_votes")),
                        weekly_volume_usd=_positive_or_none(raw_pool.get("weekly_volume_usd")),
                        predicted_volume_usd=_positive_or_none(raw_pool.get("predicted_volume_usd")),
                        prediction_confidence=_bounded_or_none(raw_pool.get("prediction_confidence")),
                    )
                )

    return pool_history, protocol_samples


def _apply_pool_history(pool: PoolOpportunity, observations: list[PoolObservation]) -> None:
    apr_values = [value for value in (_positive_or_none(item.apr) for item in observations) if value is not None]
    reward_values = [
        value for value in (_positive_or_none(item.total_rewards_usd) for item in observations) if value is not None
    ]
    vote_values = [value for value in (_positive_or_none(item.current_votes) for item in observations) if value is not None]

    history_points = len(observations)
    history_weight = clamp(history_points / 8.0, 0.0, 1.0)
    sample_score = clamp(history_points / 6.0, 0.0, 1.0)

    historical_avg_apr = mean(apr_values) if apr_values else None
    historical_avg_rewards = mean(reward_values) if reward_values else None

    reward_cv = coefficient_of_variation(reward_values)
    apr_cv = coefficient_of_variation(apr_values)
    vote_cv = coefficient_of_variation(vote_values)
    volatility_components = [
        clamp(component, 0.0, 1.5)
        for component in (reward_cv, apr_cv, vote_cv)
        if component is not None
    ]
    raw_stability = 1.0 - mean(volatility_components) if volatility_components else 0.55
    stability_score = clamp((0.45 + 0.55 * raw_stability) * (0.55 + 0.45 * sample_score), 0.35, 0.98)

    confidence_components = [0.35 + 0.65 * sample_score, stability_score]
    if pool.prediction_confidence is not None:
        confidence_components.append(clamp(pool.prediction_confidence, 0.35, 1.0))
    model_confidence = clamp(mean(confidence_components), 0.35, 0.98)

    momentum = _compute_momentum(reward_values or apr_values)
    volume_factor = _volume_forecast_factor(pool)

    current_rewards = _positive_or_none(pool.total_rewards_usd)
    reward_baseline = current_rewards or historical_avg_rewards or 0.0
    if current_rewards and historical_avg_rewards:
        reward_baseline = current_rewards * (1.0 - 0.45 * history_weight) + historical_avg_rewards * (0.45 * history_weight)

    confidence_factor = 0.75 + 0.35 * model_confidence
    momentum_factor = clamp(1.0 + momentum * 0.35, 0.8, 1.2)
    expected_rewards = reward_baseline * confidence_factor * momentum_factor * volume_factor
    if current_rewards:
        expected_rewards = clamp(expected_rewards, current_rewards * 0.55, max(current_rewards * 1.6, current_rewards))
    elif historical_avg_rewards:
        expected_rewards = historical_avg_rewards * confidence_factor * momentum_factor * volume_factor
    else:
        expected_rewards = 0.0

    current_apr = _positive_or_none(pool.apr)
    expected_apr = current_apr or historical_avg_apr
    if current_apr and historical_avg_apr:
        expected_apr = current_apr * (1.0 - 0.4 * history_weight) + historical_avg_apr * (0.4 * history_weight)
    if expected_apr is not None:
        expected_apr *= clamp(0.85 + 0.3 * model_confidence + momentum * 0.15, 0.7, 1.3)

    effective_votes = max(_positive_or_none(pool.current_votes) or 0.0, 1.0)
    analysis_score = expected_rewards / effective_votes * model_confidence if effective_votes else None

    pool.history_points = history_points
    pool.historical_avg_apr = historical_avg_apr
    pool.historical_avg_rewards_usd = historical_avg_rewards
    pool.stability_score = stability_score
    pool.model_confidence = model_confidence
    pool.momentum_pct = momentum * 100
    pool.expected_rewards_usd = expected_rewards if expected_rewards > 0 else None
    pool.expected_apr = expected_apr
    pool.analysis_score = analysis_score


def _compute_momentum(values: list[float]) -> float:
    if not values:
        return 0.0
    short_average = mean(values[-min(SHORT_WINDOW, len(values)) :])
    long_average = mean(values[-min(LONG_WINDOW, len(values)) :])
    if long_average <= 0:
        return 0.0
    return clamp((short_average - long_average) / long_average, -0.5, 0.5)


def _volume_forecast_factor(pool: PoolOpportunity) -> float:
    weekly_volume = _positive_or_none(pool.weekly_volume_usd)
    predicted_volume = _positive_or_none(pool.predicted_volume_usd)
    if not weekly_volume or not predicted_volume:
        return 1.0
    return clamp(predicted_volume / weekly_volume, 0.75, 1.35)


def _is_fullsail_preferred_pool(pool: PoolOpportunity) -> bool:
    name = (pool.name or "").upper()
    return any(keyword in name for keyword in FULLSAIL_PREFERRED_KEYWORDS)


def _fullsail_candidate_score(candidate: CandidatePool, vote_power: float) -> float:
    payout = _expected_payout(candidate.expected_rewards_usd, candidate.effective_votes, vote_power)
    confidence = candidate.pool.model_confidence or candidate.pool.prediction_confidence or 0.35
    forecast = candidate.pool.forecast_volume_usd or candidate.pool.predicted_volume_usd or candidate.pool.weekly_volume_usd or 0.0
    return payout * (0.8 + 0.2 * confidence) + math.log1p(forecast) * 0.05


def _build_candidates(protocol: ProtocolSnapshot, vote_power: float) -> list[CandidatePool]:
    protocol_votes = sum(max(pool.current_votes or 0.0, 0.0) for pool in protocol.pools)
    zero_vote_floor = max(protocol_votes * 0.0005, vote_power * 0.03, 1.0)
    candidates: list[CandidatePool] = []

    for pool in protocol.pools:
        rewards = _positive_or_none(pool.expected_rewards_usd) or _positive_or_none(pool.total_rewards_usd)
        if not rewards:
            continue
        current_votes = _positive_or_none(pool.current_votes) or 0.0
        effective_votes = current_votes if current_votes > 0 else zero_vote_floor
        candidates.append(
            CandidatePool(
                pool=pool,
                expected_rewards_usd=rewards,
                effective_votes=effective_votes,
            )
        )

    return candidates


def _optimize_allocations(candidates: list[CandidatePool], vote_power: float) -> list[tuple[CandidatePool, float]]:
    if vote_power <= 0 or not candidates:
        return []
    if len(candidates) == 1:
        return [(candidates[0], vote_power)]

    max_derivative = max(
        candidate.expected_rewards_usd / max(candidate.effective_votes, 1e-9) for candidate in candidates
    )
    low = 0.0
    high = max(max_derivative, 1e-9)

    for _ in range(80):
        lam = (low + high) / 2
        total = _total_allocation_for_lambda(candidates, lam)
        if total > vote_power:
            low = lam
        else:
            high = lam

    lam = high
    allocations = [
        (
            candidate,
            max(math.sqrt(candidate.expected_rewards_usd * candidate.effective_votes / lam) - candidate.effective_votes, 0.0),
        )
        for candidate in candidates
    ]
    allocated = sum(amount for _, amount in allocations)
    if allocated <= 0:
        best = max(candidates, key=lambda item: item.expected_rewards_usd / item.effective_votes)
        return [(best, vote_power)]

    residual = vote_power - allocated
    if residual > 0:
        best_index = max(
            range(len(allocations)),
            key=lambda index: _marginal_value(allocations[index][0], allocations[index][1]),
        )
        candidate, amount = allocations[best_index]
        allocations[best_index] = (candidate, amount + residual)

    return [(candidate, amount) for candidate, amount in allocations if amount > 1e-6]


def _total_allocation_for_lambda(candidates: list[CandidatePool], lam: float) -> float:
    if lam <= 0:
        return float("inf")
    total = 0.0
    for candidate in candidates:
        total += max(
            math.sqrt(candidate.expected_rewards_usd * candidate.effective_votes / lam) - candidate.effective_votes,
            0.0,
        )
    return total


def _marginal_value(candidate: CandidatePool, allocation_votes: float) -> float:
    denominator = candidate.effective_votes + allocation_votes
    return candidate.expected_rewards_usd * candidate.effective_votes / max(denominator * denominator, 1e-9)


def _expected_payout(expected_rewards_usd: float, current_votes: float, allocation_votes: float) -> float:
    if expected_rewards_usd <= 0 or allocation_votes <= 0:
        return 0.0
    return expected_rewards_usd * allocation_votes / (current_votes + allocation_votes)


def _positive_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _bounded_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return clamp(number, 0.0, 1.0)
