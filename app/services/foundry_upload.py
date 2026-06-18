from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.foundry_client import FoundryClient
from app.services.foundry_client import FoundryConfigError


def load_export_packet(input_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FoundryConfigError(f"No manifest.json found in {input_dir}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    object_types = manifest.get("object_types") or {}
    files: dict[str, str] = {}
    for object_type, info in object_types.items():
        filename = info.get("filename")
        if not filename:
            continue
        path = input_dir / str(filename)
        if path.is_file():
            files[str(object_type)] = path.read_text(encoding="utf-8")
    return manifest, files


def plan_foundry_upload(
    input_dir: Path,
    *,
    client: FoundryClient,
    object_types: list[str] | None = None,
) -> dict[str, Any]:
    manifest, files = load_export_packet(input_dir)
    selected = object_types or sorted(files)
    uploadable = [name for name in selected if name in files]
    missing_files = [name for name in selected if name not in files]
    missing_datasets = [name for name in uploadable if name not in client.dataset_map]
    return {
        "input_dir": str(input_dir),
        "schema_version": manifest.get("schema_version"),
        "object_types": {
            name: {
                "rows": (manifest.get("object_types") or {}).get(name, {}).get("rows"),
                "dataset_configured": name in client.dataset_map,
                "bytes": len(files[name].encode("utf-8")),
            }
            for name in uploadable
        },
        "missing_files": missing_files,
        "missing_datasets": missing_datasets,
        "ready": not missing_files and not missing_datasets and bool(uploadable),
    }


def upload_foundry_packet(
    input_dir: Path,
    *,
    client: FoundryClient,
    object_types: list[str] | None = None,
    branch: str = "master",
    prefix: str = "regional_intel",
    apply: bool = False,
) -> dict[str, Any]:
    manifest, files = load_export_packet(input_dir)
    selected = object_types or sorted(files)
    plan = plan_foundry_upload(input_dir, client=client, object_types=selected)
    if not apply:
        plan["applied"] = False
        return plan
    if not plan["ready"]:
        raise FoundryConfigError(
            "Foundry upload is not ready. Missing files or dataset mappings: "
            + json.dumps(
                {
                    "missing_files": plan["missing_files"],
                    "missing_datasets": plan["missing_datasets"],
                },
                sort_keys=True,
            )
        )
    results: dict[str, Any] = {}
    for object_type in selected:
        result = client.upload_object_file(
            object_type,
            files[object_type],
            branch=branch,
            prefix=prefix,
        )
        results[object_type] = {
            key: value
            for key, value in result.items()
            if key not in {"token", "access_token", "client_secret"}
        }
    return {
        "applied": True,
        "input_dir": str(input_dir),
        "schema_version": manifest.get("schema_version"),
        "uploaded_types": {
            name: (manifest.get("object_types") or {}).get(name, {}).get("rows")
            for name in selected
        },
        "results": results,
    }
