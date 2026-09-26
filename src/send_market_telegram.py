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
    if v >= 10:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def build_report(market, radar):
    assets = market["assets"]
    rows = []
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        a = assets[sym]
        name = sym.replace("USDT", "")
        rows.append(
            f"{name} {price(a['price'])} | 4H {p(a.get('change_4h_pct'))} | 24H {p(a.get('change_24h_pct'))}"
        )

    rotation = " > ".join(market.get("rotation_24h", []))
    summary = radar.get("summary", {})
    gem = f"Gem: {summary.get('EARLY_IGNITION',0)} EARLY | {summary.get('WAKE_UP',0)} WAKE"
    head = (
        f"📊 MARKET BRIEF {market.get('generated_at_ict','?')[11:16]} ICT | "
        f"{market.get('regime','UNKNOWN')}"
    )
    return "\n".join([
        head,
        *rows,
        f"Rotation 24H: {rotation}",
        gem,
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
