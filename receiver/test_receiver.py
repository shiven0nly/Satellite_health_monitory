"""Smoke test for receiver api."""
import sys, types, pathlib

src = pathlib.Path("api.py").read_text(encoding="utf-8")
ns = {}
exec(compile(src, "api.py", "exec"), ns)

app = ns["app"]
alerts = ns["alerts"]
alerts.clear()

assert len(alerts) == 0, "Alerts list should start empty"
print("PASS  receiver api load and clean state test")
