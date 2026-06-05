from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from urllib.parse import urlparse

from cloud_app.backtester import BACKTEST_MODES, run_walkforward_backtest
from cloud_app.config import settings
from cloud_app.db import get_state, initialize_database
from cloud_app.market_data import latest_prices, sync_market_data
from cloud_app.scanner import latest_strategy_selection, latest_strategy_validation, list_signals, run_daily_scan
from cloud_app.workflow import run_daily_workflow


st.set_page_config(page_title="Swing Trader Cloud", page_icon="ST", layout="wide")


def money(value, digits: int = 0) -> str:
    try:
        return f"₹{float(value):,.{digits}f}"
    except Exception:
        return "₹0"


def pct(value) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "0.00%"


def ensure_db() -> None:
    try:
        initialize_database()
    except OperationalError as exc:
        show_database_error(exc)
        st.stop()
    except SQLAlchemyError as exc:
        show_database_error(exc)
        st.stop()


def database_host_hint() -> tuple[str, str]:
    normalized = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    host = parsed.hostname or "unknown"
    port = parsed.port or "default"
    return host, str(port)


def show_database_error(exc: Exception) -> None:
    host, port = database_host_hint()
    st.error("Database connection failed before the app could load.")
    st.caption(f"Configured database host: `{host}` on port `{port}`. Password and username are hidden.")

    if host.startswith("db.") and host.endswith("supabase.co"):
        st.warning(
            "This is the direct Supabase database host. Streamlit Cloud and GitHub Actions usually need "
            "the Supabase pooled connection string instead."
        )
        st.markdown(
            "Update both Streamlit secrets and GitHub Actions secrets so `DATABASE_URL` uses a "
            "`pooler.supabase.com` host and ends with `?sslmode=require`."
        )
    elif "pooler.supabase.com" in host:
        st.warning(
            "The app is using a Supabase pooler host, so the remaining likely causes are an incorrect "
            "database password, wrong pooler mode/port, or missing SSL."
        )
        st.markdown(
            "Re-copy the exact Supabase pooler URI, replace `[YOUR-PASSWORD]`, and keep "
            "`?sslmode=require` at the end."
        )
    else:
        st.warning("The database host does not look like the normal Supabase direct or pooler hostname.")

    with st.expander("Technical error type"):
        st.code(type(exc).__name__)


def selected_panel(selection: dict) -> None:
    mode = selection.get("mode", "none")
    name = selection.get("strategy_name") or "No validated strategy"
    st.info(f"Selected strategy today: **{name}** | Mode: **{mode}** | Score: **{selection.get('selection_score', 0)}**")
    if selection.get("reason"):
        st.caption(selection["reason"])


def setup_card(signal: dict) -> None:
    factors = signal.get("factor_breakdown_json") if isinstance(signal.get("factor_breakdown_json"), dict) else {}
    bt = signal.get("backtest_summary_json") if isinstance(signal.get("backtest_summary_json"), dict) else {}
    with st.container(border=True):
        left, right = st.columns([3, 1])
        with left:
            st.subheader(f"{signal['symbol']} · {signal.get('company_name', '')}")
            st.caption(f"{signal.get('sector', '')} · {signal.get('strategy_name', '')}")
        with right:
            st.metric("Confidence", f"{signal.get('confidence_score', 0):.0f}%")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Buy zone", f"{signal.get('entry_low'):.2f}-{signal.get('entry_high'):.2f}")
        c2.metric("Stop", f"{signal.get('stop_loss'):.2f}")
        c3.metric("Target", f"{signal.get('target_price'):.2f}")
        c4.metric("Risk/reward", f"{signal.get('risk_reward_ratio'):.2f}")
        st.write(signal.get("reason_summary", ""))
        with st.expander("Backtest and filter details"):
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Trades", bt.get("sample_size", 0))
            b2.metric("Win rate", pct(bt.get("win_rate", 0)))
            b3.metric("Profit factor", bt.get("profit_factor", 0))
            b4.metric("Max drawdown", pct(bt.get("max_drawdown", 0)))
            st.json(
                {
                    "market_regime": factors.get("market_regime"),
                    "sector_rank": factors.get("sector_rank"),
                    "sector_strength_score": factors.get("sector_strength_score"),
                    "sector_filter": factors.get("sector_filter"),
                }
            )


