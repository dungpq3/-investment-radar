#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data" / "radar" / "latest.json"
CONFIG = ROOT / "config" / "radar.json"
STATE = ROOT / "data" / "watchlist" / "state.json"
LATEST = ROOT / "data" / "watchlist" / "latest.json"
HISTORY_DIR = ROOT / "data" / "watchlist" / "history"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def move_pct(now_price: float, watch_price: float) -> float:
    if not watch_price:
        return 0.0
    return (now_price / watch_price - 1.0) * 100.0


def qualifies(c, policy):
    return (
        c.get("state") in set(policy["states"])
        and float(c.get("signal_score", 0)) >= float(policy["min_score"])
        and int(c.get("confirmed_candles_3x4h", 0)) >= int(policy["min_confirmed_candles"])
        and bool(c.get("setup_id"))
    )


def main():
    radar = load(RADAR, {})
    cfg = load(CONFIG, {})
    policy = cfg["paper_watch"]
    prev = load(STATE, {"schema_version": 1, "items": {}})

    generated = parse_iso(radar["generated_at_utc"])
    run_id = radar["run_id"]
    by_symbol = {c["symbol"]: c for c in radar.get("candidates", [])}
    items = prev.get("items", {})
    added = []
    expired = []

    # Add newly qualified setups. A setup_id is immutable for one signal episode.
    for c in radar.get("candidates", []):
        if not qualifies(c, policy):
            continue
        setup_id = c["setup_id"]
        if setup_id in items:
            continue

        watch_price = float(c.get("last_price") or c.get("close_4h") or 0)
        if watch_price <= 0:
            continue

        item = {
            "setup_id": setup_id,
            "symbol": c["symbol"],
            "status": "WATCH_ONLY",
            "position_opened": False,
            "paper_only": True,
            "first_seen_run": run_id,
            "first_seen_at_utc": radar["generated_at_utc"],
            "first_seen_at_ict": radar.get("generated_at_ict"),
            "watch_price": watch_price,
            "watch_state": c.get("state"),
            "watch_score": c.get("signal_score"),
            "watch_grade": c.get("score_grade"),
            "watch_structure_score": c.get("structure_score"),
            "watch_trigger_score": c.get("trigger_score"),
            "watch_opportunity_tier": c.get("opportunity_tier"),
            "watch_confirmed_candles": c.get("confirmed_candles_3x4h"),
            "watch_volume_ratio_4h": c.get("volume_ratio_4h"),
            "watch_ret_12h_pct": c.get("ret_12h_pct"),
            "entry_reference_at_watch": c.get("entry_reference"),
            "dca_reference_at_watch": c.get("dca_reference"),
            "targets_pct": policy["targets_pct"],
            "targets_hit": {str(x): False for x in policy["targets_pct"]},
            "mfe_snapshot_pct": 0.0,
            "mae_snapshot_pct": 0.0,
            "last_price": watch_price,
            "last_state": c.get("state"),
            "last_score": c.get("signal_score"),
            "last_seen_run": run_id,
            "last_seen_at_utc": radar["generated_at_utc"],
        }
        items[setup_id] = item
        added.append(setup_id)

    # Update active paper-watch cohorts from each 4h snapshot.
    max_age = float(policy["max_age_hours"])
    for setup_id, item in list(items.items()):
        if item.get("status") != "WATCH_ONLY":
            continue

        first_seen = parse_iso(item["first_seen_at_utc"])
        age_hours = (generated - first_seen).total_seconds() / 3600.0
        symbol = item["symbol"]
        c = by_symbol.get(symbol)

        if c:
            now_price = float(c.get("last_price") or c.get("close_4h") or item["last_price"])
            mv = move_pct(now_price, float(item["watch_price"]))
            item["last_price"] = now_price
            item["last_state"] = c.get("state")
            item["last_score"] = c.get("signal_score")
            item["last_structure_score"] = c.get("structure_score")
            item["last_trigger_score"] = c.get("trigger_score")
            item["last_opportunity_tier"] = c.get("opportunity_tier")
            item["last_seen_run"] = run_id
            item["last_seen_at_utc"] = radar["generated_at_utc"]
            item["mfe_snapshot_pct"] = round(max(float(item.get("mfe_snapshot_pct", 0)), mv), 3)
            item["mae_snapshot_pct"] = round(min(float(item.get("mae_snapshot_pct", 0)), mv), 3)
            for target in item["targets_pct"]:
                if mv >= float(target):
                    item["targets_hit"][str(target)] = True

        item["age_hours"] = round(age_hours, 2)
        item["move_since_watch_pct"] = round(move_pct(float(item["last_price"]), float(item["watch_price"])), 3)

        if age_hours >= max_age:
            item["status"] = "EXPIRED"
            item["expired_run"] = run_id
            item["expired_at_utc"] = radar["generated_at_utc"]
            expired.append(setup_id)

    active = [x for x in items.values() if x.get("status") == "WATCH_ONLY"]
    active.sort(key=lambda x: (-float(x.get("last_score") or 0), x["first_seen_at_utc"]))
    active = active[: int(policy["max_active"])]

    latest = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at_utc": radar["generated_at_utc"],
        "generated_at_ict": radar.get("generated_at_ict"),
        "status": "OK",
        "policy": {
            "states": policy["states"],
            "min_score": policy["min_score"],
            "min_confirmed_candles": policy["min_confirmed_candles"],
            "max_age_hours": policy["max_age_hours"],
            "targets_pct": policy["targets_pct"],
        },
        "note": "Paper watch only; no real position is opened.",
        "added_this_run": added,
        "expired_this_run": expired,
        "active_count": len(active),
        "active": active,
    }

    write(STATE, {"schema_version": 1, "updated_run": run_id, "items": items})
    write(LATEST, latest)
    append(HISTORY_DIR / generated.strftime("%Y-%m-%d.ndjson"), latest)

    print(
        f"PAPER_WATCH=OK ACTIVE={len(active)} ADDED={len(added)} "
        f"EXPIRED={len(expired)} RUN_ID={run_id}"
    )


if __name__ == "__main__":
    main()
