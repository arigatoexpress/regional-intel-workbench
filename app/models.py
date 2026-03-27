from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProtocolId = Literal["blackhole", "supernova", "fullsail"]


class KeyStat(BaseModel):
    label: str
    value: str


class PoolOpportunity(BaseModel):
    rank: int
    pool_key: str
    name: str
    fee_tier: str | None = None
    tvl_usd: float | None = None
    fees_usd: float | None = None
    incentives_usd: float | None = None
    total_rewards_usd: float | None = None
    apr: float | None = None
    current_votes: float | None = None
    vote_share_pct: float | None = None
    weekly_volume_usd: float | None = None
    predicted_volume_usd: float | None = None
    forecast_volume_usd: float | None = None
    forecast_volume_low_usd: float | None = None
    forecast_volume_high_usd: float | None = None
    prediction_confidence: float | None = None
    expected_rewards_usd: float | None = None
    expected_apr: float | None = None
    historical_avg_apr: float | None = None
    historical_avg_rewards_usd: float | None = None
    history_points: int = 0
    stability_score: float | None = None
    model_confidence: float | None = None
    momentum_pct: float | None = None
    analysis_score: float | None = None
    ranking_score: float
    source_page: int | None = None


class ProtocolSnapshot(BaseModel):
    id: ProtocolId
    name: str
    chain: str
    vote_power_symbol: str
    ranking_basis: str
    analysis_basis: str | None = None
    source: str
    epoch_label: str | None = None
    countdown: str | None = None
    ends_at_ms: int | None = None
    history_window_days: int | None = None
    history_samples: int = 0
    key_stats: list[KeyStat] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    pools: list[PoolOpportunity] = Field(default_factory=list)
    error: str | None = None


class StrategyAllocation(BaseModel):
    rank: int
    pool_key: str
    name: str
    fee_tier: str | None = None
    allocation_votes: float
    allocation_pct: float
    expected_weekly_payout_usd: float
    expected_capture_pct: float | None = None
    suggested_prediction_usd: float | None = None
    prediction_range_low_usd: float | None = None
    prediction_range_high_usd: float | None = None
    current_apr: float | None = None
    expected_apr: float | None = None
    history_points: int = 0
    stability_score: float | None = None
    model_confidence: float | None = None


class ProtocolStrategy(BaseModel):
    protocol_id: ProtocolId
    protocol_name: str
    strategy_mode: str = "allocation"
    preference_label: str | None = None
    vote_power: float
    lookback_days: int
    history_samples: int = 0
    expected_weekly_payout_usd: float = 0.0
    best_single_pool_name: str | None = None
    best_single_pool_payout_usd: float | None = None
    improvement_vs_best_single_pct: float | None = None
    max_recommended_pools: int = 0
    allocations: list[StrategyAllocation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StrategySnapshot(BaseModel):
    updated_at: str
    protocols: list[ProtocolStrategy] = Field(default_factory=list)


class DashboardSnapshot(BaseModel):
    updated_at: str
    cache_ttl_seconds: int
    protocols: list[ProtocolSnapshot]
    global_notes: list[str]
