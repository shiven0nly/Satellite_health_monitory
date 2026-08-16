"""
sender/app.py — Satellite Telemetry Simulator (Streamlit, port 8501)

Generates synthetic satellite telemetry readings and POSTs them to the
backend anomaly engine at :8000/analyze.

Channels emitted cover all thresholds defined in backend/app/engine.py:
  orientation_pitch_deg, orientation_roll_deg, orientation_yaw_deg
  nav_position_error_m
  power_bus_voltage_v, power_bus_current_a
  component_temp_c
  (+ legacy channels for backward compat)

The UI lets the operator pick any satellite, choose an anomaly subsystem
to inject, fire single or continuous bursts, and watch colour-coded
live feedback.
"""

import math
import random
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000/telemetry"
SATELLITES   = ["SAT-ALPHA", "SAT-BETA", "SAT-GAMMA", "SAT-DELTA", "SAT-EPSILON"]

ANOMALY_MODES = [
    "None",
    "Power Bus (voltage drop)",
    "Orientation (pitch/roll/yaw spike)",
    "Navigation (position error)",
    "Thermal (component overtemp)",
    "Signal (weak downlink)",
    "Random subsystem",
]


# ── Telemetry generation ──────────────────────────────────────────────────────

def _sine(base: float, amp: float, t: float, period: float) -> float:
    return base + amp * math.sin(2 * math.pi * t / period)


def generate_telemetry(satellite_id: str, anomaly_mode: str = "None") -> dict:
    t = time.time() % 3600

    payload: dict = {
        # Identity
        "satellite_id": satellite_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),

        # ── New canonical channels ────────────────────────────────────────
        # Orientation  [limits: pitch/roll ±5°, yaw ±10°]
        "orientation_pitch_deg":  round(random.gauss(0.0, 0.8), 3),
        "orientation_roll_deg":   round(random.gauss(0.0, 0.8), 3),
        "orientation_yaw_deg":    round(random.gauss(0.0, 1.5), 3),

        # Navigation   [limit: 0–50 m]
        "nav_position_error_m":   round(abs(random.gauss(10.0, 4.0)), 2),

        # Power bus    [voltage 26–32 V, current 0–15 A]
        "power_bus_voltage_v":    round(_sine(29.0, 1.5, t, 180), 3),
        "power_bus_current_a":    round(abs(random.gauss(7.0, 1.5)), 2),

        # Thermal      [limit: -20–85 °C]
        "component_temp_c":       round(_sine(35.0, 12.0, t, 200), 2),

        # ── Legacy channels (kept for backward compat) ────────────────────
        "battery_voltage":        round(_sine(28.0, 2.5, t, 120), 3),
        "temperature_celsius":    round(_sine(22.0, 10.0, t, 90), 2),
        "signal_strength_dbm":    round(random.uniform(-90, -55), 1),
        "cpu_usage_percent":      round(random.uniform(5, 55), 1),
        "memory_usage_percent":   round(random.uniform(20, 65), 1),
        "solar_panel_voltage":    round(_sine(16.0, 3.5, t, 150), 3),
        "attitude_roll_deg":      round(random.gauss(0.0, 0.4), 3),
        "attitude_pitch_deg":     round(random.gauss(0.0, 0.4), 3),
        "attitude_yaw_deg":       round(random.gauss(0.0, 0.4), 3),
        "altitude_km":            round(550 + random.gauss(0, 1.5), 2),
    }

    # ── Anomaly injection ─────────────────────────────────────────────────────
    effective_mode = anomaly_mode
    if anomaly_mode == "Random subsystem":
        effective_mode = random.choice([m for m in ANOMALY_MODES if m not in ("None", "Random subsystem")])

    if effective_mode == "Power Bus (voltage drop)":
        # Drift voltage down toward the 26 V floor — will trigger trending then breach
        payload["power_bus_voltage_v"] = round(random.uniform(24.0, 26.5), 3)
        payload["power_bus_current_a"] = round(random.uniform(13.0, 16.0), 2)  # also high

    elif effective_mode == "Orientation (pitch/roll/yaw spike)":
        payload["orientation_pitch_deg"] = round(random.uniform(6.0, 12.0) * random.choice([-1, 1]), 3)
        payload["orientation_roll_deg"]  = round(random.uniform(6.0, 12.0) * random.choice([-1, 1]), 3)
        payload["orientation_yaw_deg"]   = round(random.uniform(11.0, 25.0) * random.choice([-1, 1]), 3)

    elif effective_mode == "Navigation (position error)":
        payload["nav_position_error_m"] = round(random.uniform(55.0, 120.0), 2)

    elif effective_mode == "Thermal (component overtemp)":
        payload["component_temp_c"] = round(random.uniform(86.0, 130.0), 2)

    elif effective_mode == "Signal (weak downlink)":
        payload["signal_strength_dbm"] = round(random.uniform(-125, -112), 1)

    return payload


