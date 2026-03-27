# Contributing

Thanks for contributing.

## Product direction

This repository currently contains two product surfaces:

- `Regional Intelligence Workbench` — the primary product and active development focus
- `ve-vote-monitor` — a retained legacy dashboard kept for compatibility and local use

When in doubt, optimize for the intelligence platform first.

## Development loop

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
uvicorn app.main:app --reload --port 8768
```

## Validation

```bash
python -m unittest discover -s tests -v
python scripts/ui_smoke.py
```

## Guardrails

- Keep collection public-source only
- Do not add login-gated scraping or paywall bypass
- Preserve provenance on surfaced intelligence items
- Prefer small, test-backed changes over large rewrites
