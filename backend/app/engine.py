"""
backend/app/engine.py — Rule-based anomaly engine

Implements two layers of detection:
  1. Threshold checks  — instantaneous out-of-band values
  2. Trend detection   — rolling window slope analysis (requires history)
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import List, Tuple

from .schemas import TelemetryReading

# ── Configurable thresholds ───────────────────────────────────────────────────
THRESHOLDS = {
    "battery_voltage":      (22.0, 32.0),   # (min, max) volts
    "temperature_celsius":  (-20.0, 80.0),  # °C
    "signal_strength_dbm":  (-110.0, -30.0),
    "cpu_usage_percent":    (0.0, 90.0),
    "memory_usage_percent": (0.0, 90.0),
    "solar_panel_voltage":  (10.0, 22.0),
    "attitude_roll_deg":    (-15.0, 15.0),
    "attitude_pitch_deg":   (-15.0, 15.0),
    "altitude_km":          (400.0, 700.0),
}

# Rolling history per satellite (last N readings per field)
_HISTORY_LEN = 10
_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=_HISTORY_LEN))
)

TREND_FIELDS = ["battery_voltage", "temperature_celsius", "solar_panel_voltage"]
TREND_SLOPE_WARN = 0.5    # |slope| per reading that triggers warning
TREND_SLOPE_CRIT = 1.5    # |slope| per reading that triggers critical


# ── Internal helpers ──────────────────────────────────────────────────────────

def _linear_slope(values: list[float]) -> float:
    """Least-squares slope of y = values[i]; x = [0,1,2,…]."""
    n = len(values)
    if n < 3:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def _check_thresholds(reading: TelemetryReading) -> List[Tuple[str, str]]:
    """Return list of (field, severity) for any out-of-band value."""
    issues: List[Tuple[str, str]] = []
    for field, (lo, hi) in THRESHOLDS.items():
        val = getattr(reading, field, None)
        if val is None:
            continue
        if val < lo or val > hi:
            # How far outside the band?
            band_width = hi - lo
            deviation = max(lo - val, val - hi)
            sev = "critical" if deviation > 0.2 * band_width else "warning"
            issues.append((field, sev))
    return issues


def _check_trends(satellite_id: str, reading: TelemetryReading) -> List[Tuple[str, str]]:
    """Return list of (field, severity) for rapid-trend anomalies."""
    hist = _history[satellite_id]
    issues: List[Tuple[str, str]] = []
    for field in TREND_FIELDS:
        val = getattr(reading, field, None)
        if val is None:
            continue
        hist[field].append(val)
        if len(hist[field]) >= 3:
            slope = abs(_linear_slope(list(hist[field])))
            if slope >= TREND_SLOPE_CRIT:
                issues.append((f"{field}_trend", "critical"))
            elif slope >= TREND_SLOPE_WARN:
                issues.append((f"{field}_trend", "warning"))
    return issues


# ── Public API ────────────────────────────────────────────────────────────────

def detect(reading: TelemetryReading) -> Tuple[str, str, List[str]]:
    """
    Analyse one telemetry reading.

    Returns
    -------
    (status, severity, anomaly_names)
      status   : "ok" | "anomaly_detected"
      severity : "normal" | "warning" | "critical"
      anomaly_names : list of human-readable anomaly labels
    """
    threshold_issues = _check_thresholds(reading)
    trend_issues = _check_trends(reading.satellite_id, reading)

    all_issues = threshold_issues + trend_issues

    if not all_issues:
        return "ok", "normal", []

    severities = [sev for _, sev in all_issues]
    overall = "critical" if "critical" in severities else "warning"
    names = [field for field, _ in all_issues]
    return "anomaly_detected", overall, names
