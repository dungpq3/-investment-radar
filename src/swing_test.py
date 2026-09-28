#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data" / "radar" / "latest.json"
CONFIG = ROOT / "config" / "radar.json"
STATE = ROOT / "data" / "swing" / "state.json"
LATEST = ROOT / "data" / "swing" / "latest.json"
HISTORY_DIR = ROOT / "data" / "swing" / "history"
TRADES = ROOT / "data" / "swing" / "trades.ndjson"

ICT = dt.timezone(dt.timedelta(hours=7))
API_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def ict_date(ts: dt.datetime) -> str:
    return ts.astimezone(ICT).date().isoformat()


def ict_iso(ts: dt.datetime) -> str:
    return ts.astimezone(ICT).isoformat(timespec="seconds")


def pct(now: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return (now / base - 1.0) * 100.0


def http_json(url: str, timeout: int = 20, attempts: int = 3) -> Any:
    headers = {"User-Agent": "investment-radar/swing-test-v1"}
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last_exc}")


def choose_api_base() -> str:
    errors = []
    for base in API_BASES:
        try:
            payload = http_json(base + "/api/v3/time", attempts=2)
            if isinstance(payload, dict) and "serverTime" in payload:
                return base
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    raise RuntimeError("no Binance public API endpoint reachable; " + " | ".join(errors))


def klines(api_base: str, symbol: str, interval: str, limit: int = 1000) -> list[list[Any]]:
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    payload = http_json(f"{api_base}/api/v3/klines?{q}")
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected kline payload for {symbol}")
    return payload


def eligible(c: dict[str, Any], policy: dict[str, Any]) -> bool:
    return (
        c.get("opportunity_tier") in set(policy["eligible_tiers"])
        and c.get("state") in set(policy["eligible_states"])
        and float(c.get("signal_score") or 0.0) >= float(policy["min_signal_score"])
        and c.get("entry_reference", {}).get("state") != "EXTENDED_ABOVE_REF"
        and float(c.get("last_price") or 0.0) > 0
    )


def selector_score(c: dict[str, Any]) -> float:
    tier_bonus = {"READY": 10.0, "WATCH": 5.0}.get(c.get("opportunity_tier"), 0.0)
    return round(
        float(c.get("signal_score") or 0.0)
        + 0.15 * float(c.get("trigger_score") or 0.0)
        + 0.10 * float(c.get("structure_score") or 0.0)
        + tier_bonus,
        3,
    )


