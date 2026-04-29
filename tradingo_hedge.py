import MetaTrader5 as mt5
import numpy as np
import time, json, logging
from datetime import datetime, timezone
from pathlib import Path

# Configurazione Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("hedge.log", encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("HEDGE")

class HedgeEngine:
    def __init__(self):
        # Parametri di Login forzati per Ultima Markets
        self.terminal_path = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
        self.login = 843409
        self.password = "v!34bIbx"
        self.server = "UltimaMarkets-Demo"
        
        self.symbol = "XAUUSD"
        self.state_file = Path("tradingo_state.json")
        self.magic = 20260002
        self.loop_interval = 1.0

    def _get_atr(self):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, 14)
        if rates is None or len(rates) < 14: return 1.5
        return np.mean(np.abs(rates['high'] - rates['low']))

    def _connect(self):
        # Forza l'apertura del terminale corretto e il login
        ok = mt5.initialize(
            path=self.terminal_path, 
            login=self.login, 
            password=self.password, 
            server=self.server
        )
        if not ok:
            log.error(f"Connessione Ultima Markets FALLITA: {mt5.last_error()}")
            return False
        
        acc = mt5.account_info()
        if acc:
            log.info(f"Hedge Connesso -> Account: {acc.login} | Server: {acc.server} | Balance: {acc.balance}")
        return True

    def run(self):
        if not self._connect(): return
        log.info("Hedge Engine v2.5 operativo su Ultima Markets")
        
        while True:
            try:
                if not self.state_file.exists():
                    time.sleep(1); continue

                st = json.loads(self.state_file.read_text())
                atr = self._get_atr()
                tick = mt5.symbol_info_tick(self.symbol)
                
                # Check Trigger Fase 2 (1.2x ATR)
                if st.get("prop_ticket") and not st.get("fase2_attiva"):
                    entry = st.get("prop_entry_price", 0)
                    dist = abs(tick.bid - entry)
                    trigger_val = atr * 1.2
                    
                    if dist >= trigger_val:
                        log.info(f"TRIGGER FASE 2 - Distanza: {dist:.2f} >= Soglia: {trigger_val:.2f}")
                        st["fase2_attiva"] = True
                        buffer = atr * 0.5 # Buffer Dinamico Anti-Rumore
                        
                        hedge_pos = mt5.positions_get(magic=self.magic)
                        if hedge_pos:
                            h = hedge_pos[0]
                            nsl = (tick.bid - buffer) if h.type == mt5.ORDER_TYPE_BUY else (tick.ask + buffer)
                            log.info(f"Decoupling Hedge - New SL (0.5x ATR): {nsl:.2f}")
                            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": h.ticket, "sl": nsl})
                        
                        self.state_file.write_text(json.dumps(st))

                # Gestione Trailing Post-Decoupling
                if st.get("fase2_attiva"):
                    hedge_pos = mt5.positions_get(magic=self.magic)
                    if hedge_pos:
                        h = hedge_pos[0]
                        trail_dist = atr * 1.5
                        nsl = (tick.bid - trail_dist) if h.type == mt5.ORDER_TYPE_BUY else (tick.ask + trail_dist)
                        
                        if (h.type == mt5.ORDER_TYPE_BUY and nsl > h.sl) or (h.type == mt5.ORDER_TYPE_SELL and (nsl < h.sl or h.sl == 0)):
                            log.info(f"TRAILING HEDGE - New SL: {nsl:.2f}")
                            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": h.ticket, "sl": nsl})

                time.sleep(self.loop_interval)
            except Exception as e:
                log.error(f"Errore loop Hedge: {e}")
                time.sleep(1)

if __name__ == "__main__":
    HedgeEngine().run()

