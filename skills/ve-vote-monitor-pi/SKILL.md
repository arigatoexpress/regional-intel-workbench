---
name: ve-vote-monitor-pi
description: Use when operating the local ve Vote Monitor service on a Raspberry Pi, checking weekly vote recommendations, refreshing snapshots, or returning Telegram-ready digests for Blackhole, Supernova, and Full Sail over localhost or Tailscale.
---

# ve Vote Monitor Pi

Use this skill when the user wants the local Raspberry Pi vote-monitor service, not the browser dashboard internals.

## Quick commands

- Health and refresh:
  - `systemctl status ve-vote-monitor ve-vote-monitor-collector.timer`
  - `ve-vote-monitor collect --force`
- Local digest:
  - `ve-vote-monitor digest --format telegram --blackhole <veBLACK> --supernova <veNOVA> --fullsail <veSAIL>`
- Local API:
  - `curl "http://127.0.0.1:8787/api/digest?format=telegram&blackhole=<veBLACK>&supernova=<veNOVA>&fullsail=<veSAIL>"`

## Operating workflow

1. Check the local service and timer.
2. Refresh the snapshot if the data is stale.
3. Return the digest, not the full raw dashboard payload, unless the user explicitly asks for raw JSON.
4. Honor the Full Sail `IKA` preference unless the user explicitly asks to remove it.

## Telegram bot guidance

- Keep the Telegram bot thin.
- Let the bot call the local CLI or `/api/digest` endpoint and send the returned text directly.
- Prefer Telegram long polling on the Pi unless you already have a reliable public webhook path.

## Raspberry Pi guidance

- Run the monitor on the controller Pi, not the trading engine Pi, if browser scraping load matters.
- Keep the API bound to `127.0.0.1` by default.
- If you want remote access from the tailnet, expose the local service through your existing Tailscale setup rather than opening it broadly on the LAN.
