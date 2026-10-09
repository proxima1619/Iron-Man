"""Generate visibly synthetic recordings to demonstrate the fitting workflow."""
from dataclasses import replace
import json
from pathlib import Path
from backend.simulator.model import MODEL, advance_state
from backend.simulator.calibration import CalibrationDataset


def recording(identifier, initial_temperature, initial_speed, controls):
    model = replace(MODEL, nominal_heat_input_w=38000, full_speed_conductance_w_per_k=1100, pump_response_s=28)
    temperature, speed = initial_temperature, initial_speed
    samples = []
    for t in range(181):
        target, load = controls[min(t // 60, 2)]
        if t % 5 == 0:
            samples.append(dict(time_s=t, temperature_c=temperature, pump_speed_pct=speed,
                                target_pct=target, load_ratio=load))
        if t < 180:
            temperature, speed = advance_state(temperature, speed, target, load, 1, 1, model=model)
    return {"recording_id": identifier, "efficiency": 1, "samples": samples}


def example():
    return CalibrationDataset(source_id="synthetic-workflow-example-not-equipment-data", data_origin="synthetic",
        candidate_model_version="synthetic-fit-example-v1", thermal_capacity_j_per_k=200000,
        capacity_source="synthetic generator assumption; not measured", coolant_temperature_c=25,
        coolant_source="synthetic constant; not measured",
        training=[recording("synthetic-train", 55, 100, [(60,.7), (90,.9), (75,.5)])],
        validation=[recording("synthetic-validation", 65, 60, [(95,.6), (70,.8), (100,.7)])],
        max_temperature_rmse_c=.1, max_temperature_error_c=.2, max_speed_rmse_pct=.1)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "examples" / "simulator"
    root.mkdir(parents=True, exist_ok=True)
    (root / "calibration-synthetic.json").write_text(json.dumps(example().model_dump(), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (root / "CalibrationDataset.schema.json").write_text(json.dumps(CalibrationDataset.model_json_schema(), indent=2)+"\n", encoding="utf-8")
