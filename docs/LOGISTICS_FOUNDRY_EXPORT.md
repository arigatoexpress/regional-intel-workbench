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

## Foundry Deployment Shape

1. Generate the object files locally.
2. Review `manifest.json` and dropped rows.
3. Upload object files as Foundry datasets when access is approved.
4. Use Python transforms to validate and normalize fields.
5. Bind curated datasets to Ontology object types after governance review.

## Production Boundary

Do not connect this export to live FedEx internal systems until data
classification, retention, access control, and Ontology approval are complete.
