import re
from pathlib import Path

PROP_LOG  = r"C:\TradinGO_Math\prop.log"
HEDGE_LOG = r"C:\TradinGO_Math\hedge.log"
OUTPUT    = r"C:\TradinGO_Math\tradingo_analysis.txt"
DATE_FROM = "2026-04-21"
DATE_TO   = "2026-04-25"

def parse_log(path, label):
    lines = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if not m: continue
                ts = m.group(1)
                if not (DATE_FROM <= ts[:10] <= DATE_TO): continue
                if any(kw in line for kw in [
                    "Segnale","Handshake","hedge_ready","Prop →","Hedge →",
                    "Prop chiusa","Trade chiuso","Trend Riding",
                    "SL protettivo","Trailing SL","RECOVERY",
                    "Connesso","Apertura","✅","❌",
                    "ticket=","pnl=","sig_id=","HARD STOP","DD",
                    "Cooldown","Nuovo giorno","⏳","⛔","⚠",
                    "paired","RIDING","riding","apro","aperto",
                ]):
                    lines.append(f"[{label}] {line.rstrip()}")
    except FileNotFoundError:
        lines.append(f"[{label}] FILE NON TROVATO: {path}")
    return lines

prop_lines  = parse_log(PROP_LOG,  "PROP")
hedge_lines = parse_log(HEDGE_LOG, "HEDGE")
all_lines   = prop_lines + hedge_lines
all_lines.sort(key=lambda x: x[7:26])
output = "\n".join(all_lines)
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output)
print(f"Righe estratte: {len(all_lines)}")
print(f"Salvato in: {OUTPUT}")
