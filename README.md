<div align="center">

<img src="docs/assets/regional-intel-workbench-card.svg" alt="Regional Intelligence Workbench product card" width="100%">

# Regional Intelligence Workbench

**A public-source regional intelligence console for local markets, client feeds, and provenance-ready decision packets.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-analyst%20console-009688?style=for-the-badge&logo=fastapi&logoColor=white)](app/main.py)
[![Tests](https://img.shields.io/badge/tests-37%2F37%20passing-16A34A?style=for-the-badge)](tests)
[![UI smoke](https://img.shields.io/badge/UI%20smoke-Playwright%20verified-2563EB?style=for-the-badge)](scripts/ui_smoke.py)
[![Public source only](https://img.shields.io/badge/guardrail-public%20source%20only-0F766E?style=for-the-badge)](#ethics-and-provenance)
[![Foundry ready](https://img.shields.io/badge/export-Foundry%20NDJSON-7C3AED?style=for-the-badge)](app/services/foundry_export.py)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-111827?style=for-the-badge)](LICENSE)

</div>

Regional Intelligence Workbench turns public regional signals into a practical analyst surface: permits, local news, open business data, source health, entity timelines, client-specific feeds, and read-only OODA packets. It is designed for high-context local-market research where every surfaced item needs provenance a human can inspect before acting.

The current workspace covers **Austin**, **Houston**, and **Gunnison / Crested Butte Valley**. Its first production-style client feed is the **Blanga Austin STNL + Redevelopment Feed** at `/blanga/austin`; the legacy `ve-vote-monitor` dashboard remains available at `/vote-monitor` for compatibility.

## Demo Preview

<p align="center">
  <img src="docs/assets/regional-intel-console.png" alt="Regional Intelligence Workbench analyst console showing Austin regional intelligence controls" width="92%">
</p>

<p align="center">
  <img src="docs/assets/blanga-austin-feed.png" alt="Blanga Austin client intelligence feed with deal radar metrics and map" width="92%">
</p>

## Current Snapshot

The committed public-source snapshot was refreshed on **2026-04-29 at 05:44 UTC** after repairing Austin's moved Small Business Division URL and compacting malformed legacy history records.

| Metric | Current value |
| --- | ---: |
| Regions | 3 |
| News items | 7 |
| Permit items | 120 |
| Public business leads | 240 |
| Public professional contacts | 7 |
| Organization profiles | 180 |
| Source-health rows | 20 |

## At a Glance

| Surface | What it does |
| --- | --- |
| `/intel` | Shared analyst console for search, graph exploration, opportunities, briefs, monitor rules, watchlists, annotations, collections, and source diagnostics. |
| `/blanga/austin` | Curated Austin brokerage feed for single-tenant retail, redevelopment, vacancy, commercial permit, and operator lead signals. |
| `/api/intel/*` | JSON endpoints for health, snapshots, recent signals, graph data, alerts, OODA packets, briefings, trends, source history, and analyst stores. |
| `regional-intel` | CLI for refreshes, search, opportunity ranking, briefing packs, Foundry export, and read-only OODA packets. |
| Foundry export | Local NDJSON export with row hashes, file hashes, source-health summary, and provenance drop reporting. |

## Showcase Path

For a quick demo, start the app locally, open `/intel` to show the shared regional console, then open `/blanga/austin` to show how the same graph becomes a polished client workflow. The strongest talking points are public-source guardrails, source-level provenance, the Austin redevelopment feed, and the read-only OODA packet path.

```bash
regional-intel serve --port 8768
regional-intel intel-ooda-packet --region austin_tx --json
```

See [`docs/SHOWCASE.md`](docs/SHOWCASE.md) for a tighter demo script,
CLI snippets, screenshot policy, and provenance guardrails.

## Intelligence Loop

```mermaid
flowchart LR
    A["Public sources<br/>open data, RSS, public pages, OSM"] --> B["Regional collector<br/>retry-aware source pulls"]
    B --> C["Snapshot + history<br/>regions, signals, source health"]
    C --> D["Analyst console<br/>search, graph, briefs, timelines"]
    C --> E["Client feeds<br/>Blanga Austin"]
    C --> F["Foundry export<br/>NDJSON + manifest"]
    C --> G["OODA packet<br/>read-only recommendations"]
    D --> H["Human review<br/>verify provenance before action"]
    E --> H
    G --> H
```

## Product Surfaces

### Intelligence Console

The shared analyst workspace at `/intel` supports cross-entity search across news, permits, businesses, contacts, and organizations. It also includes relationship graph exploration, opportunity scoring, regional briefs, entity timelines, source history, incident tracking, monitor rules, saved watchlists, analyst annotations, collections, and multi-collection briefing bundles.

### Client-Specific Feeds

Client feeds are curated views on top of the shared intelligence graph. The current feed is:

| Feed | Audience | Focus |
| --- | --- | --- |
| `/blanga/austin` | Single-tenant retail and redevelopment brokerage in the Austin MSA | Deal radar, vacancy and closure signals, retail construction, tenant-improvement activity, redevelopment watch, operator discovery, public contact paths, and recent change tracking. |

### Legacy Vote Monitor

The original vote-monitor surface remains available at `/vote-monitor` and is still served by the same FastAPI app. Active development is now centered on the regional intelligence platform.

## Regional Coverage

| Region | Live / adapted coverage | Current limits |
| --- | --- | --- |
| Austin, Texas | Austin Open Data permits, Hays County public permits, Williamson County public permits, Google News RSS filtering, OpenStreetMap / Overpass, Austin public economic-development contacts. | Subscription business outlets remain manual-reference only. |
| Houston, Texas | Houston public planning development spreadsheets, Houston-area public news signals, OpenStreetMap / Overpass, public economic-development and innovation contacts. | The generic Houston permitting portal is cataloged, but live extraction is limited to anonymous public planning artifacts. |
| Gunnison / Crested Butte Valley, Colorado | Public local news signals, official Gunnison County and Town of Crested Butte pages, OpenStreetMap / Overpass, public community-development contacts. | Live permit extraction still needs a stable anonymous public adapter. |

## Ethics and Provenance

This product is intentionally constrained:

- Public-source collection only.
- No login-gated scraping.
- No paywall bypass.
- No private-person dossiering.
- Public professional and business contacts only.
- Source name and source URL retained for surfaced signals.
- OODA packets are read-only and do not perform external refreshes or external writes.

## Architecture

```mermaid
flowchart TB
    CLI["regional-intel CLI"] --> Service["RegionalIntelService"]
    API["FastAPI app"] --> Service
    Service --> Sources["Public source adapters"]
    Sources --> Snapshot["RegionalIntelSnapshot"]
    Snapshot --> History["regional_intel_history.jsonl"]
    Snapshot --> Analyst["Analyst stores<br/>watchlist, annotations, collections, monitor rules"]
    Snapshot --> Insights["Insights layer<br/>alerts, opportunities, graph, timelines"]
    Insights --> UI["/intel and client views"]
    Insights --> Export["Foundry NDJSON export"]
    Insights --> OODA["Regional OODA packet"]
```

Key modules:

| Path | Role |
| --- | --- |
| `app/main.py` | FastAPI routes, HTML surfaces, and JSON API endpoints. |
| `app/services/regional_intel.py` | Region profiles, public source catalog, collection logic, ethics rules, and snapshots. |
| `app/services/client_views.py` | Curated client-feed composition, currently Blanga Austin. |
| `app/services/intel_insights.py` | Graph, opportunities, alerts, changes, timelines, briefings, and monitor evaluations. |
| `app/services/foundry_export.py` | Foundry-ready NDJSON export and manifest generation. |
| `app/services/regional_ooda.py` | Read-only regional OODA packet generation from stored snapshots. |

## Quick Start

```bash
cd /Users/aribs/Code/regional-intel-workbench
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
uvicorn app.main:app --reload --port 8768
```

Open:

- [http://127.0.0.1:8768](http://127.0.0.1:8768)
- [http://127.0.0.1:8768/intel](http://127.0.0.1:8768/intel)
- [http://127.0.0.1:8768/blanga/austin](http://127.0.0.1:8768/blanga/austin)
- [http://127.0.0.1:8768/vote-monitor](http://127.0.0.1:8768/vote-monitor)

## CLI

Primary CLI:

```bash
regional-intel --help
```

Compatibility alias:

```bash
ve-vote-monitor --help
```

Useful commands:

```bash
regional-intel intel-collect --force
regional-intel intel-snapshot --region austin_tx
regional-intel intel-search "Amy's Ice Creams" --region austin_tx
regional-intel intel-opportunities --region houston_tx
regional-intel intel-alerts --region austin_tx
regional-intel intel-region-briefing --region austin_tx
regional-intel intel-briefing <item_id>
regional-intel intel-monitor-rules --region austin_tx
regional-intel intel-foundry-export --region austin_tx --output-dir data/foundry/regional-intel
regional-intel intel-ooda-packet --region austin_tx --json
regional-intel serve --port 8768
```

`intel-foundry-export` writes local Foundry-ready NDJSON files for `Region`, `IntelItem`, and `IntelSourceHealth` from the latest stored snapshot by default. The manifest includes row hashes, file hashes, provenance drop counts, and a source-health summary. Add `--refresh` only when you want to refresh public sources before exporting.

`intel-ooda-packet` is read-only. It uses the latest stored regional snapshot, performs no external refresh, performs no Foundry/GCS/BQ writes, and returns safe act recommendations only.

## API Highlights

```text
GET  /api/intel/health
GET  /api/intel/regions
GET  /api/intel/sources
GET  /api/intel/snapshot
GET  /api/intel/recent
GET  /api/intel/search
GET  /api/intel/source-health
GET  /api/intel/source-history
GET  /api/intel/source-incidents
GET  /api/intel/alerts
GET  /api/intel/graph
GET  /api/intel/opportunities
GET  /api/intel/ooda-packet
GET  /api/intel/briefs
GET  /api/intel/region-briefing/{region_id}
GET  /api/intel/briefing/{item_id}
GET  /api/intel/items/{kind}/{item_id}
GET  /api/intel/timeline/{item_id}
GET  /api/intel/region-changes
GET  /api/intel/entity-changes
GET  /api/intel/watchlist
GET  /api/intel/collections
GET  /api/intel/bundles
GET  /api/intel/monitor-rules
GET  /api/client-views
GET  /api/client-views/{view_id}
```

`/api/intel/recent?limit=10&region=austin_tx` returns a compact feed for external dashboards, including item identity, kind, region, title, timestamp, severity, score, source provenance, tags, and a deep link back into `/intel`.

## Validation

API regression:

```bash
uv run --python 3.11 python -m unittest discover -s tests -v
```

Headless UI smoke:

```bash
python scripts/ui_smoke.py
```

The GitHub workflow uses the `SAPPHIRE_RUNNER` no-spend gate and skips hosted Actions unless a self-hosted runner label is configured. The UI smoke covers `/blanga/austin` on desktop and mobile, `/intel?region=austin_tx` on desktop, map presence, key metric rendering, and horizontal overflow regressions.

## Repository Layout

```text
app/        FastAPI app, templates, static frontend, services, and presenters
data/       Local snapshot history and runtime analyst stores
deploy/     Legacy/local deployment assets
scripts/    UI smoke and utility scripts
tests/      API, export, resilience, and workflow-gate regression tests
```

## Roadmap

- Scheduled refresh and notification workflow for monitor-rule matches.
- Stronger permit/news address enrichment for client feeds.
- Additional client-specific views beyond Blanga Austin.
- A stable anonymous public adapter for Gunnison / Crested Butte permit activity.
- Eventual repo extraction / rename once the intelligence platform fully outgrows the legacy vote-monitor identity.

## License

Apache-2.0. See [LICENSE](LICENSE).
