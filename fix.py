code = r"""import MetaTrader5 as mt5
import time, json, logging
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("prop.log", encoding="utf-8"), logging.StreamHandler()])
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
        self.loop_interval = 1.0
        self.state_file = Path("tradingo_state.json")
        self.magic = 20260001
        self._ticket = 0
        self._signal_id = 0
        self.max_spread = 80

    def _connect(self):
        if not mt5.initialize(path=self.terminal_path, login=self.login, password=self.password, server=self.server):
            log.error(f"Connessione fallita: {mt5.last_error()}")
            return False
        log.info("Connesso al terminale PROP")
        return True

    def get_market_data(self):
        tick = mt5.symbol_info_tick(self.symbol)
        sym = mt5.symbol_info(self.symbol)
        if tick is None or sym is None: return None, None
        spread = int((tick.ask - tick.bid) / sym.point)
        return tick, spread

    def _open_trade(self, signal, atr):
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None: return None
        if signal == Signal.BUY:
            ot, pr = mt5.ORDER_TYPE_SELL, tick.bid
            sl = pr + (atr * 1.5)
        else:
            ot, pr = mt5.ORDER_TYPE_BUY, tick.ask
            sl = pr - (atr * 1.5)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.prop_lot,
            "type": ot, "price": pr, "sl": sl, "magic": self.magic,
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"TRADE APERTO - Ticket: {res.order} | Prezzo: {pr} | SL: {sl}")
            return res.order
        log.error(f"Errore apertura: {res.comment if res else mt5.last_error()}")
        return None

    def run(self):
        if not self._connect(): return
        log.info("Prop Engine v2.3 Operativo - Telemetria attiva")
        while True:
            try:
                tick, sp = self.get_market_data()
                if tick:
                    sp_ok = "V" if sp <= self.max_spread else "X"
                    log.info(f"Ciclo -> sp={sp}[{sp_ok}] | Price={tick.bid:.2f} | Ticket={self._ticket}")
                else:
                    log.warning("In attesa dati MT5...")
                    time.sleep(2); continue

                if not self.state_file.exists():
                    time.sleep(1); continue
                try:
                    st = json.loads(self.state_file.read_text())
                except:
                    time.sleep(0.5); continue

                # Gestione posizione aperta
                if self._ticket > 0:
                    pos = mt5.positions_get(ticket=self._ticket)
                    if not pos:
                        log.info(f"Posizione {self._ticket} chiusa. Reset.")
                        self._ticket = 0
                    elif st.get("fase2_attiva") and not st.get("fase2_prop_sl_locked"):
                        atr = st.get("atr", 1.5)
                        buffer = 60 * mt5.symbol_info(self.symbol).point
                        if pos[0].type == mt5.ORDER_TYPE_SELL:
                            new_sl = tick.bid + buffer
                        else:
                            new_sl = tick.ask - buffer
                        log.info(f"[FASE 2] Congelamento SL Prop: {new_sl:.2f}")
                        res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": self._ticket, "symbol": self.symbol, "sl": new_sl})
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            st["fase2_prop_sl_locked"] = True
                            self.state_file.write_text(json.dumps(st, indent=2))

                # Handshake e apertura
                current_sig = st.get("signal", "NONE")
                sig_id = st.get("signal_id", 0)
                if current_sig != "NONE" and sig_id > self._signal_id and self._ticket == 0:
                    if st.get("hedge_ready"):
                        if sp <= self.max_spread:
                            log.info(f"Segnale {current_sig} (ID: {sig_id}) confermato. Apertura Prop...")
                            self._ticket = self._open_trade(current_sig, st.get("atr", 1.5))
                            self._signal_id = sig_id
                            if self._ticket:
                                st["prop_ticket"] = self._ticket
                                self.state_file.write_text(json.dumps(st, indent=2))
                        else:
                            log.warning(f"Spread troppo alto ({sp} > {self.max_spread})")

                time.sleep(self.loop_interval)
            except Exception as e:
                log.error(f"Errore: {e}")
                time.sleep(1)

if __name__ == "__main__":
    PropEngine().run()
"""

with open("tradingo_prop.py", "w", encoding="utf-8") as f:
    f.write(code)
print("tradingo_prop.py scritto correttamente!")
