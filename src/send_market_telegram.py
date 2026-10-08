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
    x = float(v)
    if x >= 1000:
        return f"{x/1000:.2f}k"
    if x >= 100:
        return f"{x:.0f}"
    if x >= 10:
        return f"{x:.1f}"
    if x >= 1:
        return f"{x:.2f}"
    return f"{x:.4f}"


def money(v):
    if v is None:
        return "?"
    x = float(v)
    sign = "+" if x > 0 else ""
    if abs(x) >= 1000:
        return f"{sign}{x/1000:.2f}b"
    return f"{sign}{x:.0f}m"


def table(headers, rows):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    fmt = lambda r: " ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers)))
    return "\n".join([fmt(headers), *(fmt(r) for r in rows)])


def etf_row(market, name):
    e = market.get("etf", {}).get(name, {})
    if e.get("status") != "OK":
        return [name, "?", "?"]
    return [name, money(e.get("latest_flow_usdm")), money(e.get("five_session_flow_usdm"))]


def trap_row(assets, name):
    a = assets[name + "USDT"]
    z = a.get("volume_clusters", {}).get("overhead")
    if not z:
        return [name, "?", "?"]
    return [name, f"{price(z['low'])}-{price(z['high'])}", p(z.get("distance_pct"))]


def verdict(name, a, e):
    z = a.get("volume_clusters", {}).get("overhead")
    dist = z.get("distance_pct") if z else None
    flow1 = e.get("latest_flow_usdm") if e.get("status") == "OK" else None
    flow5 = e.get("five_session_flow_usdm") if e.get("status") == "OK" else None
    ch24 = a.get("change_24h_pct")

    if None in (dist, flow1, flow5, ch24):
        return "data thiếu"

    flow_up = flow1 > 0 and flow5 > 0
    flow_down = flow1 < 0 and flow5 < 0
    near = dist <= 1.0

    if flow_up and ch24 < 0 and near:
        return "ETF↑ · giá↓ · kẹt gần → hấp thụ chưa xong"
    if flow_up and ch24 >= 0 and near:
        return "ETF↑ · giá↑ · kẹt gần → test cản"
    if flow_up and not near:
        return "ETF↑ · còn room tới cản"
    if flow_down and near:
        return "ETF↓ · kẹt gần → cản dày"
    if flow_down:
        return "ETF↓ · cần hấp thụ lại"
    return "flow lệch pha"


def build_report(market, radar):
    assets = market["assets"]
    names = ("BTC", "ETH", "SOL")

    px_rows = []
    for name in names:
        a = assets[name + "USDT"]
        px_rows.append([name, price(a["price"]), p(a.get("change_4h_pct")), p(a.get("change_24h_pct"))])

    etf_rows = [etf_row(market, n) for n in names]
    trap_rows = [trap_row(assets, n) for n in names]

    dates = [
        e.get("latest_date")
        for e in market.get("etf", {}).values()
        if e.get("status") == "OK" and e.get("latest_date")
    ]
    etf_date = max(dates) if dates else "?"
    rotation = " > ".join(market.get("rotation_24h", []))
    summary = radar.get("summary", {})

    views = [
        f"<b>{n}</b> {verdict(n, assets[n + 'USDT'], market.get('etf', {}).get(n, {}))}"
        for n in names
    ]

    macro = market.get("macro_overlay") or {}
    ry = macro.get("us_real_yield_10y") or {}
    dollar = macro.get("dxy") or {}
    ry_direction = ry.get("direction", "?") if ry.get("status") == "OK" else "STALE/UNKNOWN"
    dxy_direction = dollar.get("direction", "?") if dollar.get("status") == "OK" else "STALE/UNKNOWN"
    macro_line = (f"🌐 <b>MACRO</b> {macro.get('macro_state', 'UNKNOWN')} "
                  f"| TIPS10Y {ry_direction} · DXY {dxy_direction} "
                  f"(context only)")

    return "\n".join([
        f"₿ <b>CORE REBALANCE</b> {market.get('generated_at_ict','?')[11:16]} | {market.get('regime','?')} | {rotation}",
        "<pre>" + html.escape(table(["Coin","Px","4H","24H"], px_rows)) + "</pre>",
        f"💰 <b>ETF</b> {etf_date}",
        "<pre>" + html.escape(table(["Coin","1D","5S"], etf_rows)) + "</pre>",
        "🧱 <b>KẸT GIÁ</b>",
        "<pre>" + html.escape(table(["Coin","Vùng","Δ"], trap_rows)) + "</pre>",
        macro_line,
        "🔎 " + " | ".join(views),
        f"💎 {summary.get('EARLY_IGNITION',0)} early · {summary.get('WAKE_UP',0)} wake",
        f"<code>M{market.get('run_id','?')[-7:-1]} R{radar.get('run_id','?')[-7:-1]}</code>",
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
