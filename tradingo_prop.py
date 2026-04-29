import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time, json, logging
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum

# Configurazione Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("prop.log", encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("PROP")

class Signal(str, Enum):
    BUY = "BUY"; SELL = "SELL"; NONE = "NONE"

class PropEngine:
    def __init__(self):
        self.terminal_path = r"C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe"
        self.login = 1610077148
        self.password = "4h!R9TkJ"
        self.server = "STARTRADERFinancial-Demo"
        self.symbol = "XAUUSD"
        self.prop_lot = 1.00
        self.loop_interval = 0.5  # Sincronizzazione millimetrica
        self.state_file = Path("tradingo_state.json")
        self.magic = 20260001
        self._ticket = 0
        self._signal_id = 0

    def _connect(self):
        if not mt5.initialize(path=self.terminal_path, login=self.login, password=self.password, server=self.server):
            log.error(f"Connessione fallita: {mt5.last_error()}")
            return False
        log.info("Connesso al terminale PROP")
        return True

    def _open_trade(self, signal, atr):
        tick = mt5.symbol_info_tick(self.symbol)
        if signal == Signal.BUY:
            ot, pr = mt5.ORDER_TYPE_SELL, tick.bid
            sl = pr + (atr * 1.5)
        else:
            ot, pr = mt5.ORDER_TYPE_BUY, tick.ask
            sl = pr - (atr * 1.5)
        
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.prop_lot,
            "type": ot, "price": pr, "sl": sl, "magic": self.magic,
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"TRADE APERTO - Ticket: {res.order} | Prezzo: {pr} | SL: {sl} | ATR: {atr:.2f}")
            return res.order
        log.error(f"Errore apertura: {res.comment if res else mt5.last_error()}")
        return None

    def run(self):
        if not self._connect(): return
        log.info("Prop Engine v2.3 in ascolto...")
        while True:
            try:
                if not self.state_file.exists(): 
                    time.sleep(1); continue
                
                st = json.loads(self.state_file.read_text())
                
                # Monitoraggio Fase 2
                if self._ticket > 0 and st.get("fase2_attiva") and not st.get("fase2_prop_sl_locked"):
                    pos = mt5.positions_get(ticket=self._ticket)
                    if pos:
                        atr = st.get("atr", 1.5)
                        tick = mt5.symbol_info_tick(self.symbol)
                        buffer = atr * 0.5
                        new_sl = (tick.bid + buffer) if pos[0].type == mt5.ORDER_TYPE_SELL else (tick.ask - buffer)
                        
                        log.info(f"[FASE 2] Congelamento SL Prop - Caso: {st.get('fase2_caso')} | New SL: {new_sl:.2f} | Buffer ATR: {buffer:.2f}")
                        res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": self._ticket, "sl": new_sl})
                        if res.retcode == mt5.TRADE_RETCODE_DONE:
                            st["fase2_prop_sl_locked"] = True
                            self.state_file.write_text(json.dumps(st))
                            log.info("SL Prop bloccato con successo")

                # Handshake con Hedge
                current_sig = st.get("signal", "NONE")
                sig_id = st.get("signal_id", 0)
                if current_sig != "NONE" and sig_id > self._signal_id:
                    if st.get("hedge_ready"):
                        log.info(f"Ricevuto segnale {current_sig} (ID: {sig_id}) - Hedge confermato, apro Prop...")
                        self._ticket = self._open_trade(current_sig, st.get("atr", 1.5))
                        self._signal_id = sig_id
                        st["prop_ticket"] = self._ticket
                        self.state_file.write_text(json.dumps(st))
                
                time.sleep(self.loop_interval)
            except Exception as e:
                log.error(f"Errore nel loop: {e}")
                time.sleep(1)

if __name__ == "__main__":
    PropEngine().run()
