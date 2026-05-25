import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from manual_trading.order_manager import ManualTradeInput, OrderManager, build_manual_trade_plan

REGISTRY_PATH = ROOT / "config" / "systems_registry.json"
CONFIG_PATH = ROOT / "config" / "systems_config.json"
STRATEGIES_PATH = ROOT / "strategies" / "registry.json"
SCRIPTS_DIR = ROOT / "scripts"
DEFAULT_MANUAL_DB = ROOT / "data" / "manual_orders.sqlite"


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


def run_python_module(module: str, *args: str, timeout: int = 120) -> tuple[int, str]:
    cmd = [sys.executable, "-m", module, *args]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
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
manual_config = config.setdefault("manual_trading", {})
manual_db_path = ROOT / manual_config.get("orders_db", "data/manual_orders.sqlite")
order_manager = OrderManager(manual_db_path)
process_status = get_process_rows(systems)

st.title("TradinGO Platform Control Center")
st.caption("Dashboard unificata per sistemi live, strategie, backtest, config, log e script di gestione.")

if st.button("Refresh"):
    st.rerun()

tab_status, tab_manual, tab_config, tab_backtest, tab_strategies, tab_logs = st.tabs(
    ["Stato sistemi", "Manual Trade", "Configurazione", "Backtest", "Strategie", "Log"]
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


with tab_manual:
    st.subheader("Manual Trade - TradinGO-Math")
    st.warning(
        "Fase 2 demo: questa schermata calcola, mette in coda ed esegue su MT5 solo se execution_enabled e' attivo. "
        "Usare prima lotti minimi e conti demo."
    )

    defaults = {
        "tenant_id": manual_config.get("default_tenant_id", "daniele"),
        "symbol": manual_config.get("default_symbol", "XAUUSD"),
        "entry_price": float(manual_config.get("default_reference_price", 3300.0)),
        "sl_distance": float(manual_config.get("default_sl_distance", 10.0)),
        "tp_distance": float(manual_config.get("default_tp_distance", 20.0)),
        "prop_balance": float(manual_config.get("default_prop_balance", 100000.0)),
        "hedge_balance": float(manual_config.get("default_hedge_balance", 10000.0)),
        "prop_risk_pct": float(manual_config.get("default_prop_risk_pct", 0.5)),
        "contract_size": float(manual_config.get("contract_size", 100.0)),
        "hedge_multiplier": float(manual_config.get("hedge_lot_multiplier", 1.4)),
        "max_prop_lot": float(manual_config.get("max_prop_lot", 10.0)),
        "max_hedge_lot": float(manual_config.get("max_hedge_lot", 10.0)),
        "hedge_equity_floor": float(manual_config.get("hedge_equity_floor", 0.0)),
        "phase2_trigger_sl_fraction": float(manual_config.get("phase2_trigger_sl_fraction", 0.5)),
        "execution_enabled": bool(manual_config.get("execution_enabled", False)),
    }

    with st.form("manual_trade_form"):
        c1, c2, c3 = st.columns(3)
        tenant_id = c1.text_input("Tenant / utente", value=defaults["tenant_id"])
        symbol = c2.text_input("Symbol", value=defaults["symbol"])
        hedge_direction = c3.selectbox("Direzione Hedge", options=["BUY", "SELL"], help="La prop viene calcolata speculare/contraria.")

        c4, c5, c6 = st.columns(3)
        entry_price = c4.number_input("Prezzo riferimento", min_value=0.00001, value=defaults["entry_price"], step=0.1)
        sl_distance = c5.number_input("Distanza SL punti/prezzo", min_value=0.00001, value=defaults["sl_distance"], step=0.1)
        tp_distance = c6.number_input("Distanza TP punti/prezzo", min_value=0.00001, value=defaults["tp_distance"], step=0.1)

        c7, c8, c9 = st.columns(3)
        prop_balance = c7.number_input("Balance prop", min_value=0.0, value=defaults["prop_balance"], step=1000.0)
        hedge_balance = c8.number_input("Balance hedge", min_value=0.0, value=defaults["hedge_balance"], step=1000.0)
        prop_risk_pct = c9.number_input("Rischio prop per trade %", min_value=0.0, value=defaults["prop_risk_pct"], step=0.1)

        c10, c11, c12, c13 = st.columns(4)
        daily_dd_max = c10.number_input("Max DD daily prop %", min_value=0.0, value=float(config.get("risk_limits", {}).get("prop_daily_drawdown_max_pct", 3.0)), step=0.1)
        total_dd_max = c11.number_input("Max DD total prop %", min_value=0.0, value=float(config.get("risk_limits", {}).get("prop_total_drawdown_max_pct", 10.0)), step=0.1)
        daily_dd_used = c12.number_input("DD daily gia' usato %", min_value=0.0, value=0.0, step=0.1)
        total_dd_used = c13.number_input("DD total gia' usato %", min_value=0.0, value=0.0, step=0.1)

        c14, c15, c16 = st.columns(3)
        contract_size = c14.number_input("Contract size", min_value=0.00001, value=defaults["contract_size"], step=1.0)
        hedge_multiplier = c15.number_input("Moltiplicatore hedge", min_value=0.0, value=defaults["hedge_multiplier"], step=0.1)
        max_hedge_lot = c16.number_input("Max hedge lot", min_value=0.01, value=defaults["max_hedge_lot"], step=0.1)

        c17, c18, c19 = st.columns(3)
        hedge_equity_floor = c17.number_input("Equity floor hedge assoluto", min_value=0.0, value=defaults["hedge_equity_floor"], step=100.0, help="Se equity hedge <= questo valore, l'executor chiude le posizioni hedge secondo lo scope configurato.")
        phase2_fraction = c18.number_input("Trigger Fase 2 x SL", min_value=0.0, value=defaults["phase2_trigger_sl_fraction"], step=0.1, help="0.5 significa: fase2 quando il movimento raggiunge 50% della distanza SL.")
        execution_enabled = c19.checkbox("Esecuzione demo MT5 abilitata", value=defaults["execution_enabled"])

        notes = st.text_area("Note piano", value="")
        calculate = st.form_submit_button("Calcola piano")
        queue = st.form_submit_button("Metti in coda")
        execute_now = st.form_submit_button("Apri subito su MT5 demo", type="primary")

    if calculate or queue or execute_now:
        manual_config.update({
            "default_symbol": symbol.strip().upper() or "XAUUSD",
            "default_reference_price": entry_price,
            "default_sl_distance": sl_distance,
            "default_tp_distance": tp_distance,
            "default_prop_balance": prop_balance,
            "default_hedge_balance": hedge_balance,
            "default_prop_risk_pct": prop_risk_pct,
            "contract_size": contract_size,
            "hedge_lot_multiplier": hedge_multiplier,
            "max_hedge_lot": max_hedge_lot,
            "hedge_equity_floor": hedge_equity_floor,
            "phase2_trigger_sl_fraction": phase2_fraction,
            "execution_enabled": execution_enabled,
        })
        save_json(CONFIG_PATH, config)
        try:
            manual_input = ManualTradeInput(
                tenant_id=tenant_id.strip() or "daniele",
                symbol=symbol.strip().upper() or "XAUUSD",
                hedge_direction=hedge_direction,
                entry_price=entry_price,
                sl_distance=sl_distance,
                tp_distance=tp_distance,
                prop_balance=prop_balance,
                hedge_balance=hedge_balance,
                prop_daily_dd_max_pct=daily_dd_max,
                prop_total_dd_max_pct=total_dd_max,
                prop_daily_dd_used_pct=daily_dd_used,
                prop_total_dd_used_pct=total_dd_used,
                prop_risk_pct=prop_risk_pct,
                prop_contract_size=contract_size,
                hedge_lot_multiplier=hedge_multiplier,
                max_prop_lot=defaults["max_prop_lot"],
                max_hedge_lot=max_hedge_lot,
                notes=notes,
            )
            plan = build_manual_trade_plan(manual_input)
            st.session_state["last_manual_plan"] = plan
            if queue or execute_now:
                order_manager.queue_plan(plan)
                st.success(f"Piano messo in coda: {plan.plan_id}")
            if execute_now:
                if not manual_config.get("execution_enabled", False):
                    st.error("execution_enabled e' false. Abilita la spunta nel form prima di eseguire.")
                else:
                    code, out = run_python_module("manual_trading.executor", "--once", timeout=180)
                    if code == 0:
                        st.success("Executor completato: controlla ticket/stato nella coda.")
                    else:
                        st.error(f"Executor errore {code}")
                    if out:
                        st.code(out, language="text")
                    st.rerun()
        except Exception as exc:
            st.error(f"Errore calcolo piano: {exc}")

    plan = st.session_state.get("last_manual_plan")
    if plan:
        st.markdown("### Piano suggerito")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Prop", f"{plan.prop_direction} {plan.prop_lot:.2f} lot")
        m2.metric("Hedge", f"{plan.hedge_direction} {plan.hedge_lot:.2f} lot")
        m3.metric("Risk budget prop", f"{plan.risk_budget:.2f}")
        m4.metric("Perdita prop stimata", f"{plan.estimated_prop_loss:.2f}")

        st.json(
            {
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "entry_price": plan.entry_price,
                "prop": {"direction": plan.prop_direction, "lot": plan.prop_lot, "sl": plan.prop_sl, "tp": plan.prop_tp},
                "hedge": {"direction": plan.hedge_direction, "lot": plan.hedge_lot, "sl": plan.hedge_sl, "tp": plan.hedge_tp},
                "estimates": {
                    "prop_loss": plan.estimated_prop_loss,
                    "prop_profit": plan.estimated_prop_profit,
                    "hedge_loss": plan.estimated_hedge_loss,
                    "hedge_profit": plan.estimated_hedge_profit,
                    "remaining_daily_dd_pct": plan.remaining_daily_dd_pct,
                    "remaining_total_dd_pct": plan.remaining_total_dd_pct,
                },
            }
        )

    st.markdown("### Esecuzione demo")
    st.caption("Se hai gia' ordini in coda, usa il bottone qui sotto. Per un nuovo trade puoi usare direttamente 'Apri subito su MT5 demo' nel form.")
    c_exec1, c_exec2 = st.columns(2)
    if c_exec1.button("Esegui coda ora su MT5", type="primary"):
        if not manual_config.get("execution_enabled", False):
            st.error("execution_enabled e' false. Abilita la spunta nel form e ricalcola/salva prima di eseguire.")
        else:
            code, out = run_python_module("manual_trading.executor", "--once", timeout=180)
            if code == 0:
                st.success("Executor completato.")
            else:
                st.error(f"Executor errore {code}")
            if out:
                st.code(out, language="text")
            st.rerun()
    if c_exec2.button("Aggiorna coda"):
        st.rerun()

    st.markdown("### Coda ordini manuali")
    orders = order_manager.list_orders(limit=50)
    if orders:
        visible_cols = [
            "created_at", "tenant_id", "symbol", "status", "hedge_direction", "prop_direction",
            "prop_lot", "hedge_lot", "prop_sl", "prop_tp", "hedge_sl", "hedge_tp",
            "prop_ticket", "hedge_ticket", "phase2_active", "estimated_prop_loss",
            "estimated_hedge_profit", "execution_error",
        ]
        st.dataframe([{k: row.get(k) for k in visible_cols} for row in orders], use_container_width=True)
    else:
        st.info("Nessun ordine manuale in coda.")

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
