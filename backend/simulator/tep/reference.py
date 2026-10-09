"""Inspect a pinned local simulation dataset without replaying it as a new run.

Raw files are user supplied and kept outside the package. Their hashes identify
this upload, not a verified public release. No clocks, seeds or states are
reconstructed from the 52 recorded values.
"""
import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from .reference_contracts import (
    ReferenceCatalog, ReferenceFile, ReferenceMetadata, ReferenceSeries,
    ReferenceStatistics, ReferenceVariable,
)
from .variables import VARIABLES

ROOT = Path(__file__).resolve().parents[3]
LIMITATION = (
    "시뮬레이션 참조 기록이며 현장 실측이 아닙니다. 다운로드 출처·파일별 생성 설정은 미확인입니다. "
    "표본 번호는 0부터 시작하며 timestamp는 없습니다. 180초 간격은 동봉 코드의 설정으로만 확인했습니다. "
    "동봉 폐루프 제어 코드와 현재 개루프 실행의 조건이 다르므로 실측 오차·동일 조건 정확도·안전 한계로 사용하지 않습니다."
)


class ReferenceFailure(Exception):
    def __init__(self, code: str, detail: str, status_code: int = 503):
        super().__init__(detail)
        self.code, self.detail, self.status_code = code, detail, status_code


@lru_cache(maxsize=1)
def profile():
    return json.loads(Path(__file__).with_name("reference.lock.json").read_text(encoding="utf-8"))


def directory() -> Path:
    return Path(os.getenv("IRON_MAN_TEP_REFERENCE_DIR", str(ROOT / "archive" / "TEP_data"))).resolve()


def read_pinned(root: Path, name: str, expected_sha: str) -> bytes:
    try:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ReferenceFailure("REFERENCE_UNAVAILABLE", "참조 데이터 파일이 없거나 데이터 폴더 밖에 있습니다.")
        if path.stat().st_size > 2_000_000:
            raise ReferenceFailure("INVALID_REFERENCE", "참조 파일 크기가 지원 범위를 벗어났습니다.")
        raw = path.read_bytes()
    except OSError as exc:
        raise ReferenceFailure("REFERENCE_UNAVAILABLE", "참조 데이터 폴더를 읽을 수 없습니다.") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ReferenceFailure("REFERENCE_PROFILE_MISMATCH", "참조 파일이 확인한 버전과 다릅니다. 출처·변수 정의를 다시 확인해야 합니다.")
    return raw


def metadata(root: Path) -> ReferenceMetadata:
    lock = profile()
    for name, sha in lock["source_files_sha256"].items():
        read_pinned(root, name, sha)
    return ReferenceMetadata(source_files_sha256=lock["source_files_sha256"],
                             column_order=lock["column_order"], limitation=LIMITATION)


def definitions() -> dict[str, ReferenceVariable]:
    result = {}
    try:
        for column, key in enumerate(profile()["column_order"]):
            original = VARIABLES[key]
            # The supplied Fortran dictionary uses "Separator" for XMEAS22.
            name = "Separator cooling water outlet temperature" if key == "XMEAS22" else original.name
            result[key] = ReferenceVariable(name=name, unit=original.unit, column_index=column)
    except (KeyError, ValidationError) as exc:
        raise ReferenceFailure("UNKNOWN_REFERENCE_UNITS", "참조 변수 정의·단위를 확인할 수 없습니다.") from exc
    return result


def descriptor(root: Path, file_id: str) -> ReferenceFile:
    info = profile()["files"].get(file_id)
    if info is None:
        raise ReferenceFailure("UNKNOWN_REFERENCE_FILE", "지원하지 않는 참조 파일입니다.", 404)
    path = (root / file_id).resolve()
    return ReferenceFile(file_id=file_id, **info, present=path.is_relative_to(root) and path.is_file())


def catalog() -> ReferenceCatalog:
    root = directory()
    return ReferenceCatalog(metadata=metadata(root), variables=definitions(),
                            files=[descriptor(root, key) for key in profile()["files"]])


def parse_rows(raw: bytes, observations: int, layout: str) -> list[list[float]]:
    """Validate every value, then normalize the exceptional d00.dat transpose."""
    if layout not in {"variables_by_observations", "observations_by_variables"}:
        raise ReferenceFailure("INVALID_REFERENCE", "참조 파일의 배열 방향을 확인할 수 없습니다.")
    try:
        rows = [[float(value) for value in line.split()] for line in raw.decode("ascii").splitlines() if line.strip()]
    except (ValueError, UnicodeError) as exc:
        raise ReferenceFailure("INVALID_REFERENCE", "참조 파일에 숫자가 아닌 값이 있습니다.") from exc
    transposed = layout == "variables_by_observations"
    expected_rows, expected_columns = (52, observations) if transposed else (observations, 52)
    if len(rows) != expected_rows or any(len(row) != expected_columns for row in rows):
        raise ReferenceFailure("INVALID_REFERENCE", "참조 파일의 관측 수·52개 변수 구조가 맞지 않습니다.")
    if any(not math.isfinite(value) for row in rows for value in row):
        raise ReferenceFailure("INVALID_REFERENCE", "참조 파일에 NaN 또는 무한대가 있습니다.")
    return [list(row) for row in zip(*rows)] if transposed else rows


def series(file_id: str, variable: str) -> ReferenceSeries:
    root = directory()
    file = descriptor(root, file_id)
    variables = definitions()
    if variable not in variables:
        raise ReferenceFailure("UNKNOWN_REFERENCE_VARIABLE", "참조 데이터에 없는 변수입니다.", 422)
    meta = metadata(root)
    raw = read_pinned(root, file_id, file.sha256)
    rows = parse_rows(raw, file.observation_count, file.stored_layout)
    definition = variables[variable]
    values = [row[definition.column_index] for row in rows]
    return ReferenceSeries(metadata=meta, file=file, variable=variable, definition=definition,
        sample_indices=list(range(len(values))), values=values,
        statistics=ReferenceStatistics(minimum=min(values), maximum=max(values), mean=math.fsum(values) / len(values)))
