import json
import os
import platform
import subprocess
import time
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "systems_registry.json"
CONFIG_PATH = ROOT / "config" / "systems_config.json"
STRATEGIES_PATH = ROOT / "strategies" / "registry.json"
SCRIPTS_DIR = ROOT / "scripts"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        st.error(f"JSON non valido in {path}: {exc}")
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run_script(script_name: str, *args: str) -> tuple[int, str]:
    script = SCRIPTS_DIR / script_name
    if platform.system().lower() != "windows":
        return 1, "Gli script PowerShell sono eseguibili dalla VPS Windows o dal PC Windows, non da questo ambiente."
    if not script.exists():
        return 1, f"Script non trovato: {script}"
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def get_process_rows(systems):
    if platform.system().lower() != "windows":
        return {}
    try:
        ps = (
            "Get-CimInstance Win32_Process | "
            "? { $_.Name -match '^(python|pythonw)\\.exe$' } | "
            "Select ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            capture_output=True,
            timeout=20,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {}
        rows = json.loads(proc.stdout)
        if isinstance(rows, dict):
            rows = [rows]
    except Exception:
        return {}

    status = {}
    for system in systems:
        match = (system.get("process_match") or system.get("entrypoint") or "").lower()
        found = []
        for row in rows:
            command = str(row.get("CommandLine", "")).lower()
            if match and match.lower().replace("\\", "/") in command.replace("\\", "/"):
                found.append(str(row.get("ProcessId")))
        status[system["id"]] = found
    return status


def tail_file(path: str, lines: int = 100) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return f"Log non trovato: {path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:])
    except Exception as exc:
        return f"Errore lettura log {path}: {exc}"


st.set_page_config(page_title="TradinGO Platform", page_icon="TG", layout="wide")

registry = load_json(REGISTRY_PATH, {"systems": []})
config = load_json(CONFIG_PATH, {"systems": {}, "global": {}})
strategies = load_json(STRATEGIES_PATH, {"strategies": []})
systems = registry.get("systems", [])
system_config = config.setdefault("systems", {})
process_status = get_process_rows(systems)

st.title("TradinGO Platform Control Center")
st.caption("Dashboard unificata per sistemi live, strategie, backtest, config, log e script di gestione.")

if st.button("Refresh"):
    st.rerun()

tab_status, tab_config, tab_backtest, tab_strategies, tab_logs = st.tabs(
    ["Stato sistemi", "Configurazione", "Backtest", "Strategie", "Log"]
)

with tab_status:
    st.subheader("Stato sistemi")
    cols = st.columns([2, 1, 1, 1, 1, 2, 2])
    headers = ["Nome", "Stato", "PID", "Broker", "Account", "Cartella", "Azioni"]
    for col, header in zip(cols, headers):
        col.markdown(f"**{header}**")

    for system in systems:
        sid = system["id"]
        pids = process_status.get(sid, [])
        running = bool(pids)
        cols = st.columns([2, 1, 1, 1, 1, 2, 2])
        cols[0].write(system.get("name", sid))
        cols[1].markdown(":green[ON]" if running else ":red[OFF]")
        cols[2].write(", ".join(pids) if pids else "-")
        cols[3].write(system.get("broker", "-"))
        cols[4].write(system.get("account", "-"))
        cols[5].code(system.get("working_directory", ""), language=None)
        with cols[6]:
            a, b, c = st.columns(3)
            if a.button("Start", key=f"start-{sid}"):
                code, out = run_script("start_all.ps1", sid)
                st.toast(out or f"Start {sid}: {code}")
            if b.button("Stop", key=f"stop-{sid}"):
                code, out = run_script("stop_all.ps1", sid)
                st.toast(out or f"Stop {sid}: {code}")
            if c.button("Restart", key=f"restart-{sid}"):
                code, out = run_script("restart.ps1", sid)
                st.toast(out or f"Restart {sid}: {code}")

    st.caption("Auto-refresh leggero ogni 30 secondi.")
    time.sleep(0.1)

with tab_config:
    st.subheader("Configurazione parametri")
    st.info("Questa configurazione e' il pannello centrale. I sistemi legacy leggeranno questi valori dopo la migrazione graduale.")

    changed = False
    for system in systems:
        sid = system["id"]
        cfg = system_config.setdefault(sid, {})
        with st.expander(system.get("name", sid), expanded=False):
            cfg["enabled"] = st.checkbox("Enabled", value=bool(cfg.get("enabled", system.get("enabled", False))), key=f"cfg-enabled-{sid}")
            cfg["broker"] = st.text_input("Broker", value=str(cfg.get("broker", system.get("broker", ""))), key=f"cfg-broker-{sid}")
            cfg["account"] = st.text_input("Account", value=str(cfg.get("account", system.get("account", ""))), key=f"cfg-account-{sid}")
            cfg["server"] = st.text_input("Server", value=str(cfg.get("server", system.get("server", ""))), key=f"cfg-server-{sid}")
            cfg["magic"] = st.text_input("Magic", value="" if system.get("magic") is None else str(cfg.get("magic", system.get("magic", ""))), key=f"cfg-magic-{sid}")
            cfg["notes"] = st.text_area("Note", value=str(cfg.get("notes", system.get("notes", ""))), key=f"cfg-notes-{sid}")
            changed = True

    if st.button("Salva config"):
        if changed:
            save_json(CONFIG_PATH, config)
            st.success(f"Salvato {CONFIG_PATH}")

with tab_backtest:
    st.subheader("Backtest")
    st.write("Modulo pronto per collegarsi a `backtest/engine.py`.")
    uploaded = st.file_uploader("Upload CSV M1", type=["csv"])
    selected_strategy = st.selectbox(
        "Strategia",
        options=[s.get("id", "") for s in strategies.get("strategies", [])] or ["Nessuna strategia registrata"],
    )
    st.text_input("Pair", value="XAUUSD")
    st.number_input("Capitale iniziale", min_value=0.0, value=10000.0, step=1000.0)
    if st.button("Lancia backtest"):
        if uploaded is None:
            st.warning("Carica un CSV M1 o aggiungi dati in backtest/data.")
        else:
            st.info(f"Backtest richiesto per {selected_strategy}. Integrazione esecuzione in fase successiva.")

with tab_strategies:
    st.subheader("Registry strategie")
    strategy_rows = strategies.get("strategies", [])
    st.json(strategy_rows)
    st.caption("Aggiungero' qui le strategie estratte dai file TXT quando me li fornirai.")

with tab_logs:
    st.subheader("Ultimi log")
    selected = st.selectbox("Sistema", options=[s["id"] for s in systems])
    system = next((s for s in systems if s["id"] == selected), {})
    log_files = system.get("log_files") or []
    if not log_files:
        st.warning("Nessun log configurato per questo sistema.")
    for log_file in log_files:
        st.markdown(f"**{log_file}**")
        st.code(tail_file(log_file, 100), language="text")
