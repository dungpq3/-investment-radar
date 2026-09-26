#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "radar.json"
LATEST_PATH = ROOT / "data" / "radar" / "latest.json"
HEALTH_PATH = ROOT / "data" / "health" / "latest.json"
STATE_PATH = ROOT / "data" / "state" / "radar_state.json"
HISTORY_DIR = ROOT / "data" / "radar" / "history"

API_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

STABLE_BASES = {
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "BUSD",
    "EUR", "AEUR", "EURI", "TRY", "BRL", "GBP", "JPY", "AUD", "RUB",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def ict_iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_ndjson(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def http_json(url: str, timeout: int = 20, attempts: int = 3) -> Any:
    headers = {"User-Agent": "investment-radar/1.0"}
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
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


def pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a / b - 1.0) * 100.0


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def closed_klines(rows: list[list[Any]], now_ms: int) -> list[list[Any]]:
    return [r for r in rows if len(r) > 6 and int(r[6]) <= now_ms]


def klines(api_base: str, symbol: str, interval: str, limit: int) -> list[list[Any]]:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = f"{api_base}/api/v3/klines?{query}"
    payload = http_json(url)
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected klines payload for {symbol} {interval}")
    return payload


def spread_bps(book: dict[str, Any]) -> float | None:
    bid = fnum(book.get("bidPrice"))
    ask = fnum(book.get("askPrice"))
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 10000


def weekly_features(rows: list[list[Any]]) -> dict[str, Any] | None:
    if len(rows) < 12:
        return None
    highs = [fnum(r[2]) for r in rows]
    lows = [fnum(r[3]) for r in rows]
    closes = [fnum(r[4]) for r in rows]
    current = closes[-1]
    if current <= 0:
        return None

    last52_h = highs[-52:] if len(highs) >= 52 else highs
    last52_l = lows[-52:] if len(lows) >= 52 else lows
    major_high = max(highs)
    high52 = max(last52_h)
    low52 = min(last52_l)
    pos52 = 0.0 if high52 <= low52 else (current - low52) / (high52 - low52)

    last26_l = lows[-26:] if len(lows) >= 26 else lows
    idx_low = min(range(len(last26_l)), key=last26_l.__getitem__)
    weeks_since_low = len(last26_l) - 1 - idx_low

    last12_h = highs[-12:] if len(highs) >= 12 else highs
    last12_l = lows[-12:] if len(lows) >= 12 else lows
    base_low = min(last12_l)
    base_high = max(last12_h)
    base_range_pct = 0.0 if base_low <= 0 else (base_high / base_low - 1.0) * 100.0

    return {
        "history_weeks": len(rows),
        "major_high": major_high,
        "drawdown_major_pct": pct(current, major_high),
        "high_52w": high52,
        "low_52w": low52,
        "position_52w": round(pos52, 4),
        "weeks_since_26w_low": weeks_since_low,
        "base_range_12w_pct": base_range_pct,
        "weekly_close": current,
    }


def volume_ratio(vols: list[float], idx: int, lookback: int = 20) -> float:
    start = max(0, idx - lookback)
    baseline = vols[start:idx]
    if len(baseline) < 5:
        return 0.0
    avg = statistics.fmean(baseline)
    return vols[idx] / avg if avg > 0 else 0.0


def four_hour_features(rows: list[list[Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    if len(rows) < 25:
        return None
    opens = [fnum(r[1]) for r in rows]
    highs = [fnum(r[2]) for r in rows]
    closes = [fnum(r[4]) for r in rows]
    vols = [fnum(r[5]) for r in rows]
    i = len(rows) - 1
    last = closes[i]
    if last <= 0:
        return None

    indices = list(range(max(0, i - 2), i + 1))
    ratios = [volume_ratio(vols, j) for j in indices]
    confirms = 0
    for off, j in enumerate(indices):
        green = closes[j] > opens[j]
        prior = closes[j - 1] if j > 0 else closes[j]
        advance = pct(closes[j], prior)
        if green and advance >= 0.75 and ratios[off] >= 1.20:
            confirms += 1

    prior_high20 = max(highs[max(0, i - 20):i])
    breakout = last > prior_high20
    near_breakout = last >= prior_high20 * float(cfg["signal"]["near_breakout_ratio"])

    old_vols = vols[i - 21:i - 1]
    volume_ratio_8h = 0.0
    if len(old_vols) >= 10:
        base = statistics.fmean(old_vols)
        if base > 0:
            volume_ratio_8h = statistics.fmean(vols[i - 1:i + 1]) / base

    return {
        "close_4h": last,
        "ret_4h_pct": pct(last, closes[i - 1]),
        "ret_8h_pct": pct(last, closes[i - 2]),
        "ret_12h_pct": pct(last, closes[i - 3]),
        "volume_ratio_4h": volume_ratio(vols, i),
        "volume_ratio_8h": volume_ratio_8h,
        "confirmed_candles_3x4h": confirms,
        "breakout_20x4h": breakout,
        "near_breakout_20x4h": near_breakout,
        "prior_high_20x4h": prior_high20,
        "last_closed_kline_close_time_ms": int(rows[-1][6]),
    }


def daily_features(rows: list[list[Any]]) -> dict[str, Any] | None:
    if len(rows) < 25:
        return None
    highs = [fnum(r[2]) for r in rows]
    closes = [fnum(r[4]) for r in rows]
    i = len(rows) - 1
    prior_high20 = max(highs[max(0, i - 20):i])
    return {
        "ret_3d_pct": pct(closes[i], closes[i - 3]),
        "daily_breakout_20d": closes[i] > prior_high20,
        "near_daily_breakout_20d": closes[i] >= prior_high20 * 0.98,
    }


def classify_state(feat: dict[str, Any], cfg: dict[str, Any]) -> str:
    sig = cfg["signal"]
    r12 = feat.get("ret_12h_pct", 0.0)
    v4 = feat.get("volume_ratio_4h", 0.0)
    c3 = feat.get("confirmed_candles_3x4h", 0)
    moved24 = feat.get("change_24h_pct", 0.0)

    if moved24 >= sig["already_moved_24h_pct"] or r12 >= sig["already_moved_12h_pct"]:
        return "ALREADY_MOVED"

    near_breakout = bool(
        feat.get("breakout_20x4h")
        or feat.get("near_breakout_20x4h")
        or feat.get("daily_breakout_20d")
        or feat.get("near_daily_breakout_20d")
    )
    if (
        sig["early_min_12h_pct"] <= r12 <= sig["early_max_12h_pct"]
        and v4 >= sig["early_min_volume_ratio_4h"]
        and c3 >= sig["early_min_confirmed_candles"]
        and near_breakout
    ):
        return "EARLY_IGNITION"

    if (
        sig["wake_min_12h_pct"] <= r12 <= sig["wake_max_12h_pct"]
        and v4 >= sig["wake_min_volume_ratio_4h"]
    ):
        return "WAKE_UP"

    return "DORMANT_BASE"


def signal_score(feat: dict[str, Any]) -> float:
    # Ranking only; not a probability or expected return.
    dd = abs(min(0.0, feat.get("drawdown_major_pct", 0.0)))
    base = min(20.0, feat.get("weeks_since_26w_low", 0) * 1.5)
    vol = min(25.0, max(0.0, feat.get("volume_ratio_4h", 0.0) - 1.0) * 12.5)
    mom = min(15.0, max(0.0, feat.get("ret_12h_pct", 0.0)) * 0.75)
    brk = 15.0 if feat.get("breakout_20x4h") or feat.get("daily_breakout_20d") else 8.0 if feat.get("near_breakout_20x4h") else 0.0
    liq = 5.0 if feat.get("spread_bps") is not None and feat.get("spread_bps", 9999) <= 40 else 2.5
    depth = min(20.0, dd / 5.0)
    return round(min(100.0, depth + base + vol + mom + brk + liq), 1)


def weekly_preselect(w: dict[str, Any], cfg: dict[str, Any]) -> bool:
    p = cfg["weekly_preselect"]
    return (
        w["drawdown_major_pct"] <= p["max_drawdown_major_pct"]
        and w["position_52w"] <= p["max_position_52w"]
        and w["weeks_since_26w_low"] >= p["min_weeks_since_26w_low"]
        and w["base_range_12w_pct"] <= p["max_base_range_12w_pct"]
    )


def safe_symbol(symbol_info: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if symbol_info.get("status") != "TRADING":
        return False
    if symbol_info.get("quoteAsset") != cfg["quote_asset"]:
        return False
    if not symbol_info.get("isSpotTradingAllowed", True):
        return False
    base = symbol_info.get("baseAsset", "")
    if base in STABLE_BASES:
        return False
    if base.endswith(LEVERAGED_SUFFIXES):
        return False
    return True


def main() -> int:
    started = now_utc()
    now_ms = int(started.timestamp() * 1000)
    cfg = load_json(CONFIG_PATH, {})
    prior_state = load_json(STATE_PATH, {"symbols": {}})
    errors: list[str] = []
    api_base = "UNKNOWN"

    try:
        api_base = choose_api_base()
        exchange = http_json(api_base + "/api/v3/exchangeInfo")
        tickers = http_json(api_base + "/api/v3/ticker/24hr")
        books = http_json(api_base + "/api/v3/ticker/bookTicker")

        ticker_map = {x.get("symbol"): x for x in tickers if isinstance(x, dict)}
        book_map = {x.get("symbol"): x for x in books if isinstance(x, dict)}
        symbols = [s for s in exchange.get("symbols", []) if safe_symbol(s, cfg)]

        liquid: list[dict[str, Any]] = []
        for s in symbols:
            sym = s["symbol"]
            t = ticker_map.get(sym, {})
            b = book_map.get(sym, {})
            qv = fnum(t.get("quoteVolume"))
            spr = spread_bps(b)
            if qv < cfg["min_quote_volume_24h"]:
                continue
            if spr is None or spr > cfg["max_spread_bps"]:
                continue
            liquid.append({
                "symbol": sym,
                "base_asset": s.get("baseAsset"),
                "quote_volume_24h": qv,
                "change_24h_pct": fnum(t.get("priceChangePercent")),
                "last_price": fnum(t.get("lastPrice")),
                "spread_bps": spr,
                "top_bid_usdt": fnum(b.get("bidPrice")) * fnum(b.get("bidQty")),
                "top_ask_usdt": fnum(b.get("askPrice")) * fnum(b.get("askQty")),
            })

        def get_weekly(meta: dict[str, Any]):
            sym = meta["symbol"]
            try:
                rows = closed_klines(klines(api_base, sym, "1w", int(cfg["weekly_history_limit"])), now_ms)
                return sym, weekly_features(rows), None
            except Exception as exc:
                return sym, None, str(exc)

        weekly_map: dict[str, dict[str, Any]] = {}
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for sym, wf, err in pool.map(get_weekly, liquid):
                if err:
                    errors.append(f"weekly {sym}: {err}")
                elif wf:
                    weekly_map[sym] = wf

        preselected = [
            m for m in liquid
            if m["symbol"] in weekly_map and weekly_preselect(weekly_map[m["symbol"]], cfg)
        ]

        def get_fast(meta: dict[str, Any]):
            sym = meta["symbol"]
            try:
                r4 = closed_klines(klines(api_base, sym, "4h", 80), now_ms)
                rd = closed_klines(klines(api_base, sym, "1d", 60), now_ms)
                return sym, four_hour_features(r4, cfg), daily_features(rd), None
            except Exception as exc:
                return sym, None, None, str(exc)

        fast_map: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for sym, f4, fd, err in pool.map(get_fast, preselected):
                if err:
                    errors.append(f"fast {sym}: {err}")
                elif f4 and fd:
                    fast_map[sym] = (f4, fd)

        candidates: list[dict[str, Any]] = []
        new_state: dict[str, Any] = {
            "schema_version": 1,
            "updated_at_utc": started.isoformat(timespec="seconds"),
            "symbols": {},
        }
        prior_symbols = prior_state.get("symbols", {}) if isinstance(prior_state, dict) else {}

        for meta in preselected:
            sym = meta["symbol"]
            if sym not in fast_map:
                continue
            f4, fd = fast_map[sym]
            feat = {**meta, **weekly_map[sym], **f4, **fd}
            state = classify_state(feat, cfg)
            previous = prior_symbols.get(sym, {}).get("state")
            feat["state"] = state
            feat["previous_state"] = previous
            feat["state_changed"] = previous is not None and previous != state
            feat["signal_score"] = signal_score(feat)
            candidates.append(feat)
            new_state["symbols"][sym] = {
                "state": state,
                "signal_score": feat["signal_score"],
                "last_price": feat["last_price"],
                "updated_at_utc": started.isoformat(timespec="seconds"),
            }

        rank = {"EARLY_IGNITION": 0, "WAKE_UP": 1, "DORMANT_BASE": 2, "ALREADY_MOVED": 3}
        candidates.sort(key=lambda x: (rank.get(x["state"], 9), -x["signal_score"]))
        candidates = candidates[: int(cfg["output"]["max_candidates"])]

        counts = {k: 0 for k in rank}
        for c in candidates:
            counts[c["state"]] = counts.get(c["state"], 0) + 1

        status = "OK"
        error_ratio = len(errors) / max(1, len(liquid) + len(preselected))
        if errors and error_ratio > 0.20:
            status = "PARTIAL"

        finished = now_utc()
        run_id = started.strftime("%Y%m%dT%H%M%SZ")
        latest = {
            "schema_version": 1,
            "run_id": run_id,
            "generated_at_utc": started.isoformat(timespec="seconds"),
            "generated_at_ict": ict_iso(started),
            "status": status,
            "source": {
                "venue": "Binance Spot public market data",
                "api_base": api_base,
                "closed_candles_only": True,
                "intervals": ["4h", "1d", "1w"],
            },
            "scan": {
                "spot_usdt_universe": len(symbols),
                "liquid_universe": len(liquid),
                "weekly_preselected": len(preselected),
                "fully_evaluated": len(fast_map),
                "errors": len(errors),
                "duration_seconds": round((finished - started).total_seconds(), 2),
            },
            "summary": counts,
            "candidates": candidates,
            "errors_sample": errors[:12],
        }
        health = {
            "schema_version": 1,
            "run_id": run_id,
            "status": status,
            "generated_at_utc": started.isoformat(timespec="seconds"),
            "generated_at_ict": ict_iso(started),
            "api_base": api_base,
            "duration_seconds": latest["scan"]["duration_seconds"],
            "errors": len(errors),
            "error_sample": errors[:5],
        }

        write_json(LATEST_PATH, latest)
        write_json(HEALTH_PATH, health)
        write_json(STATE_PATH, new_state)
        append_ndjson(HISTORY_DIR / started.strftime("%Y-%m-%d.ndjson"), {
            "run_id": run_id,
            "generated_at_utc": latest["generated_at_utc"],
            "status": status,
            "scan": latest["scan"],
            "summary": counts,
            "candidates": candidates,
        })
        print(
            f"RADAR_STATUS={status} RUN_ID={run_id} LIQUID={len(liquid)} "
            f"PRESELECT={len(preselected)} EVALUATED={len(fast_map)} ERRORS={len(errors)}"
        )
        return 0

    except Exception as exc:
        finished = now_utc()
        run_id = started.strftime("%Y%m%dT%H%M%SZ")
        health = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "FAILED",
            "generated_at_utc": started.isoformat(timespec="seconds"),
            "generated_at_ict": ict_iso(started),
            "api_base": api_base,
            "duration_seconds": round((finished - started).total_seconds(), 2),
            "error": str(exc),
        }
        write_json(HEALTH_PATH, health)
        write_json(LATEST_PATH, {
            "schema_version": 1,
            "run_id": run_id,
            "generated_at_utc": started.isoformat(timespec="seconds"),
            "generated_at_ict": ict_iso(started),
            "status": "FAILED",
            "candidates": [],
            "error": str(exc),
        })
        print(f"RADAR_STATUS=FAILED RUN_ID={run_id} ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
