from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.intel_models import IntelWatchlistEntry
from app.utils import utc_now_iso


class IntelWatchlistStore:
    def __init__(self, path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / "data" / "intel_watchlist.json"
        self._lock = Lock()

    def list_entries(self) -> list[IntelWatchlistEntry]:
        with self._lock:
            payload = self._read_unlocked()
        entries = [IntelWatchlistEntry.model_validate(item) for item in payload]
        entries.sort(key=lambda item: (item.status != "active", item.updated_at), reverse=True)
        return entries

    def save_entry(
        self,
        *,
        kind: str,
        label: str,
        region_id: str | None = None,
        item_id: str | None = None,
        source_url: str | None = None,
        note: str | None = None,
    ) -> IntelWatchlistEntry:
        now = utc_now_iso()
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if raw.get("kind") == kind and raw.get("item_id") == item_id and item_id:
                    raw["updated_at"] = now
                    raw["label"] = label or raw.get("label") or "Saved item"
                    if region_id:
                        raw["region_id"] = region_id
                    if source_url:
                        raw["source_url"] = source_url
                    if note is not None:
                        raw["note"] = note
                    raw["status"] = "active"
                    self._write_unlocked(payload)
                    return IntelWatchlistEntry.model_validate(raw)

            entry = IntelWatchlistEntry(
                entry_id=f"wl_{len(payload) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                created_at=now,
                updated_at=now,
                kind=kind,
                label=label or "Saved item",
                region_id=region_id,
                item_id=item_id,
                source_url=source_url,
                note=note,
            )
            payload.append(entry.model_dump())
            self._write_unlocked(payload)
            return entry

    def delete_entry(self, entry_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            retained = [item for item in payload if item.get("entry_id") != entry_id]
            if len(retained) == len(payload):
                return False
            self._write_unlocked(retained)
        return True

    def _read_unlocked(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _write_unlocked(self, payload: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
