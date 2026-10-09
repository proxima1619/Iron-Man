"""Owner 3: replace with actual source retrieval and structured LLM review."""
from backend.contracts import NewRequest, Snapshot, EvidenceReview, Scenario

def review_evidence(request: NewRequest, snapshot: Snapshot) -> EvidenceReview:
    return EvidenceReview(cards=[{
        "evidence_id": "demo-evidence-01", "source_id": "team-demo-note",
        "title": "팀 작성 모의 운전 조건", "stance": "limitation",
        "claim": "냉각 효율 저하 조건을 추가 확인하는 흐름을 시연합니다.",
        "applicability": "unknown", "locator": "fixtures/demo-source.md",
        "source_url": None, "source_type": "team_authored_fixture",
    }], proposed_tests=[Scenario(kind="degraded_cooling", evidence_id="demo-evidence-01")],
        limitation="실제 검색·논문·LLM 검토가 아닙니다. 가상 설비 전용 모의 응답입니다.")
