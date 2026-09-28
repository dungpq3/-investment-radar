# Investment Radar

Deterministic 4-hour market-data scanner for the Investment Intelligence workflow.

## Purpose

GitHub Actions collects and normalizes public Binance Spot market data so downstream reports do not need to rescan the full market every cycle.

The scanner intentionally does **not** make a real trade decision. It classifies evidence into compact states:

- `DORMANT_BASE`
- `WAKE_UP`
- `EARLY_IGNITION`
- `ALREADY_MOVED`

The target pattern is a deeply drawn-down, liquid token that has based for weeks and begins showing confirming 4H candles before a vertical move.

## GEM swing paper experiment

`gem-swing-paper-v1.0.0` converts the discovery stream into a controlled paper experiment while preserving the full market history for tuning.

Rules for the first version:

- Paper-only; no exchange key and no live order path.
- One active swing slot at a time.
- At most one new entry per ICT day.
- Candidate is locked at the first qualifying scheduled scan and is never replaced later that day using hindsight.
- Eligible candidates are `READY` or `WATCH`, `WAKE_UP`/`EARLY_IGNITION`, signal score >= 70, and not already extended above the entry reference.
- Paper market entry: 100 USDT.
- One mechanical paper DCA: +100 USDT if price reaches -12% from the original signal price.
- Canonical exit: +25% from current effective average cost; shadow checkpoints at +20/+25/+30% are recorded.
- Hard paper stop: -25% from current effective average cost.
- Maximum holding time: 168 hours.
- Simulation includes 10 bps fee per fill and 5 bps slippage per fill.
- Active positions are replayed with closed 15-minute candles so intraday TP/DCA/SL touches are not lost between 4H scans. Ambiguous same-candle high/low ordering uses a conservative adverse-first convention.
- After a round closes, the system remains scan-only for the rest of that ICT day. The next new entry is no earlier than the next day.
- Top runner-ups are retained as negative controls; legacy paper-watch cohorts remain stored for model tuning.

Formal experiment data is written under `data/swing/`. The intended review horizon is about 30 days, using net P/L, hit rate, expectancy, MFE/MAE, time-to-move, scan slot/delay, DCA frequency and runner-up outcomes before considering any live trading automation.

## Schedule

Runs at approximately **03:05 / 07:05 / 11:05 / 15:05 / 19:05 / 23:05 ICT**, just after Binance 4H candle closes. Push/manual runs may verify and update an active paper trade, but off-schedule runs do not create a new synthetic entry.

## Outputs

- `data/radar/latest.json` — latest normalized radar snapshot for ChatGPT/IIF.
- `data/health/latest.json` — `OK`, `PARTIAL`, or `FAILED` pipeline health.
- `data/state/radar_state.json` — prior state for transition detection.
- `data/radar/history/YYYY-MM-DD.ndjson` — append-only scanner history.
- `data/watchlist/` — broad legacy watch cohorts / negative-control evidence.
- `data/swing/latest.json` — one-slot GEM paper strategy state for the latest run.
- `data/swing/state.json` — persistent paper position, daily locks and closed rounds.
- `data/swing/trades.ndjson` — append-only closed paper rounds.
- `data/swing/history/YYYY-MM-DD.ndjson` — append-only strategy snapshots.

Telegram remains deliberately terse. The formal paper strategy state is persisted independently of the notification renderer.

## Telegram

Add these repository Actions secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

If they are absent, the market scan and paper experiment still run and persist JSON; Telegram is simply skipped.

## Data safety

This is a **public repository**. Do not put account/NAV/holding snapshots or any secrets here. The GEM experiment uses synthetic paper balances only. See `docs/data-policy.md`.
