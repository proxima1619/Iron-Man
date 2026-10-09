"""Owner 3: compatible fixture and validated pre-collected document review."""
import hashlib
import json
import os
from pathlib import Path
from backend.contracts import NewRequest, Snapshot, EvidenceReview, Scenario
from backend.evidence import llm
from backend.evidence.schema import Analysis

SOURCE_PATH = Path(__file__).resolve().parents[2] / "data" / "sources" / "cooling-demo.json"


def load_sources(path: Path | None = None) -> list[dict]:
    if path is None:
        path = Path(os.environ.get("IRON_MAN_EVIDENCE_SOURCE_PATH", str(SOURCE_PATH)))
    sources = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValueError("Invalid source collection")
    seen = set()
    required = {"source_id", "title", "publisher", "version", "published_at", "usage",
                "source_url", "source_type", "locator", "text"}
    for source in sources:
        if not isinstance(source, dict) or set(source) != required:
            raise ValueError("Invalid source metadata")
        if any(not isinstance(source[k], str) or not source[k].strip()
               for k in required - {"source_url"}):
            raise ValueError("Missing source metadata")
        if source["source_url"] is not None and not str(source["source_url"]).startswith("https://"):
            raise ValueError("Invalid source URL")
        if source["source_id"] in seen or len(source["text"]) > 10000:
            raise ValueError("Duplicate or oversized source")
        seen.add(source["source_id"])
    return sources


def validate_analysis(raw: dict, sources: list[dict]) -> EvidenceReview:
    analysis = Analysis.model_validate(raw)
    by_id = {source["source_id"]: source for source in sources}
    cards, tests = [], []
    for index, claim in enumerate(analysis.cards):
        source = by_id.get(claim.source_id)
        if source is None or claim.excerpt not in source["text"]:
            raise ValueError("Unknown source or fabricated quotation")
        if claim.applicability == "applicable" and claim.missing_conditions:
            raise ValueError("Contradictory applicability")
        if claim.proposed_test and (claim.stance == "support" or
                                   claim.applicability not in {"applicable", "partial"}):
            raise ValueError("Unsupported counterexample")
        evidence_id = f"evidence-{index + 1:02d}"
        card = claim.model_dump()
        card.update({key: source[key] for key in source if key != "text"})
        card["evidence_id"] = evidence_id
        card["parameter_origin"] = "demo_assumption" if claim.proposed_test else None
        cards.append(card)
        if claim.proposed_test and not tests:
            tests.append(Scenario(kind=claim.proposed_test, evidence_id=evidence_id))
    sufficient = bool(cards) and any(c["applicability"] in {"applicable", "partial"} for c in cards)
    sufficient = sufficient and not analysis.missing_conditions
    limitation = "사전 수집 문서의 실제 LLM 검토. 팀 작성 가상 설비 규정이며 실제 제조사 자료·현실 안전 검증이 아닙니다."
    if analysis.missing_conditions:
        limitation += " 미확인 조건: " + "; ".join(analysis.missing_conditions)
    fingerprint = hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    limitation += f" 문서 묶음 SHA256: {fingerprint}"
    return EvidenceReview(mock=False, status="completed" if sufficient else "insufficient",
                          cards=cards, proposed_tests=tests, limitation=limitation)

def review_evidence(request: NewRequest, snapshot: Snapshot) -> EvidenceReview:
    mode = os.environ.get("IRON_MAN_EVIDENCE_MODE", "fixture")
    if mode != "fixture":
        try:
            if mode != "live":
                raise ValueError("Unsupported evidence mode")
            sources = load_sources()
            if not sources:
                return EvidenceReview(mock=False, status="insufficient", cards=[], proposed_tests=[],
                                      limitation="사전 수집 문서에 관련 근거가 없습니다.")
            return validate_analysis(llm.analyze({"request": request.model_dump(),
                                                 "snapshot": snapshot.model_dump(),
                                                 "documents": sources}), sources)
        except Exception:
            return EvidenceReview(mock=False, status="failed", cards=[], proposed_tests=[],
                                  limitation="문서·LLM 검토 실패 또는 시간 초과. 실행을 보류하고 설정·출처를 확인하세요.")
    return EvidenceReview(mock=True, status="demo_fixture", cards=[{
        "evidence_id": "demo-evidence-01", "source_id": "team-demo-note",
        "title": "팀 작성 모의 운전 조건", "stance": "limitation",
        "claim": "냉각 효율 저하 조건을 추가 확인하는 흐름을 시연합니다.",
        "applicability": "unknown", "locator": "fixtures/demo-source.md",
        "source_url": None, "source_type": "team_authored_fixture",
    }], proposed_tests=[Scenario(kind="degraded_cooling", evidence_id="demo-evidence-01")],
        limitation="실제 검색·논문·LLM 검토가 아닙니다. 가상 설비 전용 모의 응답입니다.")
