"""
sender/app.py — Manual Satellite Telemetry Simulator
=====================================================
Run with:  uv run streamlit run app.py --server.port 8501

Human-operated test harness for the anomaly pipeline.
Provides sliders for all monitored channels, sends a single JSON
snapshot to the backend on demand, and displays colour-coded flag
responses.  Optionally auto-drifts one channel to exercise the
trend-detection layer without real telemetry data.

No persistence — session_state only, resets on browser refresh.
"""

import os
import time

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000/telemetry")

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🛰️ Satellite Telemetry Simulator",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }

    /* ── dark panel ── */
    .panel {
        background: linear-gradient(140deg,#0d1b2a 0%,#1a2744 100%);
        border: 1px solid #2d3f5e;
        border-radius: 14px;
        padding: 1.1rem 1.3rem 1.3rem;
        margin-bottom: 0.8rem;
    }
    .panel-title {
        font-size: 1rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        margin-bottom: 0.6rem;
        text-transform: uppercase;
    }

    /* ── flag cards ── */
    .flag-critical {
        background: #2d0a0a;
        border-left: 4px solid #ef4444;
        border-radius: 8px;
        padding: 0.55rem 0.9rem;
        margin: 0.3rem 0;
        font-size: 0.85rem;
    }
    .flag-warning {
        background: #2d1f08;
        border-left: 4px solid #f59e0b;
        border-radius: 8px;
        padding: 0.55rem 0.9rem;
        margin: 0.3rem 0;
        font-size: 0.85rem;
    }
    .flag-ok {
        background: #0a2d14;
        border-left: 4px solid #22c55e;
        border-radius: 8px;
        padding: 0.65rem 0.9rem;
        margin: 0.3rem 0;
        font-size: 0.9rem;
        font-weight: 600;
    }
    .expl-box {
        background: #111827;
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 0.65rem 0.9rem;
        margin-top: 0.5rem;
        font-size: 0.84rem;
        font-style: italic;
        color: #d1d5db;
    }

    /* ── Send button ── */
    div[data-testid="stButton"] > button {
        background: linear-gradient(135deg,#3b82f6 0%,#6366f1 100%);
        color: white;
        font-weight: 700;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 2rem;
        font-size: 1rem;
        transition: opacity .2s;
    }
    div[data-testid="stButton"] > button:hover { opacity: 0.85; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS: dict = {
    "last_response":  None,   # last raw API response dict
    "drift_active":   False,
    "drift_step":     0,
    # drift seed values (overridden by sliders on each send)
    "drift_pitch":    0.0,
    "drift_roll":     0.0,
    "drift_yaw":      0.0,
    "drift_pos_err":  10.0,
    "drift_voltage":  29.0,
    "drift_current":  5.0,
    "drift_temp":     35.0,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── HTTP helper ───────────────────────────────────────────────────────────────

def post_telemetry(payload: dict) -> dict | None:
    """POST payload to backend.  Returns parsed JSON or None on error."""
    try:
        r = requests.post(BACKEND_URL, json=payload, timeout=8)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(
            f"❌ **Backend unreachable** — cannot connect to `{BACKEND_URL}`.  "
            "Is the backend running?  (`uv run uvicorn app.main:app --port 8000`)"
        )
    except requests.exceptions.Timeout:
        st.error("⏱️ **Request timed out** — backend took > 8 s to respond.")
    except requests.exceptions.HTTPError as exc:
        st.error(f"🔴 **Backend error {exc.response.status_code}** — {exc.response.text[:200]}")
    except Exception as exc:
        st.error(f"❌ **Unexpected error** — {exc}")
    return None


def _build_payload(
    p: float, r: float, y: float,
    pe: float, v: float, a: float, t: float,
) -> dict:
    """Construct the JSON body to POST to the backend."""
    from datetime import datetime, timezone
    return {
        "satellite_id":          "satellite-sim-01",
        "timestamp":             datetime.now(timezone.utc).isoformat(),
        "orientation_pitch_deg": round(p, 3),
        "orientation_roll_deg":  round(r, 3),
        "orientation_yaw_deg":   round(y, 3),
        "nav_position_error_m":  round(pe, 3),
        "power_bus_voltage_v":   round(v, 3),
        "power_bus_current_a":   round(a, 3),
        "component_temp_c":      round(t, 3),
        # legacy fields — engine checks these too; set safe defaults
        "battery_voltage":       28.0,
        "temperature_celsius":   22.0,
        "signal_strength_dbm":   -70.0,
        "cpu_usage_percent":     30.0,
        "memory_usage_percent":  40.0,
        "solar_panel_voltage":   16.0,
        "attitude_roll_deg":     round(r, 3),
        "attitude_pitch_deg":    round(p, 3),
        "attitude_yaw_deg":      round(y, 3),
        "altitude_km":           550.0,
    }


# ── Response renderer ─────────────────────────────────────────────────────────

def _render_response(result: dict) -> None:
    flags       = result.get("flags", [])
    severity    = result.get("severity", "normal")
    explanation = result.get("explanation", "")
    delivery_ok = result.get("delivery_ok", True)

    st.markdown("---")
    st.markdown("#### 📟 Backend Response")

    if not flags:
        st.markdown("<div class='flag-ok'>✅ All systems <b>NOMINAL</b> — no anomalies detected.</div>",
                    unsafe_allow_html=True)
    else:
        for f in flags:
            ftype = f.get("type", "")
            ch    = f.get("channel", "?")
            val   = f.get("value", "?")

            if ftype == "threshold_breach":
                limit   = f.get("limit", "?")
                icon    = "🔴"
                css_cls = "flag-critical"
                detail  = f"value <b>{val}</b> has breached hard limit <b>{limit}</b>"
            else:
                steps   = f.get("projected_breach_in_steps", "?")
                icon    = "🟡"
                css_cls = "flag-warning"
                detail  = f"value <b>{val}</b> — projected breach in <b>~{steps} steps</b>"

            st.markdown(
                f"<div class='{css_cls}'>"
                f"{icon} <b>{ch}</b> &nbsp;|&nbsp; {ftype.replace('_',' ')} &nbsp;|&nbsp; {detail}"
                f"</div>",
                unsafe_allow_html=True,
            )

        if explanation:
            st.markdown(
                f"<div class='expl-box'>💬 <b>CASSANDRA:</b> {explanation}</div>",
                unsafe_allow_html=True,
            )

        if not delivery_ok:
            st.warning(
                "⚠️ Anomaly detected locally — but **alert delivery to receiver failed**.  "
                "Check that the receiver API is running on `:8502`."
            )


# ── Sidebar: drift controls ───────────────────────────────────────────────────
with st.sidebar:
    st.header("🌀 Drift Simulator")
    st.caption("Auto-increment one channel per cycle to trigger the trend detector.")

    drift_on = st.toggle("Enable gradual drift", value=st.session_state.drift_active)
    st.session_state.drift_active = drift_on

    drift_channel = st.selectbox(
        "Channel to drift",
        options=[
            "orientation_pitch_deg",
            "orientation_roll_deg",
            "orientation_yaw_deg",
            "nav_position_error_m",
            "power_bus_voltage_v",
            "power_bus_current_a",
            "component_temp_c",
        ],
    )
    drift_delta = st.slider("Step size per cycle", 0.1, 5.0, 0.5, step=0.1)
    drift_delay = st.slider("Delay between cycles (s)", 1, 10, 3)
    drift_dir   = st.radio("Direction", ["⬆ Increase", "⬇ Decrease"], horizontal=True)

    st.divider()
    st.caption(f"Sending to `{BACKEND_URL}`")


# ── Main header ───────────────────────────────────────────────────────────────
st.title("🛰️ Satellite Telemetry Simulator")
st.caption(
    "Manually control each subsystem channel and fire a telemetry snapshot at the "
    "anomaly engine.  Push sliders **beyond their normal limits** to trigger breach flags."
)

st.markdown("---")

# ── Four subsystem panels ─────────────────────────────────────────────────────
col_a, col_b = st.columns(2, gap="large")
col_c, col_d = st.columns(2, gap="large")

with col_a:
    st.markdown("<div class='panel'><div class='panel-title'>🛰️ Orientation</div></div>",
                unsafe_allow_html=True)
    pitch = st.slider(
        "Pitch (deg)  ·  normal: −5 → +5",
        min_value=-30.0, max_value=30.0, value=0.0, step=0.1,
        key="s_pitch",
        help="Pitch angle. Hard limits ±5°.",
    )
    roll = st.slider(
        "Roll (deg)  ·  normal: −5 → +5",
        min_value=-30.0, max_value=30.0, value=0.0, step=0.1,
        key="s_roll",
        help="Roll angle. Hard limits ±5°.",
    )
    yaw = st.slider(
        "Yaw (deg)  ·  normal: −10 → +10",
        min_value=-45.0, max_value=45.0, value=0.0, step=0.1,
        key="s_yaw",
        help="Yaw angle. Hard limits ±10°.",
    )

with col_b:
    st.markdown("<div class='panel'><div class='panel-title'>📡 Navigation</div></div>",
                unsafe_allow_html=True)
    pos_err = st.slider(
        "Position Error (m)  ·  normal: 0 → 50",
        min_value=0.0, max_value=150.0, value=10.0, step=0.5,
        key="s_pos_err",
        help="Navigation position error. Hard limit 50 m.",
    )
    st.markdown("")   # vertical whitespace to balance panel height with col_a

with col_c:
    st.markdown("<div class='panel'><div class='panel-title'>🔋 Power Bus</div></div>",
                unsafe_allow_html=True)
    voltage = st.slider(
        "Bus Voltage (V)  ·  normal: 26 → 32",
        min_value=18.0, max_value=40.0, value=29.0, step=0.1,
        key="s_voltage",
        help="Power bus voltage. Hard limits 26–32 V.",
    )
    current = st.slider(
        "Bus Current (A)  ·  normal: 0 → 15",
        min_value=0.0, max_value=25.0, value=5.0, step=0.1,
        key="s_current",
        help="Power bus current. Hard limit 15 A.",
    )

with col_d:
    st.markdown("<div class='panel'><div class='panel-title'>🌡️ Thermal</div></div>",
                unsafe_allow_html=True)
    temp = st.slider(
        "Component Temp (°C)  ·  normal: −20 → 85",
        min_value=-40.0, max_value=130.0, value=35.0, step=0.5,
        key="s_temp",
        help="Component temperature. Hard limits −20 to 85 °C.",
    )

st.markdown("---")

# ── Current values summary ────────────────────────────────────────────────────
with st.expander("📋 Current payload preview", expanded=False):
    st.json({
        "satellite_id":        "satellite-sim-01",
        "timestamp":           "(auto-set at send time)",
        "orientation_pitch_deg": pitch,
        "orientation_roll_deg":  roll,
        "orientation_yaw_deg":   yaw,
        "nav_position_error_m":  pos_err,
        "power_bus_voltage_v":   voltage,
        "power_bus_current_a":   current,
        "component_temp_c":      temp,
    })

# ── Send button (manual) ──────────────────────────────────────────────────────
send_col, _ = st.columns([1, 3])
with send_col:
    send_btn = st.button("📡 Send Telemetry Snapshot", use_container_width=True)

response_slot = st.empty()


if send_btn:
    payload = _build_payload(pitch, roll, yaw, pos_err, voltage, current, temp)
    with st.spinner("Sending …"):
        result = post_telemetry(payload)
    if result is not None:
        st.session_state.last_response = result
        with response_slot.container():
            _render_response(result)

elif st.session_state.last_response:
    with response_slot.container():
        _render_response(st.session_state.last_response)


# ── Drift loop (simple, no threading) ────────────────────────────────────────
if drift_on:
    sign = +1 if "Increase" in drift_dir else -1

    # Seed drift channel with current slider value on first activation
    _key_map = {
        "orientation_pitch_deg": pitch,
        "orientation_roll_deg":  roll,
        "orientation_yaw_deg":   yaw,
        "nav_position_error_m":  pos_err,
        "power_bus_voltage_v":   voltage,
        "power_bus_current_a":   current,
        "component_temp_c":      temp,
    }

    # Store per-channel drift value in session_state
    drift_ss_key = f"drift_val_{drift_channel}"
    if drift_ss_key not in st.session_state:
        st.session_state[drift_ss_key] = _key_map[drift_channel]

    current_drift_val = st.session_state[drift_ss_key]

    st.info(
        f"🌀 **Drift active** — `{drift_channel}` = **{current_drift_val:.2f}** "
        f"(step {sign * drift_delta:+.1f} every {drift_delay}s)"
    )

    # Build payload with drifted channel overriding the slider
    drift_payload_base = _build_payload(pitch, roll, yaw, pos_err, voltage, current, temp)
    drift_payload_base[drift_channel] = round(current_drift_val, 3)

    with st.spinner(f"Sending drift cycle {st.session_state.drift_step + 1} …"):
        drift_result = post_telemetry(drift_payload_base)

    if drift_result is not None:
        st.session_state.last_response     = drift_result
        st.session_state.drift_step       += 1
        # Advance the drift value for next cycle
        st.session_state[drift_ss_key]     = current_drift_val + sign * drift_delta
        with response_slot.container():
            _render_response(drift_result)

    time.sleep(drift_delay)
    st.rerun()

else:
    # Reset drift state when toggled off so next enable starts fresh
    drift_ss_key = f"drift_val_{drift_channel}"
    if drift_ss_key in st.session_state:
        del st.session_state[drift_ss_key]
    st.session_state.drift_step = 0
