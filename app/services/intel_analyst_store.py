from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.intel_models import IntelAnalystAnnotation
from app.utils import clean_text
from app.utils import utc_now_iso


class IntelAnalystStore:
    def __init__(self, path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / "data" / "intel_annotations.json"
        self._lock = Lock()

    def get_annotation(
        self, *, target_kind: str, target_id: str
    ) -> IntelAnalystAnnotation | None:
        with self._lock:
            payload = self._read_unlocked()
        for item in payload:
            if (
                item.get("target_kind") == target_kind
                and item.get("target_id") == target_id
            ):
                return IntelAnalystAnnotation.model_validate(item)
        return None

    def save_annotation(
        self, *, target_kind: str, target_id: str, note: str, tags: list[str]
    ) -> IntelAnalystAnnotation:
        now = utc_now_iso()
        cleaned_tags = []
        seen: set[str] = set()
        for value in tags:
            tag = clean_text(value).strip().lower()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            cleaned_tags.append(tag)
        with self._lock:
            payload = self._read_unlocked()
            for item in payload:
                if (
                    item.get("target_kind") == target_kind
                    and item.get("target_id") == target_id
                ):
                    item["updated_at"] = now
                    item["note"] = note
                    item["tags"] = cleaned_tags
                    self._write_unlocked(payload)
                    return IntelAnalystAnnotation.model_validate(item)
            annotation = IntelAnalystAnnotation(
                annotation_id=f"ann_{len(payload) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                target_kind=target_kind,
                target_id=target_id,
                created_at=now,
                updated_at=now,
                note=note,
                tags=cleaned_tags,
            )
            payload.append(annotation.model_dump())
            self._write_unlocked(payload)
            return annotation

    def delete_annotation(self, *, target_kind: str, target_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            retained = [
                item
                for item in payload
                if not (
                    item.get("target_kind") == target_kind
                    and item.get("target_id") == target_id
                )
            ]
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
