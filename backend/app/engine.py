"""
backend/app/engine.py
=====================
Satellite telemetry anomaly engine.

Detection strategy
------------------
This module implements **two layers of deterministic, rule-based detection**.
It is NOT a trained machine-learning model and does NOT claim to be one.

Layer 1 — Hard threshold breach
    Each telemetry channel has a documented operational envelope (min/max).
    A reading that falls outside that envelope is flagged immediately as a
    "threshold_breach" at severity="critical".

Layer 2 — Linear trend projection
    For channels with at least 3 historical readings in their rolling window,
    a simple rate-of-change (slope) is computed:

        slope = (newest_value - value_N_steps_ago) / N

    The engine then linearly extrapolates:

        projected_breach_in_steps = distance_to_nearest_limit / |slope|

    If that projection is ≤ TREND_LOOKAHEAD_STEPS (default 5), it raises a
    "trending_toward_failure" flag at severity="warning" — even if the current
    reading is still within bounds.

No scikit-learn, PyTorch, or any external ML library is used.
All logic is pure Python arithmetic.

Public API
----------
    check_telemetry(payload: dict) -> list[dict]
        Core entry point.  Accepts any flat dict of {channel: value} pairs,
        ignores channels not in THRESHOLDS, and returns a (possibly empty)
        list of anomaly flag dicts.

    detect(reading: TelemetryReading) -> tuple[str, str, list[str]]
        Thin backward-compatible wrapper around check_telemetry() used by
        main.py; adapts the TelemetryReading Pydantic model to a plain dict.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Operational envelope per telemetry channel.
# Source: mission-ops specification (hard limits, not statistical guesses).
THRESHOLDS: dict[str, dict[str, float]] = {
    "orientation_pitch_deg":  {"min": -5.0,  "max":  5.0},
    "orientation_roll_deg":   {"min": -5.0,  "max":  5.0},
    "orientation_yaw_deg":    {"min": -10.0, "max": 10.0},
    "nav_position_error_m":   {"min":  0.0,  "max": 50.0},
    "power_bus_voltage_v":    {"min": 26.0,  "max": 32.0},
    "power_bus_current_a":    {"min":  0.0,  "max": 15.0},
    "component_temp_c":       {"min": -20.0, "max": 85.0},
    # Legacy / additional channels kept from v1 so existing sender payloads
    # continue to be checked without any schema change.
    "battery_voltage":        {"min": 22.0,  "max": 32.0},
    "temperature_celsius":    {"min": -20.0, "max": 80.0},
    "signal_strength_dbm":    {"min": -110.0,"max": -30.0},
    "cpu_usage_percent":      {"min":  0.0,  "max": 90.0},
    "memory_usage_percent":   {"min":  0.0,  "max": 90.0},
    "solar_panel_voltage":    {"min": 10.0,  "max": 22.0},
    "attitude_roll_deg":      {"min": -15.0, "max": 15.0},
    "attitude_pitch_deg":     {"min": -15.0, "max": 15.0},
    "altitude_km":            {"min": 400.0, "max": 700.0},
}

# Rolling window length.  Each channel keeps the last HISTORY_LEN readings.
HISTORY_LEN: int = 20

# Minimum readings before trend analysis is attempted (prevents noisy startup
# false-positives when N is so small that any tiny jitter looks like a trend).
MIN_HISTORY_FOR_TREND: int = 3

# How many steps ahead to project when deciding whether to flag a trend.
# Flag if the linear extrapolation breaches a limit within this many steps.
TREND_LOOKAHEAD_STEPS: int = 5

# ---------------------------------------------------------------------------
# In-memory rolling history
# ---------------------------------------------------------------------------
# Keyed by channel name → deque of float values (newest at the right).
# This is module-level state, intentionally simple: no DB, resets on restart.
_history: dict[str, deque[float]] = defaultdict(
    lambda: deque(maxlen=HISTORY_LEN)
)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _rate_of_change(values: list[float]) -> float:
    """
    Compute the average rate of change per step across a window.

    Uses the first-and-last approach (not least-squares) which is cheap,
    adequate for a linear trend signal, and easy to reason about:

        slope = (last - first) / (n - 1)

    Returns 0.0 if fewer than 2 values are provided (guarded by caller).
    """
    n = len(values)
    if n < 2:
        return 0.0
    return (values[-1] - values[0]) / (n - 1)


def _steps_to_breach(
    current_value: float,
    slope: float,
    lo: float,
    hi: float,
) -> int | None:
    """
    Given a current value and a per-step slope, return how many steps until
    the linear extrapolation exits [lo, hi], or None if it never will at
    this rate (slope is zero or pointing toward the safe interior).

    Returns an integer ≥ 1, or None.
    """
    if slope == 0.0:
        return None

    steps: list[int] = []

    if slope > 0:
        # Trending upward — check against the upper limit.
        distance = hi - current_value
        if distance > 0:
            steps.append(int(distance / slope))  # floor → conservative
    elif slope < 0:
        # Trending downward — check against the lower limit.
        distance = current_value - lo
        if distance > 0:
            steps.append(int(distance / (-slope)))

    return min(steps) if steps else None


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------

def _check_threshold(channel: str, value: float) -> dict[str, Any] | None:
    """
    Compare a single channel value against its hard limits.

    Returns a flag dict on breach, or None if the value is in-range.
    """
    spec = THRESHOLDS.get(channel)
    if spec is None:
        return None  # Unknown channel — not our concern.

    lo, hi = spec["min"], spec["max"]

    if lo <= value <= hi:
        return None  # Within bounds.

    limit = lo if value < lo else hi
    return {
        "channel": channel,
        "type": "threshold_breach",
        "value": value,
        "limit": limit,
        "severity": "critical",
    }


def _check_trend(channel: str, value: float) -> dict[str, Any] | None:
    """
    Append *value* to the channel's rolling history, then check whether the
    linear trend projects a limit breach within TREND_LOOKAHEAD_STEPS.

    Returns a flag dict if a worrying trend is detected, or None otherwise.

    Note: history is updated unconditionally so the window always stays fresh,
    even for channels that are currently in hard-breach (double flagging is
    fine — the threshold flag takes priority in UI presentation).
    """
    spec = THRESHOLDS.get(channel)
    if spec is None:
        return None

    _history[channel].append(value)
    window = list(_history[channel])

    if len(window) < MIN_HISTORY_FOR_TREND:
        return None  # Not enough history yet — skip to avoid false positives.

    lo, hi = spec["min"], spec["max"]
    slope = _rate_of_change(window)

    steps = _steps_to_breach(value, slope, lo, hi)

    if steps is None or steps > TREND_LOOKAHEAD_STEPS or steps < 1:
        return None

    # Only flag this as a *trend warning* if the value is currently in-range.
    # If it's already breached, the threshold check handles it.
    if not (lo <= value <= hi):
        return None

    return {
        "channel": channel,
        "type": "trending_toward_failure",
        "value": value,
        "projected_breach_in_steps": steps,
        "severity": "warning",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_telemetry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Analyse a flat telemetry payload dict and return all anomaly flags found.

    Parameters
    ----------
    payload : dict
        Any flat ``{channel_name: numeric_value}`` mapping.  Non-numeric
        values and channels absent from THRESHOLDS are silently ignored.

    Returns
    -------
    list[dict]
        A list of anomaly flag dicts.  Empty list means everything is nominal.

        Each flag has the shape:

        Threshold breach::

            {
                "channel":  str,
                "type":     "threshold_breach",
                "value":    float,
                "limit":    float,      # the exact limit that was violated
                "severity": "critical",
            }

        Trend toward failure::

            {
                "channel":                  str,
                "type":                     "trending_toward_failure",
                "value":                    float,
                "projected_breach_in_steps": int,
                "severity":                 "warning",
            }

    Algorithm
    ---------
    For each channel present in both *payload* and THRESHOLDS:

    1. **Hard breach** — if ``value < min`` or ``value > max``, emit a
       ``threshold_breach`` flag immediately.
    2. **Trend projection** — append the value to a rolling deque of length
       ``HISTORY_LEN``.  If at least ``MIN_HISTORY_FOR_TREND`` readings exist,
       compute the average per-step rate-of-change and linearly project forward.
       If the projection exits the envelope within ``TREND_LOOKAHEAD_STEPS``
       steps *and* the current value is still in-range, emit a
       ``trending_toward_failure`` flag.

    This is purely deterministic threshold + slope arithmetic.
    It is NOT a trained machine-learning model.
    """
    flags: list[dict[str, Any]] = []

    for channel, raw_value in payload.items():
        # Skip non-numeric values (e.g. satellite_id, timestamp strings).
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        # Layer 1: hard threshold breach.
        threshold_flag = _check_threshold(channel, value)
        if threshold_flag:
            flags.append(threshold_flag)

        # Layer 2: trend toward future breach.
        # History is updated inside _check_trend regardless of breach status.
        trend_flag = _check_trend(channel, value)
        if trend_flag:
            flags.append(trend_flag)

    return flags


# ---------------------------------------------------------------------------
# Backward-compatible wrapper used by main.py
# ---------------------------------------------------------------------------

def detect(reading: "TelemetryReading") -> tuple[str, str, list[str]]:  # type: ignore[name-defined]
    """
    Thin adapter so ``main.py`` can keep calling ``detect(reading)`` without
    changes while the core logic lives in ``check_telemetry``.

    Parameters
    ----------
    reading : TelemetryReading
        A validated Pydantic model instance.

    Returns
    -------
    (status, severity, anomaly_names)
        status        : "ok" | "anomaly_detected"
        severity      : "normal" | "warning" | "critical"
        anomaly_names : list of channel / flag-type strings
    """
    flags = check_telemetry(reading.model_dump())

    if not flags:
        return "ok", "normal", []

    severities = {f["severity"] for f in flags}
    overall = "critical" if "critical" in severities else "warning"

    # Build a human-readable label for each flag.
    names: list[str] = []
    for f in flags:
        if f["type"] == "threshold_breach":
            names.append(f"{f['channel']}:breach")
        else:
            names.append(f"{f['channel']}:trending({f['projected_breach_in_steps']}steps)")

    return "anomaly_detected", overall, names
