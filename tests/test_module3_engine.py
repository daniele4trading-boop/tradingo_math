"""Modulo 3 acceptance test: selezione + z-score su cache Modulo 2 (no MT5)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import statsmodels  # noqa: F401
except ModuleNotFoundError:
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    hint = (
        "statsmodels non installato. Esegui uno dei seguenti:\n"
        "  python -m pip install scipy statsmodels\n"
        "  C:\\StatArb\\ensure_module3_deps.bat\n"
        "  C:\\StatArb\\run_module3_acceptance.bat\n"
    )
    if venv_py.exists():
        hint += f"Oppure usa la venv: {venv_py} tests\\test_module3_engine.py\n"
    print(hint, file=sys.stderr)
    raise SystemExit(1)

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params
from engine.pair_engine import analyze_cached_pair

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module3_acceptance.txt"


class _Tee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _print_table(results: list) -> None:
    headers = (
        "coppia",
        "cat",
        "corr",
        "adf_p",
        "coint_p",
        "hl_h",
        "sel",
        "zscore",
        "signal",
        "trig_tf",
    )
    widths = [14, 8, 7, 8, 8, 7, 4, 8, 12, 7]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))
    for result in results:
        sel = result.selection
        sig = result.signal
        values = [
            result.pair_label,
            result.category,
            f"{sel.correlation:.3f}" if sel.correlation == sel.correlation else "n/d",
            f"{sel.adf_pvalue_full:.4f}" if sel.adf_pvalue_full == sel.adf_pvalue_full else "n/d",
            f"{sel.coint_pvalue:.4f}" if sel.coint_pvalue == sel.coint_pvalue else "n/d",
            f"{sel.halflife_h:.1f}" if sel.halflife_h == sel.halflife_h else "inf",
            "sì" if sel.selected else "no",
            f"{sig.zscore:.3f}" if sig else "n/d",
            sig.state.value if sig else "ERROR",
            sig.recommended_trigger_tf if sig else result.trigger_tf,
        ]
        print(" | ".join(str(v).ljust(w) for v, w in zip(values, widths)))


def _run_acceptance() -> int:
    accounts = load_accounts()
    params = load_params()
    profile = get_profile("data_source", accounts)

    print("MODULO 3 — test accettazione signal engine")
    print(f"Profilo data_source: {profile.name}")
    print(f"Fonte dati: cache CSV Modulo 2 in state/data/{profile.name}/")
    sel = params["selection"]
    corr_rule = (
        f"abs(corr)>={sel['correlation_prefilter']}"
        if sel.get("correlation_use_abs")
        else f"corr>={sel['correlation_prefilter']}"
    )
    coint_rule = "coint" if sel.get("require_cointegration", True) else "no-coint"
    tw_rule = "2win" if sel["require_two_window_validation"] else "1win"
    bonf = "bonf" if sel["bonferroni_correction"] else "no-bonf"
    print(
        f"Selezione: {corr_rule} adf<={sel['adf_pvalue_max']} ({coint_rule}, {tw_rule}, {bonf}) "
        f"hl=[{sel['halflife_min_hours']},{sel['halflife_max_hours']}]h"
    )
    print(f"Segnali: entry_z={params['signals']['entry_z']} exit_z={params['signals']['exit_z']}")
    print(f"Coppie canoniche: {len(CANDIDATE_PAIRS)}")
    print()

    results = []
    failures = []
    selected_count = 0

    for candidate in CANDIDATE_PAIRS:
        result = analyze_cached_pair(
            profile,
            accounts,
            params,
            candidate.index,
            candidate.leg_a,
            candidate.leg_b,
            candidate.category,
        )
        results.append(result)
        if result.error:
            failures.append(f"{result.pair_label} -> {result.error}")
        elif result.selection.selected:
            selected_count += 1

    _print_table(results)

    print()
    print("=== Riepilogo selezione ===")
    print(f"  Coppie analizzate : {len(results)}")
    print(f"  Coppie selezionate: {selected_count}")
    print(f"  Coppie scartate   : {len(results) - selected_count}")

    print()
    print("=== Dettaglio scarti ===")
    printed = False
    for result in results:
        if result.error:
            print(f"  - {result.pair_label}: ERROR {result.error}")
            printed = True
        elif result.selection.reject_reasons:
            print(f"  - {result.pair_label}: {'; '.join(result.selection.reject_reasons)}")
            printed = True
    if not printed:
        print("  (nessuno)")

    print()
    print("=== Errori engine ===")
    if failures:
        for item in failures:
            print(f"  - {item}")
    else:
        print("  (nessuno)")

    return 1 if failures else 0


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("w", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, log_file)
    try:
        return _run_acceptance()
    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log salvato: {LOG_PATH}", file=original_stdout)


if __name__ == "__main__":
    raise SystemExit(main())
