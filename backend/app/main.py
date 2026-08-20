"""
backend/app/main.py — Satellite Anomaly Engine  (port 8000)
============================================================

Endpoints
---------
POST /telemetry    Primary ingest — runs detection, calls Groq, forwards to receiver.
POST /analyze      Legacy alias for /telemetry (same behaviour, kept for compat).
GET  /health       Liveness probe.
GET  /stats        In-memory counters.
GET  /recent       Last 100 alerts (newest first).

Data flow for POST /telemetry
------------------------------

  Sender
    │  POST /telemetry  {all channel readings}
    ▼
  engine.check_telemetry(payload)
    │  → list[flag_dict]   (empty → 200 "ok", no forwarding)
    ▼  (if flags non-empty)
  llm_service.explain_alert(flags)
    │  → explanation: str  (always succeeds — template fallback if Groq down)
    ▼
  _forward_alert(alert_dict)        ← fire-and-forget, 5 s timeout
    │  POST RECEIVER_URL            ← if unreachable: log + set delivery_ok=False
    ▼
  JSON 200 to sender                ← always returned, even if receiver was down
  {
    "timestamp":    ...,
    "flags":        [...],
    "explanation":  "...",
    "source":       "satellite-sim-01",
    "delivery_ok":  true | false,   ← sender can show ⚠️ if False
    "severity":     "normal|warning|critical",
    "status":       "ok|anomaly_detected"
  }

Failure contract
----------------
- Groq unreachable  → explanation is a template string; response is still 200.
- Receiver down     → delivery_ok=False in response; log warning; still 200.
- Neither failure crashes the /telemetry handler.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .engine import check_telemetry
from .llm_service import explain_alert
from .schemas import AnomalyFlag, TelemetryReading

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

RECEIVER_URL: str = os.getenv("RECEIVER_URL", "http://localhost:8502/receive_alert")
SOURCE_ID:    str = os.getenv("SOURCE_ID",    "satellite-sim-01")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Satellite Anomaly Engine",
    description=(
        "Threshold + linear-trend anomaly detection for satellite telemetry. "
        "NOT a trained ML model — see engine.py. "
        "LLM explanation layer uses Groq (CASSANDRA persona)."
    ),
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory state ───────────────────────────────────────────────────────────

_stats: dict[str, int] = defaultdict(int)
_recent_alerts: deque[dict[str, Any]] = deque(maxlen=100)


# ── Response model ────────────────────────────────────────────────────────────

class TelemetryResponse(BaseModel):
    """Returned by POST /telemetry (and /analyze) to the sender."""
    timestamp:   str
    source:      str
    status:      str                # "ok" | "anomaly_detected"
    severity:    str                # "normal" | "warning" | "critical"
    flags:       list[AnomalyFlag]
    anomalies:   list[str]         # short labels, mirrors flags for quick scan
    explanation: str               # always populated (template if Groq down)
    delivery_ok: bool              # False if receiver POST failed


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _overall_severity(flags: list[dict]) -> tuple[str, str]:
    """Return (status, severity) from a list of engine flag dicts."""
    if not flags:
        return "ok", "normal"
    severities = {f["severity"] for f in flags}
    return "anomaly_detected", "critical" if "critical" in severities else "warning"


def _flag_label(f: dict) -> str:
    """Short human-readable label for one flag dict."""
    if f["type"] == "threshold_breach":
        return f"{f['channel']}:breach(limit={f['limit']})"
    steps = f.get("projected_breach_in_steps", "?")
    return f"{f['channel']}:trending({steps}steps)"


def _build_alert_body(
    reading: TelemetryReading,
    flags: list[dict],
    explanation: str,
    severity: str,
    status: str,
) -> dict[str, Any]:
    """
    Construct the JSON body posted to the receiver.

    Kept separate from the FastAPI response model so the receiver can evolve
    its schema independently without touching the Pydantic models here.
    """
    return {
        "satellite_id": reading.satellite_id,
        "timestamp":    reading.timestamp,
        "source":       SOURCE_ID,
        "status":       status,
        "severity":     severity,
        "anomalies":    [_flag_label(f) for f in flags],
        "flags":        flags,         # raw engine dicts (serialisable)
        "explanation":  explanation,
        "raw_values":   reading.model_dump(),
    }


# ── Receiver forwarding ───────────────────────────────────────────────────────

def _forward_alert_sync(alert_body: dict[str, Any]) -> bool:
    """
    Synchronous POST to the receiver service.

    Returns True if the receiver accepted (2xx), False on any failure.
    NEVER raises — logs the error and returns False instead.

    Kept synchronous (httpx without async) to honour the constraint:
    "backend must remain synchronous and simple — no background workers".
    """
    if not RECEIVER_URL:
        logger.warning("RECEIVER_URL is not set — alert not forwarded.")
        return False
    try:
        resp = httpx.post(RECEIVER_URL, json=alert_body, timeout=5.0)
        resp.raise_for_status()
        logger.info("Alert forwarded to receiver (%s)  status=%d", RECEIVER_URL, resp.status_code)
        return True
    except httpx.ConnectError:
        logger.warning("Receiver unreachable (%s) — alert NOT delivered.", RECEIVER_URL)
    except httpx.TimeoutException:
        logger.warning("Receiver timed out (>5 s) — alert NOT delivered.")
    except httpx.HTTPStatusError as exc:
        logger.warning("Receiver returned %d — alert NOT delivered.", exc.response.status_code)
    except Exception as exc:
        logger.warning("Unexpected error forwarding alert: %s", exc)
    return False


# ── Core handler (shared by /telemetry and /analyze) ─────────────────────────

def _handle_telemetry(reading: TelemetryReading) -> TelemetryResponse:
    """
    Run the full pipeline for one telemetry reading:
      1. Threshold + trend detection  (engine.check_telemetry)
      2. LLM explanation              (llm_service.explain_alert)
      3. Receiver forwarding          (_forward_alert_sync)

    Always returns a TelemetryResponse — downstream failures do not propagate.
    """
    _stats["total_readings"] += 1

    # ── Step 1: Detection ─────────────────────────────────────────────────
    raw_flags: list[dict] = check_telemetry(reading.model_dump())
    status, severity = _overall_severity(raw_flags)
    structured_flags = [AnomalyFlag(**f) for f in raw_flags]

    # ── Step 2: LLM explanation ───────────────────────────────────────────
    # ── Updated line 207 ──────────────────────────────────────────
    explanation = explain_alert(flags=raw_flags, telemetry=reading.model_dump())
    # ── Step 3: Forward to receiver (only when anomalous) ────────────────
    delivery_ok = True
    if raw_flags:
        _stats["anomalies_detected"] += 1
        alert_body = _build_alert_body(reading, raw_flags, explanation, severity, status)
        _recent_alerts.appendleft(alert_body)
        delivery_ok = _forward_alert_sync(alert_body)
        if not delivery_ok:
            _stats["delivery_failures"] += 1

    logger.info(
        "satellite=%s  severity=%s  flags=%d  delivery_ok=%s",
        reading.satellite_id, severity, len(raw_flags), delivery_ok,
    )

    return TelemetryResponse(
        timestamp=reading.timestamp,
        source=SOURCE_ID,
        status=status,
        severity=severity,
        flags=structured_flags,
        anomalies=[_flag_label(f) for f in raw_flags],
        explanation=explanation,
        delivery_ok=delivery_ok,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    return {
        "status":       "ok",
        "service":      "backend-anomaly-engine",
        "version":      "3.0.0",
        "receiver_url": RECEIVER_URL,
        "source_id":    SOURCE_ID,
    }


@app.get("/stats", tags=["meta"])
async def stats():
    return dict(_stats)


@app.get("/recent", tags=["telemetry"])
async def recent(limit: int = 20):
    """Return the last N forwarded alert bodies (newest first)."""
    return list(_recent_alerts)[:min(limit, 100)]


@app.post("/telemetry", response_model=TelemetryResponse, tags=["telemetry"])
async def telemetry(reading: TelemetryReading):
    """
    Primary telemetry ingest endpoint.

    Accepts a full telemetry snapshot, runs anomaly detection, generates
    a Groq explanation (with template fallback), and forwards to the receiver.

    Always returns 200. ``delivery_ok: false`` signals the sender that the
    receiver was unreachable — the sender UI should surface this as a warning
    so nothing is silently lost.
    """
    return _handle_telemetry(reading)


@app.post("/analyze", response_model=TelemetryResponse, tags=["telemetry"])
async def analyze(reading: TelemetryReading):
    """Legacy alias for /telemetry — kept for backward compatibility with older senders."""
    return _handle_telemetry(reading)
