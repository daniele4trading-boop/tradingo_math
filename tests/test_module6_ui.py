"""Modulo 6 acceptance: UI assets + data services (no browser required)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module6_acceptance.txt"

REQUIRED_UI_FILES = (
    ".streamlit/config.toml",
    "ui/app.py",
    "ui/theme.py",
    "ui/services.py",
)


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


def _run_acceptance() -> int:
    failures: list[str] = []

    print("MODULO 6 — test accettazione UI")
    print()

    print("=== File UI richiesti ===")
    for relative in REQUIRED_UI_FILES:
        path = PROJECT_ROOT / relative
        if path.exists():
            print(f"  OK {relative}")
        else:
            failures.append(f"mancante: {relative}")
            print(f"  FAIL {relative}")

    print()
    print("=== Tema blu notte / oro ===")
    from ui.theme import GOLD, GOLD_BRIGHT, NIGHT_BLUE, theme_css

    css = theme_css()
    checks = [
        (NIGHT_BLUE in css, f"background {NIGHT_BLUE}"),
        (GOLD in css or GOLD_BRIGHT in css, "gold accent"),
        ("stApp" in css, "stApp selector"),
    ]
    for ok, label in checks:
        if ok:
            print(f"  OK {label}")
        else:
            failures.append(f"tema: {label}")
            print(f"  FAIL {label}")

    print()
    print("=== Streamlit import ===")
    try:
        import streamlit  # noqa: F401

        print(f"  OK streamlit {streamlit.__version__}")
    except ImportError:
        failures.append("streamlit non installato")
        print("  FAIL streamlit non installato")

    print()
    print("=== Services offline (cache engine) ===")
    from ui.services import analyze_pairs_offline, build_pair_rows, pair_rows_dataframe

    results, data_source = analyze_pairs_offline()
    rows = build_pair_rows(results)
    df = pair_rows_dataframe(rows)
    selected = sum(1 for row in rows if row.selected)
    print(f"  data_source={data_source}")
    print(f"  coppie analizzate={len(rows)} selezionate={selected}")
    print(f"  colonne dataframe={list(df.columns)}")
    if len(rows) != 10:
        failures.append(f"attese 10 coppie, ottenute {len(rows)}")
    if "Segnale" not in df.columns:
        failures.append("colonna Segnale mancante nel dataframe")

    print()
    print("=== Riepilogo ===")
    print(f"  Errori: {len(failures)}")
    if failures:
        for item in failures:
            print(f"  - {item}")
    else:
        print("  Tutti i controlli PASS")
        print()
        print("Avvio UI manuale:")
        print("  streamlit run ui\\app.py --server.port 8520")
        print("  oppure: C:\\StatArb\\run_ui.bat")

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
