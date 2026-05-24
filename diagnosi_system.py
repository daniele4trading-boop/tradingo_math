import json, time, os, subprocess, sys
from pathlib import Path
from datetime import datetime

STATE_FILE = Path("tradingo_state.json")
PROP_LOG = Path("prop.log")
HEDGE_LOG = Path("hedge.log")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}")

def check_file_access(path, label):
    """Verifica se un file esiste, è leggibile e scrivibile"""
    log(f"--- CHECK: {label} ({path}) ---")
    if not path.exists():
        log(f"  ❌ File NON ESISTE")
        return False
    
    # Dimensione
    size = path.stat().st_size
    log(f"  📄 Esiste | Dimensione: {size} bytes")
    
    # Leggibilità
    try:
        content = path.read_text(encoding="utf-8")
        log(f"  ✅ Leggibile | Primi 100 char: {content[:100]}...")
    except Exception as e:
        log(f"  ❌ NON leggibile: {e}")
        return False
    
    # Se è JSON, proviamo a parsarlo
    if path.suffix == ".json":
        try:
            data = json.loads(content)
            log(f"  ✅ JSON valido | Chiavi: {list(data.keys())}")
        except json.JSONDecodeError as e:
            log(f"  ❌ JSON CORROTTO: {e}")
            return False
    
    # Scrivibilità
    try:
        with open(path, "a") as f:
            pass  # Solo test di apertura in append
        log(f"  ✅ Scrivibile")
    except Exception as e:
        log(f"  ❌ NON scrivibile: {e}")
        return False
    
    return True

def check_mt5():
    """Verifica connessione MT5"""
    log("--- CHECK: MetaTrader 5 ---")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        log("  ❌ Modulo MetaTrader5 NON installato!")
        return False
    
    if not mt5.initialize():
        log(f"  ❌ MT5 Init fallito: {mt5.last_error()}")
        return False
    log("  ✅ MT5 inizializzato")
    
    # Prezzo
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick is None:
        log("  ❌ Tick XAUUSD = None (simbolo non trovato o non attivo)")
        mt5.shutdown()
        return False
    log(f"  ✅ Prezzo XAUUSD: Bid={tick.bid} Ask={tick.ask}")
    
    # Spread
    sym = mt5.symbol_info("XAUUSD")
    if sym:
        spread = int((tick.ask - tick.bid) / sym.point)
        log(f"  📊 Spread attuale: {spread} punti")
    
    # Storico
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 200)
    if rates is None or len(rates) == 0:
        log("  ❌ STORICO M5 VUOTO! Questo è il motivo del blocco!")
        log("  💡 SOLUZIONE: Apri il grafico XAUUSD M5 su MT5 e premi HOME")
    else:
        log(f"  ✅ Storico M5: {len(rates)} candele disponibili")
    
    # Rates per ATR (14 candele)
    rates14 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 14)
    if rates14 is None or len(rates14) < 14:
        log(f"  ❌ Solo {len(rates14) if rates14 is not None else 0} candele per ATR (servono 14)")
        log("  💡 L'Hedge si blocca qui: _get_atr() restituisce None")
    else:
        import numpy as np
        atr = np.mean(np.abs(rates14['high'] - rates14['low']))
        log(f"  ✅ ATR calcolabile: {atr:.4f}")
    
    mt5.shutdown()
    return True

def check_processes():
    """Verifica se i motori Python sono attivi"""
    log("--- CHECK: Processi Python attivi ---")
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True
        )
        lines = [l for l in result.stdout.strip().split("\n") if "python" in l.lower()]
        if lines:
            log(f"  ✅ Trovati {len(lines)} processi python.exe attivi")
            for l in lines:
                log(f"     {l.strip()}")
        else:
            log("  ❌ NESSUN processo python.exe attivo!")
            log("  💡 I motori NON sono in esecuzione. Avviali prima del test.")
    except:
        log("  ⚠ Impossibile verificare i processi")

def check_logs():
    """Verifica ultime righe dei log"""
    for logfile, label in [(PROP_LOG, "PROP LOG"), (HEDGE_LOG, "HEDGE LOG")]:
        log(f"--- CHECK: {label} ---")
        if not logfile.exists():
            log(f"  ❌ File {logfile} non esiste (motore mai avviato?)")
            continue
        try:
            lines = logfile.read_text(encoding="utf-8").strip().split("\n")
            log(f"  📄 Totale righe: {len(lines)}")
            log(f"  📅 Ultime 5 righe:")
            for l in lines[-5:]:
                log(f"     {l.strip()}")
            
            # Cerca problemi specifici
            last_lines = "\n".join(lines[-20:])
            if "DD_HALT" in last_lines or "DAILY_DD_ALERT" in last_lines:
                log(f"  ⚠ RILEVATO: Blocco Daily Drawdown nelle ultime righe!")
            if "Ciclo" in last_lines:
                log(f"  ✅ Il motore sta producendo cicli di telemetria")
            else:
                log(f"  ⚠ NESSUN ciclo 'Ciclo →' trovato nelle ultime 20 righe")
            if "In attesa" in last_lines:
                log(f"  ⚠ RILEVATO: Motore in attesa di dati MT5")
        except Exception as e:
            log(f"  ❌ Errore lettura log: {e}")

