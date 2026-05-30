# Regional Intelligence Workbench

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-analyst%20console-009688)](app/main.py)
[![Tests](https://img.shields.io/badge/tests-47%20passing-16A34A)](tests)
[![Public source only](https://img.shields.io/badge/guardrail-public%20source%20only-0F766E)](#ethics-and-provenance)
[![License](https://img.shields.io/badge/license-Apache--2.0-111827)](LICENSE)

**A public-source regional intelligence console with provenance you can inspect before acting.**

Collects permits, local news, public business data, and OSM signals for geographic regions. Surfaces everything with source URLs, source-health diagnostics, and read-only OODA recommendations.

## What this does

An ethical, local-first analyst platform that turns open data into actionable regional intelligence. Every signal carries a source name and URL you can verify. Stale or failing sources are surfaced, not hidden.

Coverage today: **Austin, TX** · **Houston, TX** · **Gunnison / Crested Butte Valley, CO**.

## Quick start

```bash
# Install
pip install -e .
python -m playwright install chromium

# Serve locally
uvicorn app.main:app --reload --port 8768
```

Open three tabs:
- `/intel` — analyst console
- `/blanga/austin` — curated client feed
- `/admin` — operator dashboard (Leaflet map + source health)

```bash
# Read-only OODA packet from stored snapshot
regional-intel intel-ooda-packet --region austin_tx --json

# Export Foundry-ready NDJSON
regional-intel intel-foundry-export --region austin_tx \
    --output-dir data/foundry/regional-intel
```

## Architecture

```
Public sources (RSS, APIs, OSM)
        │
        ▼
┌──────────────────────────┐
│ RegionalIntelService     │
│ (retry-aware collector)  │
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ JSON snapshot + history  │
└──────────────────────────┘
        │
   ┌────┴────┬────────┬─────────┐
   ▼         ▼        ▼         ▼
/intel   /blanga/*  /admin   Foundry NDJSON
console  client     dash     + manifest
         views
```

## Key features

- **Public-source-only collection** — no login-gated scraping, no paywall bypass
- **Provenance on every signal** — source name, URL, and health history
- **Analyst console** — cross-entity search, relationship graph, opportunity scoring
- **Client feeds** — curated views for specific brokerage or tenant scenarios
- **Foundry-ready export** — NDJSON with row hashes, manifest, and provenance drops
- **Read-only OODA packets** — safe action recommendations from stored snapshots

## Tech stack

- Python 3.11+, FastAPI, Pydantic v2, Jinja2
- Vanilla JS frontends, Leaflet maps, Chart.js
- Playwright for browser smoke tests

## Data sources

All sources are public and openly accessible:
- City open-data permit portals
- Google News RSS feeds
- OpenStreetMap / Overpass
- Public economic-development contact directories

Subscription outlets are manual-reference only; no paywall bypass.

## Ethics and provenance

- Public-source collection only
- No private-person dossiering; organization-level public contacts only
- Source name + URL retained on every surfaced signal
- Source-health and history make stale or failing sources visible
- Humans verify provenance before any outreach or operational action

## Agent collaborators

See [AGENTS.md](AGENTS.md) for architecture details, safety boundaries, test commands, and deployment procedures.

## License

[Apache-2.0](LICENSE)