# ── HTTP helper ───────────────────────────────────────────────────────────────

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


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🛰️ Satellite Telemetry Sender",
    page_icon="🛰️",
    layout="wide",
)

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
    .flag-breach   { color: #ef4444; font-weight: 600; }
    .flag-trend    { color: #f59e0b; font-weight: 600; }
    .status-ok     { color: #22c55e; font-weight: 700; }
    .status-warn   { color: #f59e0b; font-weight: 700; }
    .status-crit   { color: #ef4444; font-weight: 700; }

    .channel-table th { background: #1e293b; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛰️ Satellite Telemetry Sender")
st.caption(
    "Simulates satellite health telemetry across **orientation, navigation, power, "
    "thermal** and legacy subsystems, then forwards each reading to the anomaly engine."
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Mission Control")
    satellite     = st.selectbox("Satellite", SATELLITES)
    anomaly_mode  = st.selectbox("Anomaly injection", ANOMALY_MODES)
    interval_sec  = st.slider("Burst interval (s)", 1, 10, 3)
    burst_count   = st.number_input("Readings per burst", 1, 20, 1, step=1)
    st.divider()
    st.info(f"Backend → `{BACKEND_URL}`")

col_left, col_right = st.columns(2)
with col_left:
    single_btn     = st.button("📡 Send Single Reading",    use_container_width=True)
with col_right:
    continuous_btn = st.button("🔄 Start Continuous Burst", use_container_width=True)

st.divider()

payload_slot  = st.empty()
response_slot = st.empty()

if "history" not in st.session_state:
    st.session_state.history = []


# ── Response renderer ─────────────────────────────────────────────────────────

def _render_response(result: dict) -> None:
    if "error" in result:
        response_slot.error(f"❌ {result['error']}")
        return

    sev          = result.get("severity", "normal")
    status       = result.get("status", "ok")
    delivery_ok  = result.get("delivery_ok", True)
    css          = "status-ok" if sev == "normal" else ("status-warn" if sev == "warning" else "status-crit")
    flags        = result.get("flags", [])

    # Build flag detail HTML
    flag_html = ""
    for f in flags:
        cls = "flag-breach" if f["type"] == "threshold_breach" else "flag-trend"
        if f["type"] == "threshold_breach":
            detail = f"value={f['value']}  limit={f['limit']}"
        else:
            detail = f"value={f['value']}  ~{f.get('projected_breach_in_steps','?')} steps to breach"
        flag_html += f"<li><span class='{cls}'>{f['channel']}</span> — {f['type']}  ({detail})</li>"

    flag_section = f"<ul style='margin:0.4rem 0 0;font-size:0.82rem;'>{flag_html}</ul>" if flag_html else ""
    expl         = result.get("explanation", "")
    expl_section = f"<p style='margin:0.5rem 0 0;font-size:0.85rem;opacity:0.85;'><i>💬 {expl}</i></p>" if expl else ""

    # Delivery warning banner (receiver was down)
    delivery_html = ""
    if not delivery_ok and flags:
        delivery_html = (
            "<p style='margin:0.4rem 0 0;color:#f59e0b;font-size:0.8rem;'>⚠️ Anomaly detected locally, "
            "but alert delivery to receiver failed — check :8502 is running.</p>"
        )

    html = f"""
    <div class='metric-card'>
      <b>Backend response</b>&nbsp;&nbsp;
      <span class='{css}'>● {status.upper()}</span>&nbsp;&nbsp;
      Severity: <span class='{css}'>{sev.upper()}</span>
      {flag_section}
      {expl_section}
      {delivery_html}
    </div>
    """
    response_slot.markdown(html, unsafe_allow_html=True)


# ── Send helpers ──────────────────────────────────────────────────────────────

def _send_and_display(n: int = 1) -> None:
    for _ in range(n):
        data   = generate_telemetry(satellite, anomaly_mode)
        payload_slot.json(data)
        result = post_telemetry(data)
        if result:
            _render_response(result)
            flags = result.get("flags", [])
            st.session_state.history.insert(
                0,
                {
                    "time":             data["timestamp"][:19].replace("T", " "),
                    "satellite":        satellite,
                    "severity":         result.get("severity", "?"),
                    "flags":            len(flags),
                    "channels":         ", ".join(f["channel"] for f in flags) or "—",
                    "anomaly_injected": anomaly_mode if anomaly_mode != "None" else "—",
                    "delivered":        "✅" if result.get("delivery_ok", True) else "⚠️ failed",
                },
            )
            st.session_state.history = st.session_state.history[:60]
        time.sleep(0.1)


# ── Button handlers ───────────────────────────────────────────────────────────

if single_btn:
    _send_and_display(int(burst_count))

if continuous_btn:
    stop_slot = st.empty()
    stop_btn  = stop_slot.button("⏹️ Stop")
    iteration = 0
    while not stop_btn:
        _send_and_display(int(burst_count))
        iteration += 1
        for remaining in range(interval_sec, 0, -1):
            stop_slot.button(f"⏹️ Stop  ({remaining}s)", key=f"stop_{iteration}_{remaining}")
            time.sleep(1)

# ── History table ─────────────────────────────────────────────────────────────

if st.session_state.history:
    st.subheader("📋 Recent Transmissions")

    df = pd.DataFrame(st.session_state.history)

    # Colour severity column
    def _colour(val: str) -> str:
        return {
            "critical": "background-color:#7f1d1d;color:#fecaca",
            "warning":  "background-color:#78350f;color:#fde68a",
            "normal":   "background-color:#14532d;color:#bbf7d0",
        }.get(val, "")

    styled = df.style.applymap(_colour, subset=["severity"])
    st.dataframe(styled, use_container_width=True)
