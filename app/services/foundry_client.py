from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_URL_ENVS = ("KADIMA_FOUNDRY_URL", "PALANTIR_FOUNDRY_URL", "FOUNDRY_URL")
_TOKEN_ENVS = ("PALANTIR_FOUNDRY_TOKEN", "FOUNDRY_TOKEN", "FOUNDRY_API_TOKEN")
_CLIENT_ID_ENVS = ("PALANTIR_FOUNDRY_CLIENT_ID", "FOUNDRY_CLIENT_ID")
_CLIENT_SECRET_ENVS = ("PALANTIR_FOUNDRY_CLIENT_SECRET", "FOUNDRY_CLIENT_SECRET")
_ONTOLOGY_ENVS = ("PALANTIR_FOUNDRY_ONTOLOGY", "FOUNDRY_ONTOLOGY")
_DATASET_MAP_ENVS = ("PALANTIR_FOUNDRY_DATASET_MAP", "FOUNDRY_DATASET_MAP")
_DEFAULT_SECRETS_DIR = Path.home() / ".config" / "regional-intel-secrets"

_SSL_CTX = ssl.create_default_context()
try:
    import certifi

    _SSL_CTX.load_verify_locations(certifi.where())
except ImportError:
    pass


class FoundryError(Exception):
    """Base Foundry integration error."""


class FoundryConfigError(FoundryError):
    """Missing or invalid Foundry configuration."""


class FoundryAuthError(FoundryError):
    """Foundry authentication failure."""


class FoundryAPIError(FoundryError):
    """Foundry API failure."""

    def __init__(self, message: str, *, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _secrets_dir() -> Path:
    override = os.getenv("REGIONAL_INTEL_SECRETS_DIR") or os.getenv(
        "FOUNDRY_SECRETS_DIR"
    )
    return Path(override).expanduser() if override else _DEFAULT_SECRETS_DIR


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def _read_secret_file(name: str) -> str | None:
    path = _secrets_dir() / name
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        logger.warning("Unable to read Foundry config file %s: %s", path, exc)
    return None


def _resolve_url() -> str | None:
    return _first_env(*_URL_ENVS) or _read_secret_file("foundry_url")


def _resolve_token() -> str | None:
    return _first_env(*_TOKEN_ENVS) or _read_secret_file("foundry_token")


def _resolve_client_id() -> str | None:
    return _first_env(*_CLIENT_ID_ENVS) or _read_secret_file("foundry_client_id")


def _resolve_client_secret() -> str | None:
    return _first_env(*_CLIENT_SECRET_ENVS) or _read_secret_file(
        "foundry_client_secret"
    )


def _resolve_dataset_map() -> dict[str, str]:
    raw = _first_env(*_DATASET_MAP_ENVS) or _read_secret_file("foundry_dataset_map")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FoundryConfigError("Foundry dataset map must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise FoundryConfigError("Foundry dataset map must be a JSON object.")

    dataset_map: dict[str, str] = {}
    for key, value in parsed.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or not value
        ):
            raise FoundryConfigError(
                "Foundry dataset map entries must be non-empty string keys and values."
            )
        dataset_map[key] = value
    return dataset_map


def _resolve_ontology() -> str | None:
    return _first_env(*_ONTOLOGY_ENVS) or _read_secret_file("foundry_ontology")


def _quote_path_segment(value: str) -> str:
    return urllib.parse.quote(value.strip("/"), safe="")


def _quote_file_path(value: str) -> str:
    return urllib.parse.quote(value.strip("/"), safe="._-")


@dataclass
class FoundryAuth:
    base_url: str
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    @classmethod
    def from_env(cls) -> FoundryAuth:
        url = _resolve_url()
        if not url:
            raise FoundryConfigError(
                "No Foundry URL configured. Set KADIMA_FOUNDRY_URL, "
                "PALANTIR_FOUNDRY_URL, FOUNDRY_URL, or write "
                f"{_secrets_dir() / 'foundry_url'}."
            )
        token = _resolve_token()
        client_id = _resolve_client_id()
        client_secret = _resolve_client_secret()
        if not token and not (client_id and client_secret):
            raise FoundryConfigError(
                "No Foundry credentials configured. Set FOUNDRY_TOKEN, "
                "PALANTIR_FOUNDRY_TOKEN, or both FOUNDRY_CLIENT_ID and "
                f"FOUNDRY_CLIENT_SECRET, or write {_secrets_dir() / 'foundry_token'}."
            )
        return cls(
            base_url=url.rstrip("/"),
            token=token,
            client_id=client_id,
            client_secret=client_secret,
        )

    @property
    def auth_mode(self) -> str:
        return "token" if self.token else "oauth"

    def bearer_token(self) -> str:
        if self.token:
            return self.token
        return self._refresh_oauth()

    def _refresh_oauth(self) -> str:
        url = f"{self.base_url}/multipass/api/oauth2/token"
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id or "",
                "client_secret": self.client_secret or "",
            }
        ).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=20, context=_SSL_CTX
            ) as response:
                payload = json.loads(response.read())
        except Exception as exc:
            raise FoundryAuthError(f"OAuth token refresh failed: {exc}") from exc
        return str(payload["access_token"])