def validation_table(metrics: dict) -> pd.DataFrame:
    rows = []
    for key, item in metrics.items():
        rows.append(
            {
                "Strategy": item.get("strategy_name", key),
                "Key": key,
                "Gate": "pass" if item.get("passes_validation") else "reject",
                "Reason": "; ".join(item.get("validation_failures") or []) or "Strict gate passed",
                "Reliability": item.get("reliability_score", 0),
                "Selection": item.get("selection_score", 0),
                "Trades": item.get("trade_count", 0),
                "Win Rate": item.get("win_rate", 0),
                "Profit Factor": item.get("profit_factor", 0),
                "Recent PF": (item.get("recent_period") or {}).get("profit_factor", 0),
                "Expectancy": item.get("expectancy", 0),
                "Max DD": item.get("max_drawdown_pct", 0),
            }
        )
    return pd.DataFrame(rows)


def run_with_progress(mode: str) -> None:
    progress_bar = st.progress(0, text="Starting daily workflow")

    def progress(label: str, pct_value: int) -> None:
        progress_bar.progress(min(max(int(pct_value), 0), 100), text=label)

    result = run_daily_workflow(mode=mode, progress=progress)
    progress("Daily workflow complete", 100)
    st.success(
        f"Done. Tested {result['strategy_validation'].get('universe_count', 0)} symbols and promoted "
        f"{result['scan'].get('signals_promoted', 0)} setup(s)."
    )


ensure_db()

st.title("Swing Trader Cloud")
st.caption("Educational swing-trading research only. Not financial advice. No broker orders are placed.")

tab_dashboard, tab_setups, tab_lab, tab_deploy = st.tabs(["Dashboard", "Today's Setups", "Strategy Lab", "Deploy Notes"])

with tab_dashboard:
    selection = latest_strategy_selection()
    selected_panel(selection)
    col1, col2, col3 = st.columns(3)
    prices = latest_prices()
    signals = list_signals(2)
    validation = latest_strategy_validation()
    col1.metric("Universe With Prices", len(prices))
    col2.metric("Today's Setups", len(signals))
    col3.metric("Validated Strategies", sum(1 for item in validation.values() if item.get("passes_validation")))

    mode = st.radio("Backtest mode for manual daily workflow", list(BACKTEST_MODES.keys()), horizontal=True, index=0)
    if st.button("Run Daily Workflow", type="primary"):
        run_with_progress(mode)
        st.rerun()

    last = get_state("last_workflow", {})
    if last:
        st.caption(f"Last workflow status: {last.get('status')} at {last.get('completed_at')}")

with tab_setups:
    st.subheader("Today's Top Setups")
    st.caption("Only the top two validated setups are shown.")
    signals = list_signals(2)
    if not signals:
        st.warning("No setups saved yet. Run the daily workflow first.")
    for signal in signals:
        setup_card(signal)

with tab_lab:
    st.subheader("Strategy Lab")
    st.caption("No-lookahead validation: signal first, entry next-day open, exits only on later candles.")
    selected_panel(latest_strategy_selection())
    lab_mode = st.radio("Backtest mode", list(BACKTEST_MODES.keys()), horizontal=True, key="lab_mode")
    if st.button("Run Strategy Lab Only"):
        progress_bar = st.progress(0, text="Starting Strategy Lab")

        def lab_progress(payload: dict) -> None:
            progress_bar.progress(int(payload.get("progress_pct", 0)), text=payload.get("step", "Running"))

        result = run_walkforward_backtest(mode=lab_mode, progress_callback=lab_progress)
        st.success(f"Strategy Lab complete. Selected: {result['selected_strategy'].get('strategy_name')}")
        st.rerun()

    table = validation_table(latest_strategy_validation())
    if table.empty:
        st.warning("No validation run saved yet.")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)

with tab_deploy:
    st.subheader("Cloud Deployment Checklist")
    st.markdown(
        """
        1. Create a free Neon or Supabase Postgres database.
        2. Copy its pooled Postgres connection string.
        3. Add `DATABASE_URL` as a Streamlit secret and as a GitHub Actions repository secret.
        4. Deploy this folder on Streamlit Community Cloud with `streamlit_app.py` as the main file.
        5. Enable the GitHub Actions workflow to refresh data daily.
        """
    )
    st.warning("This app is research-only. It does not place broker orders.")