def ranked_candidates(candidates: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    out = [c for c in candidates if eligible(c, policy)]
    out.sort(
        key=lambda c: (
            -selector_score(c),
            float(c.get("spread_bps") if c.get("spread_bps") is not None else 1e9),
            c.get("symbol", ""),
        )
    )
    return out


def scheduled_slot(ts: dt.datetime, slots: list[int]) -> tuple[str, int]:
    local = ts.astimezone(ICT)
    minute_of_day = local.hour * 60 + local.minute
    slot_minutes = sorted(int(h) * 60 + 5 for h in slots)
    candidates = [(m if m <= minute_of_day else m - 24 * 60) for m in slot_minutes]
    chosen = max(candidates)
    chosen_mod = chosen % (24 * 60)
    hh = chosen_mod // 60
    mm = chosen_mod % 60
    delay = minute_of_day - chosen
    return f"{hh:02d}:{mm:02d}", int(delay)


def buy_fill(cash_usdt: float, market_price: float, fee_bps: float, slippage_bps: float) -> dict[str, float]:
    fill_price = market_price * (1.0 + slippage_bps / 10000.0)
    gross_qty = cash_usdt / fill_price
    fee_qty = gross_qty * fee_bps / 10000.0
    net_qty = gross_qty - fee_qty
    effective_cost = cash_usdt / net_qty
    return {
        "cash_usdt": cash_usdt,
        "market_price": market_price,
        "fill_price": fill_price,
        "gross_qty": gross_qty,
        "fee_qty": fee_qty,
        "net_qty": net_qty,
        "effective_cost": effective_cost,
    }


def sell_fill(qty: float, market_price: float, fee_bps: float, slippage_bps: float) -> dict[str, float]:
    fill_price = market_price * (1.0 - slippage_bps / 10000.0)
    gross_usdt = qty * fill_price
    fee_usdt = gross_usdt * fee_bps / 10000.0
    net_usdt = gross_usdt - fee_usdt
    return {
        "qty": qty,
        "market_price": market_price,
        "fill_price": fill_price,
        "gross_usdt": gross_usdt,
        "fee_usdt": fee_usdt,
        "net_usdt": net_usdt,
    }


def recalc_position(trade: dict[str, Any]) -> None:
    fills = trade["buy_fills"]
    qty = sum(float(x["net_qty"]) for x in fills)
    deployed = sum(float(x["cash_usdt"]) for x in fills)
    trade["qty"] = qty
    trade["capital_deployed_usdt"] = deployed
    trade["avg_effective_cost"] = deployed / qty if qty > 0 else 0.0


def current_levels(trade: dict[str, Any], policy: dict[str, Any]) -> dict[str, float]:
    avg = float(trade["avg_effective_cost"])
    initial_market = float(trade["entry_market_price"])
    return {
        "tp": avg * (1.0 + float(policy["take_profit_pct"]) / 100.0),
        "stop": avg * (1.0 + float(policy["stop_loss_pct"]) / 100.0),
        "dca": initial_market * (1.0 + float(policy["dca_trigger_pct"]) / 100.0),
    }


def update_excursions(trade: dict[str, Any], high: float, low: float) -> None:
    entry = float(trade["entry_market_price"])
    trade["mfe_pct"] = round(max(float(trade.get("mfe_pct", 0.0)), pct(high, entry)), 4)
    trade["mae_pct"] = round(min(float(trade.get("mae_pct", 0.0)), pct(low, entry)), 4)


def update_shadow_targets(trade: dict[str, Any], high: float, close_ms: int, policy: dict[str, Any]) -> None:
    entry = float(trade["entry_market_price"])
    for target in policy.get("shadow_targets_pct", [20, 25, 30]):
        key = str(target)
        rec = trade["shadow_targets"].setdefault(key, {"hit": False, "first_hit_close_ms": None})
        if not rec["hit"] and high >= entry * (1.0 + float(target) / 100.0):
            rec["hit"] = True
            rec["first_hit_close_ms"] = close_ms


def close_trade(
    trade: dict[str, Any],
    market_price: float,
    reason: str,
    event_close_ms: int,
    policy: dict[str, Any],
) -> None:
    sf = sell_fill(
        float(trade["qty"]),
        market_price,
        float(policy["fee_bps"]),
        float(policy["slippage_bps"]),
    )
    trade["sell_fill"] = sf
    trade["status"] = "CLOSED"
    trade["exit_reason"] = reason
    trade["exit_market_price"] = market_price
    trade["exit_event_close_ms"] = event_close_ms
    event_dt = dt.datetime.fromtimestamp(event_close_ms / 1000.0, tz=dt.timezone.utc)
    trade["exit_at_utc"] = event_dt.isoformat(timespec="seconds")
    trade["exit_at_ict"] = ict_iso(event_dt)
    deployed = float(trade["capital_deployed_usdt"])
    net = float(sf["net_usdt"])
    trade["net_pnl_usdt"] = round(net - deployed, 6)
    trade["net_return_pct"] = round((net / deployed - 1.0) * 100.0 if deployed else 0.0, 4)
    trade["hold_hours"] = round(
        (event_dt - parse_iso(trade["entry_at_utc"])).total_seconds() / 3600.0,
        3,
    )


def process_candles(trade: dict[str, Any], rows: list[list[Any]], policy: dict[str, Any]) -> list[str]:
    events: list[str] = []
    last_processed = int(trade.get("last_processed_close_ms") or 0)
    entry_ms = int(parse_iso(trade["entry_at_utc"]).timestamp() * 1000)

    for row in rows:
        if len(row) < 7:
            continue
        open_ms = int(row[0])
        close_ms = int(row[6])
        if close_ms <= last_processed:
            continue
        # Skip the partial 15m candle containing the synthetic market-at-signal entry.
        if open_ms < entry_ms:
            trade["last_processed_close_ms"] = max(int(trade.get("last_processed_close_ms") or 0), close_ms)
            continue
        if trade.get("status") != "OPEN":
            break

        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        update_excursions(trade, high, low)
        update_shadow_targets(trade, high, close_ms, policy)

        levels_before = current_levels(trade, policy)
        dca_due = not trade.get("dca_done") and low <= levels_before["dca"]
        tp_due = high >= levels_before["tp"]
        stop_due = low <= levels_before["stop"]

        # Conservative intrabar convention: adverse path first when high/low ordering is unknowable.
        if dca_due:
            fill = buy_fill(
                float(policy["dca_usdt"]),
                levels_before["dca"],
                float(policy["fee_bps"]),
                float(policy["slippage_bps"]),
            )
            fill["kind"] = "DCA1"
            fill["event_close_ms"] = close_ms
            trade["buy_fills"].append(fill)
            trade["dca_done"] = True
            trade["dca_event_close_ms"] = close_ms
            recalc_position(trade)
            events.append("DCA1")
            # Do not allow same-candle TP after a DCA touch; this avoids optimistic path ordering.
            levels_after = current_levels(trade, policy)
            if low <= levels_after["stop"]:
                close_trade(trade, levels_after["stop"], "STOP", close_ms, policy)
                events.append("STOP")
        else:
            if stop_due and tp_due:
                trade["intrabar_ambiguous_count"] = int(trade.get("intrabar_ambiguous_count", 0)) + 1
                close_trade(trade, levels_before["stop"], "STOP", close_ms, policy)
                events.append("STOP_AMBIGUOUS")
            elif stop_due:
                close_trade(trade, levels_before["stop"], "STOP", close_ms, policy)
                events.append("STOP")
            elif tp_due:
                close_trade(trade, levels_before["tp"], "TP25", close_ms, policy)
                events.append("TP25")

        trade["last_price"] = close
        trade["last_processed_close_ms"] = close_ms

    return events


def summarize(closed: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = [float(t.get("net_pnl_usdt") or 0.0) for t in closed]
    returns = [float(t.get("net_return_pct") or 0.0) for t in closed]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    deployed = sum(float(t.get("capital_deployed_usdt") or 0.0) for t in closed)
    return {
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate_pct": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
        "net_pnl_usdt": round(sum(pnl), 4),
        "avg_net_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
        "capital_deployed_sum_usdt": round(deployed, 2),
        "return_on_deployed_pct": round(sum(pnl) / deployed * 100.0, 4) if deployed else 0.0,
        "best_trade_usdt": round(max(pnl), 4) if pnl else 0.0,
        "worst_trade_usdt": round(min(pnl), 4) if pnl else 0.0,
    }


def open_trade(c: dict[str, Any], radar: dict[str, Any], policy: dict[str, Any], runner_ups: list[dict[str, Any]]) -> dict[str, Any]:
    ts = parse_iso(radar["generated_at_utc"])
    market_price = float(c["last_price"])
    fill = buy_fill(
        float(policy["initial_usdt"]),
        market_price,
        float(policy["fee_bps"]),
        float(policy["slippage_bps"]),
    )
    slot, delay = scheduled_slot(ts, list(policy.get("scan_slots_ict", [3, 7, 11, 15, 19, 23])))
    trade = {
        "trade_id": f"{c['symbol']}-{ts.strftime('%Y%m%dT%H%M%SZ')}",
        "paper_only": True,
        "status": "OPEN",
        "symbol": c["symbol"],
        "entry_at_utc": radar["generated_at_utc"],
        "entry_at_ict": radar.get("generated_at_ict"),
        "entry_run_id": radar["run_id"],
        "entry_market_price": market_price,
        "entry_signal_score": c.get("signal_score"),
        "entry_grade": c.get("score_grade"),
        "entry_structure_score": c.get("structure_score"),
        "entry_trigger_score": c.get("trigger_score"),
        "entry_opportunity_tier": c.get("opportunity_tier"),
        "entry_state": c.get("state"),
        "entry_volume_ratio_4h": c.get("volume_ratio_4h"),
        "entry_volume_ratio_8h": c.get("volume_ratio_8h"),
        "entry_ret_12h_pct": c.get("ret_12h_pct"),
        "entry_change_24h_pct": c.get("change_24h_pct"),
        "entry_drawdown_major_pct": c.get("drawdown_major_pct"),
        "entry_position_52w": c.get("position_52w"),
        "entry_quote_volume_24h": c.get("quote_volume_24h"),
        "entry_spread_bps": c.get("spread_bps"),
        "entry_reference": c.get("entry_reference"),
        "dca_reference_from_radar": c.get("dca_reference"),
        "selector_score": selector_score(c),
        "scheduled_scan_slot_ict": slot,
        "scan_delay_min": delay,
        "runner_ups": runner_ups,
        "buy_fills": [{**fill, "kind": "ENTRY"}],
        "dca_done": False,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "shadow_targets": {
            str(x): {"hit": False, "first_hit_close_ms": None}
            for x in policy.get("shadow_targets_pct", [20, 25, 30])
        },
        "last_price": market_price,
        "last_processed_close_ms": int(ts.timestamp() * 1000),
        "intrabar_ambiguous_count": 0,
    }
    recalc_position(trade)
    trade["levels"] = current_levels(trade, policy)
    return trade


def compact_runner(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": c.get("symbol"),
        "selector_score": selector_score(c),
        "signal_score": c.get("signal_score"),
        "trigger_score": c.get("trigger_score"),
        "structure_score": c.get("structure_score"),
        "tier": c.get("opportunity_tier"),
        "state": c.get("state"),
        "last_price": c.get("last_price"),
    }


def main() -> int:
    radar = load(RADAR, {})
    cfg = load(CONFIG, {})
    policy = cfg.get("swing_test", {})
    state = load(STATE, {
        "schema_version": 1,
        "active_trade": None,
        "closed_trades": [],
        "daily_locks": {},
    })

    if not policy.get("enabled", False):
        print("SWING_TEST=DISABLED")
        return 0
    if not radar.get("generated_at_utc") or not radar.get("run_id"):
        raise RuntimeError("radar latest missing generated_at_utc/run_id")

    generated = parse_iso(radar["generated_at_utc"])
    date_ict = ict_date(generated)
    candidates = radar.get("candidates", [])
    ranked = ranked_candidates(candidates, policy)
    active = state.get("active_trade")
    events: list[str] = []
    errors: list[str] = []
    api_base = None
    closed_trade_this_run = None

    # Update an existing trade with 15m high/low path so TP/DCA/SL touches are not lost between 4h scans.
    if active and active.get("status") == "OPEN":
        try:
            api_base = choose_api_base()
            rows = klines(api_base, active["symbol"], policy.get("tracking_interval", "15m"), 1000)
            events.extend(process_candles(active, rows, policy))
        except Exception as exc:
            errors.append(str(exc))

        # Mark-to-market from the current radar snapshot when available, otherwise retain last 15m close.
        c = next((x for x in candidates if x.get("symbol") == active.get("symbol")), None)
        if c and float(c.get("last_price") or 0) > 0:
            active["last_price"] = float(c["last_price"])
            active["last_radar_state"] = c.get("state")
            active["last_radar_tier"] = c.get("opportunity_tier")
            active["last_signal_score"] = c.get("signal_score")
            active["last_trigger_score"] = c.get("trigger_score")
            active["last_structure_score"] = c.get("structure_score")

        if active.get("status") == "OPEN":
            age_h = (generated - parse_iso(active["entry_at_utc"])).total_seconds() / 3600.0
            if age_h >= float(policy["max_hold_hours"]):
                close_trade(
                    active,
                    float(active.get("last_price") or active["entry_market_price"]),
                    "TIMEOUT",
                    int(generated.timestamp() * 1000),
                    policy,
                )
                events.append("TIMEOUT")

        active["levels"] = current_levels(active, policy) if active.get("status") == "OPEN" else active.get("levels")
        active["last_update_at_utc"] = radar["generated_at_utc"]
        active["last_update_at_ict"] = radar.get("generated_at_ict")

        if active.get("status") == "CLOSED":
            closed_trade_this_run = dict(active)
            state.setdefault("closed_trades", []).append(active)
            append(TRADES, active)
            exit_day = active.get("exit_at_ict", "")[:10] or date_ict
            state.setdefault("daily_locks", {}).setdefault(exit_day, {})["closed_trade_id"] = active["trade_id"]
            state["active_trade"] = None
            active = None
        else:
            state["active_trade"] = active

    # Exactly one active slot and at most one new entry per ICT day. No same-day re-entry after any lock/exit.
    # Push/manual runs may happen between scheduled scan slots; they can verify/track state but must not create
    # a synthetic entry that the scheduled strategy would never have seen.
    _, scan_delay = scheduled_slot(generated, list(policy.get("scan_slots_ict", [3, 7, 11, 15, 19, 23])))
    entry_window_ok = scan_delay <= int(policy.get("max_scan_delay_min", 120))
    if active is None and date_ict not in state.setdefault("daily_locks", {}):
        if not entry_window_ok:
            events.append("SCAN_ONLY_OFF_SCHEDULE")
        elif ranked:
            selected = ranked[0]
            n = int(policy.get("runner_up_count", 3))
            runners = [compact_runner(x) for x in ranked[1 : 1 + n]]
            active = open_trade(selected, radar, policy, runners)
            state["active_trade"] = active
            state["daily_locks"][date_ict] = {
                "trade_id": active["trade_id"],
                "symbol": active["symbol"],
                "locked_at_utc": radar["generated_at_utc"],
                "locked_at_ict": radar.get("generated_at_ict"),
                "runner_ups": runners,
            }
            events.append("ENTRY")
        else:
            events.append("SCAN_ONLY_NO_SETUP")
    elif active is None:
        events.append("SCAN_ONLY_DAY_LOCKED")

    if active and active.get("status") == "OPEN":
        last = float(active.get("last_price") or active["entry_market_price"])
        active["mark_move_pct"] = round(pct(last, float(active["entry_market_price"])), 4)
        # Estimated liquidation value after an immediate sell, for realistic mark-to-market.
        sf = sell_fill(float(active["qty"]), last, float(policy["fee_bps"]), float(policy["slippage_bps"]))
        active["mark_net_value_usdt"] = round(sf["net_usdt"], 6)
        active["mark_net_pnl_usdt"] = round(sf["net_usdt"] - float(active["capital_deployed_usdt"]), 6)
        active["mark_net_return_pct"] = round(
            (sf["net_usdt"] / float(active["capital_deployed_usdt"]) - 1.0) * 100.0,
            4,
        )

    # Keep daily-lock state bounded; 45 days is enough for a 30-day experiment plus audit margin.
    cutoff = (generated.astimezone(ICT).date() - dt.timedelta(days=45)).isoformat()
    state["daily_locks"] = {k: v for k, v in state.get("daily_locks", {}).items() if k >= cutoff}
    state["schema_version"] = 1
    state["updated_run_id"] = radar["run_id"]
    state["updated_at_utc"] = radar["generated_at_utc"]

    summary = summarize(state.get("closed_trades", []))
    latest = {
        "schema_version": 1,
        "run_id": radar["run_id"],
        "generated_at_utc": radar["generated_at_utc"],
        "generated_at_ict": radar.get("generated_at_ict"),
        "status": "PARTIAL" if errors else "OK",
        "paper_only": True,
        "strategy_version": "gem-swing-paper-v1.0.0",
        "policy": {
            "one_active_slot": True,
            "one_new_entry_per_ict_day": True,
            "initial_usdt": policy["initial_usdt"],
            "dca_usdt": policy["dca_usdt"],
            "dca_trigger_pct": policy["dca_trigger_pct"],
            "take_profit_pct": policy["take_profit_pct"],
            "stop_loss_pct": policy["stop_loss_pct"],
            "max_hold_hours": policy["max_hold_hours"],
            "fee_bps": policy["fee_bps"],
            "slippage_bps": policy["slippage_bps"],
            "tracking_interval": policy.get("tracking_interval", "15m"),
            "intrabar_policy": "conservative_adverse_first",
        },
        "events_this_run": events,
        "active_trade": active,
        "closed_trade_this_run": closed_trade_this_run,
        "today_lock": state.get("daily_locks", {}).get(date_ict),
        "eligible_count": len(ranked),
        "eligible_preview": [compact_runner(x) for x in ranked[:4]],
        "summary": summary,
        "errors": errors,
        "note": "Paper simulation only. No exchange order is created.",
    }

    write(STATE, state)
    write(LATEST, latest)
    append(HISTORY_DIR / generated.strftime("%Y-%m-%d.ndjson"), latest)

    print(
        f"SWING_TEST={latest['status']} EVENTS={','.join(events) or '-'} "
        f"ACTIVE={active['symbol'] if active else '-'} CLOSED={summary['closed_trades']} "
        f"NET={summary['net_pnl_usdt']:+.2f} RUN_ID={radar['run_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
