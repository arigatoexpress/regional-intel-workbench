from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.intel_models import IntelMonitorRule
from app.utils import clean_text
from app.utils import utc_now_iso


class IntelMonitorStore:
    def __init__(self, path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.path = path or base_dir / "data" / "intel_monitor_rules.json"
        self._lock = Lock()

    def list_rules(self) -> list[IntelMonitorRule]:
        with self._lock:
            payload = self._read_unlocked()
        rules = [IntelMonitorRule.model_validate(item) for item in payload]
        rules.sort(
            key=lambda item: (
                item.status == "active",
                item.updated_at,
                item.title.lower(),
            ),
            reverse=True,
        )
        return rules

    def get_rule(self, rule_id: str) -> IntelMonitorRule | None:
        with self._lock:
            payload = self._read_unlocked()
        for item in payload:
            if item.get("rule_id") == rule_id:
                return IntelMonitorRule.model_validate(item)
        return None

    def save_rule(
        self,
        *,
        title: str,
        region_id: str | None = None,
        entity_kinds: list[str] | None = None,
        change_types: list[str] | None = None,
        incident_types: list[str] | None = None,
        keyword: str | None = None,
        min_score_delta: float | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
    ) -> IntelMonitorRule:
        now = utc_now_iso()
        cleaned_title = clean_text(title).strip() or "Untitled monitor rule"
        cleaned_keyword = clean_text(keyword).strip() or None
        cleaned_tags = self._clean_tags(tags or [])
        cleaned_entity_kinds = self._clean_options(entity_kinds or [])
        cleaned_change_types = self._clean_options(change_types or [])
        cleaned_incident_types = self._clean_options(incident_types or [])

        with self._lock:
            payload = self._read_unlocked()
            for raw in payload:
                if (
                    clean_text(raw.get("title", "")).strip().lower()
                    != cleaned_title.lower()
                ):
                    continue
                raw["updated_at"] = now
                raw["title"] = cleaned_title
                raw["region_id"] = region_id
                raw["entity_kinds"] = cleaned_entity_kinds
                raw["change_types"] = cleaned_change_types
                raw["incident_types"] = cleaned_incident_types
                raw["keyword"] = cleaned_keyword
                raw["min_score_delta"] = min_score_delta
                raw["note"] = note
                raw["tags"] = cleaned_tags
                raw["status"] = "active"
                self._write_unlocked(payload)
                return IntelMonitorRule.model_validate(raw)

            rule = IntelMonitorRule(
                rule_id=f"mon_{len(payload) + 1}_{now.replace(':', '').replace('-', '').replace('.', '')}",
                created_at=now,
                updated_at=now,
                title=cleaned_title,
                region_id=region_id,
                entity_kinds=cleaned_entity_kinds,
                change_types=cleaned_change_types,
                incident_types=cleaned_incident_types,
                keyword=cleaned_keyword,
                min_score_delta=min_score_delta,
                note=note,
                tags=cleaned_tags,
            )
            payload.append(rule.model_dump())
            self._write_unlocked(payload)
            return rule

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            retained = [item for item in payload if item.get("rule_id") != rule_id]
            if len(retained) == len(payload):
                return False
            self._write_unlocked(retained)
        return True

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

    def _clean_options(self, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            option = clean_text(value).strip().lower().replace(" ", "_")
            if not option or option in seen:
                continue
            cleaned.append(option)
            seen.add(option)
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
