"""Generate simulated actuator feedback for tool checks, never field validation."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from backend.simulator.tep.calibration import TEPActuatorCalibrationDataset


def example():
    runs = {"training": [], "validation": []}
    origin = datetime(2026, 10, 9, tzinfo=timezone.utc)
    for channel_index, variable in enumerate(("XMV10", "XMV11")):
        tau = (12., 8.)[channel_index]  # Tool-test assumptions; not measured TEP coefficients.
        for split, initial, first, second in (("training", 40., 48., 44.), ("validation", 42., 46., 39.)):
            actual, samples = initial, []
            for second_index in range(121):
                target = first if second_index < 60 else second
                samples.append({"time_s": second_index, "target_percent_full_scale": target,
                                "actual_percent_full_scale": actual, "quality": "valid"})
                for _ in range(10):
                    actual += (target - actual) * .1 / tau
            identity = f"synthetic-{variable}-{split}"
            runs[split].append({"recording_id": identity, "source_recording_id": identity,
                "source_file_sha256": hashlib.sha256(json.dumps(samples, sort_keys=True).encode()).hexdigest(),
                "started_at": (origin + timedelta(hours=channel_index * 4 + (split == "validation"))).isoformat(),
                "variable": variable, "samples": samples})
    return TEPActuatorCalibrationDataset.model_validate({
        "source_id": "team-generated-TEP-actuator-tool-example-v1",
        "source_uri": "generated:explicit-euler-actuator-example", "asset_id": "synthetic-actuator-example",
        "data_origin": "simulation", "mapping_status": "user_confirmed_actuator_mapping", "actuator_faults": "none",
        "candidate_model_version": "tep-actuator-candidate-example-v1",
        "channels": {variable: {"unit": "percent_full_scale", "target_tag": variable,
            "actual_tag": f"ACTUAL_{variable}", "normalization_reference": "same normalized setting as TE vpos; simulated feedback",
            "minimum_tau_s": 2., "maximum_tau_s": 30., "max_validation_rmse": .001,
            "max_validation_abs_error": .005, "actual_resolution": .0001} for variable in ("XMV10", "XMV11")},
        **runs,
    })


def main():
    parser = argparse.ArgumentParser(description="Generate a simulated TEP actuator calibration example")
    parser.add_argument("--output", type=Path, default=Path("data/tep-actuator-calibration-simulation.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(example().model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}; data_origin=simulation; not measured data")


if __name__ == "__main__":
    main()
