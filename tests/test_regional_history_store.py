from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.intel_models import RegionalIntelSnapshot
from app.services.regional_history_store import RegionalIntelHistoryStore


def _snapshot(updated_at: str) -> RegionalIntelSnapshot:
    return RegionalIntelSnapshot(updated_at=updated_at, cache_ttl_seconds=900)


class RegionalIntelHistoryStoreTestCase(unittest.TestCase):
    def test_force_append_bypasses_recent_snapshot_throttle(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = RegionalIntelHistoryStore(
                path=Path(tempdir) / "regional_intel_history.jsonl",
                min_append_interval_seconds=1_800,
            )

            first = _snapshot("2026-04-29T05:39:31+00:00")
            second = _snapshot("2026-04-29T05:40:39+00:00")

            self.assertTrue(store.append_snapshot(first))
            self.assertFalse(store.append_snapshot(second))
            self.assertTrue(store.append_snapshot(second, force=True))

            records = store.load_records(lookback_days=10_000)
            self.assertEqual([record["updated_at"] for record in records], [first.updated_at, second.updated_at])


if __name__ == "__main__":
    unittest.main()
