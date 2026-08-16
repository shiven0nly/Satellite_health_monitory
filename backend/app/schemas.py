"""
backend/app/schemas.py — Pydantic v2 models

TelemetryReading now carries all channels that engine.THRESHOLDS covers,
including the newly specified subsystem channels (orientation, navigation,
power bus, component temperature) alongside the original channels.
All new fields have safe defaults so existing senders (which don't send them)
continue to work without change.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TelemetryReading(BaseModel):
    # ── Identity ───────────────────────────────────────────────────────────
    satellite_id: str
    timestamp: str

    # ── Attitude / Orientation ─────────────────────────────────────────────
    orientation_pitch_deg: float = Field(0.0, description="Pitch angle, deg  [-5, 5]")
    orientation_roll_deg:  float = Field(0.0, description="Roll angle, deg   [-5, 5]")
    orientation_yaw_deg:   float = Field(0.0, description="Yaw angle, deg   [-10, 10]")

    # ── Navigation ─────────────────────────────────────────────────────────
    nav_position_error_m: float = Field(0.0, description="Position error, m  [0, 50]")

    # ── Power subsystem ────────────────────────────────────────────────────
    power_bus_voltage_v: float = Field(29.0, description="Bus voltage, V    [26, 32]")
    power_bus_current_a: float = Field(5.0,  description="Bus current, A    [0, 15]")

    # ── Thermal ────────────────────────────────────────────────────────────
    component_temp_c: float = Field(25.0, description="Component temp, °C  [-20, 85]")

    # ── Legacy channels (kept for backward compat with original sender) ────
    battery_voltage:      float = Field(28.0, description="Volts  [22, 32]")
    temperature_celsius:  float = Field(22.0, description="°C     [-20, 80]")
    signal_strength_dbm:  float = Field(-70.0, description="dBm   [-110, -30]")
    cpu_usage_percent:    float = Field(30.0, description="%      [0, 90]")
    memory_usage_percent: float = Field(40.0, description="%      [0, 90]")
    solar_panel_voltage:  float = Field(16.0, description="Volts  [10, 22]")
    attitude_roll_deg:    float = Field(0.0,  description="deg    [-15, 15]")
    attitude_pitch_deg:   float = Field(0.0,  description="deg    [-15, 15]")
    attitude_yaw_deg:     float = Field(0.0,  description="deg — not range-checked")
    altitude_km:          float = Field(550.0, description="km    [400, 700]")


class AnomalyFlag(BaseModel):
    """A single anomaly flag as returned by engine.check_telemetry()."""
    channel:   str
    type:      str        # "threshold_breach" | "trending_toward_failure"
    value:     float
    severity:  str        # "critical" | "warning"
    # Present only on threshold_breach:
    limit:     Optional[float] = None
    # Present only on trending_toward_failure:
    projected_breach_in_steps: Optional[int] = None


class AnomalyAlert(BaseModel):
    satellite_id: str
    timestamp:    str
    severity:     str           # "normal" | "warning" | "critical"
    status:       str           # "ok" | "anomaly_detected"
    anomalies:    List[str]     # short human-readable labels
    flags:        List[AnomalyFlag] = []   # full structured flag detail
    raw_values:   dict          # snapshot of the telemetry that triggered this
    explanation:  Optional[str] = None    # LLM-generated text (may be None)


class AnalyzeResponse(AnomalyAlert):
    """What /analyze returns to the sender."""
    pass
