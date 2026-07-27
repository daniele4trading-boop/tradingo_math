"""
TG TradinGo Bridge - v2.08
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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events

from bridge_core import (
    BridgeState,
    ProcessedMessageStore,
    apply_lot_rules,
    atomic_write_text,
    atomic_write_text_timed,
    is_unc_path,
    make_signal_id,
    match_close_all_intent,
    match_close_price_followup,
    validate_signal,
)
from bridge_journal import append_bridge_event, write_heartbeat

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

BRIDGE_VERSION = "2.08"
HEARTBEAT_INTERVAL_SEC = 30
JOURNAL_RETENTION_DAYS = 90

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
    written_targets: list[str] = []
    if meta:
        signal["message_id"]    = meta.get("message_id")
        signal["chat_id"]       = meta.get("chat_id")
        signal["telegram_date"] = meta.get("telegram_date")
        signal["event_type"]    = meta.get("event_type")
        if meta.get("chat_id") is not None and meta.get("message_id") is not None:
            signal["signal_id"] = make_signal_id(
                meta["chat_id"],
                meta["message_id"],
                meta.get("event_type") or "NEW",
            )

    apply_lot_rules(signal, channel_cfg)

    ok, reason = validate_signal(signal)
    if not ok:
        log.error(f"[{channel_cfg['id']}] Segnale non valido: {reason} | action={signal.get('action')}")
        return False

    payload = json.dumps(signal, indent=2)
    # Local disks first; UNC/Tailscale shares last so a hung SMB cannot delay Contabo.
    paths = sorted(
        get_mt5_paths(),
        key=lambda p: (1 if is_unc_path(p) else 0, str(p).lower()),
    )
    for mt5_path in paths:
        out_file = Path(mt5_path) / channel_cfg["signal_file"]
        try:
            # Short timeout on UNC so Telethon event loop never freezes for minutes.
            atomic_write_text_timed(
                out_file,
                payload,
                retries=3 if is_unc_path(out_file) else 5,
            )
            written_targets.append(str(out_file))
            log.info(f"[{channel_cfg['id']}] -> {out_file.name} | "
                     f"action={signal.get('action')} symbol={signal.get('symbol','')} "
                     f"dir={signal.get('direction','')} sid={signal.get('signal_id','')}")
        except Exception as e:
            log.error(f"[{channel_cfg['id']}] Errore scrittura {out_file}: {e}")
            # Keep going: Contabo local must succeed even if Gamehosting share hangs.
            continue
    if meta is not None:
        meta["written_targets"] = written_targets
    if not written_targets:
        log.error(f"[{channel_cfg['id']}] Nessun target mt5_instances scritto")
        return False
    return True


def coerce_edit_open_to_update(signal: dict | None, is_edit: bool) -> dict | None:
    """Avoid MSG+EDIT duplicate OPEN stacking on the EA."""
    if (
        signal
        and is_edit
        and signal.get("action") == "OPEN"
        and not signal.get("allow_stack")
    ):
        signal["action"] = "UPDATE_OPEN"
        log.info(
            f"EDIT OPEN → UPDATE_OPEN (avoid duplicate stack) "
            f"{signal.get('direction')} {signal.get('symbol')}"
        )
    return signal


def pf(s: str | None) -> float | None:
    """Parse float; return None on empty/invalid tokens (never raise)."""
    if s is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(s).strip().replace(",", "."))
    if cleaned in ("", ".", "..") or cleaned.count(".") > 1:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _close_signal(
    ch: dict,
    raw: str,
    reference_price: float | None = None,
    *,
    symbol: str | None = "XAUUSD",
) -> dict:
    sig: dict = {
        "action": "CLOSE_ALL_SYMBOL",
        "magic_base": ch["magic_base"],
        "raw_message": raw,
    }
    if symbol:
        sig["symbol"] = symbol
    if reference_price is not None:
        sig["reference_price"] = reference_price
    return sig


def _maybe_close_from_text(
    upper: str,
    ch: dict,
    raw: str,
    state: BridgeState | None = None,
    *,
    symbol: str | None = "XAUUSD",
) -> dict | None:
    """Shared close intent + optional price follow-up (after ignore_pats)."""
    matched, ref = match_close_all_intent(upper)
    if matched:
        if state is not None and ref is None:
            state.set_close_price_pending(ch["id"])
        elif state is not None and ref is not None:
            state.pop_close_price_pending(ch["id"])
        log.info(f"[{ch['id']}] CLOSE_ALL_SYMBOL ref={ref}: {raw[:60]}")
        return _close_signal(ch, raw, ref, symbol=symbol)

    if state is not None:
        follow = match_close_price_followup(upper)
        if follow is not None and state.pop_close_price_pending(ch["id"]):
            log.info(f"[{ch['id']}] CLOSE_ALL_SYMBOL follow-up price={follow}: {raw[:60]}")
            return _close_signal(ch, raw, follow, symbol=symbol)
    return None

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


def fold_accents(text: str) -> str:
    """NFKD fold: METÀ → META, useful for Ivan lot-size keywords."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


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

    # ── 2a. Chiusura generica (shared recognizer) ────────────────────────────
    if re.search(r"CAMBIO\s+DI\s+TREND", upper):
        log.info(f"[CH1] CLOSE_ALL_SYMBOL (trend): {raw[:60]}")
        return _close_signal(ch, raw, symbol="XAUUSD")
    close_sig = _maybe_close_from_text(upper, ch, raw, symbol="XAUUSD")
    if close_sig:
        return close_sig

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
    if entry is None:
        return None

    tps, sl = [], None
    for line in raw.splitlines():
        lu = strip_md(line).upper().strip()
        m_tp = re.match(r"TP\s*\d\s*[:\s]\s*([\d.,]+)", lu)
        if m_tp:
            v = pf(m_tp.group(1))
            if v is not None:
                tps.append(v)
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
# Entry range: [min, max] — EA valuta se il prezzo e' nel range (non usa la media)
# BE: AUTOMATICO nell'EA su TP1 hit — messaggi BE/SL/TP hit ignorati

