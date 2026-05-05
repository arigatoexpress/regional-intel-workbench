# AGENTS.md — Regional Intelligence Workbench

## Project Overview

The **Regional Intelligence Workbench** is an ethical, public-source regional intelligence platform. It collects, scores, and surfaces open-data signals (permits, news, business listings, public contacts) for geographic regions. The stack is Python/FastAPI with Jinja2 templates, vanilla JS frontends, and Pydantic models throughout.

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Public sources │────▶│  RegionalIntelService │────▶│  JSON snapshot  │
│  (RSS, APIs, OSM)│     │   (retry-aware)       │     │  + history      │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   ┌─────────┐           ┌──────────┐           ┌─────────────┐
   │  /intel │           │/blanga/* │           │   /admin    │
   │ console │           │client    │           │  dashboard  │
   └─────────┘           │  views   │           └─────────────┘
                         └──────────┘
```

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app: routes, dependency injection, HTML response surfaces |
| `app/services/regional_intel.py` | Source catalog, region profiles, ethics rules, snapshot builder, retry logic |
| `app/services/client_views.py` | Curated client feed composition (Blanga Austin) |
| `app/services/intel_graph.py` | Relationship graph builder across entities |
| `app/services/intel_insights.py` | Opportunities, alerts, timelines, briefings, monitor evaluations |
| `app/services/regional_ooda.py` | Read-only OODA packet generation |
| `app/services/foundry_export.py` | Foundry-ready NDJSON + manifest with row hashes |
| `app/presenters/digest.py` | Markdown digest presenter |
| `app/intel_models.py` | Pydantic v2 models for all domain objects |
| `tests/` | API, export, resilience, and unit tests |

## Conventions

### Code style
- **Formatter:** `ruff format`
- **Linter:** `ruff check`
- **Type checker:** `mypy` with `pydantic.mypy` plugin
- Run all three locally before committing:
  ```bash
  uv run ruff check app/ tests/
  uv run ruff format --check app/ tests/
  uv run mypy app/ tests/
  ```

### Commits
- Use **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`
- Keep commits atomic. One logical change per commit.

### Models
- All domain objects are Pydantic v2 `BaseModel` subclasses in `app/intel_models.py`.
- Snapshot history is stored as newline-delimited JSON in `data/regional_intel_history.jsonl`.
- Use `Field(default_factory=list)` for mutable defaults.

### Testing
- Use `unittest.TestCase` for structure.
- Use `fastapi.testclient.TestClient` for API-level tests.
- Use `tempfile.TemporaryDirectory` for isolated JSON store tests.
- Monkeypatch `main.regional_intel_service.get_snapshot` to avoid network calls in tests.
- Run tests with: `uv run python -m pytest tests/ -v`

## Safety Boundaries

This codebase enforces ethical collection constraints in code:

1. **Public sources only** — No login-gated scraping, no paywall bypass.
2. **Professional contact scope** — Only organization-level public contacts.
3. **Provenance required** — Every signal keeps `source_name` and `source_url`.
4. **Read-only OODA** — The OODA packet endpoint performs no external writes.
5. **Source health visibility** — Failing or empty sources are surfaced, not hidden.

When modifying collection logic, preserve these invariants. Do not add authenticated scrapers, private-person dossiering, or credential-based data sources.

## Deployment

### Local
```bash
uv sync --frozen
uv run python -m uvicorn app.main:app --reload --port 8768
```

### Cloud Run (primary target)
```bash
docker build -t regional-intel-admin .
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=us-central1,_SERVICE=regional-intel-admin
```

### Environment variables
- `ADMIN_TOKEN` — Required for `/admin` API mutations (set via Secret Manager in production).
- `VE_MONITOR_ADMIN_TOKEN` — Legacy alias, still supported.

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`):
- **lint** job: `ruff check` + `ruff format --check` (runs on `ubuntu-latest`)
- **type-check** job: `mypy app/ tests/` (runs on `ubuntu-latest`)
- **test** job: pytest + UI smoke (requires self-hosted runner when `SAPPHIRE_RUNNER` is set)

All jobs install dependencies with `uv sync --frozen` from `uv.lock`.

## Useful Commands

```bash
# Run all checks
uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/ && uv run mypy app/ tests/

# Run tests
uv run python -m pytest tests/ -v

# Start dev server
uv run python -m uvicorn app.main:app --reload --port 8768

# CLI operations
uv run regional-intel intel-ooda-packet --region austin_tx --json
uv run regional-intel intel-foundry-export --region austin_tx --output-dir data/foundry/regional-intel
```

## Notes for Agents

- Do not commit to `main`. Create feature branches and open PRs.
- The `data/regional_intel_history.jsonl` file is committed data; append-only changes are safe to commit.
- If you add a new Pydantic model, run `mypy` to ensure it integrates cleanly.
- When adding new regions or sources, update `app/services/regional_intel.py` and add tests for any new scoring/helpers.
