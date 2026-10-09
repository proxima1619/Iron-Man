import json
import pytest
from backend.contracts import EvidenceReview, NewRequest
from backend.evidence import service, llm
from backend.evidence.validation import verify_review_sources
from backend.gateway.service import Gateway
from scripts.export_evidence_handoff import examples, OUTPUT
from tests.test_evidence import output


@pytest.mark.parametrize("name,status", [("normal", "completed"), ("insufficient", "insufficient"),
                                       ("failed", "failed"), ("unsupported-test", "insufficient")])
def test_shared_examples_follow_exact_contract(name, status):
    review = EvidenceReview.model_validate_json((OUTPUT / f"{name}.json").read_text(encoding="utf-8"))
    assert review.status == status and "실제 LLM 미호출" in review.limitation
    if status != "completed":
        assert not review.proposed_tests
    if name == "normal":
        assert not verify_review_sources(review, service.load_sources(service.SOURCE_PATH))


def test_generation_reproduces_committed_examples():
    for name, result in examples().items():
        assert json.loads((OUTPUT / name).read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("field,value", [("source_id", "invented"), ("title", "forged"),
                                       ("excerpt", "not in document"), ("source_url", "https://example.com")])
def test_independent_source_check_rejects_tampered_card(field, value):
    sources = service.load_sources(service.SOURCE_PATH)
    review = service.validate_analysis(output(), sources)
    data = review.model_dump()
    data["cards"][0][field] = value
    altered = EvidenceReview.model_validate(data)
    assert verify_review_sources(altered, sources)


@pytest.mark.parametrize("name", ["elevated_coolant_temperature", "pump_failure", "execute_command"])
def test_unsupported_name_is_explicitly_unverified_and_never_executed(name):
    raw = output()
    raw["cards"][0]["proposed_test"] = name
    review = service.validate_analysis(raw, service.load_sources(service.SOURCE_PATH))
    assert review.status == "insufficient" and not review.proposed_tests
    assert review.cards[0].proposed_test is None
    assert name in review.limitation and "검증하지 못함" in review.limitation
    assert "2번" in review.cards[0].missing_conditions[0]


def test_blank_condition_match_is_insufficient():
    raw = output()
    raw["cards"][0]["matched_conditions"] = []
    assert service.validate_analysis(raw, service.load_sources(service.SOURCE_PATH)).status == "insufficient"


@pytest.mark.parametrize("stage", ["source_collection", "llm_review", "output_validation"])
def test_failure_stage_visible_without_provider_secrets(monkeypatch, stage):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "live")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    def fail(*args): raise TimeoutError("private_key_private_provider_body")
    if stage == "source_collection":
        monkeypatch.setattr(service, "load_sources", fail)
    elif stage == "llm_review":
        monkeypatch.setattr(llm, "analyze", fail)
    else:
        monkeypatch.setattr(llm, "analyze", lambda payload: {"unexpected": True})
    gateway = Gateway()
    try:
        result = service.review_evidence(NewRequest(
            command={"target_pct": 60}), gateway.adapter.read_state())
        assert result.status == "failed" and stage in result.limitation
        assert "private_key" not in result.limitation
    finally:
        gateway.close()


def test_simulator_assumption_and_unchanged_inputs_visible():
    from backend.evidence.context import review_context
    gateway = Gateway()
    try:
        context = review_context(NewRequest(command={"target_pct": 60}), gateway.adapter.read_state())
        scenario = context["supported_tests"][0]
        assert scenario["normal_efficiency"] == 1.0 and scenario["efficiency"] == 0.65
        assert scenario["parameter_origin"] == "demo_assumption"
        assert scenario["unchanged"] == ["pump_response_s", "load_ratio", "coolant_temperature_c"]
        assert "specific_failure" in scenario["meaning"]
    finally:
        gateway.close()
