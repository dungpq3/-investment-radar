#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "market" / "latest.json"
API_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ETF_URLS = {
    "BTC": "https://farside.co.uk/btc/",
    "ETH": "https://farside.co.uk/eth/",
    "SOL": "https://farside.co.uk/sol/",
}


def request_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 investment-radar/1.0",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_json(url: str):
    return json.loads(request_text(url))


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


def closed(rows, now_ms):
    return [r for r in rows if int(r[6]) <= now_ms]


def volume_clusters(rows, price: float, bins: int = 48):
    if len(rows) < 48 or price <= 0:
        return {"method": "14d_1h_quote_volume_profile_proxy", "overhead": None, "support": None}

    lows = [float(r[3]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        return {"method": "14d_1h_quote_volume_profile_proxy", "overhead": None, "support": None}

    width = (hi - lo) / bins
    weights = [0.0] * bins

    for r in rows:
        typical = (float(r[2]) + float(r[3]) + float(r[4])) / 3.0
        quote_vol = float(r[7]) if len(r) > 7 else float(r[5]) * typical
        idx = min(bins - 1, max(0, int((typical - lo) / width)))
        weights[idx] += quote_vol

    zones = []
    for i, weight in enumerate(weights):
        zlo = lo + i * width
        zhi = zlo + width
        center = (zlo + zhi) / 2
        zones.append({"low": zlo, "high": zhi, "center": center, "quote_volume": weight})

    above = [z for z in zones if z["center"] > price * 1.002]
    below = [z for z in zones if z["center"] < price * 0.998]

    overhead = max(above, key=lambda z: z["quote_volume"]) if above else None
    support = max(below, key=lambda z: z["quote_volume"]) if below else None

    if overhead:
        overhead["distance_pct"] = pct(overhead["center"], price)
    if support:
        support["distance_pct"] = pct(support["center"], price)

    return {
        "method": "14d_1h_quote_volume_profile_proxy",
        "note": "Proxy from Binance 1h traded quote volume; not holder cost basis.",
        "overhead": overhead,
        "support": support,
    }


def asset(base: str, symbol: str):
    t = get_json(base + "/api/v3/ticker/24hr?" + urllib.parse.urlencode({"symbol": symbol}))
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    rows4 = closed(klines(base, symbol, "4h", 5), now_ms)
    rowsd = closed(klines(base, symbol, "1d", 9), now_ms)
    rows1h = closed(klines(base, symbol, "1h", 336), now_ms)

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
        "volume_clusters": volume_clusters(rows1h, price),
    }


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.in_row = False
        self.in_cell = False
        self.cell = []
        self.cells = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_row = True
            self.cells = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.in_row and tag in ("td", "th") and self.in_cell:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
            self.cell = []
        elif tag == "tr" and self.in_row:
            if self.cells:
                self.rows.append(self.cells)
            self.in_row = False
            self.cells = []


def parse_flow(value: str):
    s = value.replace(",", "").replace("−", "-").strip()
    if not s or s in {"-", "–", "—"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group(0))
    return -abs(v) if neg else v


def etf_flow_is_fresh(asof: dt.date, today: dt.date, max_calendar_days: int = 6) -> bool:
    age = (today - asof).days
    return 0 <= age <= max_calendar_days


def etf_flow(asset_name: str):
    url = ETF_URLS[asset_name]
    html = request_text(url)
    parser = TableRows()
    parser.feed(html)

    points = []
    for cells in parser.rows:
        if not cells:
            continue
        try:
            day = dt.datetime.strptime(cells[0], "%d %b %Y").date()
        except ValueError:
            continue
        total = parse_flow(cells[-1])
        if total is not None:
            points.append((day, total))

    if not points:
        raise RuntimeError(f"No ETF rows parsed for {asset_name}")

    points.sort(key=lambda x: x[0])
    recent = points[-5:]
    latest_day, latest_flow = points[-1]
    age_days = (dt.datetime.now(dt.timezone.utc).date() - latest_day).days
    return {
        "status": "OK" if etf_flow_is_fresh(latest_day, dt.datetime.now(dt.timezone.utc).date()) else "STALE",
        "data_age_days": age_days,
        "source": "Farside Investors",
        "source_url": url,
        "latest_date": latest_day.isoformat(),
        "latest_flow_usdm": latest_flow,
        "five_session_flow_usdm": round(sum(v for _, v in recent), 1),
        "sessions_in_5d_sum": len(recent),
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

    etf = {}
    etf_errors = []
    for name in ("BTC", "ETH", "SOL"):
        try:
            etf[name] = etf_flow(name)
            if etf[name].get("status") != "OK":
                etf_errors.append(f"{name}: ETF data {etf[name].get('status')}")
        except Exception as exc:
            etf[name] = {
                "status": "UNKNOWN",
                "source": "Farside Investors",
                "source_url": ETF_URLS[name],
                "error": str(exc),
            }
            etf_errors.append(f"{name}: {exc}")

    # Macro is an independent evidence overlay, never a BTC trade trigger.
    try:
        from macro_overlay import build_overlay
        macro = build_overlay()
    except Exception as exc:
        macro = {"status": "PARTIAL", "macro_state": "UNKNOWN", "error": type(exc).__name__}

    payload = {
        "schema_version": 2,
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_ict": now.astimezone(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
        "status": "OK" if not etf_errors and macro.get("status") == "OK" else "PARTIAL",
        "source": {
            "market": "Binance Spot public market data",
            "etf": "Farside Investors",
        },
        "regime": regime(assets),
        "macro_overlay": macro,
        "rotation_24h": ranking,
        "assets": assets,
        "etf": etf,
        "errors": etf_errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"MARKET_BRIEF={payload['status']} REGIME={payload['regime']} "
        f"ROTATION={'/'.join(ranking)} ETF_ERRORS={len(etf_errors)}"
    )


if __name__ == "__main__":
    main()
