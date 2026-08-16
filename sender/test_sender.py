"""Smoke test for sender pure functions (no Streamlit server needed)."""
import sys, types, pathlib, ast

# Minimal python file parsing test for app.py
src = pathlib.Path("app.py").read_text(encoding="utf-8")
ast.parse(src)
print("PASS  app.py syntax is valid")

# Directly extract and run _build_payload definition from app.py source without executing UI
tree = ast.parse(src)
build_payload_node = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_build_payload":
        build_payload_node = node
        break

assert build_payload_node is not None, "Could not find _build_payload in app.py"

mod = ast.Module(body=[build_payload_node], type_ignores=[])
code = compile(mod, filename="app.py", mode="exec")
ns = {}
exec(code, ns)
_build_payload = ns["_build_payload"]

REQUIRED = [
    "satellite_id", "timestamp",
    "orientation_pitch_deg", "orientation_roll_deg", "orientation_yaw_deg",
    "nav_position_error_m", "power_bus_voltage_v", "power_bus_current_a",
    "component_temp_c",
]

# Normal values
p = _build_payload(1.2, -0.5, 3.0, 10.0, 29.5, 5.0, 38.0)
missing = [k for k in REQUIRED if k not in p]
assert not missing, f"Missing keys: {missing}"
assert p["satellite_id"] == "satellite-sim-01"
print("PASS  _build_payload: all required keys present")

# Out-of-bounds values should still build
p_bad = _build_payload(8.5, -7.0, 15.0, 80.0, 24.0, 16.0, 95.0)
assert p_bad["orientation_pitch_deg"] == 8.5
assert p_bad["power_bus_voltage_v"]   == 24.0
print("PASS  _build_payload: accepts out-of-bounds values")

print("\nAll sender smoke tests passed.")
