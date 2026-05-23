from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.intel_models import LogisticsDataSourceSpec
from app.intel_models import LogisticsForecastModel
from app.intel_models import LogisticsSignal
from app.services.foundry_export import build_export_plan
from app.services.foundry_export import export_snapshot
from app.services.foundry_export import logistics_signal_objects
from test_foundry_export import _snapshot


def _sources() -> list[LogisticsDataSourceSpec]:
    return [
        LogisticsDataSourceSpec(
            source_id="nws_alerts",
            name="National Weather Service Alerts",
            owner="NOAA/National Weather Service",
            source_url="https://www.weather.gov/documentation/services-web-api",
            retrieval_mode="public_api",
            rights="U.S. government public weather data; cite NOAA/NWS.",
            freshness_ttl="15 minutes",
            output_policy="Store derived alert summaries, source URLs, and hashes.",
            caveats=["Weather context is not a station operations decision."],
        ),
        LogisticsDataSourceSpec(
            source_id="synthetic_station_baseline",
            name="Synthetic Station Baseline",
            owner="AI Efficiency Team",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            retrieval_mode="synthetic_fixture",
            rights="Synthetic demo data only.",
            freshness_ttl="manual",
            output_policy="Use for demos and tests only.",
            caveats=["Not real FedEx volume, staffing, or dispatch data."],
        ),
    ]


def _signals() -> list[LogisticsSignal]:
    return [
        LogisticsSignal(
            signal_id="gunnison-winter-weather-watch",
            region_id="gunnison_valley_co",
            signal_type="weather_alert",
            title="Winter weather watch near Gunnison Valley",
            summary="Public weather signal that may require manager verification.",
            source_id="nws_alerts",
            source_name="National Weather Service",
            source_url="https://api.weather.gov/alerts/active",
            observed_at="2026-05-22T12:00:00Z",
            data_classification="public",
            confidence=0.92,
            attributes={"severity": "moderate"},
        ),
        LogisticsSignal(
            signal_id="synthetic-shift-baseline",
            region_id="gunnison_valley_co",
            signal_type="synthetic_baseline",
            title="Synthetic PM sort baseline",
            summary="Demo-only station baseline for load-estimation tests.",
            source_id="synthetic_station_baseline",
            source_name="Synthetic demo baseline",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            observed_at="2026-05-22T12:00:00Z",
            data_classification="synthetic",
            confidence=1.0,
            attributes={"baseline_packages": 1000},
        ),
    ]


def _models() -> list[LogisticsForecastModel]:
    return [
        LogisticsForecastModel(
            model_id="seasonal-baseline-v0",
            name="Seasonal Baseline V0",
            purpose="Synthetic load-estimation baseline for public-data demos.",
            source_url="https://github.com/arigatoexpress/AI-Efficiency",
            license_or_rights="Internal synthetic methodology; no real FedEx data.",
            input_policy="Public, synthetic, or derived-public inputs only.",
            output_policy="Label outputs as estimates that need human verification.",
            supported_horizons=["same_shift", "next_day"],
            caveats=["Not calibrated on production FedEx volume."],
        )
    ]


def _read_ndjson(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


class LogisticsFoundryExportTestCase(unittest.TestCase):
    def test_builds_source_signal_and_model_objects(self) -> None:
        rows_by_type, manifest = build_export_plan(
            _snapshot(),
            logistics_sources=_sources(),
            logistics_signals=_signals(),
            logistics_models=_models(),
            log_drops=False,
        )

        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["dropped_rows"]["total"], 0)
        self.assertEqual(len(rows_by_type["LogisticsDataSource"]), 2)
        self.assertEqual(len(rows_by_type["LogisticsSignal"]), 2)
        self.assertEqual(len(rows_by_type["LogisticsForecastModel"]), 1)
        self.assertTrue(manifest["policy"]["public_sources_only"])
        self.assertTrue(manifest["logistics_policy"]["no_internal_fedex_data"])
        signal = rows_by_type["LogisticsSignal"][0]
        self.assertIn(signal["data_classification"], {"public", "synthetic"})
        self.assertIn("source_rights", signal["provenance"])

    def test_drops_signals_with_bad_classification_or_missing_provenance(self) -> None:
        signals = _signals()
        signals.extend(
            [
                LogisticsSignal(
                    signal_id="internal-volume",
                    region_id="gunnison_valley_co",
                    signal_type="volume",
                    title="Internal volume",
                    summary="Should never enter public export.",
                    source_id="nws_alerts",
                    source_name="Internal",
                    source_url="https://example.test/internal",
                    observed_at="2026-05-22T12:00:00Z",
                    data_classification="internal",
                    confidence=1.0,
                ),
                LogisticsSignal(
                    signal_id="missing-source-url",
                    region_id="gunnison_valley_co",
                    signal_type="weather_alert",
                    title="Missing URL",
                    summary="No source URL.",
                    source_id="nws_alerts",
                    source_name="National Weather Service",
                    source_url="",
                    observed_at="2026-05-22T12:00:00Z",
                    data_classification="public",
                    confidence=0.5,
                ),
            ]
        )

        rows, dropped = logistics_signal_objects(signals, _sources(), log_drops=False)

        self.assertEqual(len(rows), 2)
        self.assertEqual(dropped["total"], 2)
        self.assertEqual(
            dropped["by_reason"],
            {"disallowed_data_classification": 1, "missing_provenance": 1},
        )
        self.assertNotIn("internal-volume", {row["signal_id"] for row in rows})

    def test_drops_signal_with_unknown_source(self) -> None:
        signals = [
            LogisticsSignal(
                signal_id="unknown-source",
                region_id="gunnison_valley_co",
                signal_type="road_context",
                title="Unknown source",
                summary="Should be dropped.",
                source_id="unreviewed_vendor",
                source_name="Unknown Vendor",
                source_url="https://example.test/vendor",
                observed_at="2026-05-22T12:00:00Z",
                data_classification="public",
                confidence=0.5,
            )
        ]

        rows, dropped = logistics_signal_objects(signals, _sources(), log_drops=False)

        self.assertEqual(rows, [])
        self.assertEqual(dropped["by_reason"], {"unknown_source": 1})

    def test_export_writes_deterministic_ndjson_and_manifest_hashes(self) -> None:
        with TemporaryDirectory() as tmp_a, TemporaryDirectory() as tmp_b:
            manifest_a = export_snapshot(
                _snapshot(),
                output_dir=Path(tmp_a),
                logistics_sources=_sources(),
                logistics_signals=_signals(),
                logistics_models=_models(),
            )
            manifest_b = export_snapshot(
                _snapshot(),
                output_dir=Path(tmp_b),
                logistics_sources=_sources(),
                logistics_signals=_signals(),
                logistics_models=_models(),
            )

            for filename in (
                "LogisticsDataSource.ndjson",
                "LogisticsSignal.ndjson",
                "LogisticsForecastModel.ndjson",
            ):
                bytes_a = (Path(tmp_a) / filename).read_bytes()
                bytes_b = (Path(tmp_b) / filename).read_bytes()
                self.assertEqual(bytes_a, bytes_b)

            signals = _read_ndjson(Path(tmp_a) / "LogisticsSignal.ndjson")
            self.assertEqual(len(signals), 2)
            self.assertEqual(
                manifest_a["object_types"]["LogisticsSignal"]["file_sha256"],
                hashlib.sha256(
                    (Path(tmp_a) / "LogisticsSignal.ndjson").read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                manifest_a["object_types"]["LogisticsSignal"]["file_sha256"],
                manifest_b["object_types"]["LogisticsSignal"]["file_sha256"],
            )
