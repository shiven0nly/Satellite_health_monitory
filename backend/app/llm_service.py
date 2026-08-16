"""
backend/app/llm_service.py — Groq-powered alert explanation

Reuses the same pattern established in the satellite-disaster project:
  • System prompt sets the persona / output format
  • Falls back gracefully if GROQ_API_KEY is missing or the API errors
"""
from __future__ import annotations

import os
import logging
from typing import List

logger = logging.getLogger(__name__)

try:
    from groq import Groq  # type: ignore
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False

_client: "Groq | None" = None


def _get_client() -> "Groq | None":
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or not _GROQ_AVAILABLE:
        return None
    _client = Groq(api_key=api_key)
    return _client


_SYSTEM_PROMPT = """You are CASSANDRA — an autonomous Satellite Health AI assistant.
Your role is to provide concise, actionable anomaly explanations for satellite operators.

Rules:
- Always respond in ≤3 short sentences.
- Lead with the most critical risk.
- End with one concrete recommended action.
- Use precise engineering language; avoid jargon inflation.
- If the anomaly list is empty, respond: "All systems nominal."
"""


def explain_alert(
    satellite_id: str,
    anomalies: List[str],
    raw_values: dict,
    severity: str,
) -> str | None:
    """
    Call Groq to generate a plain-English explanation of the anomalies.

    Returns None if the explanation cannot be generated (key missing, API
    error, etc.) so the caller can still return a valid response without it.
    """
    client = _get_client()
    if client is None:
        logger.debug("Groq client unavailable — skipping LLM explanation.")
        return None

    anomaly_str = ", ".join(anomalies) if anomalies else "none"
    values_str = "; ".join(f"{k}={v}" for k, v in raw_values.items())

    user_msg = (
        f"Satellite: {satellite_id}\n"
        f"Severity: {severity}\n"
        f"Anomalies detected: {anomaly_str}\n"
        f"Current telemetry snapshot: {values_str}"
    )

    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=120,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Groq API call failed: %s", exc)
        return None
