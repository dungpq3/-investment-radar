#!/usr/bin/env python3
from __future__ import annotations

import html
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


def compact_price(v):
    v = float(v)
    if v >= 1000:
        return f"{v/1000:.2f}k"
    if v >= 100:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.1f}"
    if v >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


def money(v):
    if v is None:
        return "?"
    x = float(v)
    sign = "+" if x > 0 else ""
    if abs(x) >= 1000:
        return f"{sign}{x/1000:.2f}b"
    return f"{sign}{x:.1f}m"


def etf_row(market, name):
    e = market.get("etf", {}).get(name, {})
    if e.get("status") != "OK":
        return [name, "?", "?"]
    return [
        name,
        money(e.get("latest_flow_usdm")),
        money(e.get("five_session_flow_usdm")),
    ]


def trap_row(assets, name):
    a = assets[name + "USDT"]
    z = a.get("volume_clusters", {}).get("overhead")
    if not z:
        return [name, compact_price(a["price"]), "?", "?"]
    zone = f"{compact_price(z['low'])}-{compact_price(z['high'])}"
    return [name, compact_price(a["price"]), zone, p(z.get("distance_pct"))]


def monospace_table(headers, rows):
    widths = []
    for i, h in enumerate(headers):
        widths.append(max(len(str(h)), *(len(str(r[i])) for r in rows)))
    line = lambda r: "  ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers)))
    return "\n".join([line(headers), line(["-" * w for w in widths]), *(line(r) for r in rows)])


def short_view(name, a, e):
    flow_latest = e.get("latest_flow_usdm") if e.get("status") == "OK" else None
    flow5 = e.get("five_session_flow_usdm") if e.get("status") == "OK" else None
    z = a.get("volume_clusters", {}).get("overhead")
    dist = z.get("distance_pct") if z else None
    ch24 = a.get("change_24h_pct")

    if flow_latest is None or flow5 is None or dist is None or ch24 is None:
        return "thiếu dữ liệu để ghép giá/flow/kẹt"

    flow_positive = flow_latest > 0 and flow5 > 0
    flow_negative = flow_latest < 0 and flow5 < 0
    near_trap = dist <= 1.0

    if flow_positive and ch24 < 0 and near_trap:
        return "ETF vào nhưng giá chưa hấp thụ; kẹt rất gần"
    if flow_positive and near_trap:
        return "ETF vào + giá giữ; đang sát vùng kẹt"
    if flow_positive and not near_trap:
        return "ETF vào; còn khoảng tới vùng kẹt chính"
    if flow_negative and near_trap:
        return "ETF yếu + kẹt gần; lực cản đang dày"
    if flow_negative:
        return "ETF rút; giá cần tự hấp thụ trước vùng kẹt"
    if near_trap:
        return "flow trái chiều; giá đang sát vùng kẹt"
    return "flow trái chiều; chưa bị ép ngay bởi vùng kẹt"


def build_report(market, radar):
    assets = market["assets"]
    names = ("BTC", "ETH", "SOL")

    price_rows = []
    for name in names:
        a = assets[name + "USDT"]
        price_rows.append(
            f"<b>{name}</b> {price(a['price'])} | 4H {p(a.get('change_4h_pct'))} | 24H {p(a.get('change_24h_pct'))}"
        )

    etf_rows = [etf_row(market, n) for n in names]
    trap_rows = [trap_row(assets, n) for n in names]

    etf_table = monospace_table(["Coin", "1D", "5S"], etf_rows)
    trap_table = monospace_table(["Coin", "Price", "Kẹt↑", "Δ"], trap_rows)

    views = []
    for name in names:
        a = assets[name + "USDT"]
        e = market.get("etf", {}).get(name, {})
        views.append(f"• <b>{name}</b>: {short_view(name, a, e)}")

    rotation = " > ".join(market.get("rotation_24h", []))
    summary = radar.get("summary", {})
    gem = f"Gem {summary.get('EARLY_IGNITION',0)} EARLY | {summary.get('WAKE_UP',0)} WAKE"

    dates = [
        e.get("latest_date")
        for e in market.get("etf", {}).values()
        if e.get("status") == "OK" and e.get("latest_date")
    ]
    etf_date = max(dates) if dates else "?"

    return "\n".join([
        f"📊 <b>MARKET BRIEF</b> {market.get('generated_at_ict','?')[11:16]} ICT | {market.get('regime','UNKNOWN')} | {market.get('status','?')}",
        *price_rows,
        f"Rotation 24H: {rotation} | {gem}",
        "",
        f"💰 <b>ETF FLOW</b> · {etf_date}",
        f"<pre>{html.escape(etf_table)}</pre>",
        "🧱 <b>VÙNG KẸT GIÁ</b> · volume 1H/14D proxy",
        f"<pre>{html.escape(trap_table)}</pre>",
        "🔎 <b>Giá × Flow × Kẹt</b>",
        *views,
        "",
        f"<code>market={market.get('run_id','?')} radar={radar.get('run_id','?')}</code>",
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
        "parse_mode": "HTML",
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