class FoundryClient:
    def __init__(
        self,
        auth: FoundryAuth,
        *,
        dataset_map: dict[str, str] | None = None,
        default_ontology: str | None = None,
        timeout: int = 30,
    ):
        self.auth = auth
        self.dataset_map = (
            dict(dataset_map) if dataset_map is not None else _resolve_dataset_map()
        )
        self.default_ontology = default_ontology or _resolve_ontology()
        self.timeout = timeout

    @classmethod
    def from_env(cls, **kwargs: Any) -> FoundryClient:
        return cls(FoundryAuth.from_env(), **kwargs)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.auth.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Authorization": f"Bearer {self.auth.bearer_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=_SSL_CTX
            ) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode()[:2000]
            except Exception:
                pass
            if exc.code in {401, 403}:
                raise FoundryAuthError(
                    f"Foundry API {method} {path} returned {exc.code}"
                ) from exc
            raise FoundryAPIError(
                f"Foundry API {method} {path} returned {exc.code}",
                status=exc.code,
                body=err_body,
            ) from exc
        except FoundryAuthError:
            raise
        except Exception as exc:
            raise FoundryAPIError(f"Foundry API {method} {path} failed: {exc}") from exc

    def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("GET", path, **kwargs)

    def list_datasets(self, *, page_size: int = 25) -> dict[str, Any]:
        return self._get("/api/v2/datasets", params={"pageSize": str(page_size)})

    def get_dataset(self, dataset_rid: str) -> dict[str, Any]:
        return self._get(f"/api/v2/datasets/{_quote_path_segment(dataset_rid)}")

    def list_ontologies(self) -> dict[str, Any]:
        return self._get("/api/v2/ontologies")

    def list_object_types(self, ontology: str) -> dict[str, Any]:
        return self._get(
            f"/api/v2/ontologies/{_quote_path_segment(ontology)}/objectTypes"
        )

    def list_action_types(self, ontology: str) -> dict[str, Any]:
        return self._get(
            f"/api/v2/ontologies/{_quote_path_segment(ontology)}/actionTypes"
        )

    def health(self) -> dict[str, Any]:
        try:
            datasets = self.list_datasets(page_size=1)
            return {
                "ok": True,
                "base_url": self.auth.base_url,
                "auth_mode": self.auth.auth_mode,
                "datasets_accessible": True,
                "configured_dataset_types": sorted(self.dataset_map),
                "sample_dataset_count": len(datasets.get("data") or []),
            }
        except FoundryAPIError as dataset_exc:
            try:
                ontologies = self.list_ontologies()
            except FoundryAuthError as exc:
                return {
                    "ok": False,
                    "base_url": self.auth.base_url,
                    "auth_mode": self.auth.auth_mode,
                    "error": str(exc),
                    "kind": "auth",
                }
            except FoundryError as ontology_exc:
                return {
                    "ok": False,
                    "base_url": self.auth.base_url,
                    "auth_mode": self.auth.auth_mode,
                    "error": str(ontology_exc),
                    "kind": "api",
                    "dataset_error": str(dataset_exc),
                }
            return {
                "ok": True,
                "base_url": self.auth.base_url,
                "auth_mode": self.auth.auth_mode,
                "datasets_accessible": False,
                "dataset_error": str(dataset_exc),
                "ontologies_accessible": True,
                "ontology_count": len(ontologies.get("data") or []),
                "configured_dataset_types": sorted(self.dataset_map),
            }
        except FoundryAuthError as exc:
            return {
                "ok": False,
                "base_url": self.auth.base_url,
                "auth_mode": self.auth.auth_mode,
                "error": str(exc),
                "kind": "auth",
            }
        except FoundryError as exc:
            return {
                "ok": False,
                "base_url": self.auth.base_url,
                "auth_mode": self.auth.auth_mode,
                "error": str(exc),
                "kind": "api",
            }

    def upload_dataset_file(
        self,
        dataset_rid: str,
        file_path: str,
        content: bytes | str,
        *,
        branch: str = "master",
        transaction_type: str = "UPDATE",
        content_type: str = "application/x-ndjson",
    ) -> dict[str, Any]:
        data = content.encode() if isinstance(content, str) else content
        dataset = _quote_path_segment(dataset_rid)
        foundry_file_path = _quote_file_path(file_path)
        url = (
            f"{self.auth.base_url}/api/v2/datasets/{dataset}/files/"
            f"{foundry_file_path}/upload"
        )
        url += "?" + urllib.parse.urlencode(
            {"branchName": branch, "transactionType": transaction_type}
        )
        headers = {
            "Authorization": f"Bearer {self.auth.bearer_token()}",
            "Accept": "application/json",
            "Content-Type": content_type,
        }
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=_SSL_CTX
            ) as response:
                raw = response.read()
                return (
                    json.loads(raw)
                    if raw
                    else {
                        "dataset_rid": dataset_rid,
                        "path": file_path,
                        "bytes_uploaded": len(data),
                    }
                )
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode()[:2000]
            except Exception:
                pass
            if exc.code in {401, 403}:
                raise FoundryAuthError(
                    f"Foundry upload to {dataset_rid}/{file_path} returned {exc.code}"
                ) from exc
            raise FoundryAPIError(
                f"Foundry upload to {dataset_rid}/{file_path} returned {exc.code}",
                status=exc.code,
                body=err_body,
            ) from exc

    def upload_object_file(
        self,
        object_type: str,
        content: str,
        *,
        branch: str = "master",
        prefix: str = "regional_intel",
    ) -> dict[str, Any]:
        dataset_rid = self.dataset_map.get(object_type)
        if not dataset_rid:
            raise FoundryConfigError(
                f"No Foundry dataset RID configured for object type {object_type!r}. "
                "Set FOUNDRY_DATASET_MAP or write foundry_dataset_map."
            )
        return self.upload_dataset_file(
            dataset_rid,
            f"{prefix}/{object_type}.ndjson",
            content,
            branch=branch,
        )


def configured_summary() -> dict[str, Any]:
    url = _resolve_url()
    token = _resolve_token()
    client_id = _resolve_client_id()
    ontology = _resolve_ontology()
    dataset_map = _resolve_dataset_map()
    return {
        "secrets_dir": str(_secrets_dir()),
        "url_configured": bool(url),
        "base_url": url.rstrip("/") if url else None,
        "credential_configured": bool(token or client_id),
        "auth_mode": "token" if token else "oauth" if client_id else None,
        "default_ontology": ontology,
        "configured_dataset_types": sorted(dataset_map),
    }