def parser_sala_gold(text: str, ch: dict, state: BridgeState | None = None) -> dict | None:
    if state is None:
        state, _ = _ensure_runtime()
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── Chiusura totale CH2 (shared recognizer) ─────────────────────────────
    close_sig = _maybe_close_from_text(upper, ch, raw, state)
    if close_sig:
        return close_sig

    # ── Partial / half + break even → CLOSE_HALF_BE (prima del BE-prezzo) ──
    # Deve stare PRIMA del match "N gold break even", altrimenti
    # "Partial close, break even +100 pips" cattura la virgola come prezzo.
    is_partial = contains_any(
        upper,
        "CLOSE HALF", "PARTIAL CLOSE", "PARTIAL CLOSURE", "HALF CLOSE",
        "CHIUDI META", "PARZIALE", "CLOSE PART", "PARTIAL",
    )
    is_be_msg = contains_any(
        upper, "BREAK EVEN", "BREAKEVEN", "BREAK-EVEN",
    ) or re.search(r"\bBREAK\s+EVEN\b", upper)
    if is_partial and is_be_msg:
        log.info(f"[CH2] CLOSE_HALF_BE: {raw[:60]}")
        return {"action": "CLOSE_HALF_BE", "symbol": "XAUUSD",
                "magic_base": ch["magic_base"], "raw_message": raw}

    # ── BE con prezzo esplicito: "4789 gold break Even" ─────────────────────
    # Richiede almeno 3 cifre (prezzo XAU), non pips (+100) né virgole isolate.
    m_be_price = re.search(
        r"(?<!\d)(\d{3,}(?:[.,]\d+)?)\s+(?:GOLD|XAUUSD)?\s*BREAK\s*EVEN|"
        r"BREAK\s*EVEN\s+(?:GOLD|XAUUSD)?\s*(?<!\d)(\d{3,}(?:[.,]\d+)?)",
        upper,
    )
    if m_be_price:
        raw_px = m_be_price.group(1) or m_be_price.group(2)
        be_price = pf(raw_px)
        if be_price is None or be_price < 100:
            log.debug(f"[CH2] BE price token ignorato: {raw_px!r} -> CHECK_AND_BE")
            log.info(f"[CH2] CHECK_AND_BE (break even, no usable price): {raw[:60]}")
            return {
                "action": "CHECK_AND_BE",
                "symbol": "XAUUSD",
                "tp_index": 1,
                "magic_base": ch["magic_base"],
                "raw_message": raw,
            }
        log.info(f"[CH2] BE con prezzo esplicito: {be_price}")
        return {"action": "BREAK_EVEN_PRICE", "be_price": be_price,
                "symbol": "XAUUSD", "magic_base": ch["magic_base"], "raw_message": raw}

    # ── "break even" standalone / manual BE instruction → SL a entry ───────
    # Esempi: "break Even", "MANUALLY SET A BREAK EVEN ON ALL YOUR POSITIONS!"
    if is_be_msg or re.search(r"MANUALLY\s+SET\s+A\s+BREAK\s*EVEN", upper):
        log.info(f"[CH2] CHECK_AND_BE (break even): {raw[:60]}")
        return {
            "action": "CHECK_AND_BE",
            "symbol": "XAUUSD",
            "tp_index": 1,
            "magic_base": ch["magic_base"],
            "raw_message": raw,
        }

    # ── Messaggi da ignorare completamente ───────────────────────────────────
    ignore_pats = [
        r"ZOOM\.US", r"SALA\s+APERT", r"FORMAZIONE", r"STASERA\s+FORM",
        r"TP2?\s+HIT", r"PIPS\s+BREAK",
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
                entry       = None
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

def parser_sala_vip(text: str, ch: dict, state: BridgeState | None = None) -> dict | None:
    if state is None:
        state, _ = _ensure_runtime()
    raw   = text.strip()
    upper = strip_md(raw).upper()

    # ── Messaggi da ignorare ─────────────────────────────────────────────────
    ignore_pats = [
        r"GIORNALIERO\s+RAPPORTO", r"SETTIMANALE\s+RAPPORTO", r"REPORT\s+SETTIMANALE",
        r"SALA\s+APERT", r"ZOOM\.US", r"FORMAZIONE\s+STRATEG", r"LIVE\s+DI\s+FORMAZIONE",
        r"LEZIONE\s+LIVE", r"VIDEO\s+ANALISI", r"RICORDO\s+A\s+TUTTI",
        r"ENTRATE\s+TUTTI", r"LINK\s+.*LIVE", r"ID\s+DE\s+REUNI",
        r"NEL\s+TRADING\s+NON", r"QUESTI\s+SONO\s+I\s+RISULTATI",
        r"ORDINI\s+ANCORA\s+IN\s+ESECUZIONE",
        r"QUESTO MESSAGGIO NON INCITA",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[CH3] Ignorato: {raw[:60]}")
            return None

    # ── Apertura (IT / EN) — TP arriva nel messaggio Modified successivo ─────
    m_new = re.search(
        r"(?:NUOVO\s+ORDINE|NEW\s+ORDER)\s*[-]\s*(\w+)\s+(BUY|SELL)", upper
    )
    if m_new:
        symbol    = normalize_symbol(m_new.group(1))
        direction = m_new.group(2)
        m_entry   = re.search(r"(?:ENTRATA|ENTRY)\s*[:\s]\s*([\d.,]+)", upper)
        entry     = pf(m_entry.group(1)) if m_entry else None
        state.set_forex_pending(symbol, direction, entry)
        log.info(f"[FOREX] Pending {direction} {symbol} @ {entry}")
        return None

    # ── Modifica TP/SL (IT / EN) ─────────────────────────────────────────────
    m_mod = re.search(
        r"(\w+)\s+(BUY|SELL)\s*[-]\s*(MODIFICATO|MODIFIED)", upper
    )
    if m_mod:
        symbol    = normalize_symbol(m_mod.group(1))
        direction = m_mod.group(2)

        m_tp = re.search(r"(?:NUOVO|NEW)\s+TP\s*[:\s]\s*([\d.,]+)", upper)
        m_sl = re.search(r"(?:NUOVO|NEW)\s+SL\s*[:\s]\s*([\d.,]+)", upper)

        if m_tp:
            tp_val = pf(m_tp.group(1))
            sl_val = pf(m_sl.group(1)) if m_sl else None
            if (
                state.forex_pending_symbol == symbol
                and state.forex_pending_dir == direction
            ):
                entry = state.forex_pending_entry
                log.info(
                    f"[FOREX] OPEN (pending+modified) {direction} {symbol} "
                    f"@{entry} TP={tp_val} SL={sl_val}"
                )
                signal = {
                    "action":      "OPEN",
                    "direction":   direction,
                    "symbol":      symbol,
                    "entry":       entry,
                    "tp_levels":   [tp_val],
                    "sl":          sl_val,
                    "magic_base":  ch["magic_base"],
                    "raw_message": raw,
                }
                state.set_forex_last_trade(signal)
                state.clear_forex_pending()
                return signal

            log.info(f"[FOREX] UPDATE_TP {symbol} {direction} TP={tp_val}")
            if (
                state.forex_last_trade
                and state.forex_last_trade.get("symbol") == symbol
                and state.forex_last_trade.get("direction") == direction
            ):
                state.set_forex_last_trade({
                    **state.forex_last_trade,
                    "tp_levels": [tp_val],
                    "sl": sl_val or state.forex_last_trade.get("sl"),
                })
            return {
                "action":      "UPDATE_TP",
                "symbol":      symbol,
                "direction":   direction,
                "new_tp":      tp_val,
                "tp_levels":   [tp_val],
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }

        if m_sl:
            sl_val = pf(m_sl.group(1))
            is_be  = contains_any(upper, "PAREGGIO", "BREAK EVEN", "BREAKEVEN")
            log.info(f"[FOREX] UPDATE_SL {symbol} {direction} SL={sl_val} be={is_be}")
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

    # ── Chiusura (IT / EN) ────────────────────────────────────────────────────
    m_close = re.search(r"(?:CHIUSO|CLOSED)\s*[-]\s*(\w+)\s+(BUY|SELL)", upper)
    if m_close:
        symbol    = normalize_symbol(m_close.group(1))
        direction = m_close.group(2)
        if (
            state.forex_last_trade
            and state.forex_last_trade.get("symbol") == symbol
            and state.forex_last_trade.get("direction") == direction
        ):
            state.clear_forex_last_trade()
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
# PARSER SALA ORO VIP
# ─────────────────────────────────────────────────────────────────────────────
#
# Canale sempre XAUUSD. Formati:
#   XAUUSD SELL 4020-4022 | TP 4010 | SL 4024
#   4020 sell  /  sell 4020  (senza simbolo)
#   Tp 4010 | Sl 4024  (completamento edit)
#   60 PIPS CLOSE OR BREKIVEN  -> CLOSE_HALF_BE (meta' + BE)

def _parse_oro_sl_tp(upper: str) -> tuple[float | None, list[float]]:
    sl = None
    m_sl = re.search(r"\bSL\s*[:\s|]\s*([\d.,]+)", upper)
    if m_sl:
        sl = pf(m_sl.group(1))
    tps = [pf(v) for v in re.findall(r"TP\d*\s*[:\s|]\s*([\d.,]+)", upper)]
    if not tps:
        tps = [pf(v) for v in re.findall(r"\bTP\s+([\d.,]+)", upper)]
    return sl, tps


def _parse_oro_direction_entry(upper: str) -> tuple[str | None, float | None, list[float] | None]:
    m = re.search(
        r"ZONA\s+(BUY|SELL)\s+([\d.,]+)\s*-\s*([\d.,]+)",
        upper,
    )
    if m:
        direction = m.group(1)
        v1 = pf(m.group(2))
        v2 = pf(m.group(3))
        return direction, None, [min(v1, v2), max(v1, v2)]

    m = re.search(
        r"(?:XAUUSD|GOLD)\s+(BUY|SELL)\s+([\d.,]+)(?:\s*-\s*([\d.,]+))?",
        upper,
    )
    if m:
        direction = m.group(1)
        entry1 = pf(m.group(2))
        entry2 = pf(m.group(3)) if m.group(3) else None
        if entry2 is not None:
            return direction, None, [min(entry1, entry2), max(entry1, entry2)]
        return direction, entry1, None

    m = re.search(r"([\d.,]+)\s+(BUY|SELL)\b", upper)
    if m:
        return m.group(2), pf(m.group(1)), None

    m = re.search(r"\b(BUY|SELL)\s+([\d.,]+)", upper)
    if m:
        return m.group(1), pf(m.group(2)), None

    return None, None, None


def _oro_is_close_half_be(upper: str) -> bool:
    if not re.search(r"\d+\s*PIPS?", upper):
        return False
    return contains_any(
        upper,
        "CLOSE",
        "BREK",
        "BREAK",
        "BREAKEVEN",
        " BE ",
    )


def _oro_is_reentry(upper: str) -> bool:
    """True when ORO explicitly asks to open again while a trade may still be open."""
    return bool(
        re.search(r"\bRIENTRI(?:AMO|RE)?\b", upper)
        or re.search(r"\bRIENTRO\b", upper)
        or re.search(r"\bRE[- ]?ENTRY\b", upper)
    )


def _oro_entry_interval(trade: dict) -> tuple[float, float] | None:
    er = trade.get("entry_range")
    if er and len(er) >= 2:
        return min(er[0], er[1]), max(er[0], er[1])
    entry = trade.get("entry")
    if entry is not None:
        return float(entry), float(entry)
    return None


def _oro_same_trade_setup(a: dict, b: dict, *, max_gap: float = 5.0) -> bool:
    """Same direction and compatible entry (exact, overlapping range, or near).

    Treats refinements like entry 4060 → range 4060-4062 as the same setup so
    Telegram EDITs do not emit a second OPEN.
    """
    if a.get("direction") != b.get("direction"):
        return False
    ia = _oro_entry_interval(a)
    ib = _oro_entry_interval(b)
    if ia is None or ib is None:
        return False
    a_lo, a_hi = ia
    b_lo, b_hi = ib
    # Overlap (inclusive)
    if a_lo <= b_hi and b_lo <= a_hi:
        return True
    # Near but non-overlapping (range expansion/contraction within max_gap)
    gap = max(b_lo - a_hi, a_lo - b_hi)
    return gap <= max_gap


def _oro_resolve_context(state: BridgeState) -> tuple[str | None, float | None, list[float] | None]:
    if state.oro_pending_dir:
        return state.oro_pending_dir, state.oro_pending_entry, state.oro_pending_range
    if state.oro_last_trade:
        lt = state.oro_last_trade
        return lt.get("direction"), lt.get("entry"), lt.get("entry_range")
    return None, None, None


def _oro_try_emit_pending_open(state: BridgeState, ch: dict, raw: str) -> dict | None:
    """Emit OPEN when fragmented ORO messages collected direction + SL + TP."""
    if not state.oro_pending_dir:
        return None
    if state.oro_pending_sl is None or not state.oro_pending_tps:
        return None
    direction = state.oro_pending_dir
    entry = state.oro_pending_entry
    entry_range = state.oro_pending_range
    sl = state.oro_pending_sl
    tps = list(state.oro_pending_tps)
    entry_log = f"range={entry_range}" if entry_range else f"@{entry}"
    log.info(f"[ORO] OPEN (fragmented) {direction} XAUUSD {entry_log} TP={tps} SL={sl}")
    signal = {
        "action":      "OPEN",
        "direction":   direction,
        "symbol":      "XAUUSD",
        "entry":       entry,
        "entry_range": entry_range,
        "tp_levels":   tps,
        "sl":          sl,
        "magic_base":  ch["magic_base"],
        "raw_message": raw,
    }
    state.set_oro_last_trade(signal)
    state.clear_oro_pending()
    return signal


def _oro_parse_range_only(upper: str) -> list[float] | None:
    m = re.match(r"^([\d.,]+)\s*-\s*([\d.,]+)$", upper.strip())
    if not m:
        return None
    v1 = pf(m.group(1))
    v2 = pf(m.group(2))
    return [min(v1, v2), max(v1, v2)]


def parser_sala_oro(text: str, ch: dict, state: BridgeState | None = None) -> dict | None:
    if state is None:
        state, _ = _ensure_runtime()
    raw = text.strip()
    if not raw or raw in (".", "…", "-", "—"):
        return None

    upper = strip_md(raw).upper()

    ignore_pats = [
        r"REPORT",
        r"BOOO?MM",
        r"RAGAZZI",
        r"POTREBBE",
        r"ATTENDIAMO",
        r"DOVREBBE",
        r"FORMazione",
        r"LIVE",
        r"^\d+\s+PIPS?\s*✅\s*$",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[ORO] Ignorato: {raw[:60]}")
            return None

    if _oro_is_close_half_be(upper):
        log.info(f"[ORO] CLOSE_HALF_BE: {raw[:60]}")
        return {
            "action":      "CLOSE_HALF_BE",
            "symbol":      "XAUUSD",
            "magic_base":  ch["magic_base"],
            "raw_message": raw,
        }

    sl, tps = _parse_oro_sl_tp(upper)
    direction, entry, entry_range = _parse_oro_direction_entry(upper)
    want_stack = _oro_is_reentry(upper)

    range_only = _oro_parse_range_only(upper)
    if range_only and state.oro_pending_dir:
        state.oro_pending_entry = None
        state.oro_pending_range = range_only
        state.save()
        log.info(f"[ORO] Pending range {range_only} for {state.oro_pending_dir}")
        return None

    if direction is None and (sl is not None or tps):
        direction, entry, entry_range = _oro_resolve_context(state)
        if not direction:
            log.debug(f"[ORO] SL/TP senza contesto: {raw[:60]}")
            return None

        if state.oro_pending_dir:
            state.oro_pending_add_levels(sl, tps if tps else None)
            log.info(
                f"[ORO] Fragment accumulate {direction} SL={state.oro_pending_sl} "
                f"TP={state.oro_pending_tps}"
            )
            return _oro_try_emit_pending_open(state, ch, raw)

        if tps and sl is None:
            log.info(f"[ORO] UPDATE_TP XAUUSD {direction} TP={tps[0]}")
            state.set_oro_last_trade({
                "direction": direction,
                "entry": entry,
                "entry_range": entry_range,
                "sl": state.oro_last_trade.get("sl") if state.oro_last_trade else None,
                "tp_levels": tps,
            })
            return {
                "action":      "UPDATE_TP",
                "symbol":      "XAUUSD",
                "direction":   direction,
                "new_tp":      tps[0],
                "tp_levels":   tps,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }
        if sl is not None and not tps:
            log.info(f"[ORO] UPDATE_SL XAUUSD {direction} SL={sl}")
            state.set_oro_last_trade({
                "direction": direction,
                "entry": entry,
                "entry_range": entry_range,
                "sl": sl,
                "tp_levels": state.oro_last_trade.get("tp_levels") if state.oro_last_trade else [],
            })
            return {
                "action":      "UPDATE_SL",
                "symbol":      "XAUUSD",
                "direction":   direction,
                "new_sl":      sl,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }

    if direction is None:
        return None

    if not tps and sl is None:
        state.set_oro_pending(direction, entry, entry_range)
        log.info(f"[ORO] Pending {direction} XAUUSD entry={entry} range={entry_range}")
        return None

    signal = {
        "action":      "OPEN",
        "direction":   direction,
        "symbol":      "XAUUSD",
        "entry":       entry,
        "entry_range": entry_range,
        "tp_levels":   tps,
        "sl":          sl,
        "magic_base":  ch["magic_base"],
        "raw_message": raw,
    }

    last = state.oro_last_trade
    if last and _oro_same_trade_setup(signal, last) and not want_stack:
        last_tps = last.get("tp_levels") or []
        last_sl = last.get("sl")
        tps_changed = tps != last_tps
        sl_changed = sl != last_sl
        entry_changed = _oro_entry_interval(signal) != _oro_entry_interval(last)
        if not tps_changed and not sl_changed and not entry_changed:
            log.info(f"[ORO] Duplicate OPEN ignored (same levels) {direction}")
            return None
        if tps_changed and not sl_changed and not entry_changed:
            log.info(f"[ORO] UPDATE_TP (edit) XAUUSD {direction} TP={tps}")
            signal = {
                "action":      "UPDATE_TP",
                "symbol":      "XAUUSD",
                "direction":   direction,
                "new_tp":      tps[0],
                "tp_levels":   tps,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }
        elif sl_changed and not tps_changed and not entry_changed:
            log.info(f"[ORO] UPDATE_SL (edit) XAUUSD {direction} SL={sl}")
            signal = {
                "action":      "UPDATE_SL",
                "symbol":      "XAUUSD",
                "direction":   direction,
                "new_sl":      sl,
                "magic_base":  ch["magic_base"],
                "raw_message": raw,
            }
        else:
            # Range refinement and/or combined SL+TP change → UPDATE_OPEN
            log.info(
                f"[ORO] UPDATE_OPEN (edit) XAUUSD {direction} "
                f"entry={entry} range={entry_range} TP={tps} SL={sl}"
            )
            signal["action"] = "UPDATE_OPEN"

    if signal["action"] == "OPEN":
        entry_log = f"range={entry_range}" if entry_range else f"@{entry}"
        if want_stack:
            signal["allow_stack"] = True
            log.info(
                f"[ORO] OPEN (re-entry/stack) {direction} XAUUSD {entry_log} "
                f"TP={tps} SL={sl}"
            )
        else:
            log.info(f"[ORO] OPEN {direction} XAUUSD {entry_log} TP={tps} SL={sl}")

    if signal["action"] in ("OPEN", "UPDATE_OPEN"):
        state.set_oro_last_trade(signal)
    elif signal["action"] == "UPDATE_TP":
        state.set_oro_last_trade({
            "direction": direction,
            "entry": entry,
            "entry_range": entry_range,
            "sl": last.get("sl") if last else sl,
            "tp_levels": tps,
        })
    elif signal["action"] == "UPDATE_SL":
        state.set_oro_last_trade({
            "direction": direction,
            "entry": entry,
            "entry_range": entry_range,
            "sl": sl,
            "tp_levels": last.get("tp_levels") if last else tps,
        })
    state.clear_oro_pending()
    return signal


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
            "is_add_signal":      False,
            "inherit_from_first": False,
            "magic_base":         ch["magic_base"],
            "raw_message":        raw,
        }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# PARSER IVANTRADES VIP
# ─────────────────────────────────────────────────────────────────────────────
#
# Formato tipico:
#   XAUUSD SELL 4011
#   TP 1 4006
#   TP 2 4004
#   ...
#   SL @ 4022
#
# Gestione:
#   Spostiamo SL a BE  -> CHECK_AND_BE
#   CHIUDERE ORA       -> CLOSE_ALL_SYMBOL (XAUUSD)
#   Meta size / METÀ SIZE / MEZZA SIZE -> lot_factor 0.5

def parser_ivan_vip(text: str, ch: dict, state: BridgeState | None = None) -> dict | None:
    if state is None:
        state, _ = _ensure_runtime()
    raw = text.strip()
    if not raw:
        return None

    upper = strip_md(raw).upper()

    # ignore_pats MUST run before close recognizer (preparatory phrases).
    ignore_pats = [
        r"^SL$",
        r"^PECCATO$",
        r"BUONGIORNO",
        r"GTA\s+FRATELLI",
        r"SCREEN\s+DI\s+PROFITTI",
        r"STO\s+(?:SEMPRE\s+)?VALUTANDO",
        r"^PROVIAMO$",
        r"BOOO+MM",
        r"EHEHE",
        r"TP\s*\d+\s+HIT",
        r"BE\s+HIT",
        r"TAKE\s+PROFIT",
        r"GESTIAMO\s+A\s+MERCATO",
        r"SE\s+NON\s+LI\s+PIACE",
        r"PRONTI\s+A\s+CHIUDERE",
        r"VI\s+ERO\s+MANCATO",
        r"CECCHINO",
        r"INIZIO\s+SETTIMANA",
        r"SIAMO\s+IN\s+LIVE",
        r"TIK\s*TOK",
        r"YOUTUBE\.COM",
        r"^HTTPS?://",
    ]
    for pat in ignore_pats:
        if re.search(pat, upper):
            log.debug(f"[IVAN] Ignorato: {raw[:60]}")
            return None

    if contains_any(upper, "SPOSTO SL A BE", "SPOSTIAMO SL A BE", "SL A BE"):
        log.info(f"[IVAN] CHECK_AND_BE: {raw[:60]}")
        return {
            "action":      "CHECK_AND_BE",
            "symbol":      "XAUUSD",
            "tp_index":    1,
            "magic_base":  ch["magic_base"],
            "raw_message": raw,
        }

    close_sig = _maybe_close_from_text(upper, ch, raw, state)
    if close_sig:
        return close_sig

    m_open = re.search(
        r"(XAUUSD|GOLD)\s+(BUY|SELL)\s+(\d+(?:[.,]\d+)?)",
        upper,
    )
    if not m_open:
        return None

    symbol = normalize_symbol(m_open.group(1))
    direction = m_open.group(2)
    entry = pf(m_open.group(3))
    if entry is None:
        return None

    tps: list[float] = []
    sl = None
    for line in raw.splitlines():
        lu = strip_md(line).upper().strip()
        m_tp = re.match(r"TP\s*\d+\s+([\d.,]+)", lu)
        if m_tp:
            v = pf(m_tp.group(1))
            if v is not None:
                tps.append(v)
            continue
        m_sl = re.match(r"SL\s*@?\s*([\d.,]+)", lu)
        if m_sl:
            sl = pf(m_sl.group(1))

    if not tps or sl is None:
        log.debug(f"[IVAN] Segnale incompleto: {raw[:60]}")
        return None

    # Accent-insensitive: METÀ SIZE, Meta size, MEZZA SIZE, typo META SAZIE
    folded = fold_accents(upper)
    lot_factor = 0.5 if re.search(
        r"(?:META|MEZZA|HALF)\s*(?:SIZE|SAZIE)",
        folded,
    ) else 1.0
    log.info(
        f"[IVAN] OPEN {direction} {symbol} @ {entry} TP={tps} SL={sl} "
        f"lot_factor={lot_factor}"
    )
    signal = {
        "action":      "OPEN",
        "direction":   direction,
        "symbol":      symbol,
        "entry":       entry,
        "tp_levels":   tps,
        "sl":          sl,
        "magic_base":  ch["magic_base"],
        "raw_message": raw,
    }
    if lot_factor != 1.0:
        signal["lot_factor"] = lot_factor
    return signal


# ─────────────────────────────────────────────────────────────────────────────
# MAPPA PARSER
# ─────────────────────────────────────────────────────────────────────────────

PARSERS = {
    "zanni_vip":  parser_zanni_vip,
    "sala_gold":  parser_sala_gold,
    "sala_vip":   parser_sala_vip,
    "sala_oro":   parser_sala_oro,
    "sala_stark": parser_sala_stark,
    "ivan_vip":   parser_ivan_vip,
    "placeholder": lambda _t, _c: None,
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
    log.info(f"TG TradinGo Bridge v{BRIDGE_VERSION}")
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
                append_bridge_event(CONFIG, {
                    "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "channel_id": ch_cfg["id"],
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                    "event_type": event_type,
                    "raw_text": text,
                    "outcome": "DUPLICATE",
                })
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

            matched_ignore = None
            upper_for_ignore = strip_md(text).upper()
            if ch_cfg["parser"] == "ivan_vip":
                for pat in (
                    r"PRONTI\s+A\s+CHIUDERE",
                    r"GESTIAMO\s+A\s+MERCATO",
                    r"SE\s+NON\s+LI\s+PIACE",
                    r"TP\s*\d+\s+HIT",
                ):
                    if re.search(pat, upper_for_ignore):
                        matched_ignore = pat
                        break

            try:
                if ch_cfg["parser"] in ("sala_gold", "sala_oro", "sala_vip", "ivan_vip"):
                    signal = parser(text, ch_cfg, bridge_state)
                else:
                    signal = parser(text, ch_cfg)
            except Exception as parse_exc:
                append_bridge_event(CONFIG, {
                    "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "channel_id": ch_cfg["id"],
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                    "event_type": event_type,
                    "raw_text": text,
                    "outcome": "PARSE_ERROR",
                    "error": f"{type(parse_exc).__name__}: {parse_exc}",
                })
                raise

            signal = coerce_edit_open_to_update(signal, is_edit)

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
                    append_bridge_event(CONFIG, {
                        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "channel_id": ch_cfg["id"],
                        "chat_id": int(chat_id),
                        "message_id": int(message_id),
                        "event_type": event_type,
                        "raw_text": text,
                        "outcome": "EMITTED",
                        "signal_id": signal.get("signal_id"),
                        "action": signal.get("action"),
                        "payload": signal,
                        "targets": meta.get("written_targets") or [],
                    })
            else:
                outcome = "IGNORED_PATTERN" if matched_ignore else "UNPARSED"
                append_bridge_event(CONFIG, {
                    "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "channel_id": ch_cfg["id"],
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                    "event_type": event_type,
                    "raw_text": text,
                    "outcome": outcome,
                    "matched_pattern": matched_ignore,
                })
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

        async def _heartbeat_loop():
            while True:
                write_heartbeat(CONFIG, HEARTBEAT_INTERVAL_SEC)
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            write_heartbeat(CONFIG, HEARTBEAT_INTERVAL_SEC)
            await client.run_until_disconnected()
        finally:
            hb_task.cancel()

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
