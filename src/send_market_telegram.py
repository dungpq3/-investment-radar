#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "data" / "market" / "latest.json"
RADAR = ROOT / "data" / "radar" / "latest.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def p(v):
    if v is None:
        return "?"
    return f"{float(v):+.1f}%"


def price(v):
    v = float(v)
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:,.1f}"
    if v >= 10:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.3f}"
    return f"{v:.5f}"


def money(v):
    if v is None:
        return "?"
    x = float(v)
    sign = "+" if x > 0 else ""
    return f"{sign}{x:,.1f}m"


def trap(a):
    vc = a.get("volume_clusters", {})
    z = vc.get("overhead")
    if not z:
        return "kẹt↑ ?"
    return f"kẹt↑ {price(z['low'])}-{price(z['high'])} ({p(z.get('distance_pct'))})"


def etf_line(market, name):
    e = market.get("etf", {}).get(name, {})
    if e.get("status") != "OK":
        return "ETF ?"
    return (
        f"ETF {money(e.get('latest_flow_usdm'))} | "
        f"5S {money(e.get('five_session_flow_usdm'))}"
    )


def build_report(market, radar):
    assets = market["assets"]
    rows = []
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        a = assets[sym]
        name = sym.replace("USDT", "")
        rows.append(
            f"{name} {price(a['price'])} | 4H {p(a.get('change_4h_pct'))} | 24H {p(a.get('change_24h_pct'))}\n"
            f"  {etf_line(market, name)} | {trap(a)}"
        )

    rotation = " > ".join(market.get("rotation_24h", []))
    summary = radar.get("summary", {})
    gem = f"Gem: {summary.get('EARLY_IGNITION',0)} EARLY | {summary.get('WAKE_UP',0)} WAKE"
    head = (
        f"📊 MARKET BRIEF {market.get('generated_at_ict','?')[11:16]} ICT | "
        f"{market.get('regime','UNKNOWN')} | {market.get('status','?')}"
    )
    dates = [
        e.get("latest_date")
        for e in market.get("etf", {}).values()
        if e.get("status") == "OK" and e.get("latest_date")
    ]
    etf_date = max(dates) if dates else "?"
    return "\n".join([
        head,
        *rows,
        f"Rotation 24H: {rotation}",
        f"ETF date: {etf_date} | {gem}",
        "Kẹt↑ = vùng volume 1H 14D phía trên (proxy, không phải holder cost basis).",
        f"market_run={market.get('run_id','?')} | radar_run={radar.get('run_id','?')}",
    ])


def send(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    print(text)
    if not token or not chat_id:
        print("TELEGRAM_MARKET=SKIPPED")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload)
    print("TELEGRAM_MARKET=SENT")


def main():
    send(build_report(load(MARKET), load(RADAR)))


if __name__ == "__main__":
    main()
