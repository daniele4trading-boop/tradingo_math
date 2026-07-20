"""
Scarica messaggi Telegram in un intervallo di date per i canali in config.

Output: logs/signals_YYYYMMDD_YYYYMMDD.txt

Uso:
  python fetch_date_range.py --from 2026-07-13 --to 2026-07-17
  python fetch_date_range.py --from 2026-07-13 --to 2026-07-17 --parser-dry-run
  python fetch_date_range.py --from 2026-07-13 --to 2026-07-17 --channel CH_GOLD
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import date, datetime, time, timezone
from pathlib import Path

from telethon import TelegramClient

CONFIG_FILE = os.environ.get(
    "TRADINGO_CONFIG",
    os.path.join(os.path.dirname(__file__), "tradingo_config.json"),
)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def load_config() -> dict:
    path = CONFIG_FILE
    if not os.path.exists(path):
        example = os.path.join(os.path.dirname(__file__), "tradingo_config.example.json")
        if os.path.exists(example):
            path = example
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=timezone.utc)
    return start, end


def import_parsers():
    sys.path.insert(0, os.path.dirname(__file__))
    from bridge_core import EphemeralBridgeState
    from tradingo_bridge import (
        parser_sala_gold,
        parser_sala_oro,
        parser_sala_stark,
        parser_sala_vip,
        parser_zanni_vip,
    )

    dry = EphemeralBridgeState()
    return {
        "zanni_vip": parser_zanni_vip,
        "sala_gold": lambda text, ch: parser_sala_gold(text, ch, dry),
        "sala_vip": lambda text, ch: parser_sala_vip(text, ch, dry),
        "sala_oro": parser_sala_oro,
        "sala_stark": parser_sala_stark,
        "placeholder": lambda _text, _ch: None,
    }


def format_signal(sig: dict | None) -> str:
    if not sig:
        return "IGNORED"
    parts = [sig.get("action", "?")]
    for key in ("direction", "symbol"):
        if sig.get(key):
            parts.append(str(sig[key]))
    if sig.get("tp_index"):
        parts.append(f"TP{sig['tp_index']}")
    return " | ".join(parts)


async def fetch_channel_messages(client, entity, start: datetime, end: datetime):
    msgs = []
    async for m in client.iter_messages(entity, offset_date=end, reverse=True):
        msg_dt = m.date.replace(tzinfo=timezone.utc) if m.date.tzinfo is None else m.date.astimezone(timezone.utc)
        if msg_dt < start:
            break
        if msg_dt > end:
            continue
        if m.text and m.text.strip():
            msgs.append(m)
    return msgs


async def run(args: argparse.Namespace) -> None:
    config = load_config()
    tg = config["telegram"]
    log_dir = Path(config["paths"]["logs"])
    log_dir.mkdir(parents=True, exist_ok=True)

    date_from = parse_day(args.date_from)
    date_to = parse_day(args.date_to)
    if date_to < date_from:
        raise SystemExit("--to deve essere >= --from")

    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)

    out_name = f"signals_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.txt"
    out_file = log_dir / out_name
    fixture_copy = (
        Path(__file__).resolve().parent
        / "docs"
        / "fixtures"
        / out_name
    )

    channels = config.get("channels", [])
    if args.channel:
        wanted = set(args.channel)
        channels = [ch for ch in channels if ch["id"] in wanted]
        if not channels:
            raise SystemExit(f"Nessun canale trovato per id: {', '.join(wanted)}")
    else:
        channels = [ch for ch in channels if ch.get("enabled", True)]

    parsers = import_parsers() if args.parser_dry_run else {}

    lines: list[str] = []

    def log(s: str = "") -> None:
        lines.append(s)
        safe_print(s)

    client = TelegramClient(tg["session_file"], tg["api_id"], tg["api_hash"])

    try:
        async with client:
            log("=" * 72)
            log(f"TG TradinGo — dump {date_from} → {date_to}")
            log(f"Generato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            log(f"Intervallo UTC: {start.isoformat()} → {end.isoformat()}")
            log("=" * 72)

            for ch in channels:
                cid = int(ch["telegram_id"])
                if cid == 0:
                    log(f"\n{ch['id']} | {ch.get('name')} — PLACEHOLDER (telegram_id=0, skip)")
                    continue

                log("")
                log("=" * 72)
                log(f"{ch['id']} | {ch.get('name')} | parser={ch.get('parser')}")
                log(f"telegram_id: {cid}")
                log(f"execution: {json.dumps(ch.get('execution', {}), ensure_ascii=False)}")
                log("=" * 72)

                parser_fn = parsers.get(ch.get("parser", ""))
                try:
                    entity = await client.get_entity(cid)
                    msgs = await fetch_channel_messages(client, entity, start, end)
                except Exception as exc:
                    log(f"  ERRORE: {exc}\n")
                    continue

                if not msgs:
                    log("  (nessun messaggio nel periodo)\n")
                    continue

                for i, m in enumerate(msgs, 1):
                    ts = m.date.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    log(f"[{i:02d}] {ts} | msg_id={m.id}")
                    if args.parser_dry_run and parser_fn:
                        try:
                            sig = parser_fn(m.text, ch)
                            log(f"     -> {format_signal(sig)}")
                        except Exception as exc:
                            log(f"     -> PARSER_ERROR: {exc}")
                    for row in m.text.splitlines():
                        log(f"     {row}")
                    log()

                log(f"  Totale: {len(msgs)} messaggi\n")

    except Exception:
        log("\n!!! ERRORE DURANTE DUMP !!!")
        log(traceback.format_exc())
        raise
    finally:
        payload = "\n".join(lines)
        out_file.write_text(payload, encoding="utf-8")
        fixture_copy.parent.mkdir(parents=True, exist_ok=True)
        fixture_copy.write_text(payload, encoding="utf-8")
        safe_print(f"\nOutput produzione: {out_file}")
        safe_print(f"Output repo copy:  {fixture_copy}")


def main() -> None:
    configure_stdio()
    p = argparse.ArgumentParser(description="Dump messaggi Telegram per intervallo date")
    p.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--parser-dry-run", action="store_true")
    p.add_argument("--channel", action="append", help="Filtra per id canale (es. CH_IVAN); include anche canali disabled")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
