"""Elenca simboli XM MT5 candidati e suggerisce symbol_map per XM_DEMO."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import MetaTrader5 as mt5

XM_PATH = r"C:\Program Files\XM MT5\terminal64.exe"

# canonico -> candidati in ordine di preferenza (cash # > spot > future)
CANDIDATES: dict[str, list[str]] = {
    "XAUUSD": ["GOLD#", "GOLD", "XAUUSD#", "XAUUSD"],
    "XAGUSD": ["SILVER#", "SILVER", "XAGUSD#", "XAGUSD"],
    "XPTUSD": ["XPTUSD#", "XPTUSD"],
    "XPDUSD": ["XPDUSD#", "XPDUSD"],
    "EURUSD": ["EURUSD#", "EURUSD"],
    "GBPUSD": ["GBPUSD#", "GBPUSD"],
    "AUDUSD": ["AUDUSD#", "AUDUSD"],
    "NZDUSD": ["NZDUSD#", "NZDUSD"],
    "USDCHF": ["USDCHF#", "USDCHF"],
    "US500": ["US500Cash#", "US500Cash", "US500"],
    "US30": ["US30Cash#", "US30Cash", "US30"],
    "NAS100": ["US100Cash#", "US100Cash", "USTECCash#", "USTECCash", "NAS100Cash#", "NAS100#", "NAS100"],
    "GER40": ["GER40Cash#", "GER40Cash", "GER40"],
    "EU50": ["EU50Cash#", "EU50Cash", "EU50"],
}


def _pick_symbol(all_names: set[str], candidates: list[str]) -> tuple[str | None, list[str]]:
    substring_hits: list[str] = []
    key = candidates[0].rstrip("#").replace("Cash", "")
    for name in sorted(all_names):
        if key.upper() in name.upper():
            substring_hits.append(name)

    for candidate in candidates:
        if candidate in all_names:
            return candidate, substring_hits[:8]

    return None, substring_hits[:8]


def main() -> int:
    if not mt5.initialize(path=XM_PATH):
        print("initialize FAIL:", mt5.last_error())
        return 1

    account = mt5.account_info()
    if account:
        print(f"Account: {account.login} | {account.company} | {account.server}")
    print()

    symbols = mt5.symbols_get()
    if symbols is None:
        print("symbols_get FAIL:", mt5.last_error())
        mt5.shutdown()
        return 1

    all_names = {s.name for s in symbols}
    print(f"Totale simboli broker: {len(all_names)}")
    print("-" * 70)
    print(f"{'CANONICO':10s} | {'SCELTA':22s} | substring hits")
    print("-" * 70)

    recommended: dict[str, str] = {}
    for canonical, candidates in CANDIDATES.items():
        picked, hits = _pick_symbol(all_names, candidates)
        if picked:
            ok = mt5.symbol_select(picked, True) and mt5.symbol_info(picked) is not None
            if ok:
                recommended[canonical] = picked
        label = picked if picked else "(nessuno)"
        print(f"{canonical:10s} | {label:22s} | {hits if hits else '(nessuno)'}")

    print()
    print("=== symbol_map XM_DEMO consigliata ===")
    print('"XM_DEMO": {')
    for canonical in CANDIDATES:
        value = recommended.get(canonical, "")
        print(f'  "{canonical}": "{value}",')
    print("}")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
