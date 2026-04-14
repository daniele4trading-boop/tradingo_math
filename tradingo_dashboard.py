"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          TRADINGO-MATH  —  DASHBOARD STREAMLIT                        ║
║          Porta 8501 | Avvio: streamlit run tradingo_dashboard.py             ║
╚══════════════════════════════════════════════════════════════════════════════╝

Legge il file `tradingo_state.json` generato dal motore principale e mostra
in tempo reale tutte le metriche di sistema.

Avvio VPS:
  streamlit run tradingo_dashboard.py --server.port 8501 --server.address 0.0.0.0
"""

import streamlit as st
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
STATE_FILE    = "tradingo_state.json"
REFRESH_SEC   = 60         # secondi tra un aggiornamento e l'altro
PROP_COST     = 680.0
FLOOR_EQUITY  = 9_400.0

# ──────────────────────────────────────────────────────────────────────────────
# PAGINA
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TradinGo Asymmetric",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ──────────────────────────────────────────────────────────────────────────────
# PASSWORD PROTECTION
# ──────────────────────────────────────────────────────────────────────────────
DASHBOARD_PASSWORD = "tradingo2026"   # ← CAMBIA con la tua password

def check_password() -> bool:
    """Mostra un form di login e blocca la dashboard se la password è errata."""
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <div style="max-width:380px;margin:120px auto;
                background:#0D1117;border:1px solid #21262D;
                border-radius:10px;padding:40px 36px;">
        <div style="font-family:'Share Tech Mono',monospace;font-size:22px;
                    color:#F0B429;text-align:center;letter-spacing:4px;
                    margin-bottom:8px;">⚡ TRADINGO-MATH</div>
        <div style="font-size:12px;color:#8B949E;text-align:center;
                    letter-spacing:2px;margin-bottom:28px;">ACCESSO RISERVATO</div>
    </div>
    """, unsafe_allow_html=True)

    pwd = st.text_input("Password", type="password", key="pwd_input",
                        placeholder="Inserisci la password...")
    if st.button("Accedi", use_container_width=True):
        if pwd == DASHBOARD_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Password errata.")
    return False

# ──────────────────────────────────────────────────────────────────────────────
# CSS CUSTOM — Stile dark industrial con accenti dorati (tema GOLD)
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap');

:root {
    --gold:    #F0B429;
    --gold2:   #FFD166;
    --green:   #00E676;
    --red:     #FF1744;
    --blue:    #40C4FF;
    --bg:      #080C10;
    --bg2:     #0D1117;
    --bg3:     #161B22;
    --border:  #21262D;
    --text:    #E6EDF3;
    --muted:   #8B949E;
}

html, body, [class*="css"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Rajdhani', sans-serif;
}

