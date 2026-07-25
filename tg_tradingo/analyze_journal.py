#!/usr/bin/env python3
"""Offline analysis of TG TradinGo journals (bridge events + EA trades + equity).

Usage:
  python analyze_journal.py --journal-root docs/fixtures/journal_sample --from 2026-07-22 --to 2026-07-24
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def iter_day_files(root: Path, sub: str, prefix: str, start: datetime, end: datetime):
    d = start
    while d <= end:
        yield root / sub / f"{prefix}_{d.strftime('%Y%m%d')}.csv"
        d += timedelta(days=1)


def iter_day_jsonl(root: Path, sub: str, prefix: str, start: datetime, end: datetime):
    d = start
    while d <= end:
        yield root / sub / f"{prefix}_{d.strftime('%Y%m%d')}.jsonl"
        d += timedelta(days=1)


def percentile(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def load_news(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return _load_csv(path)


def in_news_window(ts: datetime, news: list[dict], currencies: set[str] | None) -> bool:
    for n in news:
        try:
            nt = datetime.fromisoformat(n["ts_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        cur = (n.get("currency") or "").upper()
        if currencies is not None and cur not in currencies:
            continue
        if abs((ts - nt).total_seconds()) <= 300:
            return True
    return False


def report_channels(trades: list[dict]) -> dict[str, Any]:
    by_ch: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        ev = (t.get("event") or "").upper()
        if ev and ev != "CLOSE":
            continue
        if not ev and not (t.get("gross_profit") or t.get("realized_profit")):
            continue
        ch = t.get("channel") or t.get("channel_id") or "?"
        by_ch[ch].append(t)

    out = {}
    for ch, rows in sorted(by_ch.items()):
        pnls = []
        durs = []
        wins = 0
        for r in rows:
            try:
                p = float(r.get("gross_profit") or r.get("realized_profit") or 0)
            except ValueError:
                p = 0.0
            pnls.append(p)
            if p > 0:
                wins += 1
            try:
                durs.append(float(r.get("duration_sec") or 0))
            except ValueError:
                pass
        gross_win = sum(x for x in pnls if x > 0)
        gross_loss = -sum(x for x in pnls if x < 0)
        out[ch] = {
            "n": len(rows),
            "pnl": round(sum(pnls), 2),
            "win_rate": round(wins / len(rows), 3) if rows else None,
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "median_duration_sec": round(statistics.median(durs), 1) if durs else None,
            "pct_under_60s": round(sum(1 for d in durs if d < 60) / len(durs), 3) if durs else None,
        }
    return out


def report_distributions(trades: list[dict]) -> dict[str, Any]:
    by_ch: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for t in trades:
        ch = t.get("channel") or "?"
        for key, field in (
            ("mae_ccy", "mae_ccy"),
            ("mfe_ccy", "mfe_ccy"),
            ("slippage_pts", "slippage_pts"),
            ("duration_sec", "duration_sec"),
        ):
            try:
                v = float(t.get(field) or "")
            except ValueError:
                continue
            by_ch[ch][key].append(v)
        try:
            entry = float(t.get("requested_entry") or t.get("req_entry") or 0)
            sl = float(t.get("sl_initial") or t.get("req_sl") or 0)
            if entry and sl:
                by_ch[ch]["entry_sl_dist"].append(abs(entry - sl))
        except ValueError:
            pass

    out = {}
    for ch, series in by_ch.items():
        out[ch] = {}
        for name, vals in series.items():
            out[ch][name] = {
                "p50": percentile(vals, 0.50),
                "p75": percentile(vals, 0.75),
                "p95": percentile(vals, 0.95),
                "max": max(vals) if vals else None,
            }
    return out


def report_prop_curves(equity_rows: list[dict]) -> dict[str, Any]:
    if not equity_rows:
        return {}
    eqs = []
    for r in equity_rows:
        try:
            eqs.append(float(r["equity"]))
        except Exception:
            continue
    if not eqs:
        return {}
    peak = eqs[0]
    max_dd = 0.0
    worst_floating = 0.0
    for r in equity_rows:
        try:
            eq = float(r["equity"])
            bal = float(r.get("balance") or eq)
            fl = float(r.get("floating_total") or 0)
        except Exception:
            continue
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
        worst_floating = min(worst_floating, fl)

    # Daily DD vs 22:00 UTC snapshot (approx: last sample before/at 22:00 each day)
    by_day: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for r in equity_rows:
        try:
            ts = datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00"))
            eq = float(r["equity"])
        except Exception:
            continue
        by_day[ts.strftime("%Y-%m-%d")].append((ts, eq))

    daily_dd = {}
    for day, pts in by_day.items():
        pts.sort()
        snap = None
        for ts, eq in pts:
            if ts.hour < 22:
                snap = eq
        if snap is None and pts:
            snap = pts[0][1]
        if snap is None:
            continue
        trough = min(eq for _, eq in pts)
        daily_dd[day] = round(snap - trough, 2)

    return {
        "max_drawdown": round(max_dd, 2),
        "worst_floating": round(worst_floating, 2),
        "daily_dd_from_22utc_snapshot": daily_dd,
        "peak_equity": round(max(eqs), 2),
        "end_equity": round(eqs[-1], 2),
    }


def simulate_lots(
    trades: list[dict],
    multipliers: dict[str, float],
    limits: dict[str, float],
) -> dict[str, Any]:
    """Scale realized PnL by channel lot multiplier; report which prop limit binds first."""
    scaled = []
    for t in trades:
        ch = (t.get("channel") or "").lower()
        mult = 1.0
        for k, m in multipliers.items():
            if k.lower() in ch:
                mult = m
                break
        try:
            base = float(t.get("gross_profit") or t.get("realized_profit") or 0)
        except ValueError:
            base = 0.0
        scaled.append(base * mult)

    total = sum(scaled)
    # Simple bind check against absolute loss limits on cumulative path
    cum = 0.0
    peak = 0.0
    first_bind = None
    for p in scaled:
        cum += p
        peak = max(peak, cum)
        trail = peak - cum
        if first_bind is None and cum <= -limits.get("daily", 300):
            first_bind = "daily"
        if first_bind is None and trail >= limits.get("trailing", 500):
            first_bind = "trailing"
        if first_bind is None and p <= -limits.get("floating", 200):
            first_bind = "floating"
    return {
        "scaled_pnl": round(total, 2),
        "first_binding_limit": first_bind,
        "limits": limits,
        "multipliers": multipliers,
    }


def report_parser_coverage(events: list[dict]) -> dict[str, Any]:
    outcomes = Counter(e.get("outcome") for e in events)
    unparsed = [e.get("raw_text", "") for e in events if e.get("outcome") == "UNPARSED"]
    # crude similarity: first 40 chars normalized
    groups: Counter[str] = Counter()
    for t in unparsed:
        key = " ".join(t.upper().split())[:40]
        groups[key] += 1
    top = groups.most_common(30)
    return {"outcomes": dict(outcomes), "unparsed_groups": top}


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze TG TradinGo journals offline")
    ap.add_argument("--journal-root", type=Path, required=True)
    ap.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD UTC")
    ap.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD UTC")
    ap.add_argument("--news-calendar", type=Path, default=None)
    ap.add_argument(
        "--lot-mult",
        action="append",
        default=[],
        help="channel=mult e.g. ivan=0.2 stark=0.05 (relative to journal lots)",
    )
    args = ap.parse_args()
    start = _parse_day(args.date_from)
    end = _parse_day(args.date_to)
    root = args.journal_root

    events: list[dict] = []
    for p in iter_day_jsonl(root, "bridge_events", "events", start, end):
        events.extend(_load_jsonl(p))

    trades: list[dict] = []
    for p in iter_day_files(root, "trades", "trades", start, end):
        trades.extend(_load_csv(p))

    equity: list[dict] = []
    for p in iter_day_files(root, "equity", "equity", start, end):
        equity.extend(_load_csv(p))

    news = load_news(args.news_calendar)

    # News labeling on emitted opens
    news_stats = {"usd_window": 0, "all_window": 0, "labeled": 0}
    for e in events:
        if e.get("outcome") != "EMITTED" or e.get("action") not in ("OPEN", "OPEN_NOW"):
            continue
        news_stats["labeled"] += 1
        try:
            ts = datetime.fromisoformat(e["ts_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        if in_news_window(ts, news, {"USD"}):
            news_stats["usd_window"] += 1
        if in_news_window(ts, news, None):
            news_stats["all_window"] += 1

    mults = {}
    for item in args.lot_mult:
        if "=" in item:
            k, v = item.split("=", 1)
            mults[k] = float(v)

    report = {
        "window": {"from": args.date_from, "to": args.date_to},
        "channels": report_channels(trades),
        "distributions": report_distributions(trades),
        "prop_curves": report_prop_curves(equity),
        "lot_simulation": simulate_lots(
            trades,
            mults or {"ivan": 1.0, "stark": 1.0},
            {"floating": 200, "daily": 300, "trailing": 500},
        ),
        "parser_coverage": report_parser_coverage(events),
        "news_labeling": news_stats,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
