"""Explain a frozen DB record with live LLM review; never reevaluate or execute it."""
import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from fastapi import HTTPException
from backend.contracts import RequestRecord, RecordFeedback
from backend.evidence import llm, papers
from backend.evidence.schema import RecordAnalysis
from backend.evidence.service import load_sources, validate_analysis

INSTRUCTIONS = """지금 수행하는 작업은 DB에 저장된 과거 명령과 결과의 사후 설명이다.
현재 설비를 조회하거나 시뮬레이션을 새로 실행하지 않는다. saved_record의 명령·숫자·상태를 그대로 해석하라.
summary에는 이 요청에서 무엇이 일어났는지를 쉬운 한국어로 설명하라.
result_interpretation에는 저장된 시나리오별 결과와 서버 판정, 실제 적용 기록을 구분해 설명하라.
execution이 없으면 적용하지 않았다고 설명하고, status=unknown이면 결과 불명으로 설명하라.
applied는 가상 목표 속도 적용일 뿐 실측 온도 반응이 아니다. 과거 관측 시각이 오래됐다는 이유로 역사 설명을 거부하지 마라.
report 또는 simulation이 없으면 숫자·성공 결과를 만들지 말고 해당 결과가 저장되지 않았다고 명시하라.
mock과 value_origin을 확인하고 고정 모의 값, 합성 계산, 가상 적용, 실제 측정의 차이를 설명하라.
과거 모델 버전을 현재 모델로 바꾸어 설명하지 마라. 모든 숫자는 saved_record에서만 사용하라.
model_limitations에는 모델과 합성 데이터의 한계, recommended_checks에는 담당자가 다음에 확인할 항목을 적어라.
missing_conditions에는 논문과 기록의 설비·유체·온도·운전 범위 차이와 검증하지 못한 조건을 구체적으로 적어라.
피드백은 안전 승인·실행 허가가 아니다. proposed_test는 모두 null로 반환하라.
문헌 주장은 반드시 제공된 documents의 정확한 인용과 연결하라. 한국어로 답하라."""


def review_record(record: RequestRecord) -> RecordFeedback:
    if not os.getenv("OPENAI_API_KEY", "").strip() or not os.getenv("IRON_MAN_EVIDENCE_MODEL", "").strip():
        raise HTTPException(409, "서버 .env에 API 키와 모델을 설정하고 서버를 재시작하세요.")
    # No contact, approval identity or audit trail is submitted to the model.
    saved = {
        "request_id": record.id, "revision": record.revision, "status": record.status,
        "command": record.request.command.model_dump(), "purpose": record.request.purpose,
        "report": record.report.model_dump() if record.report else None,
        "execution": record.execution.model_dump() if record.execution else None,
    }
    fingerprint = hashlib.sha256(json.dumps(saved, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        source_mode = os.getenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
        if source_mode == "local":
            sources = load_sources()
        elif source_mode == "europepmc":
            sources = papers.retrieve_papers(os.getenv("IRON_MAN_EVIDENCE_QUERY") or papers.DEFAULT_QUERY)
        else:
            raise ValueError("Invalid source mode")
        if not sources:
            raise ValueError("No sources")
    except Exception:
        raise HTTPException(502, "논문 원문을 가져오지 못했습니다. 서버의 문서 경로 또는 검색 연결을 확인하세요.") from None
    try:
        raw = llm.analyze({"saved_record": saved, "documents": sources},
                          output_schema=RecordAnalysis, extra_instructions=INSTRUCTIONS)
        analysis = RecordAnalysis.model_validate(raw)
    except HTTPError as exc:
        detail = {401: "API 키 인증에 실패했습니다.", 403: "해당 모델을 사용할 권한이 없습니다.",
                  429: "API 사용 한도 또는 요청 속도 제한에 걸렸습니다."}.get(exc.code, "API 호출에 실패했습니다. 모델 이름과 서버 설정을 확인하세요.")
        raise HTTPException(502, detail) from None
    except (TimeoutError, URLError):
        raise HTTPException(504, "AI 서버 응답이 지연되거나 연결되지 않습니다. 잠시 후 다시 요청하세요.") from None
    except Exception:
        raise HTTPException(502, "AI 피드백을 정상 형식으로 받지 못했습니다. 원래 DB 기록은 그대로 유지됩니다.") from None
    try:
        if any(card.proposed_test is not None for card in analysis.cards):
            raise ValueError("Historical feedback cannot propose tests")
        evidence = validate_analysis(analysis.model_dump(include={"cards", "missing_conditions"}), sources)
        if evidence.proposed_tests:
            raise ValueError("Historical feedback cannot propose executable tests")
    except Exception:
        raise HTTPException(502, "논문 인용이나 적용 조건 검증에 실패했습니다. 검증되지 않은 피드백은 표시하지 않습니다.") from None
    origin = "실시간 Europe PMC 논문 검색·원문 수집" if source_mode == "europepmc" else "사전 수집 문서 검토"
    evidence = evidence.model_copy(update={"limitation": origin + ". " + evidence.limitation})
    missing = list(dict.fromkeys([*analysis.missing_conditions, *(c for card in evidence.cards for c in card.missing_conditions)]))
    for stance, label in (("support", "지지 근거"), ("counter", "반례·실패 조건 근거")):
        if not any(card.stance == stance for card in evidence.cards):
            missing.append(f"수집한 문헌에서 {label}를 확보하지 못했습니다.")
    return RecordFeedback(request_id=record.id, record_revision=record.revision,
        record_digest=fingerprint, report_digest=record.report.digest if record.report else None,
        generated_at=time.time(), model=os.environ["IRON_MAN_EVIDENCE_MODEL"],
        status="completed" if evidence.status == "completed" else "insufficient",
        summary=analysis.summary, result_interpretation=analysis.result_interpretation,
        model_limitations=["저장된 합성·가상 설비 기록의 사후 설명이며 실제 설비 안전 검증이 아닙니다.", *analysis.model_limitations],
        missing_conditions=missing, recommended_checks=analysis.recommended_checks, evidence=evidence)
