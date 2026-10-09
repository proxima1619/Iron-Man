"""1-based variable definitions checked against NIST c/TENames.cpp and teprob.cpp."""
from backend.contracts import TEPVariable

XMV_NAMES = ["D feed", "E feed", "A feed", "A+C feed", "Recycle valve", "Purge valve",
             "Separator underflow", "Stripper underflow", "Stripper steam valve",
             "Reactor cooling water flow setting", "Condenser cooling water flow setting", "Agitator setting"]
MEASUREMENTS = [
    ("A feed", "kscm/h"), ("D feed", "kg/h"), ("E feed", "kg/h"),
    ("A+C feed", "kscm/h"), ("Recycle flow", "kscm/h"), ("Reactor feed", "kscm/h"),
    ("Reactor pressure", "kPa_gauge"), ("Reactor level", "percent"), ("Reactor temperature", "degC"),
    ("Purge rate", "kscm/h"), ("Separator temperature", "degC"), ("Separator level", "percent"),
    ("Separator pressure", "kPa_gauge"), ("Separator underflow", "m3/h"), ("Stripper level", "percent"),
    ("Stripper pressure", "kPa_gauge"), ("Stripper underflow", "m3/h"), ("Stripper temperature", "degC"),
    ("Stripper steam flow", "kg/h"), ("Compressor work", "kW"),
    ("Reactor cooling water outlet temperature", "degC"), ("Condenser cooling water outlet temperature", "degC"),
] + [(f"Feed composition {v}", "mole_percent") for v in "ABCDEF"] \
  + [(f"Purge composition {v}", "mole_percent") for v in "ABCDEFGH"] \
  + [(f"Product composition {v}", "mole_percent") for v in "DEFGH"]

VARIABLES = {f"XMV{i}": TEPVariable(name=name, unit="percent_full_scale")
             for i, name in enumerate(XMV_NAMES, 1)}
VARIABLES.update({f"XMEAS{i}": TEPVariable(name=name, unit=unit)
                  for i, (name, unit) in enumerate(MEASUREMENTS, 1)})
VARIABLES.update({f"ACTUAL_XMV{i}": TEPVariable(name=f"Actual {XMV_NAMES[i-1]}", unit="percent_full_scale")
                  for i in (10, 11)})
