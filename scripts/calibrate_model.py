"""python -m scripts.calibrate_model --input measurements.json --output candidate.json"""
import argparse
import json
from pathlib import Path
from backend.simulator.calibration import CalibrationDataset, calibrate


def main():
    parser = argparse.ArgumentParser(description="Offline cooling parameter fit; does not update runtime coefficients")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, help="Optionally save the input JSON schema")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("output must not overwrite input measurements")
    if args.schema and args.schema.resolve() in (args.input.resolve(), args.output.resolve()):
        parser.error("schema path must differ from input and output")
    dataset = CalibrationDataset.model_validate_json(args.input.read_text(encoding="utf-8"))
    result = calibrate(dataset)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.schema:
        args.schema.write_text(json.dumps(CalibrationDataset.model_json_schema(), indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}; validation_passed={result['validation_passed']}; activated=False; data_origin={result['data_origin']}")


if __name__ == "__main__":
    main()
