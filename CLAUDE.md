# Regional Intelligence Workbench

Ethical, public-source regional business intelligence platform. FastAPI + Jinja2 + Playwright. Python 3.11+.

## Architecture

- **Backend**: FastAPI with Jinja2 templates, async httpx/Playwright for collection
- **Frontend**: Server-rendered HTML with JavaScript interactivity (no React/Vue)
- **Storage**: JSONL files in `data/` (no database — file-based snapshots)
- **Deployment**: systemd services, designed for local or Pi deployment via Tailscale

## Directory Layout

```
regional-intel-workbench/
├── app/
│   ├── main.py                    # FastAPI server, 30+ endpoints, WebSocket handlers
│   ├── cli.py                     # CLI: 30+ commands (regional-intel, ve-vote-monitor)
│   ├── config.py                  # Environment-based settings
│   ├── models.py                  # DeFi vote escrow models (legacy)
│   ├── intel_models.py            # Regional intel: NewsSignal, PermitSignal, BusinessLead, etc.
│   ├── utils.py                   # Shared utilities
│   ├── services/
│   │   ├── regional_intel.py      # Core collection engine (Google News RSS, OSM, permits)
│   │   ├── intel_insights.py      # Briefings, opportunity scoring, alerts, monitor rules
│   │   ├── intel_graph.py         # Relationship graph (org → businesses/news/contacts)
│   │   ├── client_views.py        # Composable client feed framework
│   │   ├── regional_history_store.py  # JSONL snapshots, delta tracking
│   │   ├── intel_collection_store.py  # Analyst collections
│   │   ├── intel_bundle_store.py  # Multi-collection briefing bundles
│   │   ├── intel_monitor_store.py # Change watchers with triggers
│   │   ├── intel_watchlist_store.py # Personal watchlists
│   │   ├── intel_analyst_store.py # Analyst annotations
│   │   ├── aggregator.py         # Legacy vote escrow aggregation
│   │   └── strategy.py           # DeFi strategy modeling
│   ├── presenters/                # Response formatting
│   ├── static/                    # CSS, JS, images
│   └── templates/                 # Jinja2 HTML templates
├── data/                          # Runtime data (JSONL snapshots, collections, monitors)
├── deploy/
│   ├── systemd/                   # Service + timer units
│   └── pi/                        # Raspberry Pi-specific deployment
├── scripts/
│   └── ui_smoke.py                # Playwright UI smoke tests
├── skills/
│   └── ve-vote-monitor-pi/        # Claude skill for Pi monitoring
├── tests/
│   └── test_intel_app.py          # 6 integration tests
└── pyproject.toml                 # Package definition
```

## Key Commands

```bash
# Run server
uvicorn app.main:app --host 0.0.0.0 --port 8787

# CLI
regional-intel collect --region austin_tx
regional-intel snapshot --region austin_tx
regional-intel brief --region austin_tx
regional-intel health

# Tests (requires venv)
source .venv/bin/activate && python -m pytest tests/ -v

# UI smoke test
python scripts/ui_smoke.py
```

## Product Surfaces

| Route | Description |
|-------|-------------|
| `/intel` | Intelligence console — search, graph, scoring, monitor rules |
| `/blanga/austin` | Blanga client feed — Austin STNL brokerage workflow |
| `/vote-monitor` | Legacy DeFi vote escrow dashboard |

## Regions

- `austin_tx` — Austin, Texas
- `houston_tx` — Houston, Texas
- `gunnison_co` — Gunnison/Crested Butte Valley, Colorado

## Ethical Guardrails

- Public-source collection ONLY (no login-gated scraping)
- No paywall bypass
- Professional contacts only (no personal/private data)
- All signals require provenance (source URL + timestamp)

## Satellite Integration

Part of the Sapphire OS ecosystem. Orchestrated by `~/Code/Sapphire/`, not absorbed into it.
Designed to complement cyber-threat-bot (security signals) with business/regional intelligence.

## Code Style

- Python: type hints, async/await for I/O, Pydantic models
- Templates: Jinja2 with Tailwind CSS
- Services never import from other services — only from models/config
