# Regional Intelligence Workbench Showcase

The workbench is a public-source analyst console for regional market signals,
client-specific feeds, source health, and read-only OODA packets.

## Demo Path

Start the app locally:

```bash
regional-intel serve --port 8768
```

Then open:

| Surface | URL | What to show |
|---|---|---|
| Shared console | `http://127.0.0.1:8768/intel` | search, graph, opportunities, source diagnostics, watchlists, collections |
| Blanga Austin feed | `http://127.0.0.1:8768/blanga/austin` | deal radar, vacancy and closure signals, commercial permit context, operator discovery |
| Legacy vote monitor | `http://127.0.0.1:8768/vote-monitor` | backwards-compatible legacy surface |
| Client API | `http://127.0.0.1:8768/api/client-views/blanga_austin` | JSON feed for a client-specific view |

## Strongest Talking Points

- Public-source-only collection model.
- Source URLs and source health retained for surfaced items.
- Austin, Houston, and Gunnison / Crested Butte coverage in one snapshot model.
- Client-specific feeds sit on top of the shared graph rather than forking the
  collector.
- Foundry-ready NDJSON export includes row hashes, file hashes, provenance drop
  counts, and source-health summary.
- OODA packets are read-only and do not refresh external sources or write to
  Foundry/GCS/BigQuery.

## CLI Snippets

```bash
regional-intel intel-snapshot --region austin_tx
regional-intel intel-search "redevelopment" --region austin_tx
regional-intel intel-opportunities --region houston_tx
regional-intel intel-region-briefing --region austin_tx
regional-intel intel-foundry-export --region austin_tx --output-dir data/foundry/regional-intel
regional-intel intel-ooda-packet --region austin_tx --json
```

## Provenance And Ethics

This product should remain safe to show because it is intentionally constrained:

- no login-gated scraping,
- no paywall bypass,
- no private-person dossiering,
- public professional and business contacts only,
- human review before action,
- no external writes from OODA packet generation.

## Visual Assets

Use these committed assets for quick decks or README previews:

- [assets/regional-intel-workbench-card.svg](assets/regional-intel-workbench-card.svg)
- [assets/regional-intel-console.png](assets/regional-intel-console.png)
- [assets/blanga-austin-feed.png](assets/blanga-austin-feed.png)
