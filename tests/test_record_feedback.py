"""Historical explanations remain available without trusting invalid citations."""
import copy
import json
from types import SimpleNamespace
import pytest
from backend.contracts import Command, TEPCommand
from backend.evidence import feedback, service, llm
from backend.evidence.schema import RecordAnalysis


def output(sources):
    return {"summary": "저장된 결과를 설명합니다.",
        "result_interpretation": "당시 관측이 만료되어 계산하지 않았습니다.",
        "model_limitations": ["실측 검증 미완료"],
        "recommended_checks": ["새 계산은 새 요청으로 진행하세요."],
        "missing_conditions": [],
        "cards": [{"source_id": sources[0]["source_id"], "claim": "문헌의 적용 조건 확인 필요",
            "stance": "limitation", "excerpt": sources[0]["text"][:120],
            "applicability": "partial", "matched_conditions": [],
            "missing_conditions": ["현재 설비 적용성 미확인"], "proposed_test": None}]}


@pytest.mark.parametrize("invalid_field,value", [("excerpt", "fabricated excerpt"), ("source_id", "old-fixture")])
def test_invalid_citation_is_hidden_but_explanation_available(invalid_field, value):
    sources = service.load_sources()
    raw = output(sources)
    invalid = copy.deepcopy(raw["cards"][0])
    invalid[invalid_field] = value
    raw["cards"].append(invalid)
    review, gaps = feedback.validate_record_evidence(RecordAnalysis.model_validate(raw), sources)
    assert review.status == "insufficient" and not review.mock
    assert len(review.cards) == 1 and review.cards[0].excerpt != "fabricated excerpt"
    assert any("1건" in gap for gap in gaps)
    assert not review.proposed_tests


def test_all_invalid_citations_return_insufficient_without_cards():
    sources = service.load_sources()
    raw = output(sources)
    raw["cards"][0]["excerpt"] = "fabricated excerpt"
    review, gaps = feedback.validate_record_evidence(RecordAnalysis.model_validate(raw), sources)
    assert not review.cards and review.status == "insufficient"
    assert gaps


def test_historical_test_proposal_cannot_execute():
    sources = service.load_sources()
    raw = output(sources)
    raw["cards"][0].update(proposed_test="degraded_cooling", applicability="mismatch")
    review, gaps = feedback.validate_record_evidence(RecordAnalysis.model_validate(raw), sources)
    assert not review.proposed_tests
    assert review.cards[0].proposed_test is None
    assert any("시험 제안" in gap for gap in gaps)


@pytest.mark.parametrize("is_tep", [False, True])
def test_old_report_is_explained_without_reusing_old_evidence(monkeypatch, is_tep):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODEL", "test-model")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    report_data = {"reason_code": "INVALID_STATE", "snapshot": {"observed_at": 1},
                   "evidence": {"cards": [{"source_id": "old-fixture"}]},
                   "tep_evidence": {"cards": []}, "simulation": None}
    original = copy.deepcopy(report_data)
    report = SimpleNamespace(digest="saved-digest", model_dump=lambda: copy.deepcopy(report_data))
    record = SimpleNamespace(id="old-record", revision=1, status="hold", report=report,
        execution=None, request=SimpleNamespace(purpose="과거 기록 설명",
            command=TEPCommand(type="set_tep_cooling_water", variable="XMV10", value=42) if is_tep else Command(target_pct=80)))
    captured = {}
    def analyze(payload, **kwargs):
        captured.update(payload)
        return output(payload["documents"])
    monkeypatch.setattr(feedback.llm, "analyze", analyze)
    result = feedback.review_record(record)
    assert result.summary and result.report_digest == "saved-digest"
    assert captured["saved_record"]["report"]["snapshot"]["observed_at"] == 1
    assert "evidence" not in captured["saved_record"]["report"]
    assert "tep_evidence" not in captured["saved_record"]["report"]
    assert all(source["source_type"] == "paper" for source in captured["documents"])
    assert report_data == original


def test_record_transport_constrains_citations_to_supplied_passages(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODEL", "test-model")
    sources = service.load_sources()
    raw = output(sources)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            return json.dumps({"status": "completed", "output": [{"type": "message",
                "content": [{"type": "output_text", "text": json.dumps(raw)}]}]}).encode()
    def send(request, timeout):
        body = json.loads(request.data)
        properties = body["text"]["format"]["schema"]["$defs"]["Claim"]["properties"]
        assert properties["source_id"]["enum"] == [s["source_id"] for s in sources]
        quotes = properties["excerpt"]["enum"]
        assert all(any(quote in s["text"] for s in sources) and 0 < len(quote) <= 400 for quote in quotes)
        assert json.loads(body["input"])["citation_choices"]
        return Response()
    monkeypatch.setattr(llm, "urlopen", send)
    assert llm.analyze({"documents": sources}, output_schema=RecordAnalysis) == raw
