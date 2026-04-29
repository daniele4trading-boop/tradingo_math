"""
Reset stato FTMO dopo reset conto prop.
Esegui UNA VOLTA prima di riavviare tradingo_system.py
"""
import json
from datetime import datetime

# Reset ftmo_state.json
ftmo_state = {
    "start_of_day_balance": 100000.0,
    "last_update_date": datetime.now().strftime("%Y-%m-%d"),
    "daily_dd_triggered": False,
    "total_dd_triggered": False,
    "best_balance": 100000.0,
}

with open("ftmo_state.json", "w") as f:
    json.dump(ftmo_state, f, indent=2)

print("✅ ftmo_state.json resettato → balance base = 100.000")

# Reset tradingo_state.json (rimuove DD_HALT)
import os
for fname in ["tradingo_state.json", "tradingo_state.tmp"]:
    if os.path.exists(fname):
        os.remove(fname)
        print(f"✅ {fname} rimosso")

print("\nOra puoi riavviare: python tradingo_system.py")
