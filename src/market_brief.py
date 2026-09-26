#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "market" / "latest.json"
API_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "investment-radar/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def choose_base():
    for base in API_BASES:
        try:
            x = get_json(base + "/api/v3/time")
            if "serverTime" in x:
                return base
        except Exception:
            pass
    raise RuntimeError("No Binance public endpoint reachable")


def klines(base: str, symbol: str, interval: str, limit: int):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    return get_json(f"{base}/api/v3/klines?{q}")


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0 if b else 0.0


def asset(base: str, symbol: str):
    t = get_json(base + "/api/v3/ticker/24hr?" + urllib.parse.urlencode({"symbol": symbol}))
    rows4 = klines(base, symbol, "4h", 5)
    rowsd = klines(base, symbol, "1d", 9)
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    rows4 = [r for r in rows4 if int(r[6]) <= now_ms]
    rowsd = [r for r in rowsd if int(r[6]) <= now_ms]
    c4 = [float(r[4]) for r in rows4]
    cd = [float(r[4]) for r in rowsd]
    price = float(t["lastPrice"])
    return {
        "symbol": symbol,
        "price": price,
        "change_4h_pct": pct(c4[-1], c4[-2]) if len(c4) >= 2 else None,
        "change_12h_pct": pct(c4[-1], c4[-4]) if len(c4) >= 4 else None,
        "change_24h_pct": float(t["priceChangePercent"]),
        "change_7d_pct": pct(cd[-1], cd[-8]) if len(cd) >= 8 else None,
        "quote_volume_24h": float(t["quoteVolume"]),
        "last_closed_4h_ms": int(rows4[-1][6]) if rows4 else None,
    }


def regime(assets):
    btc = assets["BTCUSDT"]
    vals24 = [a["change_24h_pct"] for a in assets.values()]
    if btc["change_24h_pct"] >= 1.5 and sum(v > 0 for v in vals24) == 3:
        return "RISK_ON"
    if btc["change_24h_pct"] <= -1.5 and sum(v < 0 for v in vals24) == 3:
        return "RISK_OFF"
    return "MIXED"


def main():
    now = dt.datetime.now(dt.timezone.utc)
    base = choose_base()
    assets = {s: asset(base, s) for s in SYMBOLS}
    ranking = sorted(
        (s.replace("USDT", "") for s in SYMBOLS),
        key=lambda x: assets[x + "USDT"]["change_24h_pct"],
        reverse=True,
    )
    payload = {
        "schema_version": 1,
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_ict": now.astimezone(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
        "status": "OK",
        "source": "Binance Spot public market data",
        "regime": regime(assets),
        "rotation_24h": ranking,
        "assets": assets,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MARKET_BRIEF=OK REGIME={payload['regime']} ROTATION={'/'.join(ranking)}")


if __name__ == "__main__":
    main()
