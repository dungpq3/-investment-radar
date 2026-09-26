# Investment Radar

Deterministic 4-hour market-data scanner for the Investment Intelligence workflow.

## Purpose

GitHub Actions collects and normalizes public Binance Spot market data so downstream reports do not need to rescan the full market every cycle.

The scanner intentionally does **not** make a trade decision. It classifies evidence into compact states:

- `DORMANT_BASE`
- `WAKE_UP`
- `EARLY_IGNITION`
- `ALREADY_MOVED`

The target pattern is a deeply drawn-down, liquid token that has based for weeks and begins showing 2-3 confirming 4H candles before a vertical move.

## Schedule

Runs at approximately **03:05 / 07:05 / 11:05 / 15:05 / 19:05 / 23:05 ICT**, just after Binance 4H candle closes.

## Outputs

- `data/radar/latest.json` — latest normalized radar snapshot for ChatGPT/IIF.
- `data/health/latest.json` — `OK`, `PARTIAL`, or `FAILED` pipeline health.
- `data/state/radar_state.json` — prior state for transition detection.
- `data/radar/history/YYYY-MM-DD.ndjson` — append-only run history.

Telegram is deliberately terse. ChatGPT/IIF can read the same `run_id` and add light contextual analysis without rescanning all symbols.

## Telegram

Add these repository Actions secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

If they are absent, the market scan still runs and persists JSON; Telegram is simply skipped.

## Data safety

This is a **public repository**. Do not put account/NAV/holding snapshots or any secrets here. See `docs/data-policy.md`.
