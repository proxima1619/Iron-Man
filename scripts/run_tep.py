"""Reproduce a real external TEP pair (not a fixture). Run after tep.build."""
import argparse
from pathlib import Path
from backend.contracts import TEPCommand
from backend.simulator.tep.service import simulate

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variable", choices=["XMV10", "XMV11"], default="XMV10")
    p.add_argument("--value", type=float, default=42.0)
    p.add_argument("--duration", type=int, default=600)
    p.add_argument("--sample", type=int, default=10)
    p.add_argument("--output", type=Path, default=Path("data/tep-result.json"))
    p.add_argument("--repeat", action="store_true")
    a = p.parse_args()
    command = TEPCommand(type="set_tep_cooling_water", variable=a.variable, value=a.value,
                         duration_s=a.duration, sample_period_s=a.sample)
    result = simulate(command)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{result.status}: {result.detail}\nResult: {a.output.resolve()}")
    if result.status != "completed":
        return 1
    if a.repeat:
        repeated = simulate(command)
        if result != repeated:
            print("Reproducibility check FAILED")
            return 2
        print("Reproducibility check passed: identical independent runs")
    for key in ("XMEAS7", "XMEAS9", "XMEAS11", "XMEAS21", "XMEAS22"):
        print(f"{key} final delta: {result.comparison[key].final_delta:.8g} {result.variables[key].unit}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
