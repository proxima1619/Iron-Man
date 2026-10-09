"""Execute the pinned TE core twice, validate the protocol, and compare simulations."""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import uuid

from backend.contracts import (TEPCommand, TEPConfiguration, TEPState, TEPResult,
    TEPProvenance, TEPBranch, TEPPoint, TEPMetric, TEPShutdownRule)
from .build import ROOT, DEFAULT_OUTPUT, FLAGS, source_lock, sha, launcher, engine_path
from .variables import VARIABLES

MODEL_VERSION = "nist-tep-81a7ac9-ironman-v1"
POLICY_VERSION = "tep-hold-only-v1"
# teinit uses single precision constants converted to doubles; preserve that conversion.
INITIAL_XMV = [struct.unpack('f', struct.pack('f', v))[0] for v in (
    63.05263039, 53.97970677, 24.64355755, 61.30192144, 22.21, 40.06374673,
    38.1003437, 46.53415582, 47.44573456, 41.10581288, 18.11349055, 50.)]
HEADER = ["time_s", "shutdown"] + [f"XMV{i}" for i in range(1, 13)] \
    + [f"XMEAS{i}" for i in range(1, 42)] + [f"STATE{i}" for i in range(1, 51)]
LIMITATION = ("공개 TEP 시뮬레이션 데이터. 원본 기본 초기 상태·외란 없음·개루프 입력 유지 시험입니다. "
    "실측 오차 평가와 실제 설비 적용성 검증은 미완료입니다. 장기 안정성·최적 제어·안전 승인을 뜻하지 않습니다.")
SHUTDOWN_RULES = [
    TEPShutdownRule(quantity="reactor_pressure", unit="kPa_gauge", maximum=3000),
    TEPShutdownRule(quantity="reactor_temperature", unit="degC", maximum=175),
    TEPShutdownRule(quantity="reactor_liquid_volume", unit="m3", minimum=2, maximum=24),
    TEPShutdownRule(quantity="separator_liquid_volume", unit="m3", minimum=1, maximum=12),
    TEPShutdownRule(quantity="stripper_liquid_volume", unit="m3", minimum=1, maximum=8),
]

