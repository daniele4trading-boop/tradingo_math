"""Risk manager per la challenge Velotrade PRO 1-Step.

Regole implementate (fonte: velotrade.com/challenges e velotrade.com/how-it-works):

* max drawdown **statico**: floor fissato all'attivazione al `1 - max_dd_pct` del
  saldo iniziale, mai spostato (10.000 -> 9.700 al 3%);
* daily loss: l'equity non puo' scendere piu' di `daily_loss_pct` sotto il saldo di
  chiusura del giorno precedente; il contatore si azzera ogni giorno alle 00:30 UTC;
* entrambi i vincoli sono valutati sull'**equity flottante**, quindi il floor
  effettivo e' il piu' alto dei due.

Il sizing usa il modello a serbatoio: si rischia una frazione fissa della distanza
fra saldo e floor, cosi' il serbatoio si contrae del fattore (1 - f) a ogni perdita
piena e non puo' azzerarsi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta


@dataclass(frozen=True)
class RiskConfig:
    initial_balance: float
    cap_size: float
    max_dd_pct: float = 0.03
    daily_loss_pct: float = 0.03
    daily_reset_utc: time = time(0, 30)
    risk_fraction: float = 0.05
    block_new_at_allowance_used: float = 0.60
    close_all_at_allowance_used: float = 0.80
    max_open_positions: int = 2
    max_open_positions_per_strategy: int = 1
    min_quantity: float = 0.01
    quantity_increment: float = 0.01
    round_below_min_to_min: bool = True


@dataclass
class AccountState:
    """Fotografia del conto letta dal broker piu' lo stato del contatore daily."""

    equity: float
    balance: float
    open_positions: int = 0
    day_start_balance: float | None = None
    day_key: date | None = None
    halted_until_reset: bool = False


class RiskDecision(str):
    pass


ALLOW = "ALLOW"
BLOCK_NEW = "BLOCK_NEW"
CLOSE_ALL = "CLOSE_ALL"


def trading_day_key(now: datetime, reset: time) -> date:
    """Giorno di trading corrente: cambia al reset (00:30 UTC), non a mezzanotte."""
    now = now.astimezone(UTC)
    boundary = now.replace(
        hour=reset.hour, minute=reset.minute, second=0, microsecond=0
    )
    if now < boundary:
        return (now - timedelta(days=1)).date()
    return now.date()


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

    # --- floor ---------------------------------------------------------------

    @property
    def static_floor(self) -> float:
        return self.cfg.initial_balance * (1.0 - self.cfg.max_dd_pct)

    def daily_floor(self, day_start_balance: float) -> float:
        return day_start_balance * (1.0 - self.cfg.daily_loss_pct)

    def effective_floor(self, state: AccountState) -> float:
        day_start = (
            state.day_start_balance
            if state.day_start_balance is not None
            else self.cfg.initial_balance
        )
        return max(self.static_floor, self.daily_floor(day_start))

    def allowance(self, state: AccountState) -> float:
        """Perdita ancora consentita nella giornata, dal saldo di inizio giornata."""
        day_start = (
            state.day_start_balance
            if state.day_start_balance is not None
            else self.cfg.initial_balance
        )
        return max(0.0, day_start - self.effective_floor(state))

    def allowance_used(self, state: AccountState) -> float:
        allowance = self.allowance(state)
        if allowance <= 0:
            return 1.0
        day_start = (
            state.day_start_balance
            if state.day_start_balance is not None
            else self.cfg.initial_balance
        )
        return max(0.0, (day_start - state.equity) / allowance)

    # --- serbatoio e sizing --------------------------------------------------

    def static_reservoir(self, state: AccountState) -> float:
        """Serbatoio di lungo periodo: distanza dal floor statico, congelata a cap_size."""
        return max(0.0, min(state.balance, self.cfg.cap_size) - self.static_floor)

    def daily_reservoir(self, state: AccountState) -> float:
        """Margine residuo verso il floor che morde oggi, sull'equity flottante."""
        return max(0.0, state.equity - self.effective_floor(state))

    def reservoir(self, state: AccountState) -> float:
        """Il serbatoio effettivo e' il piu' stretto dei due vincoli.

        Serve entrambi i termini: il primo congela la size a regime (cap_size), il
        secondo evita che una giornata gia' in perdita rischi come una giornata
        appena aperta, e tiene la size positiva anche quando il daily floor sale
        sopra cap_size perche' il conto e' molto in profitto.
        """
        return min(self.static_reservoir(state), self.daily_reservoir(state))

    def risk_amount(self, state: AccountState) -> float:
        return self.cfg.risk_fraction * self.reservoir(state)

    def quantity(self, state: AccountState, sl_distance: float) -> tuple[float, str]:
        """Quantita' in once per XAU (lotSize=1: 1 unita' = 1 USD per 1 USD di prezzo).

        Ritorna (quantita', motivo). Quantita' 0 significa "non operare".
        """
        if sl_distance <= 0:
            return 0.0, "sl_distance<=0"
        raw = self.risk_amount(state) / sl_distance
        step = self.cfg.quantity_increment
        rounded = math.floor(raw / step) * step
        rounded = round(rounded, 8)
        if rounded < self.cfg.min_quantity:
            if self.cfg.round_below_min_to_min:
                return self.cfg.min_quantity, "rounded_up_to_min"
            return 0.0, "below_min_quantity"
        return rounded, "ok"

    # --- guard --------------------------------------------------------------

    def evaluate(self, state: AccountState) -> tuple[str, str]:
        """Decisione di rischio corrente: ALLOW / BLOCK_NEW / CLOSE_ALL."""
        floor = self.effective_floor(state)
        if state.equity <= floor:
            return CLOSE_ALL, "equity_at_or_below_floor"
        used = self.allowance_used(state)
        if used >= self.cfg.close_all_at_allowance_used:
            return CLOSE_ALL, f"allowance_used={used:.3f}"
        if state.halted_until_reset:
            return BLOCK_NEW, "halted_until_reset"
        if used >= self.cfg.block_new_at_allowance_used:
            return BLOCK_NEW, f"allowance_used={used:.3f}"
        if state.open_positions >= self.cfg.max_open_positions:
            return BLOCK_NEW, "max_open_positions"
        return ALLOW, "ok"

    def close_all_equity(self, state: AccountState) -> float:
        day_start = (
            state.day_start_balance
            if state.day_start_balance is not None
            else self.cfg.initial_balance
        )
        return day_start - self.cfg.close_all_at_allowance_used * self.allowance(state)

    def block_new_equity(self, state: AccountState) -> float:
        day_start = (
            state.day_start_balance
            if state.day_start_balance is not None
            else self.cfg.initial_balance
        )
        return day_start - self.cfg.block_new_at_allowance_used * self.allowance(state)

    def roll_day(self, state: AccountState, now: datetime) -> bool:
        """Aggiorna il contatore giornaliero al reset. True se il giorno e' cambiato."""
        key = trading_day_key(now, self.cfg.daily_reset_utc)
        if state.day_key == key:
            return False
        state.day_key = key
        state.day_start_balance = state.balance
        state.halted_until_reset = False
        return True
