import os
import logging
from typing import Any, Optional
from dotenv import load_dotenv
import google.generativeai as genai

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ── Easy-to-understand Operator Persona ───────────────────────────────────────
# ── Advanced Predictive Operator Persona ──────────────────────────────────────
_SYSTEM_PROMPT = """\
You are CASSANDRA, an advanced predictive AI monitoring satellite telemetry.
Your goal is to provide a comprehensive, highly intelligent operator brief that highlights predictive ML insights and catches ALL concurrent anomalies.

Rules:
- Respond in exactly 3 powerful, professional sentences.
- Sentence 1 (Diagnostics): Explicitly identify ALL sensor readings that are currently out of normal bounds (e.g., if both Temperature and Bus Current are high, you MUST state both) and provide their exact values.
- Sentence 2 (Predictive Insight): Synthesize these raw readings with the ML anomaly flags (like the LSTM predictor) to explain the specific cascading hardware failure that will occur if the current degradation trend continues.
- Sentence 3 (Mitigation Protocol): Recommend a precise, multi-step emergency action (e.g., shedding payload load AND adjusting attitude for thermal relief).
- Tone: Maintain an authoritative, advanced aerospace engineering tone. Highlight the predictive nature of the alert without using opaque math jargon.
"""

def _template_explanation(flags: list[dict[str, Any]]) -> str:
    if not flags:
        return "All satellite systems are operating within normal parameters."
    first = flags[0]
    return f"Warning: {first.get('channel', 'A subsystem')} is reporting irregular activity. Review telemetry and prepare mitigation procedures."

def explain_alert(flags: list[dict[str, Any]], telemetry: Optional[dict[str, Any]] = None) -> str:
    if not flags and not telemetry:
        return "All systems nominal — no anomalies detected."
    if not GEMINI_API_KEY:
        return _template_explanation(flags)

    # Compile flag details
    flag_details = [
        f"- {f.get('channel')}: {f.get('type')} (Current: {f.get('value')}, Threshold: {f.get('limit', 'N/A')})"
        for f in flags
    ]

    # Include raw payload values (e.g. 130°C component temp, bus voltage)
    telemetry_summary = ""
    if telemetry:
        telemetry_summary = "Current Sensor Readings:\n" + "\n".join([f"- {k}: {v}" for k, v in telemetry.items()])

    prompt = f"""
{telemetry_summary}

ML Anomaly & Trend Detections:
{chr(10).join(flag_details) if flag_details else 'No explicit threshold breaches, but unusual trend pattern detected.'}

Please provide an easy-to-understand 3-sentence operational brief:
"""

    try:
        model = genai.GenerativeModel(
            model_name="gemini-3.5-flash-lite",
            system_instruction=_SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=2500,
            ),
        )
        response = model.generate_content(prompt)
        return response.text.strip() if response and response.text else _template_explanation(flags)
    except Exception as exc:
        logger.warning("Gemini API call failed (%s); using fallback.", exc)
        return _template_explanation(flags)