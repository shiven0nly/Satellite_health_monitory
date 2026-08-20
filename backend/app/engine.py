"""
backend/engine.py
=================
Deep Learning Telemetry Anomaly Engine with UI-to-Sensor Mapping.

Maps incoming semantic telemetry fields (from the sender UI sliders) 
onto the 21-dimensional sensor array required by the ONNX models.
"""
from __future__ import annotations
import pandas as pd
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path & Asset Resolution
# ---------------------------------------------------------------------------
# Navigate exactly 4 folders up from engine.py to reach the root workspace
BASE_DIR = Path(__file__).resolve().parents[3]
PKG_DIR = BASE_DIR / "satellite_frontend_backend_pkg"

# Load Configuration
CONFIG_PATH = PKG_DIR / "engine_config.json"
try:
    with open(CONFIG_PATH, "r") as f:
        ENGINE_CONFIG = json.load(f)
except Exception as e:
    logger.error(f"Failed to load engine_config.json: {e}")
    ENGINE_CONFIG = {
        "autoencoder": {"sequence_length": 50, "optimal_threshold": 0.025},
        "rul_predictor": {"sequence_length": 30, "max_rul_clip": 125},
        "sensor_features": [f"sensor_{i}" for i in range(1, 22)]
    }

AE_SEQ_LEN = ENGINE_CONFIG["autoencoder"]["sequence_length"]
AE_THRESHOLD = ENGINE_CONFIG["autoencoder"]["optimal_threshold"]
RUL_SEQ_LEN = ENGINE_CONFIG["rul_predictor"]["sequence_length"]
MAX_RUL = ENGINE_CONFIG["rul_predictor"]["max_rul_clip"]
SENSOR_FEATURES = ENGINE_CONFIG["sensor_features"]

MAX_HISTORY = max(AE_SEQ_LEN, RUL_SEQ_LEN)
_history: deque[np.ndarray] = deque(maxlen=MAX_HISTORY)

# ---------------------------------------------------------------------------
# ML Model & Scaler Initialization
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ML Model & Scaler Initialization
# ---------------------------------------------------------------------------
try:
    feature_scaler = joblib.load(PKG_DIR / "scaler_features.pkl")
    target_scaler = joblib.load(PKG_DIR / "scaler_target.pkl")

    ae_session = ort.InferenceSession(str(PKG_DIR / "satellite_autoencoder_v2.onnx"))
    rul_session = ort.InferenceSession(str(PKG_DIR / "prognostic_rul_engine.onnx"))
    
    ae_input_name = ae_session.get_inputs()[0].name
    rul_input_name = rul_session.get_inputs()[0].name

    MODELS_LOADED = True
    logger.info("ONNX Models and Scalers loaded successfully.")

    # --- NEW WARM-UP LOGIC START ---
    # Pre-fill the history deque with normal baseline data so the models run instantly
    baseline_features = np.array([[
        518.67, 642.19, 1587.28, 1405.05, 14.62, 21.61, 554.28, 2387.99,
        9063.06, 1.3, 47.37, 522.21, 2388.02, 8139.4, 8.3809, 0.03,
        391.0, 2388.0, 100.0, 38.95, 23.36
    ]])
    scaled_baseline = feature_scaler.transform(baseline_features)[0]
    for _ in range(MAX_HISTORY):
        _history.append(scaled_baseline)
    logger.info(f"Pre-warmed ML buffer with {MAX_HISTORY} steps. Ready for instant inference!")
    # --- NEW WARM-UP LOGIC END ---

except Exception as e:
    logger.error(f"Failed to load ML assets from {PKG_DIR}. Error: {e}")
    MODELS_LOADED = False


# ---------------------------------------------------------------------------
# UI-to-Sensor Mapping Bridge
# ---------------------------------------------------------------------------
def _map_payload_to_sensors(payload: dict[str, Any]) -> list[float]:
    """
    Translates high-level UI controls/legacy properties into the 21-feature 
    sensor array (sensor_1 to sensor_21) expected by the ONNX models.
    """
    # Extract values from the sender UI payload with sensible baseline defaults
    pitch = float(payload.get("orientation_pitch_deg", 0.0))
    roll = float(payload.get("orientation_roll_deg", 0.0))
    yaw = float(payload.get("orientation_yaw_deg", 0.0))
    pos_err = float(payload.get("nav_position_error_m", 10.0))
    voltage = float(payload.get("power_bus_voltage_v", 29.0))
    current = float(payload.get("power_bus_current_a", 5.0))
    temp = float(payload.get("component_temp_c", 35.0))
    battery = float(payload.get("battery_voltage", 28.0))
    signal = float(payload.get("signal_strength_dbm", -70.0))
    cpu = float(payload.get("cpu_usage_percent", 30.0))
    memory = float(payload.get("memory_usage_percent", 40.0))
    altitude = float(payload.get("altitude_km", 550.0))

    # Construct the 21-feature vector anchored to normal telemetry baselines
    sensors = [
        518.67 + (pitch * 2.0),       # sensor_1: Pitch coupling
        642.19 + (roll * 2.0),        # sensor_2: Roll coupling
        1587.28 + (temp * 0.8),       # sensor_3: Thermal relation
        1405.05 + (current * 12.0),   # sensor_4: Current relation
        14.62,                        # sensor_5
        21.61,                        # sensor_6
        554.28 + (altitude * 0.01),   # sensor_7: Altitude relation
        2387.99 + (voltage * 0.5),    # sensor_8: Voltage relation
        9063.06 + (pos_err * 8.0),    # sensor_9: Navigation error relation
        1.3,                          # sensor_10
        47.37 + (cpu * 0.15),         # sensor_11: CPU load relation
        522.21 + (memory * 0.15),     # sensor_12: Memory load relation
        2388.02,                      # sensor_13
        8139.4 + (battery * 15.0),    # sensor_14: Battery relation
        8.3809,                       # sensor_15
        0.03,                         # sensor_16
        391.0 + (yaw * 2.0),          # sensor_17: Yaw relation
        2388.0,                       # sensor_18
        100.0,                        # sensor_19
        38.95 + (signal * 0.05),      # sensor_20: Signal relation
        23.36                         # sensor_21
    ]
    return sensors
