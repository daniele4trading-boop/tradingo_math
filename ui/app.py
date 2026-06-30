"""StatArb Streamlit dashboard — Modulo 6."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from ui.services import (
    backtest_results_dataframe,
    load_dashboard_snapshot,
    pair_rows_dataframe,
    run_backtests_offline,
)
from ui.theme import theme_css

st.set_page_config(
    page_title="StatArb",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(theme_css(), unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_snapshot(include_live: bool) -> dict:
    snap = load_dashboard_snapshot(include_live=include_live)
    return {
        "pair_rows": snap.pair_rows,
        "portfolio": snap.portfolio,
        "account_metrics": snap.account_metrics,
        "risk_warnings": snap.risk_warnings,
        "data_source": snap.data_source,
        "leg_a_profile": snap.leg_a_profile,
        "leg_b_profile": snap.leg_b_profile,
        "dry_run": snap.dry_run,
        "load_errors": snap.load_errors,
    }


def _render_header(snap: dict) -> None:
    st.markdown('<p class="gold-title">StatArb Pairs Trading</p>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="gold-subtitle">Data {snap["data_source"]} · '
        f"Leg A {snap['leg_a_profile']} · Leg B {snap['leg_b_profile']} · "
        f"Dry-run {'ON' if snap['dry_run'] else 'OFF'}</p>",
        unsafe_allow_html=True,
    )


def _render_accounts(metrics: list) -> None:
    st.subheader("Account & Risk")
    if not metrics:
        st.info("Metriche live non disponibili (MT5 non connesso o errore).")
        return
    cols = st.columns(len(metrics))
    for col, metric in zip(cols, metrics):
        with col:
            st.metric("Equity", f"{metric.equity:,.2f}")
            st.caption(metric.profile_name)
            st.write(f"Margin level: {metric.margin_level:.1f}%")
            st.write(f"Daily loss: {metric.daily_loss_pct:.2f}%")
            st.write(f"Drawdown: {metric.drawdown_pct:.2f}%")


def _render_portfolio(portfolio) -> None:
    st.subheader("Portfolio aperto")
    if portfolio is None:
        st.caption("Portfolio live non caricato.")
        return
    st.write(f"Pair hedged aperti: **{portfolio.open_pair_count}**")
    if portfolio.open_pairs:
        for item in portfolio.open_pairs:
            st.write(f"• {item.pair_label}")
    if portfolio.unhedged_pairs:
        st.markdown(
            '<div class="warn-gold">Posizioni UNHEDGED: '
            + ", ".join(p.pair_label for p in portfolio.unhedged_pairs)
            + "</div>",
            unsafe_allow_html=True,
        )


def _render_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    st.subheader("Avvisi risk")
    for warning in warnings:
        st.markdown(f'<div class="warn-gold">{warning}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner="Backtest su cache…")
def _cached_backtest() -> dict:
    results, summary = run_backtests_offline()
    return {
        "results": results,
        "summary": summary,
    }


def _render_backtest(bt: dict) -> None:
    summary = bt["summary"]
    window = (
        f"ultimi {summary.lookback_days} giorni"
        if summary.lookback_days > 0
        else "intera finestra cache"
    )
    st.subheader(f"Backtest ({window})")
    st.caption(
        "Simulazione offline su cache Modulo 2 con i parametri attuali "
        "(segnali, sizing, costi). Non è consulenza finanziaria."
    )
    cols = st.columns(4)
    cols[0].metric("Trade totali", summary.total_trades)
    cols[1].metric("Ret% portfolio*", f"{summary.total_return_pct:.2f}")
    cols[2].metric("Net PnL*", f"{summary.net_pnl:,.1f}")
    cols[3].metric("Coppie net > 0", summary.pairs_profitable)
    st.caption(
        f"*Somma per coppia su equity iniziale {summary.initial_equity:,.0f} "
        f"(coppie analizzate {summary.pairs_analyzed}, selezionate {summary.pairs_selected})"
    )
    df = backtest_results_dataframe(bt["results"])
    st.dataframe(df, use_container_width=True, hide_index=True)


def main() -> None:
    with st.sidebar:
        st.markdown("### Controlli")
        include_live = st.toggle("Connessione MT5 live", value=True)
        if st.button("Aggiorna dati", use_container_width=True):
            _cached_snapshot.clear()
            _cached_backtest.clear()
        st.markdown("---")
        st.markdown("### Da cellulare")
        st.markdown(
            '<p class="mobile-url">http://144.91.76.28:8520</p>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Avvia run_ui_public.bat sulla VPS (bind 0.0.0.0). "
            "Apri porta 8520 nel firewall Windows se non risponde."
        )
        st.markdown("---")
        st.caption("Tema: blu notte / oro")
        st.caption("Porta default: 8520")

    snap = _cached_snapshot(include_live=include_live)
    _render_header(snap)

    if snap["load_errors"]:
        for err in snap["load_errors"]:
            st.warning(err)

    _render_accounts(snap["account_metrics"])
    _render_warnings(snap["risk_warnings"])
    _render_portfolio(snap["portfolio"])

    st.subheader("Coppie & segnali (cache Modulo 2)")
    df = pair_rows_dataframe(snap["pair_rows"])
    selected = sum(1 for row in snap["pair_rows"] if row.selected)
    actionable = sum(
        1
        for row in snap["pair_rows"]
        if row.selected and row.signal not in ("FLAT", "ERROR") and row.gate_allowed
    )
    st.caption(f"Selezionate: {selected} · Azionabili (signal + risk): {actionable}")
    st.dataframe(df, use_container_width=True, hide_index=True)

    _render_backtest(_cached_backtest())

    with st.expander("Legenda segnali"):
        st.markdown(
            """
            - **LONG_SPREAD** — spread sotto media (z ≤ -entry)
            - **SHORT_SPREAD** — spread sopra media (z ≥ entry)
            - **FLAT** — nessun ingresso
            - **Risk OK** — gate Modulo 5 su conti + portfolio
            """
        )


if __name__ == "__main__":
    main()
