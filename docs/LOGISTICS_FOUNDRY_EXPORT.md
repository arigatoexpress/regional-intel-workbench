# Logistics Foundry Export

This export slice creates Foundry-ready object files for station-ops logistics
signals while preserving the regional-intel provenance rules.

It is intentionally public/synthetic only. It does not use FedEx package,
customer, employee, route, truck, aircraft, facility-security, pricing, or
production dispatch data.

## Object Files

The export writes:

- `LogisticsDataSource.ndjson`
- `LogisticsSignal.ndjson`
- `LogisticsForecastModel.ndjson`
- `manifest.json`

Each object type has stable object IDs, deterministic ordering, row hashes, and
file hashes.

## Allowed Signal Classifications

- `public`
- `synthetic`
- `derived_public`

Any signal marked `internal`, `restricted`, or with another unreviewed
classification is dropped and recorded in the manifest.

## Provenance Guard

`LogisticsSignal` rows are dropped when they are missing:

- `source_name`
- `source_url`
- `observed_at`

Rows are also dropped when `source_id` does not match a reviewed
`LogisticsDataSource`.

## Existing Export Command

```bash
uv run regional-intel intel-foundry-export \
  --include-logistics-fixture \
  --output-dir data/foundry/regional-intel
```

This uses the existing `intel-foundry-export` Palantir Foundry integration and
adds the logistics object files to the same manifest. The fixture is safe to
inspect because it uses only public-source metadata and synthetic station
baselines.

## Kadima Connectivity

The repo now includes a small Foundry REST client for safe live readbacks and
dry-run upload planning.

Configuration can come from environment variables or secret files:

| Setting | Environment Variables | Secret File Name |
| --- | --- | --- |
| Foundry base URL | `KADIMA_FOUNDRY_URL`, `PALANTIR_FOUNDRY_URL`, `FOUNDRY_URL` | `foundry_url` |
| Bearer token | `PALANTIR_FOUNDRY_TOKEN`, `FOUNDRY_TOKEN`, `FOUNDRY_API_TOKEN` | `foundry_token` |
| OAuth client id | `PALANTIR_FOUNDRY_CLIENT_ID`, `FOUNDRY_CLIENT_ID` | `foundry_client_id` |
| OAuth client secret | `PALANTIR_FOUNDRY_CLIENT_SECRET`, `FOUNDRY_CLIENT_SECRET` | `foundry_client_secret` |
| Default ontology | `PALANTIR_FOUNDRY_ONTOLOGY`, `FOUNDRY_ONTOLOGY` | `foundry_ontology` |
| Dataset map JSON | `PALANTIR_FOUNDRY_DATASET_MAP`, `FOUNDRY_DATASET_MAP` | `foundry_dataset_map` |

The default secret directory is `~/.config/regional-intel-secrets`. Set
`REGIONAL_INTEL_SECRETS_DIR` or `FOUNDRY_SECRETS_DIR` to use a different secure
directory. Keep that directory `700` and files `600`.

Check the target without exposing credentials:

```bash
uv run regional-intel intel-foundry-status --json
```

Discover visible ontologies, object types, and action types:

```bash
uv run regional-intel intel-foundry-discover --json
```

Generate a review packet:

```bash
uv run regional-intel intel-foundry-export \
  --include-logistics-fixture \
  --output-dir data/foundry/regional-intel \
  --json
```

Plan an upload without writing to Foundry:

```bash
uv run regional-intel intel-foundry-upload \
  --input-dir data/foundry/regional-intel \
  --json
```

Only add `--apply` after the dataset map points to approved Foundry dataset
RIDs for each object type.

## Current Kadima Readback

Last live readback: 2026-05-23.

The existing Kadima target is reachable at:

```text
https://kadima.usw-17.palantirfoundry.com
```

The configured credential can read Ontology metadata. The visible default
ontology is:

```text
ontology-8928df68-411d-463a-9683-33687b864e51
```

Visible object types include:

- `ExampleFlight`
- `ExampleRoute`
- `ExampleAirport`
- `ExampleCarrier`
- `ExampleAircraft`
- `ExampleRouteAlert`
- `Alert`
- `DailyBrief`
- `ServiceHealth`
- `ThreatIntel`
- `PaperTrade`

The dataset-list endpoint currently returns `404` for this credential/path, so
the status command treats Ontology metadata access as a valid connectivity
signal while marking dataset access as unavailable.

The current export packet dry run produces:

| Object Type | Rows | Upload State |
| --- | ---: | --- |
| `Region` | 3 | missing dataset RID |
| `IntelItem` | 556 | missing dataset RID |
| `IntelSourceHealth` | 20 | missing dataset RID |
| `LogisticsDataSource` | 3 | missing dataset RID |
| `LogisticsSignal` | 3 | missing dataset RID |
| `LogisticsForecastModel` | 1 | missing dataset RID |

This means the next Foundry step is not more code. The next step is choosing
whether to create governed datasets/object types for these regional objects, or
to map a narrow subset into existing approved object types such as `Alert`,
`DailyBrief`, or `ExampleRouteAlert`.

## Foundry Deployment Shape

1. Generate the object files locally.
2. Review `manifest.json` and dropped rows.
3. Configure approved dataset RIDs in `foundry_dataset_map`.
4. Dry-run `intel-foundry-upload` and confirm every object type is mapped.
5. Upload object files as Foundry datasets when access is approved.
6. Use Python transforms to validate and normalize fields.
7. Bind curated datasets to Ontology object types after governance review.

## Production Boundary

Do not connect this export to live FedEx internal systems until data
classification, retention, access control, and Ontology approval are complete.
