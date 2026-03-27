from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.intel_models import IntelCollection
from app.intel_models import IntelCollectionItemRef
from app.utils import clean_text
from app.utils import utc_now_iso


class IntelCollectionStore:
    def __init__(self, path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / "data" / "intel_collections.json"
        self._lock = Lock()

    def list_collections(self) -> list[IntelCollection]:
        with self._lock:
            payload = self._read_unlocked()
        collections = [IntelCollection.model_validate(item) for item in payload]
        collections.sort(key=lambda item: (item.status == "active", item.updated_at, item.title.lower()), reverse=True)
        return collections

    def get_collection(self, collection_id: str) -> IntelCollection | None:
        with self._lock:
            payload = self._read_unlocked()
        for item in payload:
            if item.get("collection_id") == collection_id:
                return IntelCollection.model_validate(item)
        return None

    def save_collection(
        self,
        *,
        title: str,
        region_id: str | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
    ) -> IntelCollection:
        now = utc_now_iso()
        cleaned_title = clean_text(title).strip() or "Untitled collection"
        cleaned_tags = self._clean_tags(tags or [])
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if clean_text(raw.get("title", "")).strip().lower() != cleaned_title.lower():
                    continue
                raw["updated_at"] = now
                raw["title"] = cleaned_title
                if region_id is not None:
                    raw["region_id"] = region_id
                if note is not None:
                    raw["note"] = note
                raw["tags"] = cleaned_tags
                raw["status"] = "active"
                self._write_unlocked(payload)
                return IntelCollection.model_validate(raw)

            collection = IntelCollection(
                collection_id=f"col_{len(payload) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                created_at=now,
                updated_at=now,
                title=cleaned_title,
                region_id=region_id,
                note=note,
                tags=cleaned_tags,
            )
            payload.append(collection.model_dump())
            self._write_unlocked(payload)
            return collection

    def delete_collection(self, collection_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            retained = [item for item in payload if item.get("collection_id") != collection_id]
            if len(retained) == len(payload):
                return False
            self._write_unlocked(retained)
        return True

    def save_item(
        self,
        *,
        collection_id: str,
        kind: str,
        label: str,
        region_id: str | None = None,
        item_id: str | None = None,
        source_url: str | None = None,
        note: str | None = None,
    ) -> IntelCollectionItemRef:
        now = utc_now_iso()
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if raw.get("collection_id") != collection_id:
                    continue
                items = raw.setdefault("items", [])
                for item in items:
                    if item_id and item.get("kind") == kind and item.get("item_id") == item_id:
                        item["updated_at"] = now
                        item["label"] = label or item.get("label") or "Saved item"
                        if region_id is not None:
                            item["region_id"] = region_id
                        if source_url is not None:
                            item["source_url"] = source_url
                        if note is not None:
                            item["note"] = note
                        item["status"] = "active"
                        raw["updated_at"] = now
                        self._write_unlocked(payload)
                        return IntelCollectionItemRef.model_validate(item)
                ref = IntelCollectionItemRef(
                    ref_id=f"cri_{len(items) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                    created_at=now,
                    updated_at=now,
                    kind=kind,
                    label=label or "Saved item",
                    region_id=region_id,
                    item_id=item_id,
                    source_url=source_url,
                    note=note,
                )
                items.append(ref.model_dump())
                raw["updated_at"] = now
                self._write_unlocked(payload)
                return ref
        raise KeyError(collection_id)

    def delete_item(self, collection_id: str, ref_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if raw.get("collection_id") != collection_id:
                    continue
                items = raw.get("items") or []
                retained = [item for item in items if item.get("ref_id") != ref_id]
                if len(retained) == len(items):
                    return False
                raw["items"] = retained
                raw["updated_at"] = utc_now_iso()
                self._write_unlocked(payload)
                return True
        return False

    def _clean_tags(self, tags: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in tags:
            tag = clean_text(value).strip().lower()
            if not tag or tag in seen:
                continue
            cleaned.append(tag)
            seen.add(tag)
        return cleaned

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
