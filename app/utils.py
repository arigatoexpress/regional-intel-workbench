from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from statistics import mean


ABBREVIATIONS = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
    "T": 1_000_000_000_000,
}

COUNTDOWN_PART_RE = re.compile(r"(?P<value>\d+)\s*(?P<unit>[dhms])", re.IGNORECASE)
NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
COMPACT_RE = re.compile(r"(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*([KMBT]?)", re.IGNORECASE)


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    if avg <= 0:
        return None
    variance = mean((value - avg) ** 2 for value in values)
    return math.sqrt(variance) / avg


def parse_compact_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = (
        value.strip()
        .replace("~", "")
        .replace("$", "")
        .replace("%", "")
        .replace(" ", "")
    )
    if not cleaned or cleaned in {"--", "-", "N/A"}:
        return None
    match = COMPACT_RE.search(cleaned)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    suffix = match.group(2).upper()
    return number * ABBREVIATIONS.get(suffix, 1)


def parse_metric_or_zero(value: str | None) -> float:
    if not value:
        return 0.0
    lowered = value.lower()
    if "no available" in lowered or lowered in {"n/a", "--"}:
        return 0.0
    parsed = parse_compact_number(value)
    return parsed if parsed is not None else 0.0


def parse_vote_window(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    parts = [part.strip() for part in value.split("/") if part.strip()]
    if len(parts) == 2:
        return parse_compact_number(parts[0]), parse_compact_number(parts[1])
    parsed = parse_compact_number(value)
    return parsed, None


def parse_countdown_to_ms(countdown: str | None) -> int | None:
    if not countdown:
        return None
    total_seconds = 0
    for match in COUNTDOWN_PART_RE.finditer(countdown):
        raw = int(match.group("value"))
        unit = match.group("unit").lower()
        if unit == "d":
            total_seconds += raw * 86_400
        elif unit == "h":
            total_seconds += raw * 3_600
        elif unit == "m":
            total_seconds += raw * 60
        elif unit == "s":
            total_seconds += raw
    if total_seconds <= 0:
        return None
    return int((datetime.now(tz=UTC).timestamp() + total_seconds) * 1000)


def normalize_fullsail_vote_power(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number >= 1_000_000_000:
        return number / 1_000_000
    return number


def normalize_fullsail_prediction_usd(
    value: str | int | float | None,
    weekly_volume_usd: float | None,
) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number <= 0:
        return 0.0
    if (
        weekly_volume_usd
        and weekly_volume_usd > 0
        and number / weekly_volume_usd > 1_000
    ):
        return number / 1_000_000
    if number >= 1_000_000_000:
        return number / 1_000_000
    return number


def confidence_from_history(volume_history: list[dict]) -> float | None:
    comparable_errors: list[float] = []
    for entry in volume_history:
        predicted = parse_metric_or_zero(str(entry.get("predicted_volume_usd", "")))
        actual = parse_metric_or_zero(str(entry.get("fact_volume_usd", "")))
        if predicted <= 0 or actual <= 0:
            continue
        comparable_errors.append(abs(actual - predicted) / max(actual, 1.0))
    if len(comparable_errors) < 3:
        return None
    confidence = 1.0 - mean(comparable_errors)
    return round(clamp(confidence, 0.35, 1.0), 3)


def forecast_volume_from_history(
    volume_history: list[dict],
    weekly_volume_usd: float | None,
    predicted_volume_usd: float | None,
) -> tuple[float | None, float | None, float | None]:
    actuals: list[float] = []
    predictions: list[float] = []

    for entry in volume_history:
        actual = parse_metric_or_zero(str(entry.get("fact_volume_usd", "")))
        predicted = parse_metric_or_zero(str(entry.get("predicted_volume_usd", "")))
        if actual > 0:
            actuals.append(actual)
        if predicted > 0:
            predictions.append(predicted)

    weighted_components: list[tuple[float, float]] = []
    if actuals:
        ewma = actuals[0]
        for value in actuals[1:]:
            ewma = 0.45 * value + 0.55 * ewma
        weighted_components.append((ewma, 0.55))
        weighted_components.append((mean(actuals[-min(4, len(actuals)) :]), 0.25))
    if weekly_volume_usd and weekly_volume_usd > 0:
        weighted_components.append((weekly_volume_usd, 0.15))
    if predicted_volume_usd and predicted_volume_usd > 0:
        weighted_components.append((predicted_volume_usd, 0.20))
    if predictions:
        weighted_components.append(
            (mean(predictions[-min(3, len(predictions)) :]), 0.10)
        )

    if not weighted_components:
        return None, None, None

    total_weight = sum(weight for _, weight in weighted_components)
    forecast = (
        sum(value * weight for value, weight in weighted_components) / total_weight
    )

    recent_actuals = actuals[-min(6, len(actuals)) :]
    volatility = coefficient_of_variation(recent_actuals) if recent_actuals else None
    band_ratio = clamp(0.20 + (volatility or 0.35) * 0.50, 0.20, 0.75)
    low = max(forecast * (1.0 - band_ratio), 0.0)
    high = forecast * (1.0 + band_ratio)
    return round(forecast, 2), round(low, 2), round(high, 2)


def format_usd_compact(value: float | None) -> str:
    if value is None:
        return "--"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"


def format_number_compact(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "--"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    if math.isfinite(value):
        return f"{value:,.{decimals}f}"
    return "--"


def clean_text(value: str | int | float | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def make_pool_key(name: str | None, fee_tier: str | None = None) -> str:
    return f"{clean_text(name).lower()}|{clean_text(fee_tier).lower()}"


def first_number_text(value: str | None) -> str:
    if not value:
        return ""
    match = NUMBER_RE.search(value)
    return match.group(0) if match else ""
