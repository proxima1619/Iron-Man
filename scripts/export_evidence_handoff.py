"""Export schema-valid module responses; no LLM execution, secrets or server DB.

The success and missing-condition cases use team-authored deterministic claims
and real collected paper paragraphs, respectively. Manifest labels test inputs.
"""
import json
from pathlib import Path
from unittest.mock import patch
from backend.contracts import NewRequest, Command, Snapshot
from backend.evidence import service
from backend.evidence.context import review_context
from backend.evidence.validation import source_bundle_digest, verify_review_sources
from backend.simulator.service import MODEL_VERSION

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "contracts" / "examples" / "evidence-handoff"


def examples():
    request = NewRequest(command=Command(target_pct=60))
    snapshot = Snapshot(revision=3, temperature_c=60.97200057806551, load_ratio=1,
        pump_speed_pct=68.92520713290413, target_pump_speed_pct=60, observed_at=1700000000,
        simulation_time_s=30, model_version=MODEL_VERSION)
    context = review_context(request, snapshot)
    sources = service.load_sources(service.SOURCE_PATH)
    source = sources[1]
    raw = {"cards": [{"source_id": source["source_id"], "claim": "가상 설비에서 냉각 효율 저하 조건을 추가 확인한다.",
        "stance": "counter", "excerpt": source["text"], "applicability": "applicable",
        "matched_conditions": ["cooling-demo-01의 set_pump_speed 변경 검토", "문서는 가상 설비 데모에만 적용"],
        "missing_conditions": [], "proposed_test": "degraded_cooling"}], "missing_conditions": []}
    normal = service.validate_analysis(raw, sources, context)
    assert not verify_review_sources(normal, sources)
    paper_sources = service.load_sources(ROOT / "data" / "sources" / "paper-sources.json")
    paper = paper_sources[1]
    paragraph = paper["text"].split("\n\n")[0]
    insufficient = service.validate_analysis({"cards": [{"source_id": paper["source_id"],
        "claim": "인산·증기 열교환기 연구와 가상 냉각 탱크의 운전 조건 동일성을 확인하지 못했다.",
        "stance": "limitation", "excerpt": paragraph[:400], "applicability": "mismatch",
        "matched_conditions": ["열교환 성능 검토 주제"],
        "missing_conditions": ["유체·설비 동일성", "현재 온도·실제/목표 속도에 대한 문헌 적용 범위"],
        "proposed_test": None}], "missing_conditions": []}, paper_sources, context)
    unknown_test = {"cards": [{**raw["cards"][0], "proposed_test": "elevated_coolant_temperature"}], "missing_conditions": []}
    unsupported = service.validate_analysis(unknown_test, sources, context)
    with patch.dict("os.environ", {"IRON_MAN_EVIDENCE_MODE": "live", "IRON_MAN_EVIDENCE_SOURCE_MODE": "local"}), patch(
        "backend.evidence.service.load_sources", return_value=sources), patch(
        "backend.evidence.llm.analyze", side_effect=TimeoutError("not included in output")):
        failed = service.review_evidence(request, snapshot)
    manifest = {"example_only": True, "llm_executed": False, "live_model_quality_verified": False,
        "generation": "Deterministic schema/validator/exception paths; not live LLM inference",
        "request": request.model_dump(), "snapshot": snapshot.model_dump(),
        "source_bundles": {"team": source_bundle_digest(sources), "papers": source_bundle_digest(paper_sources)},
        "files": {"normal.json": "completed team-document test response",
                  "insufficient.json": "real paper excerpt with unconfirmed applicability",
                  "failed.json": "LLM timeout test response",
                  "unsupported-test.json": "unverified proposal omitted pending owner 2 agreement"}}
    labelled = [review.model_copy(update={"limitation": "자동 시험 예시 · 실제 LLM 미호출. "
                + review.limitation.replace("실제 LLM 문서 검토.", "근거 출력 계약 검증.")})
                for review in (normal, insufficient, failed, unsupported)]
    return {"normal.json": labelled[0].model_dump(), "insufficient.json": labelled[1].model_dump(),
            "failed.json": labelled[2].model_dump(), "unsupported-test.json": labelled[3].model_dump(),
            "manifest.json": manifest}


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, value in examples().items():
        (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(OUTPUT))
