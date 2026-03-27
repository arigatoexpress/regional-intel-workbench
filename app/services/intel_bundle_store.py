from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.intel_models import IntelBriefingBundle
from app.intel_models import IntelBriefingBundleRef
from app.utils import clean_text
from app.utils import utc_now_iso


class IntelBundleStore:
    def __init__(self, path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / 'data' / 'intel_briefing_bundles.json'
        self._lock = Lock()

    def list_bundles(self) -> list[IntelBriefingBundle]:
        with self._lock:
            payload = self._read_unlocked()
        bundles = [IntelBriefingBundle.model_validate(item) for item in payload]
        bundles.sort(key=lambda item: (item.status == 'active', item.updated_at, item.title.lower()), reverse=True)
        return bundles

    def get_bundle(self, bundle_id: str) -> IntelBriefingBundle | None:
        with self._lock:
            payload = self._read_unlocked()
        for item in payload:
            if item.get('bundle_id') == bundle_id:
                return IntelBriefingBundle.model_validate(item)
        return None

    def save_bundle(self, *, title: str, region_id: str | None = None, note: str | None = None, tags: list[str] | None = None) -> IntelBriefingBundle:
        now = utc_now_iso()
        cleaned_title = clean_text(title).strip() or 'Untitled bundle'
        cleaned_tags = self._clean_tags(tags or [])
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if clean_text(raw.get('title', '')).strip().lower() != cleaned_title.lower():
                    continue
                raw['updated_at'] = now
                raw['title'] = cleaned_title
                if region_id is not None:
                    raw['region_id'] = region_id
                if note is not None:
                    raw['note'] = note
                raw['tags'] = cleaned_tags
                raw['status'] = 'active'
                self._write_unlocked(payload)
                return IntelBriefingBundle.model_validate(raw)

            bundle = IntelBriefingBundle(
                bundle_id=f"bun_{len(payload) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                created_at=now,
                updated_at=now,
                title=cleaned_title,
                region_id=region_id,
                note=note,
                tags=cleaned_tags,
            )
            payload.append(bundle.model_dump())
            self._write_unlocked(payload)
            return bundle

    def delete_bundle(self, bundle_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            retained = [item for item in payload if item.get('bundle_id') != bundle_id]
            if len(retained) == len(payload):
                return False
            self._write_unlocked(retained)
        return True

    def save_collection_ref(self, *, bundle_id: str, collection_id: str, label: str) -> IntelBriefingBundleRef:
        now = utc_now_iso()
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if raw.get('bundle_id') != bundle_id:
                    continue
                refs = raw.setdefault('collections', [])
                for ref in refs:
                    if ref.get('collection_id') == collection_id:
                        ref['updated_at'] = now
                        ref['label'] = label or ref.get('label') or 'Saved collection'
                        raw['updated_at'] = now
                        self._write_unlocked(payload)
                        return IntelBriefingBundleRef.model_validate(ref)
                ref = IntelBriefingBundleRef(
                    ref_id=f"bref_{len(refs) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                    created_at=now,
                    updated_at=now,
                    collection_id=collection_id,
                    label=label or 'Saved collection',
                )
                refs.append(ref.model_dump())
                raw['updated_at'] = now
                self._write_unlocked(payload)
                return ref
        raise KeyError(bundle_id)

    def delete_collection_ref(self, bundle_id: str, ref_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if raw.get('bundle_id') != bundle_id:
                    continue
                refs = raw.get('collections') or []
                retained = [item for item in refs if item.get('ref_id') != ref_id]
                if len(retained) == len(refs):
                    return False
                raw['collections'] = retained
                raw['updated_at'] = utc_now_iso()
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
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _write_unlocked(self, payload: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
