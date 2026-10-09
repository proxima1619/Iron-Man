"""Deterministic schema examples; no LLM or simulation execution."""
import copy
import json
from pathlib import Path
from backend.contracts import NewRequest, TEPEvidenceReview
from backend.evidence import tep
from backend.simulator.tep import service as simulator

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "contracts/examples/tep-evidence"


def examples():
    request = NewRequest(equipment_id="tep-sim-01", command={"type": "set_tep_cooling_water", "variable": "XMV10",
        "value": 42, "duration_s": 600, "sample_period_s": 10})
    data = tep.registry()
    sources = tep.model_sources(data)
    context = {"model_version": simulator.MODEL_VERSION, "initial_profile": "nist-teinit-base-case-v1",
        "configuration": simulator.configuration(request.command).model_dump(), "requested_variable": "XMV10", "variables": data["variables"]}
    support = {"source_id": "tep-variable-contract", "claim": "TEP 변수·지원 시험 정의를 확인한다.", "stance": "support",
        "excerpt": '"model_version": "' + simulator.MODEL_VERSION + '"', "applicability": "applicable",
        "matched_conditions": ["XMV10 percent_full_scale, 기본 초기화와 외란 없는 입력 변경"], "missing_conditions": [],
        "proposed_test": None, "evidence_purpose": "model_definition", "variable_ids": ["XMV10"]}
    raw = {"cards": [support, {**support, "source_id": "tep-wrapper", "stance": "counter",
        "claim": "고장 시험으로 간주하지 않고 기준 유지와 변경 입력을 비교한다.", "excerpt": "inputs[index - 1] = value;",
        "proposed_test": tep.TEST_ID}], "missing_conditions": []}
    normal = tep.validate_analysis(raw, sources, context)
    unsupported_raw = copy.deepcopy(raw)
    unsupported_raw["cards"][1]["proposed_test"] = "degraded_cooling"
    unsupported = tep.validate_analysis(unsupported_raw, sources, context)
    paper = tep.load_sources(ROOT / "data/sources/paper-sources.json")[1]
    insufficient_raw = {"cards": [{**support, "source_id": paper["source_id"], "claim": "인산·증기 연구와 TEP 공정의 유체·운전 조건 대응을 확인하지 못했다.",
        "excerpt": paper["text"].split("\n\n")[0][:400], "evidence_purpose": "physical_mechanism", "applicability": "partial",
        "missing_conditions": ["TEP 운전 모드·유체·변수 적용 범위 미확인"]}], "missing_conditions": []}
    insufficient = tep.validate_analysis(insufficient_raw, [*sources, paper], context)
    failed = TEPEvidenceReview(model_version=simulator.MODEL_VERSION, initial_profile=context["initial_profile"],
        mock=False, status="failed", missing_conditions=["REVIEW_FAILED:llm_review"], limitation=tep.LIMITATION + " 검토 실패 단계: llm_review.")
    result = {name: review.model_copy(update={"limitation": "자동 계약 검증 예시 · 실제 LLM 미호출. " + review.limitation}).model_dump()
        for name, review in (("normal.json", normal), ("insufficient.json", insufficient), ("unsupported.json", unsupported), ("failed.json", failed))}
    result["manifest.json"] = {"example_only": True, "llm_executed": False, "simulation_executed": False,
        "request": request.model_dump(), "meaning": "normal is model-definition mapping validation, not paper applicability or safety proof"}
    return result


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, result in examples().items():
        (OUTPUT / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
