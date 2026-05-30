# AGENTS.md — Regional Intelligence Workbench

## What this repo does

Ethical, public-source regional intelligence platform. Collects, scores, and surfaces open-data signals (permits, news, business listings, public contacts) for geographic regions. FastAPI + Jinja2 + vanilla JS.

## Key directories and files

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app: routes, DI, HTML surfaces |
| `app/services/regional_intel.py` | Source catalog, region profiles, ethics rules, snapshots |
| `app/services/client_views.py` | Curated client feed composition (Blanga Austin) |
| `app/services/intel_insights.py` | Opportunities, alerts, timelines, briefings |
| `app/services/regional_ooda.py` | Read-only OODA packet generation |
| `app/services/foundry_export.py` | Foundry-ready NDJSON + manifest with row hashes |
| `app/intel_models.py` | Pydantic v2 domain models |
| `tests/` | API, export, resilience, and unit tests |

## How to run tests / dev server

```bash
# Run all checks
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy app/ tests/

# Run tests
uv run python -m pytest tests/ -v          # 47 tests

# Dev server
uv run python -m uvicorn app.main:app --reload --port 8768

# Browser smoke
python scripts/browser_smoke.py
```

## Safety boundaries

1. **Public sources only** — no login-gated scraping, no paywall bypass
2. **Professional contact scope** — organization-level public contacts only
3. **Provenance required** — every signal keeps `source_name` and `source_url`
4. **Read-only OODA** — performs no external writes
5. **Do NOT** add authenticated scrapers, private-person dossiering, or credential-based sources
6. **Do NOT** commit to `main`. Create feature branches and open PRs

## Current status

- 47 tests passing locally; admin frontend live at regional.sapphirealpha.xyz
- 3 regions covered; Foundry NDJSON export shipped
- Local-first demo path stable
