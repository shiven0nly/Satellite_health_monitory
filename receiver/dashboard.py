"""
receiver/dashboard.py — Satellite Alert Dashboard (Streamlit, port 8503)

Polls receiver API at http://localhost:8502/alerts every few seconds.
Renders alert cards, severity metrics, and handles offline or empty alert states cleanly.
"""
from __future__ import annotations

import os
import time
from typing import Any, List

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8502/alerts")

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

    .metric-container {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
    }

    .alert-card {
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.8rem;
        border-left: 5px solid;
    }
    .alert-critical { background: #2d0a0a; border-color: #ef4444; }
    .alert-warning  { background: #2d1f08; border-color: #f59e0b; }
    .alert-normal   { background: #0a2d14; border-color: #22c55e; }

    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .badge-critical { background: #7f1d1d; color: #fecaca; }
    .badge-warning  { background: #92400e; color: #fde68a; }
    .badge-normal   { background: #166534; color: #bbf7d0; }

    .flag-pill {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 3px 8px;
        font-size: 0.8rem;
        font-family: monospace;
        margin-right: 4px;
        margin-bottom: 4px;
        display: inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def fetch_alerts() -> tuple[List[dict[str, Any]] | None, str | None]:
    try:
        resp = requests.get(API_URL, timeout=4)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.ConnectionError:
        return None, f"Cannot connect to API at {API_URL}. Is receiver/api.py running on port 8502?"
    except Exception as exc:
        return None, f"Error fetching alerts: {exc}"


def render_card(alert: dict[str, Any]) -> str:
    sev = alert.get("severity", "warning").lower()
    badge_cls = "badge-critical" if sev == "critical" else ("badge-warning" if sev == "warning" else "badge-normal")
    card_cls = "alert-critical" if sev == "critical" else ("alert-warning" if sev == "warning" else "alert-normal")

    timestamp = alert.get("timestamp", alert.get("received_at", ""))
    ts_str = timestamp[:19].replace("T", " ") if timestamp else "Unknown time"
    source = alert.get("source", alert.get("satellite_id", "satellite-sim-01"))
    explanation = alert.get("explanation", "")

    # Flag list or legacy anomalies string list
    flags = alert.get("flags", [])
    flag_html = ""
    if flags:
        for f in flags:
            ch = f.get("channel", "?")
            ftype = f.get("type", "")
            val = f.get("value", "")
            if ftype == "threshold_breach":
                limit = f.get("limit", "")
                detail = f"{val} (limit: {limit})"
            else:
                steps = f.get("projected_breach_in_steps", "?")
                detail = f"{val} (~{steps} steps to breach)"
            flag_html += f"<span class='flag-pill'>⚠️ {ch}: {detail}</span>"
    else:
        anoms = alert.get("anomalies", [])
        for a in anoms:
            flag_html += f"<span class='flag-pill'>⚠️ {a}</span>"

    expl_html = f"<p style='margin:0.5rem 0 0;font-style:italic;color:#cbd5e1;font-size:0.9rem;'>💬 {explanation}</p>" if explanation else ""

    return f"""
    <div class='alert-card {card_cls}'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;'>
            <div>
                <span class='badge {badge_cls}'>{sev}</span>
                <strong style='margin-left:0.5rem;'>🛰️ {source}</strong>
            </div>
            <span style='font-size:0.8rem; color:#94a3b8;'>{ts_str}</span>
        </div>
        <div style='margin-bottom:0.4rem;'>{flag_html}</div>
        {expl_html}
    </div>
    """


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    interval = st.slider("Refresh interval (seconds)", min_value=2, max_value=10, value=3)
    if st.button("🔄 Manual Refresh", use_container_width=True):
        st.rerun()

# ── Title & Status Header ─────────────────────────────────────────────────────
st.title("🚨 Satellite Alert Intake Dashboard")

alerts_data, err_msg = fetch_alerts()

if err_msg:
    st.error(f"❌ {err_msg}")
elif alerts_data is None or len(alerts_data) == 0:
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Alerts", 0)
    col2.metric("Critical", 0)
    col3.metric("Warning", 0)
    st.markdown("---")
    st.success("🟢 No alerts received yet — system nominal")
else:
    total_count = len(alerts_data)
    crit_count = sum(1 for a in alerts_data if a.get("severity") == "critical")
    warn_count = sum(1 for a in alerts_data if a.get("severity") == "warning")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Alerts", total_count)
    col2.metric("🔴 Critical", crit_count)
    col3.metric("🟡 Warning", warn_count)

    st.markdown("---")
    st.subheader(f"Recent Alerts ({total_count})")

    cards_html = "".join(render_card(alert) for alert in alerts_data)
    st.markdown(cards_html, unsafe_allow_html=True)

if auto_refresh:
    time.sleep(interval)
    st.rerun()