#!/usr/bin/env python3
"""Offline dry-run of the Telegram parsers — no Telethon, no VPS, no JSON written.

Two input formats:

1. Sampler dumps (``docs/fixtures/signal_samples.txt``, ``logs/signals_*.txt``)::

     python parser_dryrun.py --dump docs/fixtures/signal_samples.txt

2. Bridge journal events (``journal/bridge_events/events_YYYYMMDD.jsonl``)::

     python parser_dryrun.py --events journal/bridge_events/events_20260724.jsonl --diff

   ``--diff`` replays every event through the current parsers and reports where the
   recomputed outcome/action differs from the one recorded in production.

Channel state (CH2 naked→UPDATE, ORO pending, FOREX pending) is kept in an
in-memory ``EphemeralBridgeState`` so message order matters, exactly like live.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

TG_ROOT = Path(__file__).resolve().parent
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))

from bridge_core import EphemeralBridgeState, validate_signal  # noqa: E402
from tradingo_bridge import (  # noqa: E402
    PARSERS,
    apply_lot_rules,
    coerce_edit_open_to_update,
)

STATEFUL_PARSERS = ("sala_gold", "sala_oro", "sala_vip", "sala_stark", "ivan_vip")

# Sampler header: "  CH2 — SALA GOLD VIP" / "CH_ORO — SALA ORO VIP"
_HEADER_RE = re.compile(r"^\s*(CH[\w]*)\s+[—-]\s+(.+?)\s*$")
_TG_ID_RE = re.compile(r"^\s*Telegram ID:\s*(-?\d+)\s*$")
_MSG_RE = re.compile(r"^\s*\[(\d+)\]\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$")

# Channel id → parser name for sampler dumps that predate CHANNEL_MAP ids.
DEFAULT_PARSER_BY_CHANNEL = {
    "CH1": "zanni_vip",
    "CH2": "sala_gold",
    "CH3": "sala_vip",
    "CH4": "sala_stark",
    "CH_GOLD": "sala_gold",
    "CH_FOREX": "sala_vip",
    "CH_ORO": "sala_oro",
    "CH_STARK": "sala_stark",
    "CH_IVAN": "ivan_vip",
}

MAGIC_BY_CHANNEL = {
    "CH1": 11000,
    "CH2": 12000,
    "CH3": 13000,
    "CH4": 14000,
    "CH_GOLD": 12000,
    "CH_FOREX": 13000,
    "CH_ORO": 14100,
    "CH_STARK": 14000,
    "CH_IVAN": 17000,
}


def channel_cfg(channel_id: str) -> dict:
    return {
        "id": channel_id,
        "name": channel_id,
        "magic_base": MAGIC_BY_CHANNEL.get(channel_id, 19000),
        "signal_file": f"signal_{channel_id.lower()}.json",
        "execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10},
    }


def run_parser(
    parser_name: str,
    text: str,
    ch: dict,
    state: EphemeralBridgeState,
    *,
    is_edit: bool = False,
) -> tuple[dict | None, str]:
    """Return (signal, outcome) where outcome mirrors the journal vocabulary."""
    parser = PARSERS.get(parser_name)
    if parser is None:
        return None, f"NO_PARSER({parser_name})"
    try:
        if parser_name in STATEFUL_PARSERS:
            signal = parser(text, ch, state)
        else:
            signal = parser(text, ch)
    except Exception as exc:  # pragma: no cover - diagnostic tool
        return None, f"PARSE_ERROR({type(exc).__name__}: {exc})"

    signal = coerce_edit_open_to_update(signal, is_edit)
    if signal is None:
        return None, "UNPARSED"

    apply_lot_rules(signal, ch)
    ok, reason = validate_signal(signal)
    if not ok:
        return signal, f"INVALID({reason})"
    return signal, "EMITTED"


def describe(signal: dict | None) -> str:
    if not signal:
        return "-"
    bits = [signal.get("action", "?")]
    for key in ("direction", "symbol"):
        if signal.get(key):
            bits.append(str(signal[key]))
    if signal.get("entry") is not None:
        bits.append(f"@{signal['entry']}")
    if signal.get("entry_range"):
        bits.append(f"range={signal['entry_range']}")
    if signal.get("tp_levels"):
        bits.append(f"TP={signal['tp_levels']}")
    if signal.get("sl") is not None:
        bits.append(f"SL={signal['sl']}")
    for key in ("new_tp", "new_sl", "be_price", "reference_price", "lot_factor"):
        if signal.get(key) is not None:
            bits.append(f"{key}={signal[key]}")
    if signal.get("fixed_lot") is not None:
        bits.append(f"lot={signal['fixed_lot']}x{signal.get('trades')}")
    return " ".join(bits)


def iter_dump_sections(path: Path):
    """Yield (channel_id, [(index, ts, text), ...]) from a sampler dump."""
    channel_id: str | None = None
    messages: list[tuple[str, str, str]] = []
    cur: list[str] | None = None
    cur_head: tuple[str, str] | None = None

    def flush_msg():
        nonlocal cur, cur_head
        if cur_head and cur is not None:
            text = "\n".join(cur).strip()
            if text:
                messages.append((cur_head[0], cur_head[1], text))
        cur, cur_head = None, None

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m_msg = _MSG_RE.match(line)
        if m_msg:
            flush_msg()
            cur_head = (m_msg.group(1), m_msg.group(2))
            cur = []
            continue
        if _TG_ID_RE.match(line):
            continue
        m_head = _HEADER_RE.match(line)
        if m_head and m_head.group(1) in DEFAULT_PARSER_BY_CHANNEL:
            flush_msg()
            if channel_id and messages:
                yield channel_id, list(messages)
            channel_id = m_head.group(1)
            messages = []
            continue
        if cur is not None:
            if line.strip().startswith("Totale messaggi"):
                flush_msg()
                continue
            cur.append(line.strip())

    flush_msg()
    if channel_id and messages:
        yield channel_id, messages


def cmd_dump(args: argparse.Namespace) -> int:
    path = Path(args.dump)
    counters: dict[str, Counter] = {}
    for channel_id, messages in iter_dump_sections(path):
        if args.channel and channel_id not in args.channel:
            continue
        parser_name = args.parser or DEFAULT_PARSER_BY_CHANNEL[channel_id]
        ch = channel_cfg(channel_id)
        state = EphemeralBridgeState()
        counter = counters.setdefault(channel_id, Counter())
        print("=" * 78)
        print(f"{channel_id}  (parser: {parser_name})  {len(messages)} messaggi")
        print("=" * 78)
        for idx, ts, text in messages:
            signal, outcome = run_parser(parser_name, text, ch, state)
            counter[outcome.split("(")[0]] += 1
            if args.only_unparsed and outcome == "EMITTED":
                continue
            head = text.replace("\n", " | ")
            if len(head) > 90:
                head = head[:87] + "..."
            print(f"[{idx}] {ts}  {outcome:<9} {describe(signal)}")
            print(f"      MSG: {head}")
    print()
    print("── Riepilogo ─────────────────────────────────────────────────────────────")
    for channel_id, counter in counters.items():
        total = sum(counter.values())
        detail = " ".join(f"{k}={v}" for k, v in sorted(counter.items()))
        print(f"{channel_id}: {total} msg | {detail}")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    rows: list[dict] = []
    for raw in Path(args.events).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            rows.append(json.loads(raw))
    rows.sort(key=lambda r: (r.get("ts_utc") or "", r.get("message_id") or 0))

    states: dict[str, EphemeralBridgeState] = {}
    diffs = 0
    counter: Counter = Counter()
    for row in rows:
        channel_id = row.get("channel_id") or "?"
        if args.channel and channel_id not in args.channel:
            continue
        parser_name = args.parser or DEFAULT_PARSER_BY_CHANNEL.get(channel_id)
        if not parser_name:
            print(f"! canale sconosciuto {channel_id}: passa --parser")
            continue
        state = states.setdefault(channel_id, EphemeralBridgeState())
        signal, outcome = run_parser(
            parser_name,
            row.get("raw_text") or "",
            channel_cfg(channel_id),
            state,
            is_edit=(row.get("event_type") == "EDIT"),
        )
        counter[outcome.split("(")[0]] += 1
        recorded = row.get("outcome")
        rec_action = row.get("action")
        new_action = (signal or {}).get("action")
        same_outcome = (
            outcome == recorded
            or (recorded == "IGNORED_PATTERN" and outcome == "UNPARSED")
            or recorded == "DUPLICATE"
        )
        changed = (not same_outcome) or (recorded == "EMITTED" and rec_action != new_action)
        if changed:
            diffs += 1
        if args.diff and not changed:
            continue
        flag = "DIFF" if changed else "same"
        head = (row.get("raw_text") or "").replace("\n", " | ")[:90]
        print(
            f"{row.get('ts_utc')} {channel_id} {row.get('event_type')} "
            f"[{flag}] prod={recorded}/{rec_action} now={outcome}/{new_action}"
        )
        print(f"      MSG: {head}")
        if signal:
            print(f"      NOW: {describe(signal)}")
    print()
    detail = " ".join(f"{k}={v}" for k, v in sorted(counter.items()))
    print(f"Totale {sum(counter.values())} eventi | {detail} | diff={diffs}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dump", help="sampler dump txt (signal_samples.txt, signals_*.txt)")
    src.add_argument("--events", help="journal bridge_events jsonl")
    ap.add_argument("--channel", action="append", help="filtra per channel id (ripetibile)")
    ap.add_argument("--parser", help="forza un parser per tutti i messaggi")
    ap.add_argument("--only-unparsed", action="store_true", help="mostra solo i non emessi")
    ap.add_argument("--diff", action="store_true", help="solo eventi con outcome cambiato")
    args = ap.parse_args()
    if args.dump:
        return cmd_dump(args)
    return cmd_events(args)


if __name__ == "__main__":
    raise SystemExit(main())
