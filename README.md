# Regional Intelligence Workbench

Regional Intelligence Workbench is an ethical, public-source intelligence platform for region-specific business research.

Today the primary product surface is a regional intelligence console focused on:

- Austin, Texas
- Houston, Texas
- Gunnison / Crested Butte Valley, Colorado

On top of the shared intelligence engine, the repo also supports composable client-specific views. The first production-style client feed is the Blanga Austin brokerage workflow at `/blanga/austin`.

This repository also retains the original `ve-vote-monitor` dashboard as a compatibility surface for local use, but active development is now centered on the intelligence platform.

## Product surfaces

### 1. Intelligence Console

The shared analyst workspace at `/intel` supports:

- cross-entity search across news, permits, businesses, contacts, and organizations
- relationship graph exploration
- opportunity scoring
- source health, source history, and incident tracking
- regional briefs and regional change logs
- entity timelines and entity-level change tracking
- saved watchlists
- analyst annotations and tags
- collections and multi-collection briefing bundles
- monitor rules for high-value change detection

### 2. Client-specific feeds

Client feeds are curated views built on top of the shared intelligence graph.

Current feed:

- `/blanga/austin` — Austin STNL / redevelopment brokerage view for the Blanga Intelligence System

This feed includes:

- deal radar
- vacancy and closure signals
- retail construction and tenant-improvement activity
- redevelopment and repositioning watch
- retail operator and tenant lead discovery
- public contact paths
- recent change tracking
- intelligence-map workflow with deep links back into `/intel`

### 3. Legacy vote monitor

The legacy vote-monitor surface remains available at `/vote-monitor` and is still served by the same FastAPI app. It is no longer the primary identity of the repo.

## Ethical guardrails

This product is intentionally constrained.

- Public-source collection only
- No login-gated scraping
- No paywall bypass
- No private-person dossiering
- Public professional/business contacts only
- Provenance retained for surfaced signals

## Current source coverage

Live or partially live sources currently include:

- Austin Open Data permits
- Hays County public permits
- Williamson County public permits
- Houston Planning public development spreadsheets
- Google News RSS with regional/source filtering
- OpenStreetMap / Overpass for mapped business discovery
- official regional economic-development and public-contact pages

Known limits:

- Gunnison / Crested Butte permit ingestion is still pending a stable anonymous public adapter
- Houston generic permit portal is cataloged, but only public planning spreadsheets are currently adapted live
- paywalled sources may be referenced manually but are not scraped

## Local development

```bash
cd "/Users/aribs/Documents/Organized/Codex Projects"
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

Primary CLI name:

```bash
regional-intel --help
```

Compatibility alias retained:

```bash
ve-vote-monitor --help
```

Useful commands:

```bash
regional-intel intel-collect --force
regional-intel intel-snapshot --region austin_tx
regional-intel intel-search "Amy's Ice Creams" --region austin_tx
regional-intel intel-opportunities --region houston_tx
regional-intel intel-briefing <item_id>
regional-intel intel-collections
regional-intel intel-bundles
regional-intel intel-monitor-rules --region austin_tx
regional-intel intel-foundry-export --region austin_tx --output-dir data/foundry/regional-intel
regional-intel serve --port 8768
```

`intel-foundry-export` writes local Foundry-ready NDJSON files for
`Region`, `IntelItem`, and `IntelSourceHealth` from the latest stored snapshot
by default. Add `--refresh` only when you want to refresh public sources before
exporting.

## Validation

API regression:

```bash
python -m unittest discover -s tests -v
```

Headless UI smoke:

```bash
python scripts/ui_smoke.py
```

The UI smoke covers:

- `/blanga/austin` on desktop and mobile
- `/intel?region=austin_tx` on desktop
- map presence
- key section/metric rendering
- horizontal overflow regressions

## API highlights

```text
GET  /api/intel/health
GET  /api/intel/snapshot
GET  /api/intel/recent
GET  /api/intel/search
GET  /api/intel/source-health
GET  /api/intel/source-history
GET  /api/intel/source-incidents
GET  /api/intel/briefs
GET  /api/intel/graph
GET  /api/intel/opportunities
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

`/api/intel/recent?limit=10&region=austin_tx` returns a compact feed for
external dashboards, including `id`, `kind`, `region`, `title`, `timestamp`,
`severity`, `score`, source provenance, tags, and an `/intel` deep link.

## Repository layout

- `/Users/aribs/Documents/Organized/Codex Projects/app` — FastAPI app, templates, static frontend, service layer
- `/Users/aribs/Documents/Organized/Codex Projects/data` — local snapshot history and runtime stores
- `/Users/aribs/Documents/Organized/Codex Projects/tests` — API regression tests
- `/Users/aribs/Documents/Organized/Codex Projects/scripts` — smoke and utility scripts
- `/Users/aribs/Documents/Organized/Codex Projects/deploy` — legacy/local deployment assets

## Near-term roadmap

- scheduled refresh and notification workflow for monitor-rule matches
- stronger permit/news address enrichment for client feeds
- more client-specific views beyond Blanga Austin
- eventual repo extraction / rename so the intelligence platform stands on its own without the legacy vote-monitor history

## License

Apache-2.0. See `/Users/aribs/Documents/Organized/Codex Projects/LICENSE`.