def inject_and_monitor():
    """Inietta segnale e monitora reazione in tempo reale"""
    log("="*60)
    log("FASE 2: INIEZIONE SEGNALE E MONITORAGGIO")
    log("="*60)
    
    sig_id = int(time.time())
    data = {
        "signal": "BUY",
        "signal_id": sig_id,
        "atr": 15.0,
        "hedge_ready": False,
        "prop_closed": False,
        "prop_ticket": 0,
        "hedge_ticket": 0,
        "fase2_attiva": False,
        "timestamp": datetime.utcnow().isoformat(),
        "mode": "DIAGNOSTIC_TEST"
    }
    
    log(f"📡 Scrittura segnale BUY (ID: {sig_id})...")
    try:
        STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log("  ✅ File scritto con successo")
    except Exception as e:
        log(f"  ❌ IMPOSSIBILE SCRIVERE: {e}")
        return
    
    # Monitoriamo per 30 secondi
    log("⏳ Monitoraggio reazione (30 secondi)...")
    
    prop_log_size = PROP_LOG.stat().st_size if PROP_LOG.exists() else 0
    hedge_log_size = HEDGE_LOG.stat().st_size if HEDGE_LOG.exists() else 0
    
    for i in range(30):
        time.sleep(1)
        changes = []
        
        # Check se il JSON è cambiato
        try:
            current = json.loads(STATE_FILE.read_text())
            if current.get("hedge_ready"):
                changes.append("hedge_ready=TRUE ✅")
            if current.get("prop_ticket", 0) > 0:
                changes.append(f"prop_ticket={current['prop_ticket']} ✅")
            if current.get("hedge_ticket", 0) > 0:
                changes.append(f"hedge_ticket={current['hedge_ticket']} ✅")
            if current.get("signal_id") != sig_id:
                changes.append(f"⚠ signal_id CAMBIATO: {current.get('signal_id')} (era {sig_id})")
        except:
            changes.append("⚠ JSON illeggibile")
        
        # Check se i log sono cresciuti
        if PROP_LOG.exists():
            new_size = PROP_LOG.stat().st_size
            if new_size > prop_log_size:
                # Leggi le nuove righe
                with open(PROP_LOG, "r", encoding="utf-8") as f:
                    f.seek(prop_log_size)
                    new_lines = f.read().strip().split("\n")
                for nl in new_lines:
                    if nl.strip():
                        changes.append(f"[PROP] {nl.strip()}")
                prop_log_size = new_size
        
        if HEDGE_LOG.exists():
            new_size = HEDGE_LOG.stat().st_size
            if new_size > hedge_log_size:
                with open(HEDGE_LOG, "r", encoding="utf-8") as f:
                    f.seek(hedge_log_size)
                    new_lines = f.read().strip().split("\n")
                for nl in new_lines:
                    if nl.strip():
                        changes.append(f"[HEDGE] {nl.strip()}")
                hedge_log_size = new_size
        
        if changes:
            log(f"[T+{i+1}s] Cambiamenti rilevati:")
            for c in changes:
                log(f"  → {c}")
            
            # Se entrambi hanno risposto, successo
            try:
                final = json.loads(STATE_FILE.read_text())
                if final.get("prop_ticket", 0) > 0:
                    log("🔥 SUCCESS: Trade aperti con successo!")
                    return
            except:
                pass
        else:
            if i % 5 == 4:  # Ogni 5 secondi se nulla cambia
                log(f"[T+{i+1}s] ... nessuna reazione dai motori")
    
    log("")
    log("❌ TIMEOUT: Nessuna reazione completa dopo 30 secondi")
    log("")
    log("📋 DIAGNOSI FINALE:")
    try:
        final = json.loads(STATE_FILE.read_text())
        if not final.get("hedge_ready"):
            log("  → L'HEDGE non ha scritto hedge_ready=True")
            log("  → Possibili cause:")
            log("    1. Il motore hedge NON è in esecuzione")
            log("    2. Il motore hedge è bloccato su _get_atr() (dati storici mancanti)")
            log("    3. Il motore hedge ha un nome diverso per state_file")
        elif final.get("hedge_ready") and final.get("prop_ticket", 0) == 0:
            log("  → L'Hedge ha risposto, ma la PROP non ha aperto")
            log("  → Possibili cause:")
            log("    1. Il motore prop NON è in esecuzione")
            log("    2. Spread troppo alto")
            log("    3. Il motore prop è bloccato prima di leggere il JSON")
    except:
        log("  → Impossibile leggere lo stato finale")

def main():
    log("="*60)
    log("  TRADINGO SYSTEM DIAGNOSTIC v1.0")
    log(f"  Cartella: {os.getcwd()}")
    log(f"  Data/Ora: {datetime.now()}")
    log("="*60)
    print()
    
    # Fase 1: Diagnostica
    log("FASE 1: DIAGNOSTICA COMPLETA")
    log("="*60)
    
    check_processes()
    print()
    check_mt5()
    print()
    check_file_access(STATE_FILE, "State File JSON")
    print()
    check_file_access(Path("config.json"), "Config JSON")
    print()
    check_logs()
    print()
    
    # Fase 2: Test Iniezione
    input("Premi INVIO per procedere con l'iniezione del segnale di test...")
    print()
    inject_and_monitor()

if __name__ == "__main__":
    main()
