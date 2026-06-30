"""Fetch messages from 4 channels for April 21 analysis"""
import asyncio, json, os
from datetime import datetime, timezone
from pathlib import Path

CONFIG_FILE = r"C:\TG_TradinGo\tradingo_config.json"
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

TG = CONFIG["telegram"]
OUT = Path(r"C:\TG_TradinGo\logs\signals_apr21.txt")

CHANNELS = [
    {"id": "CH1", "name": "ZANNI VIP SIGNALS",  "telegram_id": -1003026686847},
    {"id": "CH2", "name": "SALA GOLD VIP",       "telegram_id": -1003302540529},
    {"id": "CH3", "name": "SALA VIP",            "telegram_id": -1002890661441},
    {"id": "CH4", "name": "SALA STARK",          "telegram_id": -1002073368935},
]

from telethon import TelegramClient

async def dump():
    from datetime import date
    client = TelegramClient(TG["session_file"], TG["api_id"], TG["api_hash"])
    lines = []
    def log(s=""): print(s); lines.append(s)

    async with client:
        for ch in CHANNELS:
            log("="*60)
            log(f"{ch['id']} — {ch['name']}")
            log("="*60)
            entity = await client.get_entity(ch["telegram_id"])
            msgs = await client.get_messages(entity, limit=80)
            count = 0
            for m in reversed(msgs):
                if not m.text or not m.text.strip(): continue
                # Solo messaggi del 20-21 aprile
                d = m.date.date()
                if d.month == 4 and d.day in [20,21]:
                    count += 1
                    ts = m.date.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    log(f"[{count:02d}] {ts}")
                    for row in m.text.splitlines():
                        log(f"     {row}")
                    log()
            log(f"  Totale: {count} messaggi")
            log()

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSalvato: {OUT}")

if __name__ == "__main__":
    asyncio.run(dump())
