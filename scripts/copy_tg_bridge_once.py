"""One-shot: copia tradingo_bridge.py e fixture log in repo. Esegui sulla VPS."""
from pathlib import Path
import shutil

pairs = [
    (r"C:\TG_TradinGo\tradingo_bridge.py", r"C:\StatArb\tg_tradingo\tradingo_bridge.py"),
    (r"C:\TG_TradinGo\logs\signal_samples.txt", r"C:\StatArb\tg_tradingo\docs\fixtures\signal_samples.txt"),
    (r"C:\TG_TradinGo\logs\signals_apr21.txt", r"C:\StatArb\tg_tradingo\docs\fixtures\signals_apr21.txt"),
    (r"C:\TG_TradinGo\logs\channel_dump.txt", r"C:\StatArb\tg_tradingo\docs\fixtures\channel_dump.txt"),
]
for src, dst in pairs:
    s, d = Path(src), Path(dst)
    if not s.exists():
        print(f"SKIP missing {s}")
        continue
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(s, d)
    print(f"OK {d} ({d.stat().st_size} bytes)")