# ---------------------------------------------------------------------------
# Core Detection Logic
# ---------------------------------------------------------------------------
def check_telemetry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Process incoming telemetry payload through the Autoencoder and RUL models.
    """
    flags: list[dict[str, Any]] = []

    if not MODELS_LOADED:
        return flags

    # 1. Map UI variables to the 21 sensor columns
    raw_features = _map_payload_to_sensors(payload)

    # 2. Scale features with DataFrame and append to rolling history buffer
    try:
        input_df = pd.DataFrame([raw_features], columns=SENSOR_FEATURES)
        scaled_telemetry = feature_scaler.transform(input_df)
        _history.append(scaled_telemetry[0])
    except Exception as e:
        logger.error(f"Feature scaling failed: {e}")
        return flags

    # 3. Autoencoder Anomaly Detection (Requires AE_SEQ_LEN steps)
    # 3. Autoencoder Anomaly Detection (Requires AE_SEQ_LEN steps)
    if len(_history) >= AE_SEQ_LEN:
        # EXTRACT ONLY SENSOR 0 (Pitch) FOR THE AUTOENCODER
        ae_input_seq = np.array(list(_history)[-AE_SEQ_LEN:])[:, 0].astype(np.float32)
        ae_input_seq = ae_input_seq.reshape(1, AE_SEQ_LEN, 1)  # Fixed Shape: (1, 50, 1)
        
        try:
            ae_output = ae_session.run(None, {ae_input_name: ae_input_seq})[0]
            mse = float(np.mean(np.square(ae_input_seq - ae_output)))
            
            if mse > AE_THRESHOLD:
                flags.append({
                    "channel": "Autoencoder_Reconstruction_Error",
                    "type": "threshold_breach",
                    "value": round(mse, 4),
                    "limit": round(AE_THRESHOLD, 4),
                    "severity": "critical"
                })
        except Exception as e:
            logger.error(f"Autoencoder inference failed: {e}")

    # 4. RUL Prediction (Requires RUL_SEQ_LEN steps)
    if len(_history) >= RUL_SEQ_LEN:
        rul_input_seq = np.array(list(_history)[-RUL_SEQ_LEN:]).astype(np.float32)
        rul_input_seq = np.expand_dims(rul_input_seq, axis=0)  # Shape: (1, 30, 21)

        try:
            rul_scaled_pred = rul_session.run(None, {rul_input_name: rul_input_seq})[0]
            rul_pred = target_scaler.inverse_transform(rul_scaled_pred)[0][0]
            rul_pred = max(0.0, min(float(rul_pred), MAX_RUL))

            if rul_pred <= 150.0:
                flags.append({
                    "channel": "LSTM_RUL_Predictor",
                    "type": "trending_toward_failure",
                    "value": round(rul_pred, 1),
                    "projected_breach_in_steps": int(rul_pred),
                    "severity": "warning",
                })
        except Exception as e:
            logger.error(f"RUL inference failed: {e}")

    return flags

# ---------------------------------------------------------------------------
# Backward-compatible wrapper used by main.py
# ---------------------------------------------------------------------------
def detect(reading: Any) -> tuple[str, str, list[str]]:
    """
    Thin adapter for main.py to call detect() seamlessly.
    """
    flags = check_telemetry(reading.model_dump())

    if not flags:
        return "ok", "normal", []

    severities = {f["severity"] for f in flags}
    overall = "critical" if "critical" in severities else "warning"

    names: list[str] = []
    for f in flags:
        if f["type"] == "threshold_breach":
            names.append(f"{f['channel']}:breach")
        else:
            names.append(f"{f['channel']}:trending({f.get('projected_breach_in_steps', '?')}steps)")

    return "anomaly_detected", overall, names