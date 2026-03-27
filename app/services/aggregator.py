from __future__ import annotations

import asyncio
import time

from app.models import DashboardSnapshot, ProtocolSnapshot
from app.services.evm_vote_scraper import PROTOCOLS, fetch_evm_protocol_snapshots
from app.services.fullsail import fetch_fullsail_snapshot
from app.services.history_store import SnapshotHistoryStore
from app.services.strategy import LOOKBACK_DAYS, enrich_dashboard_snapshot
from app.utils import utc_now_iso


class DashboardService:
    def __init__(self, ttl_seconds: int = 180) -> None:
        self.ttl_seconds = ttl_seconds
        self.history_store = SnapshotHistoryStore()
        self._lock = asyncio.Lock()
        self._snapshot: DashboardSnapshot | None = None
        self._expires_at = 0.0

    async def get_snapshot(self, force_refresh: bool = False) -> DashboardSnapshot:
        now = time.monotonic()
        if not force_refresh and self._snapshot is not None and now < self._expires_at:
            return self._snapshot
        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._snapshot is not None and now < self._expires_at:
                return self._snapshot
            snapshot = await self._build_snapshot()
            self._snapshot = snapshot
            self._expires_at = time.monotonic() + self.ttl_seconds
            return snapshot

    async def _build_snapshot(self) -> DashboardSnapshot:
        evm_task = asyncio.create_task(fetch_evm_protocol_snapshots())
        fullsail_task = asyncio.create_task(fetch_fullsail_snapshot())

        protocols: list[ProtocolSnapshot] = []
        global_notes = [
            "Blackhole is on Avalanche, Supernova is on Ethereum, and Full Sail is on Sui.",
            "Vote power is protocol-native. Compare pools within each protocol first, then use your own vote-power inputs to estimate payout.",
        ]

        try:
            evm_protocols = await evm_task
            protocols.extend(evm_protocols)
        except Exception as exc:  # noqa: BLE001
            for protocol in PROTOCOLS:
                protocols.append(
                    ProtocolSnapshot(
                        id=protocol.id,  # type: ignore[arg-type]
                        name=protocol.name,
                        chain=protocol.chain,
                        vote_power_symbol=protocol.vote_power_symbol,
                        ranking_basis="Unavailable",
                        source=protocol.source,
                        error=str(exc),
                        notes=["This protocol failed to refresh in the last scrape attempt."],
                    )
                )
            global_notes.append("At least one EVM protocol failed to refresh. See the per-protocol error card.")

        try:
            protocols.append(await fullsail_task)
        except Exception as exc:  # noqa: BLE001
            protocols.append(
                ProtocolSnapshot(
                    id="fullsail",
                    name="Full Sail",
                    chain="Sui",
                    vote_power_symbol="veSAIL",
                    ranking_basis="Unavailable",
                    source="Full Sail public API",
                    error=str(exc),
                    notes=["Full Sail failed to refresh in the last API attempt."],
                )
            )
            global_notes.append("Full Sail failed to refresh. See the per-protocol error card.")

        order = {"blackhole": 0, "supernova": 1, "fullsail": 2}
        protocols.sort(key=lambda protocol: order.get(protocol.id, 99))

        snapshot = DashboardSnapshot(
            updated_at=utc_now_iso(),
            cache_ttl_seconds=self.ttl_seconds,
            protocols=protocols,
            global_notes=global_notes,
        )
        self.history_store.append_snapshot(snapshot)
        history_records = self.history_store.load_records(lookback_days=LOOKBACK_DAYS)
        return enrich_dashboard_snapshot(snapshot, history_records, lookback_days=LOOKBACK_DAYS)
