"""
receiver/dashboard.py — Alert Dashboard (Streamlit, port 8503)

Polls its companion FastAPI service at :8502/alerts every N seconds and
renders a live, colour-coded alert feed with charts and severity badges.
"""
from __future__ import annotations

import time
from collections import Counter

import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8502"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🚨 Satellite Alert Dashboard",
    page_icon="🚨",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .alert-card {
        border-radius: 10px;
        padding: 0.9rem 1.2rem;
        margin-bottom: 0.6rem;
        border-left: 5px solid;
    }
    .alert-normal   { background: #0f2914; border-color: #22c55e; }
    .alert-warning  { background: #2d1f08; border-color: #f59e0b; }
    .alert-critical { background: #2d0a0a; border-color: #ef4444; animation: pulse 1s infinite; }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.75; }
    }

    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
    }
    .badge-normal   { background: #166534; color: #bbf7d0; }
    .badge-warning  { background: #92400e; color: #fde68a; }
    .badge-critical { background: #7f1d1d; color: #fecaca; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_alerts(limit: int = 100) -> list[dict]:
    try:
        r = requests.get(f"{API_BASE}/alerts", params={"limit": limit}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def fetch_stats() -> dict:
    try:
        r = requests.get(f"{API_BASE}/alerts/stats", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def clear_alerts():
    try:
        requests.delete(f"{API_BASE}/alerts", timeout=5)
    except Exception:
        pass


def _badge(sev: str) -> str:
    return f"<span class='badge badge-{sev}'>{sev.upper()}</span>"


def _alert_card(alert: dict) -> str:
    sev = alert.get("severity", "normal")
    sat = alert.get("satellite_id", "?")
    ts = alert.get("timestamp", "")[:19].replace("T", " ")
    anomalies = ", ".join(alert.get("anomalies", [])) or "—"
    expl = alert.get("explanation") or ""
    expl_html = f"<p style='margin:0.4rem 0 0;font-size:0.85rem;opacity:0.85;'><i>{expl}</i></p>" if expl else ""
    return f"""
    <div class='alert-card alert-{sev}'>
      {_badge(sev)}&nbsp;&nbsp;<b>{sat}</b>&nbsp;<span style='opacity:0.6;font-size:0.8rem;'>{ts}</span>
      <p style='margin:0.3rem 0 0;'>Anomalies: <code>{anomalies}</code></p>
      {expl_html}
    </div>
    """


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔧 Dashboard Controls")
    refresh_sec = st.slider("Auto-refresh every (s)", 2, 30, 5)
    display_limit = st.slider("Alerts to display", 10, 200, 50, step=10)
    if st.button("🗑️ Clear all alerts", use_container_width=True):
        clear_alerts()
        st.success("Alerts cleared.")
    st.divider()
    st.caption(f"API → `{API_BASE}`")

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🚨 Satellite Alert Dashboard")
st.caption("Live feed of anomaly alerts received from the backend anomaly engine.")

# ── Live countdown placeholder ────────────────────────────────────────────────
countdown_slot = st.empty()

# ── Main content ──────────────────────────────────────────────────────────────
stats_row = st.columns(4)
chart_col, feed_col = st.columns([1, 2])

while True:
    alerts = fetch_alerts(display_limit)
    stats = fetch_stats()

    total = stats.get("total", len(alerts))
    sc = stats.get("severity_counts", {})
    n_crit = sc.get("critical", 0)
    n_warn = sc.get("warning", 0)
    n_norm = sc.get("normal", 0)

    with stats_row[0]:
        st.metric("📡 Total Alerts", total)
    with stats_row[1]:
        st.metric("🔴 Critical", n_crit, delta=None)
    with stats_row[2]:
        st.metric("🟡 Warning", n_warn)
    with stats_row[3]:
        st.metric("🟢 Normal", n_norm)

    # Satellite frequency chart
    with chart_col:
        st.subheader("📊 Alerts by Satellite")
        if alerts:
            sat_counts = Counter(a["satellite_id"] for a in alerts)
            df_chart = pd.DataFrame(sat_counts.items(), columns=["Satellite", "Count"])
            df_chart = df_chart.sort_values("Count", ascending=False)
            st.bar_chart(df_chart.set_index("Satellite"))
        else:
            st.info("No alerts yet — waiting for data …")

    # Alert feed
    with feed_col:
        st.subheader("📋 Alert Feed")
        if alerts:
            feed_html = "".join(_alert_card(a) for a in alerts)
            st.markdown(feed_html, unsafe_allow_html=True)
        else:
            st.info("🟢 All systems nominal — no alerts received.")

    # Countdown
    for remaining in range(refresh_sec, 0, -1):
        countdown_slot.caption(f"⏱ Refreshing in {remaining}s …")
        time.sleep(1)
    countdown_slot.caption("🔄 Refreshing …")
