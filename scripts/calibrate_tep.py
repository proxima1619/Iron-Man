"""Fit recorded TEP actuator responses; never activates the resulting candidate."""
import argparse
import hashlib
from pathlib import Path

from pydantic import ValidationError

from backend.simulator.tep.calibration import TEPActuatorCalibrationDataset, TEPActuatorCalibrationResult, fit


def main():
    parser = argparse.ArgumentParser(description="Offline TEP cooling actuator response-time fit")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("output must not overwrite the source data")
    raw, dataset = None, None
    try:
        raw = args.input.read_bytes()
        dataset = TEPActuatorCalibrationDataset.model_validate_json(raw)
        result = fit(dataset).model_copy(update={"input_file_sha256": hashlib.sha256(raw).hexdigest()})
    except (OSError, ValueError) as exc:
        code = "INVALID_DATASET" if isinstance(exc, ValidationError) else "CALIBRATION_FAILED"
        result = TEPActuatorCalibrationResult(status="failed", failure_code=code, detail=str(exc),
            input_file_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
            data_origin=dataset.data_origin if dataset else None,
            candidate_model_version=dataset.candidate_model_version if dataset else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"status={result.status}; activated=False; data_origin={result.data_origin}; saved={args.output}")
    return 0 if result.status == "candidate_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
