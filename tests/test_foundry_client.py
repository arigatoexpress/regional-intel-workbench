from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from app.services.foundry_client import FoundryAuth
from app.services.foundry_client import FoundryAPIError
from app.services.foundry_client import FoundryClient
from app.services.foundry_client import FoundryConfigError
from app.services.foundry_client import configured_summary
from app.services.foundry_upload import upload_foundry_packet


@pytest.fixture(autouse=True)
def _isolate_foundry_config(tmp_path, monkeypatch):
    monkeypatch.setenv("REGIONAL_INTEL_SECRETS_DIR", str(tmp_path))
    for name in (
        "KADIMA_FOUNDRY_URL",
        "PALANTIR_FOUNDRY_URL",
        "FOUNDRY_URL",
        "PALANTIR_FOUNDRY_TOKEN",
        "FOUNDRY_TOKEN",
        "FOUNDRY_API_TOKEN",
        "PALANTIR_FOUNDRY_CLIENT_ID",
        "FOUNDRY_CLIENT_ID",
        "PALANTIR_FOUNDRY_CLIENT_SECRET",
        "FOUNDRY_CLIENT_SECRET",
        "PALANTIR_FOUNDRY_ONTOLOGY",
        "FOUNDRY_ONTOLOGY",
        "PALANTIR_FOUNDRY_DATASET_MAP",
        "FOUNDRY_DATASET_MAP",
    ):
        monkeypatch.delenv(name, raising=False)


def test_auth_resolves_kadima_url_and_token_from_env(monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com/stargate")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")

    auth = FoundryAuth.from_env()

    assert auth.base_url == "https://kadima.example.com/stargate"
    assert auth.auth_mode == "token"


def test_auth_resolves_from_secret_files(tmp_path):
    (tmp_path / "foundry_url").write_text("https://kadima.example.com\n")
    (tmp_path / "foundry_token").write_text("secret-token\n")

    auth = FoundryAuth.from_env()

    assert auth.base_url == "https://kadima.example.com"
    assert auth.token == "secret-token"


def test_configured_summary_never_returns_secret_values(monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    monkeypatch.setenv("FOUNDRY_ONTOLOGY", "operations-ontology")
    monkeypatch.setenv(
        "FOUNDRY_DATASET_MAP",
        '{"Region":"ri.foundry.main.dataset.region"}',
    )

    summary = configured_summary()

    assert summary["base_url"] == "https://kadima.example.com"
    assert summary["credential_configured"] is True
    assert summary["default_ontology"] == "operations-ontology"
    assert summary["configured_dataset_types"] == ["Region"]
    assert "secret-token" not in json.dumps(summary)


def test_client_resolves_default_ontology_from_secret_file(tmp_path):
    (tmp_path / "foundry_url").write_text("https://kadima.example.com\n")
    (tmp_path / "foundry_token").write_text("secret-token\n")
    (tmp_path / "foundry_ontology").write_text("operations-ontology\n")

    client = FoundryClient.from_env()

    assert client.default_ontology == "operations-ontology"


def test_upload_dataset_file_encodes_nested_path(monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    client = FoundryClient.from_env()
    seen_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, **_kwargs):
        seen_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(
        "app.services.foundry_client.urllib.request.urlopen", fake_urlopen
    )

    client.upload_dataset_file(
        "ri.foundry.main.dataset.region",
        "regional_intel/Region.ndjson",
        "{}\n",
    )

    assert "files/regional_intel%2FRegion.ndjson/upload" in seen_urls[0]


def test_health_falls_back_to_ontology_when_dataset_listing_404(monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    client = FoundryClient.from_env()
    client.list_datasets = mock.Mock(
        side_effect=FoundryAPIError("dataset list missing", status=404)
    )
    client.list_ontologies = mock.Mock(return_value={"data": [{"apiName": "ontology"}]})

    health = client.health()

    assert health["ok"] is True
    assert health["datasets_accessible"] is False
    assert health["ontologies_accessible"] is True


def _write_export_packet(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "object_types": {
                    "Region": {"filename": "Region.ndjson", "rows": 1},
                    "IntelItem": {"filename": "IntelItem.ndjson", "rows": 2},
                },
            }
        )
    )
    (path / "Region.ndjson").write_text('{"object_id":"r1"}\n')
    (path / "IntelItem.ndjson").write_text('{"object_id":"i1"}\n{"object_id":"i2"}\n')


def test_upload_plan_reports_missing_dataset_map(tmp_path, monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    export_dir = tmp_path / "foundry"
    _write_export_packet(export_dir)
    client = FoundryClient.from_env()

    plan = upload_foundry_packet(export_dir, client=client, apply=False)

    assert plan["applied"] is False
    assert plan["ready"] is False
    assert plan["missing_datasets"] == ["IntelItem", "Region"]


def test_upload_packet_apply_uses_dataset_map(tmp_path, monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    monkeypatch.setenv(
        "FOUNDRY_DATASET_MAP",
        json.dumps(
            {
                "Region": "ri.foundry.main.dataset.region",
                "IntelItem": "ri.foundry.main.dataset.item",
            }
        ),
    )
    export_dir = tmp_path / "foundry"
    _write_export_packet(export_dir)
    client = FoundryClient.from_env()
    client.upload_object_file = mock.Mock(return_value={"bytes_uploaded": 5})

    result = upload_foundry_packet(export_dir, client=client, apply=True)

    assert result["applied"] is True
    assert result["uploaded_types"] == {"IntelItem": 2, "Region": 1}
    assert client.upload_object_file.call_count == 2


def test_upload_packet_apply_blocks_when_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("KADIMA_FOUNDRY_URL", "https://kadima.example.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "secret-token")
    export_dir = tmp_path / "foundry"
    _write_export_packet(export_dir)
    client = FoundryClient.from_env()

    with pytest.raises(FoundryConfigError, match="not ready"):
        upload_foundry_packet(export_dir, client=client, apply=True)
