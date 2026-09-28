#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "radar" / "latest.json"
CONFIG = ROOT / "config" / "radar.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def px(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "?"
    if x >= 1000:
        return f"{x:,.0f}"
    if x >= 100:
        return f"{x:.1f}"
    if x >= 1:
        return f"{x:.3f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"


def compact_line(c):
    er = c.get("entry_reference", {})
    score = float(c.get("signal_score") or 0)
    return (
        f"<b>{c['symbol'].replace('USDT','')}</b> {score:.0f}{c.get('score_grade','?')} "
        f"· {px(er.get('low'))}-{px(er.get('high'))}"
    )


def short_names(items):
    if not items:
        return "-"
    return " · ".join(
        f"<b>{c['symbol'].replace('USDT','')}</b> {float(c.get('signal_score') or 0):.0f}{c.get('score_grade','?')}"
        for c in items
    )


def build_report(latest, cfg):
    candidates = latest.get("candidates", [])
    ready = [c for c in candidates if c.get("opportunity_tier") == "READY"][: int(cfg["output"].get("telegram_ready", 3))]
    watch = [c for c in candidates if c.get("opportunity_tier") == "WATCH"][: int(cfg["output"].get("telegram_watch", 4))]
    extended = [c for c in candidates if c.get("opportunity_tier") == "EXTENDED"][: int(cfg["output"].get("telegram_extended", 3))]
    observe_n = sum(1 for c in candidates if c.get("opportunity_tier") == "OBSERVE")

    parts = [
        f"💎 <b>GEM RADAR</b> {latest.get('generated_at_ict','?')[11:16]} | "
        f"READY {len(ready)} · WATCH {len(watch)} · EXT {sum(1 for c in candidates if c.get('opportunity_tier') == 'EXTENDED')}"
    ]

    if ready:
        parts.append("🟢 <b>READY</b>\n" + "\n".join(compact_line(c) for c in ready))
    if watch:
        parts.append("👀 <b>WATCH</b>\n" + "\n".join(compact_line(c) for c in watch))
    if extended:
        parts.append("🔥 <b>EXT</b> " + short_names(extended))
    if observe_n:
        parts.append(f"○ OBSERVE {observe_n}")
    if not ready and not watch and not extended:
        parts.append("Không có setup nổi bật kỳ này.")

    parts.append(f"<code>R{latest.get('run_id','?')[-7:-1]}</code>")
    return "\n\n".join(parts)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    latest = load(LATEST)
    cfg = load(CONFIG)
    text = build_report(latest, cfg)
    print(text)
    if not token or not chat_id:
        print("TELEGRAM=SKIPPED missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return 0

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
        raise RuntimeError(f"Telegram send failed: {payload}")
    print("TELEGRAM=SENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
