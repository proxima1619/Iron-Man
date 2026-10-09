"""Server-owned policy for one synthetic plant. Documents cannot change these rules."""
import hashlib
import json
from backend.contracts import NewRequest, Snapshot, EvidenceReview, SimulationResult
from backend.evidence.service import load_sources
from backend.simulator.assessment import ASSESSMENT_VERSION, HORIZON_S, PARAMETER_RANGES

POLICY_VERSION = "virtual-cooling-policy-v3"
APPROVED_MODEL = "cooling-demo-v3"
LIMIT_C = 80.0
FORECAST_S = 300
SOURCE_BUNDLE_SHA256 = "99651eb7c3bbcf95f5bd49ded18d47063bbb4d2ad13b122435721390a492220a"


def scope_issue(body: NewRequest, snapshot: Snapshot, model_version: str, execution_scope: str):
    if execution_scope != "virtual" or model_version != APPROVED_MODEL:
        return "허용된 가상 어댑터·모델이 아닙니다. 실행 정책을 별도로 검토하세요."
    if (body.equipment_id != "cooling-demo-01" or body.command.type != "set_pump_speed"
        or body.command.duration_s != FORECAST_S
        or not 20 <= body.command.target_pct <= 100
        or snapshot.data_origin != "synthetic" or snapshot.model_version != APPROVED_MODEL
        or snapshot.domain_status != "ready" or snapshot.sensor_quality != "valid"
        or snapshot.target_pump_speed_pct is None
        or not 0 <= snapshot.temperature_c <= LIMIT_C
        or not 0 <= snapshot.load_ratio <= 1.5
        or not 0 <= snapshot.pump_speed_pct <= 100
        or not 0 <= snapshot.target_pump_speed_pct <= 100):
        return "가상 설비 승인 정책의 대상·상태 또는 300초 예측 범위를 벗어났습니다."
    return None


def evidence_issue(review: EvidenceReview):
    if review.status in {"insufficient", "failed"} or not review.cards:
        return "필수 근거 검토를 완료하지 못했습니다."
    if review.mock:
        # Explicit exception for the shipped, visibly labelled demo fixture only.
        # unknown applicability here never represents evidence for real equipment.
        if (review.status != "demo_fixture" or len(review.cards) != 1
            or review.cards[0].source_id != "team-demo-note"
            or review.cards[0].source_type != "team_authored_fixture"
            or review.cards[0].locator != "fixtures/demo-source.md"
            or review.cards[0].applicability != "unknown"
            or review.cards[0].missing_conditions or review.cards[0].source_url is not None):
            return "사전 지정된 가상 데모 fixture가 아닙니다."
        return None
    if review.status != "completed" or any(
        c.applicability != "applicable" or c.missing_conditions or not c.matched_conditions for c in review.cards
    ):
        return "필수 적용 조건이 확인되지 않았습니다."
    sources = load_sources()
    bundle = hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if bundle != SOURCE_BUNDLE_SHA256:
        return "근거 문서 묶음이 정책에 등록된 버전과 다릅니다."
    by_id = {source["source_id"]: source for source in sources}
    for card in review.cards:
        source = by_id.get(card.source_id)
        if (source is None or card.source_type != "team_authored_demo"
            or not card.excerpt or card.excerpt not in source["text"]
            or any(getattr(card, key) != value for key, value in source.items() if key != "text")):
            return "정책에 등록된 출처·원문과 검토 결과가 일치하지 않습니다."
    return None


def simulation_issue(result: SimulationResult):
    if result.mock or result.model_version != APPROVED_MODEL or any(
        row.value_origin != "model_calculation" or row.limit_c != LIMIT_C for row in result.scenarios
    ):
        return "지정 모델의 계산 결과와 서버 온도 한계 80°C를 확인할 수 없습니다."
    for row in result.scenarios:
        assessment = row.physical_assessment
        if (assessment is None or assessment.version != ASSESSMENT_VERSION
                or assessment.horizon_s != HORIZON_S
                or {key: value.model_dump() for key, value in assessment.parameter_ranges.items()} != PARAMETER_RANGES
                or assessment.baseline.peak_c < row.baseline_peak_c
                or assessment.candidate.peak_c < row.candidate_peak_c):
            return "장기 예측·지정 계수 범위의 평가가 누락되었거나 일치하지 않습니다."
    return None


def physical_risk(result: SimulationResult):
    """Known violations take precedence over incomplete sensitivity coverage."""
    for row in result.scenarios:
        assessment = row.physical_assessment
        if row.exceeded or row.baseline_peak_c > LIMIT_C:
            return True
        for branch in (assessment.baseline, assessment.candidate):
            if branch.peak_c > LIMIT_C or (branch.equilibrium_c is not None and branch.equilibrium_c > LIMIT_C):
                return True
        sensitivity = assessment.sensitivity
        if sensitivity.status == "completed" and any(value > LIMIT_C for value in (
                sensitivity.baseline_worst_peak_c, sensitivity.candidate_worst_peak_c,
                sensitivity.baseline_worst_equilibrium_c, sensitivity.candidate_worst_equilibrium_c)):
            return True
    return False


def coverage_issue(result: SimulationResult):
    if any(row.physical_assessment.sensitivity.status != "completed"
           or row.physical_assessment.baseline.equilibrium_status != "finite"
           or row.physical_assessment.candidate.equilibrium_status != "finite" for row in result.scenarios):
        return "장기 평형 또는 계수 민감도 시험의 지원 범위를 확인하지 못했습니다."
    return None
