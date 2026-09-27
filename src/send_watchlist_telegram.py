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
        return f"{x:,.0f}"
    if x >= 100:
        return f"{x:.1f}"
    if x >= 1:
        return f"{x:.3f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"


def signed(v):
    if v is None:
        return "?"
    return f"{float(v):+.1f}%"


def build_report(watch, cfg):
    added = set(watch.get("added_this_run", []))
    active = watch.get("active", [])[: int(cfg["paper_watch"]["telegram_max"])]

    head = (
        f"👀 <b>PAPER WATCH</b> {watch.get('generated_at_ict','?')[11:16]} ICT | "
        f"ACTIVE {watch.get('active_count',0)} | NEW {len(added)}"
    )
    parts = [
        head,
        "<i>Chỉ đưa vào tầm theo dõi/backtest — chưa vào lệnh.</i>",
    ]

    if not active:
        parts.append("Chưa có setup đạt ngưỡng paper-watch.")
    else:
        for item in active:
            new = "🆕 " if item["setup_id"] in added else ""
            target_hits = [k for k, hit in item.get("targets_hit", {}).items() if hit]
            hit_text = ",".join(target_hits) if target_hits else "-"
            er = item.get("entry_reference_at_watch") or {}
            dr = item.get("dca_reference_at_watch") or {}
            parts.append(
                f"{new}<b>{html.escape(item['symbol'].replace('USDT',''))}</b> "
                f"{float(item.get('last_score') or 0):.0f}/{item.get('watch_grade','?')} | "
                f"W {px(item.get('watch_price'))} → {px(item.get('last_price'))} | "
                f"Δ {signed(item.get('move_since_watch_pct'))}\n"
                f"  MFE/MAE {signed(item.get('mfe_snapshot_pct'))}/{signed(item.get('mae_snapshot_pct'))} | "
                f"hit {hit_text} | age {float(item.get('age_hours') or 0):.0f}h\n"
                f"  Entry-ref {px(er.get('low'))}-{px(er.get('high'))} | "
                f"DCA-ref {px(dr.get('dca1'))}/{px(dr.get('dca2'))}"
            )

    parts.append(f"<code>watch_run={watch.get('run_id','?')}</code>")
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
