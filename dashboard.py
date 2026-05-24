import streamlit as st
import json
import time
import os

# CONFIGURAZIONE
JSON_PATH = "C:/tradingo_math/tradingo_state.json"
PASSWORD = "Tradingo2026"  # Inserisci la tua password esistente

st.set_page_config(page_title="TradinGo Math v3.1", layout="wide")

# Funzione di autenticazione semplice
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True
    
    with st.container():
        st.title("TradinGo Math - Access Control")
        pwd = st.text_input("Inserisci Password", type="password")
        if st.button("Accedi"):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Password errata")
        return False

if check_password():
    # Header con refresh automatico (ogni 5 secondi)
    st.title("🚀 TradinGo-Math v3.1 Dashboard")
    
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"Errore lettura JSON: {e}")
        data = {}

    # Layout a Colonne
    col1, col2 = st.columns(2)

    with col1:
        st.header("🏆 Conto PROP ($100K)")
        pnl_prop = data.get('prop_pnl', 0.0)
        pnl_pct = (pnl_prop / 100000.0) * 100
        
        color = "normal" if pnl_prop >= 0 else "inverse"
        st.metric("PnL Corrente", f"${pnl_prop:,.2f}", f"{pnl_pct:.2f}%", delta_color=color)
        
        st.subheader("Target & Limiti")
        t_rem = data.get('prop_target_rem', 10000.0)
        l_rem = data.get('prop_loss_rem', 3000.0)
        
        st.write(f"🎯 **Mancante al Target ($10k):** ${t_rem:,.2f}")
        st.progress(min(max(pnl_prop / 10000.0, 0.0), 1.0))
        
        st.write(f"⚠️ **Distanza Hard Loss ($3k):** ${l_rem:,.2f}")
        st.warning(f"Protezione attiva se PnL < $ -3,000")

    with col2:
        st.header("💰 Conto HEDGE ($50K)")
        pnl_hedge = data.get('hedge_pnl', 0.0)
        equity_hedge = data.get('hedge_equity', 50000.0)
        
        st.metric("PnL Corrente (Utile Reale)", f"${pnl_hedge:,.2f}")
        
        st.subheader("Estrazione Utile")
        h_target = 3500.0
        h_rem = data.get('hedge_target_rem', h_target)
        
        st.write(f"💵 **Obiettivo Estrazione ($3.5k):** ${h_rem:,.2f} rimanenti")
        st.progress(min(max(pnl_hedge / h_target, 0.0), 1.0))
        
        st.info(f"Equity Attuale: ${equity_hedge:,.2f}")

    st.divider()
    
    # Stato di Sistema
    c1, c2, c3 = st.columns(3)
    with c1:
        status = "🟢 ACTIVE" if data.get('fase2_attiva') else "⚪ WAITING"
        st.write(f"**FASE 2:** {status}")
    with c2:
        st.write(f"**SESSION:** {data.get('session', 'N/A')}")
    with c3:
        st.write(f"**ATR:** {data.get('atr', 0.0):.2f}")

    # Script di auto-refresh
    time.sleep(5)
    st.rerun()
