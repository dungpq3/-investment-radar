#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "radar" / "latest.json"
SWING = ROOT / "data" / "swing" / "latest.json"
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


def signed(v, digits=1):
    if v is None:
        return "?"
    return f"{float(v):+.{digits}f}%"


def money(v):
    if v is None:
        return "?"
    return "$" + f"{float(v):+.2f}"


def coin(symbol):
    return str(symbol or "?").replace("USDT", "")


def build_report(latest, cfg, swing):
    ts = swing.get("generated_at_ict") or latest.get("generated_at_ict") or "?"
    hhmm = ts[11:16] if len(ts) >= 16 else "?"
    events = set(swing.get("events_this_run", []))
    summary = swing.get("summary", {})
    closed = swing.get("closed_trade_this_run")
    active = swing.get("active_trade")

    if closed:
        reason = closed.get("exit_reason", "CLOSED")
        icon = "✅" if float(closed.get("net_pnl_usdt") or 0) > 0 else "🛑"
        parts = [
            f"{icon} <b>GEM CLOSED</b> {hhmm} | <b>{coin(closed.get('symbol'))}</b>",
            f"{reason} · {money(closed.get('net_pnl_usdt'))} · {signed(closed.get('net_return_pct'))}",
            f"MFE {signed(closed.get('mfe_pct'))} · MAE {signed(closed.get('mae_pct'))} · hold {float(closed.get('hold_hours') or 0):.1f}h",
            "🔎 Scan-only phần còn lại của ngày; không mở lệnh thứ hai.",
        ]
    elif active:
        grade = active.get("entry_grade") or "?"
        score = float(active.get("entry_signal_score") or 0)
        levels = active.get("levels", {})
        dca_txt = "DONE" if active.get("dca_done") else px(levels.get("dca"))
        header = "💎 <b>GEM OF DAY</b>" if "ENTRY" in events else "👀 <b>GEM TRACK</b>"
        parts = [
            f"{header} {hhmm} | <b>{coin(active.get('symbol'))}</b> {score:.0f}{grade}",
            f"Entry {px(active.get('entry_market_price'))} → {px(active.get('last_price'))} · {signed(active.get('mark_move_pct'))}",
            f"Paper {money(active.get('capital_deployed_usdt'))} · net {money(active.get('mark_net_pnl_usdt'))}",
            f"TP25 {px(levels.get('tp'))} · DCA1 {dca_txt} · MFE {signed(active.get('mfe_pct'))} / MAE {signed(active.get('mae_pct'))}",
        ]
        if "DCA1" in events:
            parts.append("🟠 DCA1 đã giả lập; vốn paper hiện $200.")
    else:
        if "SCAN_ONLY_DAY_LOCKED" in events:
            state = "DAY LOCKED"
        elif "SCAN_ONLY_OFF_SCHEDULE" in events:
            state = "OFF-SCHEDULE CHECK"
        else:
            state = "NO SETUP"
        parts = [
            f"💎 <b>GEM RADAR</b> {hhmm} | {state}",
            "🔎 Scan-only · chưa có lệnh paper mới.",
        ]

    parts.append(
        f"30D PAPER: {int(summary.get('closed_trades') or 0)} vòng · "
        f"net {money(summary.get('net_pnl_usdt') or 0)} · hit {float(summary.get('hit_rate_pct') or 0):.0f}%"
    )
    parts.append(f"<code>{swing.get('strategy_version','gem-swing-paper-v1')}</code>")
    return "\n".join(parts)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    latest = load(LATEST)
    cfg = load(CONFIG)
    swing = load(SWING) if SWING.exists() else {}\n    text = build_report(latest, cfg, swing)
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