/* Header principale */
.tg-header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px 0 8px;
    border-bottom: 1px solid var(--gold);
    margin-bottom: 24px;
}
.tg-logo {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    color: var(--gold);
    letter-spacing: 4px;
    text-shadow: 0 0 20px rgba(240,180,41,0.4);
}
.tg-sub {
    font-size: 13px;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* Badge MODE */
.mode-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 3px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
}
.mode-idle        { background: #161B22; color: #8B949E; border: 1px solid #21262D; }
.mode-normal      { background: #0D2818; color: #00E676; border: 1px solid #00E676; }
.mode-mitigation  { background: #2D1B00; color: #F0B429; border: 1px solid #F0B429; }
.mode-trending    { background: #001A33; color: #40C4FF; border: 1px solid #40C4FF; }
.mode-halted      { background: #2D0000; color: #FF1744; border: 1px solid #FF1744;
                    animation: blink 1s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }

/* Metric card */
.metric-card {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 12px;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
}
.card-gold::before  { background: var(--gold); }
.card-green::before { background: var(--green); }
.card-red::before   { background: var(--red); }
.card-blue::before  { background: var(--blue); }

.metric-label {
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.metric-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 26px;
    font-weight: 700;
    line-height: 1.1;
}
.metric-sub {
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
}

/* Account panels */
.account-panel {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
}
.account-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
}
.acc-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid #161B22;
    font-size: 15px;
}
.acc-key   { color: var(--muted); }
.acc-val   { font-family: 'Share Tech Mono', monospace; color: var(--text); }
.val-pos   { color: var(--green); }
.val-neg   { color: var(--red); }
.val-warn  { color: var(--gold); }

/* Indicator strip */
.indicator-strip {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin: 16px 0;
}
.ind-chip {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 14px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
}
.ind-label { color: var(--muted); font-size: 11px; display: block; }

/* Trade ticket */
.ticket-box {
    background: var(--bg3);
    border-left: 3px solid var(--gold);
    padding: 8px 14px;
    margin: 4px 0;
    border-radius: 0 4px 4px 0;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: var(--gold2);
}

/* Progress bar floor */
.floor-bar-container {
    background: #0D1117;
    border: 1px solid var(--border);
    border-radius: 4px;
    height: 14px;
    overflow: hidden;
    margin-top: 8px;
}
.floor-bar {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s;
}

/* Connection dot */
.conn-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}
.conn-ok  { background: var(--green); box-shadow: 0 0 6px var(--green); }
.conn-err { background: var(--red);   box-shadow: 0 0 6px var(--red);   }

/* Timestamp */
.ts { font-family: 'Share Tech Mono', monospace; font-size: 11px; color: #4A5568; }

/* Streamlit overrides */
[data-testid="stMetric"] { display: none; }
div.block-container { padding-top: 1rem; padding-bottom: 1rem; max-width: 1400px; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# UTILITY
# ──────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    p = Path(STATE_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def fmt_money(v: float, decimals: int = 2) -> str:
    return f"{'+'if v>0 else ''}{v:,.{decimals}f} €"

def fmt_price(v: float) -> str:
    return f"{v:,.2f}"

def color_class(v: float, warn_threshold: float = 0) -> str:
    if v > warn_threshold:
        return "val-pos"
    elif v < 0:
        return "val-neg"
    else:
        return "val-warn"

def mode_css(mode: str) -> str:
    m = mode.lower()
    if "normal" in m:    return "mode-normal"
    if "mitigation" in m:return "mode-mitigation"
    if "trend" in m:     return "mode-trending"
    if "halt" in m:      return "mode-halted"
    return "mode-idle"


# ──────────────────────────────────────────────────────────────────────────────
# RENDER PRINCIPALE
# ──────────────────────────────────────────────────────────────────────────────
def render(state: dict):
    # ── Header ───────────────────────────────────────────────────────────────
    mode = state.get("mode", "IDLE")
    ts   = state.get("timestamp", "")
    try:
        ts_fmt = (datetime.fromisoformat(ts) + timedelta(hours=2)).strftime("%d/%m/%Y  %H:%M:%S IT") if ts else "—"
    except Exception:
        ts_fmt = ts

    st.markdown(f"""
    <div class="tg-header">
        <div>
            <div class="tg-logo">⚡ TRADINGO-MATH</div>
            <div class="tg-sub">XAUUSD Dual-Account Engine &nbsp;|&nbsp;
                <span class="mode-badge {mode_css(mode)}">{mode}</span>
                &nbsp;&nbsp;<span class="ts">{ts_fmt}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Fila principale metriche ─────────────────────────────────────────────
    net     = state.get("net_system_profit", 0.0)
    floor_d = state.get("floor_distance", 0.0)
    hedge_eq = state.get("hedge_equity", 0.0)
    pnl_h   = state.get("hedge_pnl_float", 0.0)
    spread_ok = state.get("spread_ok", True)
    spread_pts = state.get("spread_points", 0)

    net_color  = "#00E676" if net >= 0 else "#FF1744"
    flr_color  = "#00E676" if floor_d > 300 else ("#F0B429" if floor_d > 0 else "#FF1744")
    spread_color = "#00E676" if spread_ok else "#FF1744"

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f"""
        <div class="metric-card card-gold">
            <div class="metric-label">Net System Profit</div>
            <div class="metric-value" style="color:{net_color}">{fmt_money(net)}</div>
            <div class="metric-sub">Hedge realized − 680 € prop cost</div>
        </div>""", unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card card-{'green' if floor_d>300 else ('red' if floor_d<=0 else 'gold')}">
            <div class="metric-label">Distanza dal Floor</div>
            <div class="metric-value" style="color:{flr_color}">{fmt_money(floor_d)}</div>
            <div class="metric-sub">Floor = 9.400 € | Equity = {fmt_price(hedge_eq)} €</div>
        </div>""", unsafe_allow_html=True)

    with c3:
        pnl_color = "#00E676" if pnl_h >= 0 else "#FF1744"
        st.markdown(f"""
        <div class="metric-card card-blue">
            <div class="metric-label">Hedge PnL Flottante</div>
            <div class="metric-value" style="color:{pnl_color}">{fmt_money(pnl_h)}</div>
            <div class="metric-sub">Profitto/perdita posizione aperta</div>
        </div>""", unsafe_allow_html=True)

    with c4:
        st.markdown(f"""
        <div class="metric-card card-{'green' if spread_ok else 'red'}">
            <div class="metric-label">Spread</div>
            <div class="metric-value" style="color:{spread_color}">{spread_pts} pts</div>
            <div class="metric-sub">{'✓ Operativo (max 40)' if spread_ok else '✗ Bloccato (spread alto)'}</div>
        </div>""", unsafe_allow_html=True)

    # ── Floor progress bar ───────────────────────────────────────────────────
    hedge_init = 10_000.0
    floor_pct  = max(0, min(100, ((hedge_eq - FLOOR_EQUITY) / (hedge_init - FLOOR_EQUITY)) * 100))
    bar_color  = "#00E676" if floor_pct > 50 else ("#F0B429" if floor_pct > 20 else "#FF1744")
    st.markdown(f"""
    <div style="margin:-4px 0 20px">
        <div style="font-size:11px;color:#8B949E;letter-spacing:2px;
                    text-transform:uppercase;margin-bottom:4px;">
            Equity Hedge — Distanza dal Floor
        </div>
        <div class="floor-bar-container">
            <div class="floor-bar" style="width:{floor_pct:.1f}%;background:{bar_color}"></div>
        </div>
        <div style="display:flex;justify-content:space-between;
                    font-size:11px;color:#4A5568;margin-top:3px;">
            <span>Floor 9.400 €</span>
            <span>{floor_pct:.1f}%</span>
            <span>Target 10.000 €</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Account panels ───────────────────────────────────────────────────────
    col_prop, col_hedge = st.columns(2)

    with col_prop:
        prop_bal  = state.get("prop_balance", 0.0)
        prop_eq   = state.get("prop_equity", 0.0)
        prop_pnl  = state.get("prop_pnl_float", 0.0)
        prop_conn = state.get("prop_connected", False)
        p_ticket  = state.get("prop_ticket", 0)
        conn_dot  = '<span class="conn-dot conn-ok"></span>' if prop_conn else '<span class="conn-dot conn-err"></span>'

        st.markdown(f"""
        <div class="account-panel">
            <div class="account-title">{conn_dot} PROP ACCOUNT — 100k Demo</div>
            <div class="acc-row">
                <span class="acc-key">Balance</span>
                <span class="acc-val">{fmt_price(prop_bal)} €</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">Equity</span>
                <span class="acc-val">{fmt_price(prop_eq)} €</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">PnL Flottante</span>
                <span class="acc-val {color_class(prop_pnl)}">{fmt_money(prop_pnl)}</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">Costo Prop</span>
                <span class="acc-val val-neg">−680 €</span>
            </div>
            {'<div class="ticket-box">🎯 TRADE ATTIVO: #' + str(p_ticket) + '</div>' if p_ticket else ''}
        </div>
        """, unsafe_allow_html=True)

    with col_hedge:
        hedge_bal   = state.get("hedge_balance", 0.0)
        hedge_conn  = state.get("hedge_connected", False)
        realized    = state.get("hedge_realized_profit", 0.0)
        h_ticket    = state.get("hedge_ticket", 0)
        r_ticket    = state.get("reverse_ticket", 0)
        reverse_on  = state.get("reverse_active", False)
        trailing_on = state.get("trailing_active", False)
        conn_dot2   = '<span class="conn-dot conn-ok"></span>' if hedge_conn else '<span class="conn-dot conn-err"></span>'

        st.markdown(f"""
        <div class="account-panel">
            <div class="account-title">{conn_dot2} HEDGE ACCOUNT — 10k</div>
            <div class="acc-row">
                <span class="acc-key">Balance</span>
                <span class="acc-val">{fmt_price(hedge_bal)} €</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">Equity</span>
                <span class="acc-val">{fmt_price(hedge_eq)} €</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">PnL Flottante</span>
                <span class="acc-val {color_class(pnl_h)}">{fmt_money(pnl_h)}</span>
            </div>
            <div class="acc-row">
                <span class="acc-key">Profitto Realizzato</span>
                <span class="acc-val {color_class(realized)}">{fmt_money(realized)}</span>
            </div>
            {'<div class="ticket-box">📈 HEDGE APERTO: #' + str(h_ticket) + '</div>' if h_ticket else ''}
            {'<div class="ticket-box" style="border-color:#F0B429;color:#F0B429;">⚠️ REVERSE ATTIVO: #' + str(r_ticket) + '</div>' if r_ticket else ''}
        </div>
        """, unsafe_allow_html=True)

    # ── Indicatori tecnici + Controller status ────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    col_ind, col_ctrl = st.columns([3, 2])

    with col_ind:
        z_score  = state.get("atr_zscore", 0.0)
        vwap     = state.get("vwap", 0.0)
        cvd      = state.get("cvd", 0.0)
        cvd_t    = state.get("cvd_trend", "NEUTRAL")
        sig      = state.get("last_signal", "NONE")

        z_color  = "#00E676" if z_score >= 1.5 else "#F0B429"
        cvd_color = "#00E676" if cvd_t == "UP" else ("#FF1744" if cvd_t == "DOWN" else "#8B949E")
        sig_color = "#40C4FF" if sig == "BUY" else ("#F0B429" if sig == "SELL" else "#8B949E")

        st.markdown(f"""
        <div class="account-panel">
            <div class="account-title">📊 Indicatori Tecnici (M5 XAUUSD)</div>
            <div class="indicator-strip">
                <div class="ind-chip">
                    <span class="ind-label">ATR Z-SCORE</span>
                    <span style="color:{z_color};font-size:18px">{z_score:.2f}</span>
                </div>
                <div class="ind-chip">
                    <span class="ind-label">VWAP</span>
                    <span style="font-size:18px">{fmt_price(vwap)}</span>
                </div>
                <div class="ind-chip">
                    <span class="ind-label">CVD</span>
                    <span style="color:{cvd_color};font-size:18px">{cvd:+.0f}</span>
                </div>
                <div class="ind-chip">
                    <span class="ind-label">CVD TREND</span>
                    <span style="color:{cvd_color};font-size:18px">{cvd_t}</span>
                </div>
                <div class="ind-chip">
                    <span class="ind-label">SEGNALE</span>
                    <span style="color:{sig_color};font-size:18px;font-weight:700">{sig}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_ctrl:
        exp_loss = state.get("hedge_expected_loss", 0.0)
        last_err = state.get("last_error", "")

        ctrl_items = []
        if mode == "Normal Mode":
            ctrl_items.append(("🟢", "Sistema operativo", "#00E676"))
        if mode == "Mitigation":
            ctrl_items.append(("🟡", "Reverse Hedge attivo", "#F0B429"))
        if mode == "Trend Riding":
            ctrl_items.append(("🔵", "Trailing Stop ATR×2 attivo", "#40C4FF"))
        if mode == "HALTED":
            ctrl_items.append(("🔴", "SISTEMA BLOCCATO — Hard Stop", "#FF1744"))
        if trailing_on:
            ctrl_items.append(("↗", "Trailing stop in esecuzione", "#40C4FF"))
        if reverse_on:
            ctrl_items.append(("⚡", "Reverse hedge in esecuzione", "#F0B429"))

        items_html = "".join([
            f'<div class="acc-row"><span style="color:{c}">{icon} {label}</span></div>'
            for icon, label, c in ctrl_items
        ]) or '<div class="acc-row"><span class="acc-key">Nessuna azione attiva</span></div>'

        st.markdown(f"""
        <div class="account-panel">
            <div class="account-title">🎛 Smart Controller</div>
            {items_html}
            <div class="acc-row">
                <span class="acc-key">Perdita attesa hedge</span>
                <span class="acc-val val-warn">{fmt_money(-exp_loss)}</span>
            </div>
            {'<div class="acc-row"><span class="acc-key">Ultimo errore</span><span class="acc-val val-neg" style="font-size:12px">' + last_err[:40] + '...</span></div>' if last_err else ''}
        </div>
        """, unsafe_allow_html=True)

    # ── FTMO Risk Panel ──────────────────────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    render_ftmo_panel(state)

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="text-align:center;padding:20px 0 8px;
                border-top:1px solid #21262D;margin-top:24px;">
        <span class="ts">TradinGo-Math v1.0 &nbsp;|&nbsp;
        Auto-refresh ogni {REFRESH_SEC}s &nbsp;|&nbsp; {(datetime.now(timezone.utc) + timedelta(hours=2)).strftime('%H:%M:%S')} IT</span>
    </div>
    """, unsafe_allow_html=True)




# ──────────────────────────────────────────────────────────────────────────────
# FTMO RISK PANEL
# ──────────────────────────────────────────────────────────────────────────────
def render_ftmo_panel(state: dict):
    daily_pct    = state.get("ftmo_daily_dd_pct",      0.0)
    total_pct    = state.get("ftmo_total_dd_pct",      0.0)
    daily_lim    = state.get("ftmo_daily_dd_limit",    97300.0)
    total_lim    = state.get("ftmo_total_dd_limit",    90500.0)
    profit_oggi  = state.get("ftmo_profit_oggi",       0.0)
    cons_limit   = state.get("ftmo_consistency_limit", 0.0)
    cons_ok      = state.get("ftmo_consistency_ok",    True)
    can_trade    = state.get("ftmo_can_trade",         True)
    block_reason = state.get("ftmo_block_reason",      "")
    final_phase  = state.get("ftmo_final_phase",       False)

    def dd_color(pct):
        if pct < 0.015: return "#00E676"
        if pct < 0.022: return "#F0B429"
        return "#FF1744"

    daily_col = dd_color(daily_pct)
    total_col = dd_color(total_pct)
    cons_col  = "#00E676" if cons_ok else "#FF1744"

    banner = ""
    if not can_trade and block_reason not in ("OK", "FINAL_PHASE", ""):
        banner = f'''<div style="background:#2D0000;border:1px solid #FF1744;border-radius:6px;
            padding:10px 16px;margin-bottom:12px;font-family:\'Share Tech Mono\',monospace;
            color:#FF1744;font-size:13px;">⛔ NUOVI TRADE BLOCCATI — {block_reason}</div>'''
    elif final_phase:
        banner = '''<div style="background:#001A33;border:1px solid #40C4FF;border-radius:6px;
            padding:10px 16px;margin-bottom:12px;font-family:\'Share Tech Mono\',monospace;
            color:#40C4FF;font-size:13px;">🚀 FINAL PHASE — Prop quasi bruciata. Massimizza Hedge.</div>'''

    daily_bar = min(100, (daily_pct / 0.027) * 100)
    total_bar = min(100, (total_pct / 0.095) * 100)
    cons_bar  = min(100, (profit_oggi / cons_limit * 100) if cons_limit > 0 else 0)

    if cons_limit <= 0:
        cons_label = "Primo giorno — nessun limite"
        cons_val   = "N/A"
    else:
        cons_val   = f"{profit_oggi:+.0f}€ / {cons_limit:.0f}€"
        cons_label = "✓ OK" if cons_ok else "⚠ LIMITE RAGGIUNTO"

    st.markdown(f"""
    {banner}
    <div class="account-panel" style="margin-top:0">
        <div class="account-title">🛡 FTMO Risk Monitor — Challenge 100k</div>
        <div style="margin-bottom:14px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                <span style="font-size:12px;color:#8B949E;letter-spacing:1px;text-transform:uppercase">
                    Daily DD usato &nbsp;<span style="color:{daily_col}">{daily_pct:.2%}</span>
                    &nbsp;/&nbsp; soglia sicurezza 2.7%
                </span>
                <span style="font-family:'Share Tech Mono',monospace;font-size:12px;color:{daily_col}">
                    Limite equity oggi: {daily_lim:,.0f}€
                </span>
            </div>
            <div class="floor-bar-container">
                <div class="floor-bar" style="width:{daily_bar:.1f}%;background:{daily_col}"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#4A5568;margin-top:2px">
                <span>Base: balance mezzanotte ieri</span><span>Max: 2.7% → stop | 3.0% → kill</span>
            </div>
        </div>
        <div style="margin-bottom:14px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                <span style="font-size:12px;color:#8B949E;letter-spacing:1px;text-transform:uppercase">
                    Total DD usato &nbsp;<span style="color:{total_col}">{total_pct:.2%}</span>
                    &nbsp;/&nbsp; soglia sicurezza 9.5%
                </span>
                <span style="font-family:'Share Tech Mono',monospace;font-size:12px;color:{total_col}">
                    Limite equity assoluto: {total_lim:,.0f}€
                </span>
            </div>
            <div class="floor-bar-container">
                <div class="floor-bar" style="width:{total_bar:.1f}%;background:{total_col}"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#4A5568;margin-top:2px">
                <span>Base: picco balance mezzanotte (mai scende)</span><span>8.5% → Final Phase | 9.5% → stop | 10% → kill</span>
            </div>
        </div>
        <div style="margin-bottom:6px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                <span style="font-size:12px;color:#8B949E;letter-spacing:1px;text-transform:uppercase">
                    Consistency Rule &nbsp;<span style="color:{cons_col}">{cons_label}</span>
                </span>
                <span style="font-family:'Share Tech Mono',monospace;font-size:12px;color:{cons_col}">
                    {cons_val}
                </span>
            </div>
            <div class="floor-bar-container">
                <div class="floor-bar" style="width:{cons_bar:.1f}%;background:{cons_col}"></div>
            </div>
            <div style="font-size:11px;color:#4A5568;margin-top:3px">
                Limite giornaliero = profit cumulato fino a ieri (base 100.000€ fisso)
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# LOOP
# ──────────────────────────────────────────────────────────────────────────────
if not check_password():
    st.stop()

placeholder = st.empty()

while True:
    state = load_state()
    with placeholder.container():
        if not state:
            st.markdown("""
            <div style="text-align:center;padding:80px;color:#8B949E;
                        font-family:'Share Tech Mono',monospace;font-size:16px;">
                ⏳ In attesa del motore TradinGo...<br>
                <span style="font-size:12px">Assicurati che tradingo_system.py sia in esecuzione</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            render(state)
    time.sleep(REFRESH_SEC)
    st.rerun()
