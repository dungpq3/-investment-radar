#!/usr/bin/env python3
"""Evidence-only cross-asset macro overlay for BTC/ETH/SOL, no trading rules.

Use the same real-yield (FRED DFII10) and USD (DXY Yahoo) definitions as
Gold Regime. Gold ETF flows/COT are NOT proxies for BTC ETF flows/futures.
"""
import csv
import io
import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone


def direction(delta, threshold):
    if delta is None:
        return "UNKNOWN"
    if delta >= threshold:
        return "UP"
    if delta <= -threshold:
        return "DOWN"
    return "FLAT"


def fresh(date_text, today, days):
    try:
        age = (today - date.fromisoformat(date_text)).days
        return 0 <= age <= days
    except (ValueError, TypeError):
        return False


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "investment-radar-macro/1.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.read().decode("utf-8", errors="replace")


def real_yield(today, fetch=fetch_text):
    source = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
    result = {"source": source, "status": "UNKNOWN"}
    try:
        points = []
        for row in csv.DictReader(io.StringIO(fetch(source))):
            raw, stamp = row.get("DFII10"), row.get("DATE") or row.get("observation_date")
            if not raw or raw == "." or not stamp:
                continue
            val, day = float(raw), date.fromisoformat(stamp)
            if math.isfinite(val) and day <= today:
                points.append((day, val))
        points.sort()
        if len(points) >= 6:
            day, val = points[-1]
            delta = round((val - points[-6][1]) * 100.0, 2)
            result.update({"status": "OK" if fresh(day.isoformat(), today, 7) else "STALE",
                           "asof": day.isoformat(), "pct": val,
                           "delta_5sessions_bp": delta,
                           "direction": direction(delta, 5)})
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def dxy(today, fetch=fetch_text):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote("DX-Y.NYB", safe="")
           + "?interval=1d&range=1mo")
    result = {"source": url, "status": "UNKNOWN"}
    try:
        raw = json.loads(fetch(url))["chart"]["result"][0]
        points = [(datetime.fromtimestamp(t, timezone.utc).date(), float(px))
                  for t, px in zip(raw["timestamp"], raw["indicators"]["quote"][0]["close"])
                  if px is not None and math.isfinite(float(px))]
        if len(points) >= 6:
            day, val = points[-1]
            delta = round((val / points[-6][1] - 1.0) * 100.0, 3)
            result.update({"status": "OK" if fresh(day.isoformat(), today, 5) else "STALE",
                           "asof": day.isoformat(), "value": val,
                           "delta_5sessions_pct": delta,
                           "direction": direction(delta, 0.5)})
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def macro_state(ry, dollar):
    if ry.get("status") != "OK" or dollar.get("status") != "OK":
        return "UNKNOWN"
    a, b = ry.get("direction"), dollar.get("direction")
    if a == b == "UP":
        return "MACRO_HEADWIND"
    if a == b == "DOWN":
        return "MACRO_TAILWIND"
    return "MACRO_MIXED"


def build_overlay(today=None, yields_fn=real_yield, dxy_fn=dxy):
    today = today or datetime.now(timezone.utc).date()
    yield_data, dollar_data = yields_fn(today), dxy_fn(today)
    return {
        "schema_version": 1,
        "status": "OK" if yield_data.get("status") == dollar_data.get("status") == "OK" else "PARTIAL",
        "macro_state": macro_state(yield_data, dollar_data),
        "us_real_yield_10y": yield_data,
        "dxy": dollar_data,
        "policy": "Context-only; does not change crypto regime, target weights or trade signals.",
        "cross_asset_note": "TIPS yields + USD can affect BTC liquidity conditions, not a deterministic inverse correlation; Gold ETF/COT flows are NOT BTC flows.",
    }
