#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "data" / "watchlist" / "latest.json"
CONFIG = ROOT / "config" / "radar.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def px(v):
    if v is None:
        return "?"
    x = float(v)
    if x >= 1000:
        return f"{x/1000:.1f}k"
    if x >= 100:
        return f"{x:.0f}"
    if x >= 1:
        return f"{x:.2f}"
    if x >= 0.01:
        return f"{x:.4f}"
    return f"{x:.6f}"


def signed(v):
    if v is None:
        return "?"
    return f"{float(v):+.0f}%"


def table(headers, rows):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    fmt = lambda r: " ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers)))
    return "\n".join([fmt(headers), *(fmt(r) for r in rows)])


def build_report(watch, cfg):
    added = set(watch.get("added_this_run", []))
    active = watch.get("active", [])[: int(cfg["paper_watch"]["telegram_max"])]

    parts = [
        f"🧪 <b>GEM LAB</b> {watch.get('generated_at_ict','?')[11:16]} | "
        f"{watch.get('active_count',0)} active · {len(added)} new",
        "<i>Watch/backtest only — chưa vào lệnh.</i>",
    ]

    if not active:
        parts.append("Không có setup đang theo dõi.")
    else:
        rows = []
        for item in active:
            coin = ("+" if item["setup_id"] in added else "") + item["symbol"].replace("USDT","")
            tier = (item.get("last_opportunity_tier") or item.get("watch_opportunity_tier") or "?")[:5]
            hit = "/".join(k for k, v in item.get("targets_hit", {}).items() if v) or "-"
            rows.append([
                coin,
                tier,
                px(item.get("watch_price")),
                signed(item.get("move_since_watch_pct")),
                signed(item.get("mfe_snapshot_pct")),
                signed(item.get("mae_snapshot_pct")),
                hit,
            ])
        parts.append("<pre>" + html.escape(table(["Coin","Tier","Watch","Δ","MFE","MAE","Hit"], rows)) + "</pre>")

    parts.append(f"<code>W{watch.get('run_id','?')[-7:-1]}</code>")
    return "\n".join(parts)


def send(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    print(text)
    if not token or not chat_id:
        print("TELEGRAM_WATCH=SKIPPED")
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
    print("TELEGRAM_WATCH=SENT")


def main():
    send(build_report(load(WATCH), load(CONFIG)))


if __name__ == "__main__":
    main()
