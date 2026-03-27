from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from app.intel_models import RegionalIntelSnapshot


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class RegionalIntelHistoryStore:
    def __init__(
        self,
        path: Path | None = None,
        min_append_interval_seconds: int = 1_800,
        max_records: int = 1_000,
    ) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / "data" / "regional_intel_history.jsonl"
        self.min_append_interval_seconds = min_append_interval_seconds
        self.max_records = max_records
        self._lock = Lock()

    def append_snapshot(self, snapshot: RegionalIntelSnapshot) -> bool:
        record = snapshot.model_dump()
        current_timestamp = _parse_timestamp(snapshot.updated_at)

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            last_record = self._read_last_record_unlocked()
            if last_record:
                last_timestamp = _parse_timestamp(str(last_record.get("updated_at")))
                delta = (current_timestamp - last_timestamp).total_seconds()
                if delta < self.min_append_interval_seconds:
                    return False

            with self.path.open("a", encoding="utf-8") as handle:
                json.dump(record, handle, separators=(",", ":"))
                handle.write("\n")

            self._trim_if_needed_unlocked()
            return True

    def load_records(self, lookback_days: int = 30) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=lookback_days)
        records: list[dict[str, Any]] = []

        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    updated_at = record.get("updated_at")
                    if not updated_at:
                        continue
                    if _parse_timestamp(str(updated_at)) < cutoff:
                        continue
                    records.append(record)

        records.sort(key=lambda item: str(item.get("updated_at")))
        return records

    def load_latest_record(self) -> dict[str, Any] | None:
        with self._lock:
            return self._read_last_record_unlocked()

    def _read_last_record_unlocked(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        return None

    def _trim_if_needed_unlocked(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self.max_records:
            return
        retained = [line for line in lines[-self.max_records :] if line.strip()]
        self.path.write_text("\n".join(retained) + "\n", encoding="utf-8")