class RunFailure(RuntimeError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code

def snapshot(configured_at):
    return TEPState(configured_at=configured_at, model_version=MODEL_VERSION,
        source_sha256=sha(ROOT / "vendor" / "teprob.cpp"), wrapper_sha256=sha(ROOT / "runner.cpp"),
        variables_sha256=hashlib.sha256(json.dumps({k: v.model_dump() for k, v in VARIABLES.items()},
                                                   sort_keys=True).encode()).hexdigest())

def configuration(command):
    return TEPConfiguration(variable=command.variable, candidate_value=command.value,
        horizon_s=command.duration_s, sample_period_s=command.sample_period_s)

def configuration_issue(command):
    if not 0 <= command.value <= 100:
        return "정규화된 TEP 냉각수 입력의 지원 범위는 0..100 percent_full_scale입니다."
    if command.duration_s > 1800 or command.duration_s % command.sample_period_s:
        return "최소 연동의 시험 구간은 1..1800초이며 관측 주기의 정수 배수여야 합니다."
    return None

def manifest(directory):
    try:
        lock = source_lock()
        built = json.loads((directory / "build.json").read_text(encoding="utf-8"))
        if (built["source_commit"] != lock["commit"] or built["source_files_sha256"] != lock["files"]
            or built["wrapper_sha256"] != sha(ROOT / "runner.cpp") or built["compiler_flags"] != FLAGS
            or built["binary_sha256"] != sha(directory / "tep-runner")):
            raise ValueError("Source/wrapper/binary build identity mismatch; rebuild the engine")
        return built, lock
    except (OSError, ValueError, KeyError) as exc:
        raise RunFailure("ENGINE_UNAVAILABLE", f"TEP 빌드·체크섬 확인 실패: {exc}") from exc

def parse_csv(raw, command, value):
    try:
        rows = csv.reader(io.StringIO(raw.decode("utf-8")))
        if next(rows) != HEADER:
            raise ValueError("Missing/unknown columns or units")
        points, initial_state = [], None
        for index, row in enumerate(rows):
            if len(row) != len(HEADER):
                raise ValueError("Missing or additional result fields")
            values = [float(v) for v in row]
            if not all(math.isfinite(v) for v in values) or values[1] != 0:
                raise ValueError("Nonfinite result or process shutdown")
            if values[0] != index * command.sample_period_s:
                raise ValueError("Incorrect sample period or time axis")
            u, measured, state = values[2:14], values[14:55], values[55:105]
            expected_u = list(INITIAL_XMV)
            if index:
                expected_u[int(command.variable[3:]) - 1] = value
            if u != expected_u:
                raise ValueError("Applied XMV differs from requested input")
            if initial_state is None:
                initial_state = state
            points.append(TEPPoint(time_s=values[0], xmv=u, xmeas=measured,
                                   actual_cooling_setting=state[47:49]))
        if len(points) != command.duration_s // command.sample_period_s + 1:
            raise ValueError("Missing endpoint or samples")
        return TEPBranch(points=points, csv_sha256=hashlib.sha256(raw).hexdigest()), initial_state
    except (ValueError, UnicodeError, StopIteration) as exc:
        raise RunFailure("INVALID_OUTPUT", f"TEP 시계열 검증 실패: {exc}") from exc

def run_branch(command, value, binary, artifact):
    # GNU timeout bounds the Linux child even if the gateway worker is cancelled.
    args = launcher() + ["timeout", "25", engine_path(binary), command.variable[3:],
                         repr(value), str(command.duration_s), str(command.sample_period_s)]
    try:
        process = subprocess.run(args, capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RunFailure("RUN_TIMEOUT", "TEP 외부 실행 제한 시간 초과") from exc
    except OSError as exc:
        raise RunFailure("ENGINE_UNAVAILABLE", f"TEP 실행 환경에 접근할 수 없습니다: {exc}") from exc
    artifact.with_suffix(".csv").write_bytes(process.stdout)
    artifact.with_suffix(".stderr.txt").write_bytes(process.stderr)
    if process.returncode:
        code = "PROCESS_SHUTDOWN" if process.returncode == 2 else "RUN_FAILED"
        raise RunFailure(code, f"TEP 종료 코드 {process.returncode}: " + process.stderr.decode("utf-8", errors="replace")[:1000])
    return parse_csv(process.stdout, command, value)

def compare(baseline, candidate):
    if [p.time_s for p in baseline.points] != [p.time_s for p in candidate.points]:
        raise RunFailure("INVALID_OUTPUT", "기준·변경 시간축이 다릅니다.")
    result = {}
    for i in range(41):
        a = [p.xmeas[i] for p in baseline.points]
        b = [p.xmeas[i] for p in candidate.points]
        result[f"XMEAS{i+1}"] = TEPMetric(baseline_min=min(a), baseline_max=max(a),
            candidate_min=min(b), candidate_max=max(b), final_delta=b[-1]-a[-1],
            max_abs_delta=max(abs(y-x) for x, y in zip(a, b)))
    return result

def simulate(command: TEPCommand):
    common = dict(model_version=MODEL_VERSION, configuration=configuration(command), variables=VARIABLES,
                  core_shutdown_rules=SHUTDOWN_RULES)
    if issue := configuration_issue(command):
        return TEPResult(**common, status="out_of_domain", failure_code="UNSUPPORTED_INPUT", detail=issue)
    try:
        known_units = {"percent_full_scale", "kscm/h", "kg/h", "kPa_gauge", "percent", "degC", "m3/h", "kW", "mole_percent"}
        if any(definition.unit not in known_units for definition in VARIABLES.values()) or len(VARIABLES) != 55:
            common["variables"] = {} # Do not publish unchecked physical definitions even in failures.
            raise RunFailure("UNKNOWN_UNITS", "TEP 변수·단위를 확인할 수 없습니다.")
        directory = Path(os.getenv("IRON_MAN_TEP_ENGINE_DIR", str(DEFAULT_OUTPUT))).resolve()
        built, lock = manifest(directory)
        artifact_dir = Path(os.getenv("IRON_MAN_TEP_RUN_DIR", str(directory.parent / "runs"))) / str(uuid.uuid4())
        artifact_dir.mkdir(parents=True)
        artifact_dir.joinpath("configuration.json").write_text(common["configuration"].model_dump_json(indent=2), encoding="utf-8")
        index = int(command.variable[3:]) - 1
        baseline, initial_a = run_branch(command, INITIAL_XMV[index], directory / "tep-runner", artifact_dir / "baseline")
        candidate, initial_b = run_branch(command, command.value, directory / "tep-runner", artifact_dir / "candidate")
        if initial_a != initial_b or baseline.points[0] != candidate.points[0]:
            raise RunFailure("INVALID_OUTPUT", "기준·변경 초기 상태 또는 관측값이 다릅니다.")
        provenance = TEPProvenance(source_url=lock["repository"], source_commit=lock["commit"],
            **{key: built[key] for key in ("source_files_sha256", "wrapper_sha256", "binary_sha256", "compiler", "compiler_flags", "platform")},
            initial_state=initial_a, initial_xmv=INITIAL_XMV,
            initial_state_sha256=hashlib.sha256(json.dumps(initial_a, separators=(",", ":")).encode()).hexdigest(),
            license="NIST public service license / US public domain; vendor/LICENSE.md and DISCLAIMER.md")
        return TEPResult(**common, status="completed", provenance=provenance, baseline=baseline,
                         candidate=candidate, comparison=compare(baseline, candidate), detail=LIMITATION)
    except RunFailure as exc:
        return TEPResult(**common, status="failed", failure_code=exc.code, detail=str(exc))
    except Exception as exc:
        return TEPResult(**common, status="failed", failure_code="INTEGRATION_FAILURE", detail=f"TEP 연동 결과를 확인하지 못했습니다: {type(exc).__name__}")
