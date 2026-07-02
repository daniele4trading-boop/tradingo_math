"""
TG TradinGo Bridge - v2.0
Sessione Telegram riutilizzata da C:\\TelegramBridge\\telegram_bridge_session.session

CANALI:
  CH1 - ZANNI VIP SIGNALS       (-1003026686847)
  CH2 - SALA GOLD VIP           (-1003302540529)
  CH3 - SALA VIP                (-1002890661441)
  CH4 - SALA STARK              (-1002073368935)
"""

import asyncio
import json
import os
import re
import sys
import time
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events

from bridge_core import (
    BridgeState,
    ProcessedMessageStore,
    atomic_write_text,
    validate_signal,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

_BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.environ.get(
    "TRADINGO_CONFIG",
    os.path.join(_BASE_DIR, "tradingo_config.json"),
)

def load_config():
    cfg_path = CONFIG_FILE
    if not os.path.exists(cfg_path):
        example = os.path.join(_BASE_DIR, "tradingo_config.example.json")
        if os.path.exists(example):
            cfg_path = example
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR  = Path(CONFIG["paths"]["logs"])
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"tradingo_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("TradinGo")

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────

log = logging.getLogger("TradinGo")

SIGNALS_DIR: Path | None = None
STATE_DIR: Path | None = None
BRIDGE_STATE: BridgeState | None = None
PROCESSED_MESSAGES: ProcessedMessageStore | None = None


def _paths() -> tuple[Path, Path]:
    signals = Path(CONFIG["paths"]["signals"])
    state = Path(CONFIG["paths"].get("state", Path(CONFIG["paths"]["base"]) / "state"))
    return signals, state


def _ensure_runtime() -> tuple[BridgeState, ProcessedMessageStore]:
    global SIGNALS_DIR, STATE_DIR, BRIDGE_STATE, PROCESSED_MESSAGES
    if BRIDGE_STATE is None:
        SIGNALS_DIR, STATE_DIR = _paths()
        SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BRIDGE_STATE = BridgeState(STATE_DIR / "bridge_state.json")
        PROCESSED_MESSAGES = ProcessedMessageStore(STATE_DIR / "processed_messages.json")
    return BRIDGE_STATE, PROCESSED_MESSAGES

def get_mt5_paths():
    return [i["signals_path"] for i in CONFIG.get("mt5_instances", []) if i.get("enabled", True)]

def write_signal(channel_cfg: dict, signal: dict, meta: dict | None = None):
    signal["timestamp"]    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signal["channel_id"]   = channel_cfg["id"]
    signal["channel_name"] = channel_cfg["name"]
    if meta:
        signal["message_id"]    = meta.get("message_id")
        signal["chat_id"]       = meta.get("chat_id")
        signal["telegram_date"] = meta.get("telegram_date")
        signal["event_type"]    = meta.get("event_type")

    ok, reason = validate_signal(signal)
    if not ok:
        log.error(f"[{channel_cfg['id']}] Segnale non valido: {reason} | action={signal.get('action')}")
        return False

    payload = json.dumps(signal, indent=2)
    for mt5_path in get_mt5_paths():
        out_file = Path(mt5_path) / channel_cfg["signal_file"]
        try:
            atomic_write_text(out_file, payload)
            log.info(f"[{channel_cfg['id']}] -> {out_file.name} | "
                     f"action={signal.get('action')} symbol={signal.get('symbol','')} "
                     f"dir={signal.get('direction','')}")
        except Exception as e:
            log.error(f"[{channel_cfg['id']}] Errore scrittura {out_file}: {e}")
            return False
    return True

def pf(s: str) -> float:
    """Parse float pulito: rimuove asterischi, spazi, virgole."""
    return float(re.sub(r"[^\d.]", "", s.strip().replace(",", ".")))

def normalize_symbol(raw: str) -> str:
    """Rimuove suffisso 'pm', mappa alias (GOLD -> XAUUSD)."""
    s = raw.upper().strip()
    s = re.sub(r"PM$", "", s)
    aliases = {"GOLD": "XAUUSD"}
    return aliases.get(s, s)

def strip_md(text: str) -> str:
    """Rimuove markdown e caratteri invisibili (zero-width spaces, ecc.)."""
    # Rimuove markdown
    text = re.sub(r"[*`_]", " ", text)
    # Rimuove caratteri zero-width e spazi non-breaking invisibili
    text = re.sub(r"[​‌‍‎‏﻿ ⁠]", " ", text)
    # Normalizza spazi multipli
    text = re.sub(r"  +", " ", text)
    return text

def contains_any(text: str, *words) -> bool:
    t = text.upper()
    return any(w.upper() in t for w in words)

# ─────────────────────────────────────────────────────────────────────────────
# PARSER CH1 — ZANNI VIP SIGNALS
# ─────────────────────────────────────────────────────────────────────────────
#
# Formato segnale (multiriga):
#   [emoji] BUY/SELL SIMBOLO ENTRY
#   TP1: xxx
#   TP2: xxx
#   TP3: xxx
#   SL:  xxx
#
# Azioni emesse:
#   OPEN              -> nuovo trade
#   CHECK_AND_BE      -> verifica se TP1 raggiunto, se no sposta SL a BE ora
#   CHECK_AND_CLOSE_TP -> verifica se TP N gia' chiuso, se no chiudi ora

def parser_zanni_vip(text: str, ch: dict) -> dict | None:
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── 1. BE signal ─────────────────────────────────────────────────────────
    # "TP1 ✅ Spostiamo SL a BE" / "TP1 preso, sposto a BE" / "porto a BE"
    # Anche senza menzione TP1: "porto stop a BE", "sposto a BE", "metto a BE"
    be_with_tp1 = re.search(r"TP\s*1", upper) and contains_any(upper, " BE", "BREAK EVEN", "PAREGGIO")
    be_generic  = contains_any(upper, "PORTO STOP A BE", "SPOSTO A BE", "SPOSTO SL A BE",
                                "METTO A BE", "PORTO A BE", "MOVE TO BE", "SET BE")
    if be_with_tp1 or be_generic:
        log.info(f"[CH1] CHECK_AND_BE: {raw[:60]}")
        return {"action": "CHECK_AND_BE", "tp_index": 1, "raw_message": raw}

    # ── 1b. "TP2 preso" / "chiudiamo TP3" → chiudi quel TP ─────────────────
    # IMPORTANTE: questo check viene PRIMA del generico per evitare falsi positivi
    m_tp_preso = re.search(r"TP\s*(\d)\s*(?:PRESO|HIT|DONE|TAKEN|✅)", upper)
    if m_tp_preso:
        tp_n = int(m_tp_preso.group(1))
        log.info(f"[CH1] CHECK_AND_CLOSE_TP{tp_n} (preso): {raw[:60]}")
        return {"action": "CHECK_AND_CLOSE_TP", "tp_index": tp_n, "raw_message": raw}

    m_cl = re.search(r"(?:CHIUD[OI]\w*|CLOSING)\b.*?TP\s*(\d)", upper)
    if m_cl:
        tp_n = int(m_cl.group(1))
        log.info(f"[CH1] CHECK_AND_CLOSE_TP{tp_n}: {raw[:60]}")
        return {"action": "CHECK_AND_CLOSE_TP", "tp_index": tp_n, "raw_message": raw}

    # ── 2a. Chiusura generica senza menzione TP ──────────────────────────────
    # "cambio di trend, chiudiamo ora" — solo se NON c'è un numero TP
    close_generic = [
        r"CAMBIO\s+DI\s+TREND", r"CHIUDIAMO\s+ORA", r"CHIUDO\s+ORA",
        r"CLOSING\s+NOW", r"CLOSE\s+NOW", r"CHIUDO\s+TUTTO",
        r"CHIUDIAMO\s+TUTTO", r"USCIAMO", r"USCITE\s+TUTTI",
    ]
    if any(re.search(p, upper) for p in close_generic):
        log.info(f"[CH1] CLOSE_ALL_SYMBOL (generic): {raw[:60]}")
        return {"action": "CLOSE_ALL_SYMBOL", "raw_message": raw}

    # ── 3. Segnale di apertura ───────────────────────────────────────────────
    # Gestisce sia "BUY XAUUSD 4819" che "EURJPY BUY 186.942"
    # Il punto nel prezzo (186.942) non viene matchato da \w+ quindi
    # usiamo [A-Z]{3,8} per il simbolo e un pattern specifico per il prezzo
    m_dir = re.search(
        r"(?:([A-Z]{3,8})\s+)?(BUY|SELL)\s+(?:([A-Z]{3,8})\s+)?(\d+[.,]\d+|\d{3,})",
        upper
    )
    if not m_dir:
        return None

    sym1, direction, sym2, price_str = m_dir.groups()
    symbol = normalize_symbol(sym1 or sym2 or "")
    if not symbol:
        return None
    entry = pf(price_str)

    tps, sl = [], None
    for line in raw.splitlines():
        lu = strip_md(line).upper().strip()
        m_tp = re.match(r"TP\s*\d\s*[:\s]\s*([\d.,]+)", lu)
        if m_tp:
            tps.append(pf(m_tp.group(1)))
            continue
        m_sl = re.match(r"SL\s*[:\s]\s*([\d.,]+)", lu)
        if m_sl:
            sl = pf(m_sl.group(1))

    if not tps and sl is None:
        return None

    log.info(f"[CH1] OPEN {direction} {symbol} @ {entry} TP={tps} SL={sl}")
    return {
        "action":       "OPEN",
        "direction":    direction,
        "symbol":       symbol,
        "entry":        entry,
        "tp_levels":    tps,
        "sl":           sl,
        "risk_percent": ch.get("risk_percent", 0.5),
        "splits":       ch.get("splits", [0.4, 0.4, 0.2]),
        "magic_base":   ch["magic_base"],
        "raw_message":  raw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PARSER CH2 — SALA GOLD VIP
# ─────────────────────────────────────────────────────────────────────────────
#
# Formato naked (apre subito a mercato):
#   "Gold sell now"  /  "Sell gold now"  /  "Gold buy now"
#
# Formato completo (aggiorna il trade naked appena aperto, oppure standalone):
#   "Sell gold now 4775 - 4780\nSL: 4789\nTp: 4768*\nTp: 4755"
#
# Entry range: se c'e' un range [min, max], l'EA entra se il prezzo e' nel range
# BE: AUTOMATICO nell'EA su TP1 hit — messaggi BE/SL/TP hit ignorati

def parser_sala_gold(text: str, ch: dict, state: BridgeState | None = None) -> dict | None:
    if state is None:
        state, _ = _ensure_runtime()
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── BE con prezzo esplicito: "4789 gold break Even" ─────────────────────
    m_be_price = re.search(r"([\d.,]+)\s+(?:GOLD|XAUUSD)?\s*BREAK\s*EVEN|"
                           r"BREAK\s*EVEN\s+(?:GOLD|XAUUSD)?\s*([\d.,]+)", upper)
    if m_be_price:
        be_price = pf(m_be_price.group(1) or m_be_price.group(2))
        # Sanity check: prezzo BE deve essere plausibile (>100), non pips
        if be_price < 100:
            log.debug(f"[CH2] BE price {be_price} ignorato (sembra pips, non prezzo)")
        else:
            log.info(f"[CH2] BE con prezzo esplicito: {be_price}")
            return {"action": "BREAK_EVEN_PRICE", "be_price": be_price,
                    "symbol": "XAUUSD", "magic_base": ch["magic_base"], "raw_message": raw}

    # ── Chiusura totale CH2 ─────────────────────────────────────────────────
    # "Close!!!" / "Close all" / "Chiudiamo tutto"
    close_pats = [
        r"^CLOSE\s*!*$", r"^CLOSE\s+ALL", r"CHIUDIAMO\s+TUTTO",
        r"CLOSE\s+ALL\s+POSITIONS", r"EXIT\s+ALL",
    ]
    if any(re.search(p, upper.strip()) for p in close_pats):
        log.info(f"[CH2] CLOSE_ALL_SYMBOL: {raw[:60]}")
        return {"action": "CLOSE_ALL_SYMBOL", "symbol": "XAUUSD",
                "magic_base": ch["magic_base"], "raw_message": raw}

    # ── "Close half / partial close + break even" → chiudi T1 se profitto ──
    is_partial = contains_any(upper, "CLOSE HALF", "PARTIAL CLOSE", "HALF CLOSE",
                               "CHIUDI META", "PARZIALE", "CLOSE PART")
    is_be_msg  = contains_any(upper, "BREAK EVEN", "BREAKEVEN", " BE ")
    if is_partial and is_be_msg:
        log.info(f"[CH2] CLOSE_HALF_BE: {raw[:60]}")
        return {"action": "CLOSE_HALF_BE", "symbol": "XAUUSD",
                "magic_base": ch["magic_base"], "raw_message": raw}

    # ── Messaggi da ignorare completamente ───────────────────────────────────
    ignore_pats = [
        r"ZOOM\.US", r"SALA\s+APERT", r"FORMAZIONE", r"STASERA\s+FORM",
        r"TP2?\s+HIT", r"PIPS\s+BREAK", r"BREAK\s*EVEN",
        r"SL\s+HIT", r"\bSL\s+\d{4}\b",
        r"BE\s+O\s+TP", r"RICORDO\s+A\s+TUTTI", r"MINUTI\s+E\s+APRIAMO",
        r"ID\s+DE\s+REUNI", r"CODIGO\s+DE\s+ACCESO",
        r"LINK\s+.*LIVE", r"SALA\s+APERTAAAA",
        r"PIPS\s+\d", r"\+\d+\s+PIPS",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[CH2] Ignorato: {raw[:60]}")
            return None

    # ── Controlla se ci sono numeri significativi nel testo ──────────────────
    has_numbers = bool(re.search(r"\d{3,}", upper))

    # ── Determina direzione ───────────────────────────────────────────────────
    m_dir = re.search(
        r"(BUY|SELL)\s+(?:GOLD|XAUUSD)(?:\s+NOW)?|"
        r"(?:GOLD|XAUUSD)\s+(BUY|SELL)(?:\s+NOW)?",
        upper
    )
    if not m_dir:
        return None

    direction = m_dir.group(1) or m_dir.group(2)

    # ── NAKED: messaggio senza numeri → OPEN_NOW a mercato ───────────────────
    if not has_numbers:
        state.set_ch2_pending(direction)
        log.info(f"[CH2] OPEN_NOW (naked) {direction} XAUUSD — in attesa completamento")
        return {
            "action":       "OPEN_NOW",
            "direction":    direction,
            "symbol":       "XAUUSD",
            "entry":        None,
            "entry_range":  None,
            "tp_levels":    [],
            "sl":           None,
            "risk_percent": ch.get("risk_percent", 0.5),
            "splits":       ch.get("splits", [0.6, 0.4]),
            "magic_base":   ch["magic_base"],
            "raw_message":  raw,
        }

    # ── Segnale completo con numeri ───────────────────────────────────────────
    # Entry (possibile range)
    entry_raw_m = re.search(
        r"(?:BUY|SELL)\s+(?:GOLD|XAUUSD)(?:\s+NOW)?\s+([\d.,\s\-]+)|"
        r"(?:GOLD|XAUUSD)\s+(?:BUY|SELL)(?:\s+NOW)?\s+([\d.,\s\-]+)",
        upper
    )
    entry_range = None
    entry       = None
    if entry_raw_m:
        raw_entry = (entry_raw_m.group(1) or entry_raw_m.group(2) or "").strip()
        parts     = re.findall(r"[\d.,]+", raw_entry)
        if len(parts) >= 2:
            v1 = pf(parts[0])
            v2 = pf(parts[1])
            # Sanity check: se differenza > 500 punti, uno dei due è malformato
            # Usa solo il valore più grande (più vicino al prezzo reale)
            if abs(v1 - v2) > 500:
                log.warning(f"[CH2] Range anomalo [{v1},{v2}], uso solo il valore più grande")
                entry = max(v1, v2)
                entry_range = None
            else:
                entry_range = [min(v1, v2), max(v1, v2)]
                entry       = (v1 + v2) / 2
        elif len(parts) == 1:
            entry = pf(parts[0])

    # SL — cerca "SL: 4789" o riga "SL 4828"
    sl = None
    m_sl = re.search(r"\bSL\b\s*[:\s]\s*([\d.,]+)", upper)
    if m_sl:
        sl = pf(m_sl.group(1))

    # TP — gestisce "Tp: 4768*", "Tp. 4824", "TP1: 5195"
    tp_matches = re.findall(r"TP\d*\s*[:.]\s*([\d.,]+)\*?", upper)
    tps        = [pf(v) for v in tp_matches]

    # Determina se e' completamento di un OPEN_NOW o nuovo segnale standalone
    if state.ch2_pending_open and state.ch2_pending_dir == direction:
        action = "UPDATE_OPEN"
        state.clear_ch2_pending()
        log.info(f"[CH2] UPDATE_OPEN {direction} range={entry_range} TP={tps} SL={sl}")
    else:
        action = "OPEN"
        state.clear_ch2_pending()
        log.info(f"[CH2] OPEN {direction} range={entry_range} TP={tps} SL={sl}")

    return {
        "action":       action,
        "direction":    direction,
        "symbol":       "XAUUSD",
        "entry":        entry,
        "entry_range":  entry_range,
        "tp_levels":    tps,
        "sl":           sl,
        "risk_percent": ch.get("risk_percent", 0.5),
        "splits":       ch.get("splits", [0.6, 0.4]),
        "magic_base":   ch["magic_base"],
        "raw_message":  raw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PARSER CH3 — SALA VIP
# ─────────────────────────────────────────────────────────────────────────────
#
# Formato apertura:
#   NUOVO ORDINE - XAUUSDpm Buy
#   Entrata: 4736.64 [Lotti: 0.01]   <- lotto ignorato
#   Nessuno SL / Nessuno TP
#
# Formato modifica:
#   XAUUSDpm Buy - Modificato
#   Nuovo TP: 4747.00 [103.6 Pips]
#   Nuovo SL: 1.64356 [15.9 Pips]
#   Stop spostato a pareggio         <- SL e' gia' il valore numerico di BE
#
# Formato chiusura:
#   CHIUSO - XAUUSDpm Buy            <- verifica se gia' chiuso, altrimenti chiudi

def parser_sala_vip(text: str, ch: dict) -> dict | None:
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── Messaggi da ignorare ─────────────────────────────────────────────────
    ignore_pats = [
        r"GIORNALIERO\s+RAPPORTO", r"SETTIMANALE\s+RAPPORTO",
        r"SALA\s+APERT", r"ZOOM\.US", r"FORMAZIONE\s+STRATEG",
        r"LEZIONE\s+LIVE", r"VIDEO\s+ANALISI", r"RICORDO\s+A\s+TUTTI",
        r"ENTRATE\s+TUTTI", r"LINK\s+.*LIVE", r"ID\s+DE\s+REUNI",
        r"NEL\s+TRADING\s+NON", r"QUESTI\s+SONO\s+I\s+RISULTATI",
        r"ORDINI\s+ANCORA\s+IN\s+ESECUZIONE",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[CH3] Ignorato: {raw[:60]}")
            return None

    # ── Apertura nuovo ordine ─────────────────────────────────────────────────
    m_new = re.search(r"NUOVO\s+ORDINE\s*[-]\s*(\w+)\s+(BUY|SELL)", upper)
    if m_new:
        symbol    = normalize_symbol(m_new.group(1))
        direction = m_new.group(2)
        m_entry   = re.search(r"ENTRATA\s*[:\s]\s*([\d.,]+)", upper)
        entry     = pf(m_entry.group(1)) if m_entry else None
        lot       = (ch.get("fixed_lot_xauusd", 0.05)
                     if "XAUUSD" in symbol
                     else ch.get("fixed_lot_forex", 0.20))
        log.info(f"[CH3] OPEN {direction} {symbol} @ {entry} lot={lot}")
        return {
            "action":        "OPEN",
            "direction":     direction,
            "symbol":        symbol,
            "entry":         entry,
            "tp_levels":     [],
            "sl":            None,
            "use_fixed_lot": True,
            "fixed_lot":     lot,
            "magic_base":    ch["magic_base"],
            "raw_message":   raw,
        }

    # ── Modifica (TP o SL) ────────────────────────────────────────────────────
    m_mod = re.search(r"(\w+)\s+(BUY|SELL)\s*[-]\s*MODIFICATO", upper)
    if m_mod:
        symbol    = normalize_symbol(m_mod.group(1))
        direction = m_mod.group(2)

        m_tp = re.search(r"NUOVO\s+TP\s*[:\s]\s*([\d.,]+)", upper)
        m_sl = re.search(r"NUOVO\s+SL\s*[:\s]\s*([\d.,]+)", upper)

        if m_tp:
            tp_val = pf(m_tp.group(1))
            log.info(f"[CH3] UPDATE_TP {symbol} {direction} TP={tp_val}")
            return {
                "action":      "UPDATE_TP",
                "symbol":      symbol,
                "direction":   direction,
                "new_tp":      tp_val,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }

        if m_sl:
            sl_val = pf(m_sl.group(1))
            is_be  = contains_any(upper, "PAREGGIO", "BREAK EVEN")
            log.info(f"[CH3] UPDATE_SL {symbol} {direction} SL={sl_val} be={is_be}")
            return {
                "action":      "UPDATE_SL",
                "symbol":      symbol,
                "direction":   direction,
                "new_sl":      sl_val,
                "is_be":       is_be,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }

        return None

    # ── Chiusura ──────────────────────────────────────────────────────────────
    m_close = re.search(r"CHIUSO\s*[-]\s*(\w+)\s+(BUY|SELL)", upper)
    if m_close:
        symbol    = normalize_symbol(m_close.group(1))
        direction = m_close.group(2)
        log.info(f"[CH3] CHECK_AND_CLOSE {symbol} {direction}")
        return {
            "action":      "CHECK_AND_CLOSE",
            "symbol":      symbol,
            "direction":   direction,
            "magic_base":  ch["magic_base"],
            "raw_message": raw,
        }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# PARSER CH4 — SALA STARK
# ─────────────────────────────────────────────────────────────────────────────
#
# Formato markdown:
#   Apro una nuova operazione
#   XAUUSD BUY
#   Entry: 4725
#   SL: 4712.37
#   TP1: 4726.87 / TP2: 4730.77 / TP3: 4798.71 (opzionale)
#
# "Aggiungo un'altra operazione" -> is_add_signal=True, lotto dimezzato
#   - con SL/TP propri -> trade indipendente
#   - senza SL/TP -> inherit_from_first=True, EA copia valori del primo trade aperto
#
# Formato forex piatto:
#   BUY   GBPUSD 1.35864
#   SL    1.31230
#   TP    1.36050
#
# BE: automatico nell'EA su TP1 hit. "Sposto SL a Break Even" ignorato

def parser_sala_stark(text: str, ch: dict) -> dict | None:
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── Messaggi da ignorare ─────────────────────────────────────────────────
    ignore_pats = [
        r"SPOSTO\s+LO\s+STOP\s+LOSS\s+A",
        r"BREAK\s*EVEN",
        r"TAKE\s+PROFIT\s*\d*\s+PRESO",
        r"TAKE\s+PROFIT\s+PRESO",
        r"STOP\s+LOSS\s+PRESO",
        r"CHIUSA\s+A\s+BREAK",
        r"CI\s+VEDIAMO\b",
        r"WEBINARJAM",
        r"LINK\s+PER\s+PRENOTARE",
        r"COME\s+POTETE\s+CAPIRE",
        r"MINUTI\s+PRIMA",
        r"SI\s+COMINCIA",
        r"ENTRATE\s+TUTTI",
        r"LINK\s+LIVE",
        r"RAGAZZI\s+COME\s+POTETE",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[CH4] Ignorato: {raw[:60]}")
            return None

    is_add = bool(re.search(r"AGGIUNGO\s+UN", upper))

    # ── Formato markdown: "Apro" / "Aggiungo" ────────────────────────────────
    if re.search(r"(APRO|AGGIUNGO)\s+UN", upper):
        m_sd = re.search(
            r"(XAUUSD|GBPUSD|EURUSD|USDJPY|GBPJPY|AUDUSD|\w{6,7})\s+(BUY|SELL)",
            upper
        )
        if not m_sd:
            return None
        symbol    = normalize_symbol(m_sd.group(1))
        direction = m_sd.group(2)

        m_entry = re.search(r"ENTRY\s*[:\s]\s*([\d.,]+)", upper)
        entry   = pf(m_entry.group(1)) if m_entry else None

        m_sl = re.search(r"\bSL\b\s*[:\s]\s*([\d.,]+)", upper)
        sl   = pf(m_sl.group(1)) if m_sl else None

        tps = [pf(m.group(2))
               for m in re.finditer(r"TP\s*(\d)\s*[:\s]\s*([\d.,]+)", upper)]

        inherit = is_add and sl is None and not tps

        log.info(f"[CH4] {'ADD' if is_add else 'OPEN'} {direction} {symbol} @ {entry} "
                 f"SL={sl} TP={tps} inherit={inherit}")
        return {
            "action":             "OPEN",
            "direction":          direction,
            "symbol":             symbol,
            "entry":              entry,
            "tp_levels":          tps,
            "sl":                 sl,
            "risk_percent":       ch.get("risk_percent", 0.5),
            "splits":             ch.get("splits", [0.5, 0.4, 0.1]),
            "is_add_signal":      is_add,
            "inherit_from_first": inherit,
            "magic_base":         ch["magic_base"],
            "raw_message":        raw,
        }

    # ── Formato piatto forex ──────────────────────────────────────────────────
    m_flat = re.search(r"(BUY|SELL)\s+([\w]{6,7})\s+([\d.,]+)", upper)
    if m_flat:
        direction = m_flat.group(1)
        symbol    = normalize_symbol(m_flat.group(2))
        entry     = pf(m_flat.group(3))

        m_sl = re.search(r"\bSL\b\s+([\d.,]+)", upper)
        sl   = pf(m_sl.group(1)) if m_sl else None

        tps = [pf(m.group(1)) for m in re.finditer(r"\bTP\d*\s+([\d.,]+)", upper)]

        log.info(f"[CH4] OPEN FLAT {direction} {symbol} @ {entry} SL={sl} TP={tps}")
        return {
            "action":             "OPEN",
            "direction":          direction,
            "symbol":             symbol,
            "entry":              entry,
            "tp_levels":          tps,
            "sl":                 sl,
            "risk_percent":       ch.get("risk_percent", 0.5),
            "splits":             ch.get("splits", [0.5, 0.4, 0.1]),
            "is_add_signal":      False,
            "inherit_from_first": False,
            "magic_base":         ch["magic_base"],
            "raw_message":        raw,
        }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAPPA PARSER
# ─────────────────────────────────────────────────────────────────────────────

PARSERS = {
    "zanni_vip":  parser_zanni_vip,
    "sala_gold":  parser_sala_gold,
    "sala_vip":   parser_sala_vip,
    "sala_stark": parser_sala_stark,
}

def get_parser(name: str):
    p = PARSERS.get(name)
    if not p:
        log.warning(f"Parser '{name}' non trovato.")
    return p

# ─────────────────────────────────────────────────────────────────────────────
# CHANNEL MAP
# ─────────────────────────────────────────────────────────────────────────────

def build_channel_map() -> dict:
    return {
        int(ch["telegram_id"]): ch
        for ch in CONFIG["channels"]
        if ch.get("enabled", True)
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN BRIDGE
# ─────────────────────────────────────────────────────────────────────────────

async def run_bridge():
    bridge_state, processed_messages = _ensure_runtime()
    tg_cfg = CONFIG["telegram"]
    log.info("=" * 60)
    log.info("TG TradinGo Bridge v2.0")
    log.info(f"Config:  {CONFIG_FILE}")
    log.info(f"Session: {tg_cfg['session_file']}")

    channel_map = build_channel_map()
    active_ids  = list(channel_map.keys())

    if not active_ids:
        log.error("Nessun canale abilitato. Uscita.")
        return

    for cid, cfg in channel_map.items():
        log.info(f"  {cfg['id']} [{cid}] {cfg['name']} (parser: {cfg['parser']})")

    # Inizializza file segnale vuoti
    for mt5_path in get_mt5_paths():
        for cfg in channel_map.values():
            f = Path(mt5_path) / cfg["signal_file"]
            if not f.exists():
                f.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(f, json.dumps({"action": "NONE"}, indent=2))
                log.info(f"Init: {f}")

    client = TelegramClient(tg_cfg["session_file"], tg_cfg["api_id"], tg_cfg["api_hash"])

    async def process_message(event, is_edit: bool = False):
        """Handler condiviso per messaggi nuovi e modificati."""
        try:
            chat_id = event.chat_id
            text    = (event.raw_text or "").strip()
            if not text:
                return
            ch_cfg = channel_map.get(int(chat_id))
            if not ch_cfg:
                return
            parser = get_parser(ch_cfg["parser"])
            if not parser:
                return

            event_type = "EDIT" if is_edit else "NEW"
            message_id = event.id
            dedup_key = ProcessedMessageStore.make_key(
                int(chat_id), int(message_id), event_type, text
            )
            if processed_messages.is_duplicate(dedup_key):
                log.debug(
                    f"[{ch_cfg['id']}] Duplicato ignorato {event_type} id={message_id}"
                )
                return

            prefix = "EDIT" if is_edit else "MSG"
            log.info(f"[{ch_cfg['id']}] {prefix}: {text[:80].replace(chr(10), ' | ')}")

            # Per i messaggi modificati di CH2: se il testo contiene ora
            # sia la direzione che i dati completi (SL/TP), va trattato come
            # UPDATE_OPEN — forziamo il pending state se non era già impostato
            if is_edit and ch_cfg["parser"] == "sala_gold":
                upper = text.upper()
                has_numbers = bool(re.search(r"\d{3,}", upper))
                has_direction = bool(re.search(
                    r"(BUY|SELL)\s+(?:GOLD|XAUUSD)|(?:GOLD|XAUUSD)\s+(BUY|SELL)", upper
                ))
                if has_numbers and has_direction and not bridge_state.ch2_pending_open:
                    m = re.search(
                        r"(BUY|SELL)\s+(?:GOLD|XAUUSD)|(?:GOLD|XAUUSD)\s+(BUY|SELL)", upper
                    )
                    if m:
                        direction = m.group(1) or m.group(2)
                        bridge_state.set_ch2_pending(direction)
                        log.info(f"[CH2] EDIT con dati completi → forzo UPDATE_OPEN {direction}")

            if ch_cfg["parser"] == "sala_gold":
                signal = parser(text, ch_cfg, bridge_state)
            else:
                signal = parser(text, ch_cfg)

            if signal:
                msg_date = getattr(event, "date", None)
                telegram_date = (
                    msg_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if msg_date
                    else None
                )
                meta = {
                    "message_id": message_id,
                    "chat_id": int(chat_id),
                    "telegram_date": telegram_date,
                    "event_type": event_type,
                }
                if write_signal(ch_cfg, signal, meta):
                    processed_messages.mark_processed(dedup_key)
            else:
                log.debug(f"[{ch_cfg['id']}] Ignorato")

        except Exception as e:
            log.error(f"Errore: {e}\n{traceback.format_exc()}")

    @client.on(events.NewMessage(chats=active_ids))
    async def on_message(event):
        await process_message(event, is_edit=False)

    @client.on(events.MessageEdited(chats=active_ids))
    async def on_edit(event):
        await process_message(event, is_edit=True)

    @client.on(events.Raw())
    async def on_raw(update):
        """Rileva ban da canali e lo segnala immediatamente."""
        pass  # Gestito dal BanDetector sul logger Telethon

    async def check_banned_channels():
        """Controlla periodicamente se siamo stati bannati da canali sconosciuti."""
        known_ids = set(active_ids)
        try:
            dialogs = await client.get_dialogs()
            for d in dialogs:
                entity = d.entity
                eid = getattr(entity, 'id', None)
                if eid and eid not in known_ids:
                    # Canale sconosciuto — non fa nulla ma lo monitoriamo
                    pass
        except Exception as e:
            log.error(f"[BAN CHECK] Errore: {e}")

    async with client:
        log.info("Connesso. In ascolto (NewMessage + MessageEdited)...")

        # Intercetta messaggi di ban dal logger Telethon
        import logging as _logging
        class BanDetector(_logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                # Filtra solo i veri ban Telethon — formato esatto:
                # "Account is now banned in XXXXXXX"
                if "Account is now banned in" in msg:
                    # Estrai ID canale dal messaggio
                    import re as _re
                    m = _re.search(r"banned in (\d+)", msg)
                    if m:
                        banned_id = int(m.group(1))
                        if banned_id not in active_ids:
                            log.warning(
                                f"[BAN] ⚠️  Account bannato da canale ESTERNO ID={banned_id}. "
                                f"NON è uno dei 4 canali operativi. "
                                f"Esegui dump_channels.py per identificarlo."
                            )
                        else:
                            log.error(
                                f"[BAN] 🚨 Account bannato da canale OPERATIVO ID={banned_id}! "
                                f"Segnale da quel canale non sarà più ricevuto."
                            )

        ban_handler = BanDetector()
        ban_handler.setLevel(_logging.WARNING)
        _logging.getLogger("telethon").addHandler(ban_handler)

        await client.run_until_disconnected()

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT CON AUTO-RESTART
# ─────────────────────────────────────────────────────────────────────────────

def main():
    delay = 10
    while True:
        try:
            log.info("Avvio bridge...")
            asyncio.run(run_bridge())
        except KeyboardInterrupt:
            log.info("Stop manuale.")
            break
        except Exception as e:
            log.error(f"Crash: {e}\n{traceback.format_exc()}")
            log.info(f"Restart in {delay}s...")
            time.sleep(delay)

if __name__ == "__main__":
    main()
