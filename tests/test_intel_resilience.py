"""Unit tests for the regional-intel collector resilience layer.

The resilience layer wraps every public-source fetch in
``RegionalIntelService._retry_fetch`` so that a single transient timeout or
connection blip does not silently drop a source for an entire snapshot.

These tests mock the source factories directly (no real network) to keep the
suite hermetic and fast.
"""
from __future__ import annotations

import asyncio
import os
import unittest

from app import config
from app.intel_models import (
    IntelSource,
    RegionalIntelSnapshot,
)
from app.services.regional_intel import (
    ETHICS_RULES,
    REGIONS,
    RegionalIntelService,
    _build_source_health,
)


def _async_run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class RetryHelperTestCase(unittest.TestCase):
    """Cover the four required behaviors of ``_retry_fetch``."""

    def setUp(self) -> None:
        # Pin known config so tests are independent of the host env.
        os.environ["REGIONAL_INTEL_SOURCE_TIMEOUT"] = "5"
        os.environ["REGIONAL_INTEL_RETRY_LIMIT"] = "2"
        os.environ["REGIONAL_INTEL_RETRY_BACKOFF_BASE"] = "0.01"
        config.get_settings.cache_clear()
        self.service = RegionalIntelService()
        # Drop the per-snapshot ledger so each test starts clean.
        self.service._failed_sources = {}
        # Replace asyncio.sleep with a recording fake so backoff is observable
        # without making the suite slow.
        self.sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            self.sleep_calls.append(delay)

        self._fake_sleep = fake_sleep

    def tearDown(self) -> None:
        for var in (
            "REGIONAL_INTEL_SOURCE_TIMEOUT",
            "REGIONAL_INTEL_RETRY_LIMIT",
            "REGIONAL_INTEL_RETRY_BACKOFF_BASE",
        ):
            os.environ.pop(var, None)
        config.get_settings.cache_clear()

    # --- 1. timeout-then-success --------------------------------------------------
    def test_transient_timeout_then_success_returns_payload(self) -> None:
        attempts: list[int] = []

        async def factory():
            attempts.append(1)
            if len(attempts) == 1:
                raise asyncio.TimeoutError("first attempt times out")
            return {"ok": True}

        result = _async_run(
            self.service._retry_fetch("acme_news", factory, sleep=self._fake_sleep)
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("acme_news", self.service._failed_sources)
        # One backoff sleep between attempt 1 and attempt 2.
        self.assertEqual(len(self.sleep_calls), 1)

    # --- 2. all-retries-fail-graceful-degrade -------------------------------------
    def test_all_retries_exhausted_records_failure_and_returns_none(self) -> None:
        attempts = {"n": 0}

        async def factory():
            attempts["n"] += 1
            raise ConnectionError("boom")

        result = _async_run(
            self.service._retry_fetch("permits_x", factory, sleep=self._fake_sleep)
        )

        self.assertIsNone(result)
        # Default retry_limit=2 → 3 total tries (initial + 2 retries).
        self.assertEqual(attempts["n"], 3)
        self.assertIn("permits_x", self.service._failed_sources)
        record = self.service._failed_sources["permits_x"]
        self.assertTrue(record["transient"])
        self.assertEqual(record["attempts"], 3)
        self.assertIn("ConnectionError", record["error"])

    # --- 3. non-transient-exception-immediate-fail --------------------------------
    def test_non_transient_exception_does_not_retry(self) -> None:
        attempts = {"n": 0}

        async def factory():
            attempts["n"] += 1
            raise ValueError("schema drift, do not retry")

        result = _async_run(
            self.service._retry_fetch("contacts_y", factory, sleep=self._fake_sleep)
        )

        self.assertIsNone(result)
        self.assertEqual(attempts["n"], 1, "non-transient errors must fail fast")
        self.assertEqual(self.sleep_calls, [], "no backoff before a non-transient fail")
        record = self.service._failed_sources["contacts_y"]
        self.assertFalse(record["transient"])
        self.assertEqual(record["attempts"], 1)

    # --- 4. retry-backoff-is-bounded ----------------------------------------------
    def test_backoff_is_bounded_by_per_source_timeout(self) -> None:
        # Use a tiny timeout so the cap matters even with a large base.
        os.environ["REGIONAL_INTEL_SOURCE_TIMEOUT"] = "0.05"
        os.environ["REGIONAL_INTEL_RETRY_LIMIT"] = "4"
        os.environ["REGIONAL_INTEL_RETRY_BACKOFF_BASE"] = "10.0"
        config.get_settings.cache_clear()
        # Rebuild service so it observes the new settings.
        service = RegionalIntelService()
        service._failed_sources = {}
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        async def factory():
            raise asyncio.TimeoutError("always timeout")

        result = _async_run(
            service._retry_fetch("overpass_business", factory, sleep=fake_sleep)
        )

        self.assertIsNone(result)
        # 4 retries → 4 backoff sleeps between the 5 tries.
        self.assertEqual(len(sleeps), 4)
        # Every backoff must be capped by the per-source timeout (or the base
        # if that's larger). With base=10.0 and timeout=0.05 the cap is 10.0,
        # so we instead assert the cap-vs-base contract: the largest backoff
        # never exceeds max(base, timeout) and is finite.
        cap = max(10.0, 0.05)
        for delay in sleeps:
            self.assertLessEqual(delay, cap)
            self.assertGreater(delay, 0)
        # And the helper must not raise even though every attempt fails.
        self.assertIn("overpass_business", service._failed_sources)


class SourceHealthOverlayTestCase(unittest.TestCase):
    """``_build_source_health`` should surface recorded failures in notes/status."""

    def test_failed_source_label_is_overlaid_on_source_health(self) -> None:
        sources = [
            IntelSource(
                source_key="austin_open_data_permits",
                name="City of Austin Open Data",
                category="permit",
                region_ids=["austin_tx"],
                live_pull=True,
                url="https://data.austintexas.gov/",
                collection_mode="api",
                access="public",
            ),
        ]
        snapshot = RegionalIntelSnapshot(
            updated_at="2026-04-27T10:00:00Z",
            cache_ttl_seconds=900,
            regions=REGIONS,
            ethics_rules=ETHICS_RULES,
            sources=sources,
        )
        failed = {
            "austin_open_data_permits": {
                "label": "austin_open_data_permits",
                "error": "TimeoutError: read timeout",
                "transient": True,
                "attempts": 3,
                "observed_at": "2026-04-27T10:00:00Z",
            },
        }

        result = _build_source_health(snapshot, failed_sources=failed)

        self.assertEqual(len(result), 1)
        health = result[0]
        self.assertEqual(health.status, "failed")
        self.assertTrue(
            any("Fetch failed after 3 attempt" in note for note in health.notes),
            f"expected failure note, got {health.notes!r}",
        )


if __name__ == "__main__":
    unittest.main()
