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


def f(v, digits=1):
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def line(c):
    return (
        f"{c['symbol'].replace('USDT','')} "
        f"12h {f(c.get('ret_12h_pct'))}% | V {f(c.get('volume_ratio_4h'))}x | "
        f"DD {f(c.get('drawdown_major_pct'),0)}% | base {c.get('weeks_since_26w_low','?')}W"
    )


def build_report(latest, cfg):
    status = latest.get("status", "UNKNOWN")
    scan = latest.get("scan", {})
    summary = latest.get("summary", {})
    candidates = latest.get("candidates", [])
    early = [c for c in candidates if c.get("state") == "EARLY_IGNITION"][: cfg["output"]["telegram_early"]]
    wake = [c for c in candidates if c.get("state") == "WAKE_UP"][: cfg["output"]["telegram_watch"]]
    moved = [c for c in candidates if c.get("state") == "ALREADY_MOVED"][: cfg["output"]["telegram_moved"]]

    head = (
        f"RADAR {latest.get('generated_at_ict','?')[11:16]} ICT | {status} | "
        f"{scan.get('fully_evaluated','?')} eval\n"
        f"EARLY {summary.get('EARLY_IGNITION',0)} | WAKE {summary.get('WAKE_UP',0)} | "
        f"BASE {summary.get('DORMANT_BASE',0)} | MOVED {summary.get('ALREADY_MOVED',0)}"
    )
    parts = [head]
    if early:
        parts.append("🟢 EARLY\n" + "\n".join(line(c) for c in early))
    if wake:
        parts.append("🟡 WAKE\n" + "\n".join(line(c) for c in wake))
    if moved:
        parts.append("⚪ MOVED\n" + "\n".join(line(c) for c in moved))
    if not early and not wake:
        parts.append("No early signal this run.")
    parts.append(f"run={latest.get('run_id','?')}")
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
