"""
sender/app.py — Satellite Telemetry Simulator (Streamlit, port 8501)

Generates synthetic satellite telemetry readings and POSTs them to the
backend anomaly engine at :8000/analyze.  The UI lets the operator
pick any satellite, tune thresholds, fire single or continuous bursts,
and watch coloured live feedback.
"""

import time
import random
import math
import requests
import streamlit as st
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000/analyze"
SATELLITES = ["SAT-ALPHA", "SAT-BETA", "SAT-GAMMA", "SAT-DELTA", "SAT-EPSILON"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _sine_drift(base: float, amp: float, t: float, period: float = 60.0) -> float:
    return base + amp * math.sin(2 * math.pi * t / period)


def generate_telemetry(satellite_id: str, inject_anomaly: bool = False) -> dict:
    t = time.time() % 3600
    payload = {
        "satellite_id": satellite_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "battery_voltage": round(_sine_drift(28.0, 2.5, t, 120), 3),
        "temperature_celsius": round(_sine_drift(22.0, 15.0, t, 90), 2),
        "signal_strength_dbm": round(random.uniform(-90, -50), 1),
        "cpu_usage_percent": round(random.uniform(5, 60), 1),
        "memory_usage_percent": round(random.uniform(20, 70), 1),
        "solar_panel_voltage": round(_sine_drift(16.0, 4.0, t, 150), 3),
        "attitude_roll_deg": round(random.gauss(0, 0.5), 3),
        "attitude_pitch_deg": round(random.gauss(0, 0.5), 3),
        "attitude_yaw_deg": round(random.gauss(0, 0.5), 3),
        "altitude_km": round(550 + random.gauss(0, 2), 2),
    }
    if inject_anomaly:
        anomaly_type = random.choice(["power", "thermal", "attitude", "signal"])
        if anomaly_type == "power":
            payload["battery_voltage"] = round(random.uniform(18.0, 20.0), 3)
            payload["solar_panel_voltage"] = round(random.uniform(5.0, 8.0), 3)
        elif anomaly_type == "thermal":
            payload["temperature_celsius"] = round(random.uniform(85, 120), 2)
        elif anomaly_type == "attitude":
            payload["attitude_roll_deg"] = round(random.uniform(20, 45), 3)
            payload["attitude_pitch_deg"] = round(random.uniform(20, 45), 3)
        elif anomaly_type == "signal":
            payload["signal_strength_dbm"] = round(random.uniform(-120, -100), 1)
    return payload


def post_telemetry(payload: dict) -> dict | None:
    try:
        resp = requests.post(BACKEND_URL, json=payload, timeout=8)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach backend at :8000 — is it running?"}
    except requests.exceptions.Timeout:
        return {"error": "Backend timed out (>8 s)"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Streamlit UI ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🛰️ Satellite Telemetry Sender",
    page_icon="🛰️",
    layout="wide",
)

# CSS polish
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .metric-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.5rem;
    }
    .status-ok   { color: #22c55e; font-weight: 700; }
    .status-warn { color: #f59e0b; font-weight: 700; }
    .status-crit { color: #ef4444; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛰️ Satellite Telemetry Sender")
st.caption("Simulates real-time satellite health data and forwards it to the anomaly-detection backend.")

# Sidebar controls
with st.sidebar:
    st.header("⚙️ Mission Control")
    satellite = st.selectbox("Satellite", SATELLITES)
    inject_anomaly = st.checkbox("🔴 Inject anomaly", value=False)
    interval_sec = st.slider("Burst interval (s)", 1, 10, 3)
    burst_count = st.number_input("Readings per burst", 1, 20, 1, step=1)
    st.divider()
    st.info(f"Backend → `{BACKEND_URL}`")

col_left, col_right = st.columns([1, 1])

with col_left:
    single_btn = st.button("📡 Send Single Reading", use_container_width=True)

with col_right:
    continuous_btn = st.button("🔄 Start Continuous Burst", use_container_width=True)

st.divider()

payload_placeholder = st.empty()
response_placeholder = st.empty()
history_placeholder = st.empty()

if "history" not in st.session_state:
    st.session_state.history = []


def _render_response(result: dict):
    if "error" in result:
        response_placeholder.error(f"❌ {result['error']}")
        return
    status = result.get("status", "unknown")
    sev = result.get("severity", "normal")
    color_cls = "status-ok" if sev == "normal" else ("status-warn" if sev == "warning" else "status-crit")
    html = f"""
    <div class='metric-card'>
      <b>Backend response</b><br/>
      Status: <span class='{color_cls}'>{status.upper()}</span> &nbsp;|&nbsp;
      Severity: <span class='{color_cls}'>{sev.upper()}</span><br/>
      { f"<br/><i>{result.get('explanation','')}</i>" if result.get('explanation') else '' }
    </div>
    """
    response_placeholder.markdown(html, unsafe_allow_html=True)


def _send_and_display(n: int = 1):
    for _ in range(n):
        data = generate_telemetry(satellite, inject_anomaly)
        payload_placeholder.json(data)
        result = post_telemetry(data)
        if result:
            _render_response(result)
            st.session_state.history.insert(
                0,
                {
                    "time": data["timestamp"],
                    "satellite": satellite,
                    "severity": result.get("severity", "?"),
                    "anomalies": result.get("anomalies", []),
                },
            )
            st.session_state.history = st.session_state.history[:50]
        time.sleep(0.1)


if single_btn:
    _send_and_display(int(burst_count))

if continuous_btn:
    stop_btn = st.button("⏹️ Stop")
    iterations = 0
    while not stop_btn:
        _send_and_display(int(burst_count))
        iterations += 1
        status_msg = st.empty()
        status_msg.info(f"Burst #{iterations} sent — sleeping {interval_sec}s …")
        time.sleep(interval_sec)

# History table
if st.session_state.history:
    st.subheader("📋 Recent Transmissions")
    import pandas as pd
    df = pd.DataFrame(st.session_state.history)
    df["anomalies"] = df["anomalies"].apply(lambda x: ", ".join(x) if x else "—")
    st.dataframe(df, use_container_width=True)
