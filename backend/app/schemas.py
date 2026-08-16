"""
backend/app/schemas.py — Pydantic v2 models
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class TelemetryReading(BaseModel):
    satellite_id: str
    timestamp: str
    battery_voltage: float = Field(..., description="Volts")
    temperature_celsius: float
    signal_strength_dbm: float
    cpu_usage_percent: float
    memory_usage_percent: float
    solar_panel_voltage: float = Field(..., description="Volts")
    attitude_roll_deg: float = 0.0
    attitude_pitch_deg: float = 0.0
    attitude_yaw_deg: float = 0.0
    altitude_km: float = 550.0


class AnomalyAlert(BaseModel):
    satellite_id: str
    timestamp: str
    severity: str          # "normal" | "warning" | "critical"
    status: str            # "ok" | "anomaly_detected"
    anomalies: List[str]   # human-readable anomaly names
    raw_values: dict       # snapshot of the telemetry that triggered this
    explanation: Optional[str] = None   # LLM-generated text (may be None)


class AnalyzeResponse(AnomalyAlert):
    """What /analyze returns to the sender."""
    pass
