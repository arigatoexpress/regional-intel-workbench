from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    timezone: str
    default_blackhole_vote_power: float
    default_supernova_vote_power: float
    default_fullsail_vote_power: float
    public_base_url: str | None
    regional_intel_source_timeout: float
    regional_intel_retry_limit: int
    regional_intel_retry_backoff_base: float

    def default_vote_powers(self) -> dict[str, float]:
        return {
            "blackhole": self.default_blackhole_vote_power,
            "supernova": self.default_supernova_vote_power,
            "fullsail": self.default_fullsail_vote_power,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    public_base_url = os.getenv("VE_MONITOR_PUBLIC_BASE_URL")
    return Settings(
        host=os.getenv("VE_MONITOR_HOST", "127.0.0.1"),
        port=_env_int("VE_MONITOR_PORT", 8787),
        timezone=os.getenv("VE_MONITOR_TIMEZONE", "America/Denver"),
        default_blackhole_vote_power=_env_float("VE_MONITOR_BLACKHOLE_VOTE_POWER", 0.0),
        default_supernova_vote_power=_env_float("VE_MONITOR_SUPERNOVA_VOTE_POWER", 0.0),
        default_fullsail_vote_power=_env_float("VE_MONITOR_FULLSAIL_VOTE_POWER", 0.0),
        public_base_url=public_base_url.strip() if public_base_url else None,
        regional_intel_source_timeout=_env_float("REGIONAL_INTEL_SOURCE_TIMEOUT", 25.0),
        regional_intel_retry_limit=max(_env_int("REGIONAL_INTEL_RETRY_LIMIT", 2), 0),
        regional_intel_retry_backoff_base=_env_float("REGIONAL_INTEL_RETRY_BACKOFF_BASE", 0.5),
    )


def resolve_vote_powers(
    *,
    blackhole: float | None,
    supernova: float | None,
    fullsail: float | None,
    settings: Settings | None = None,
) -> dict[str, float]:
    config = settings or get_settings()
    defaults = config.default_vote_powers()

    return {
        "blackhole": max(blackhole if blackhole is not None else defaults["blackhole"], 0.0),
        "supernova": max(supernova if supernova is not None else defaults["supernova"], 0.0),
        "fullsail": max(fullsail if fullsail is not None else defaults["fullsail"], 0.0),
    }
