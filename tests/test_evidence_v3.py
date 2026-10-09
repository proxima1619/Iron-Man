from pathlib import Path
import pytest
from backend.contracts import NewRequest, Command, Snapshot
from backend.evidence import llm, service, papers
from backend.evidence.context import review_context
from backend.gateway.service import Gateway
from backend.simulator import service as simulator
from tests.test_evidence import output


@pytest.fixture(autouse=True)
def local_source(monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "live")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    monkeypatch.delenv("IRON_MAN_EVIDENCE_SOURCE_PATH", raising=False)


def test_review_after_virtual_time_uses_new_temperature_actual_and_targets(monkeypatch):
    captured = []
    monkeypatch.setattr(llm, "analyze", lambda payload: captured.append(payload) or output())
    with_gateway = Gateway()
    try:
        command = Command(target_pct=60)
        initial = with_gateway.adapter.read_state()
        with_gateway.adapter.apply_command("test-v3-only", command)
        with_gateway.adapter.advance_time(30)
        changed = with_gateway.adapter.read_state()
        assert changed.temperature_c != initial.temperature_c
        assert changed.pump_speed_pct != changed.target_pump_speed_pct
        review = service.review_evidence(NewRequest(command=Command(target_pct=80)), changed)
        context = captured[0]["review_context"]
        assert context["temperature_c"] == changed.temperature_c
        assert context["actual_pump_speed_pct"] == changed.pump_speed_pct
        assert context["current_target_pump_speed_pct"] == 60
        assert context["requested_target_pump_speed_pct"] == 80
        assert context["simulation_time_s"] == 30
        assert context["supported_tests"][0]["efficiency"] == simulator.DEGRADED_EFFICIENCY
        assert context["model_version"] == simulator.MODEL_VERSION
        assert review.proposed_tests[0].evidence_id == review.cards[0].evidence_id
        assert "기존 목표 60%" in review.limitation and "요청 목표 80%" in review.limitation
    finally:
        with_gateway.close()


def test_legacy_snapshot_target_fallback_is_explicit():
    snapshot = Snapshot(revision=1, temperature_c=60, load_ratio=1, pump_speed_pct=75, observed_at=1)
    context = review_context(NewRequest(command=Command(target_pct=60)), snapshot)
    assert context["current_target_pump_speed_pct"] == 75
    assert context["current_target_origin"] == "legacy_actual_speed_fallback"


def test_unsupported_state_returns_insufficient_before_llm(monkeypatch):
    snapshot = Snapshot(revision=1, temperature_c=130, load_ratio=1, pump_speed_pct=75, observed_at=1)
    monkeypatch.setattr(llm, "analyze", lambda *args: pytest.fail("Unexpected LLM call"))
    result = service.review_evidence(NewRequest(command=Command(target_pct=60)), snapshot)
    assert result.status == "insufficient" and "temperature_c" in result.limitation


@pytest.mark.parametrize("field,value", [("efficiency", 0.2), ("proposed_test", "pump_failure")])
def test_new_failure_or_parameter_requires_contract_not_execution(field, value):
    raw = output()
    raw["cards"][0][field] = value
    with pytest.raises(ValueError):
        service.validate_analysis(raw, service.load_sources())


def test_evidence_id_stable_when_card_order_changes():
    sources = service.load_sources()
    raw = output()
    another = {**raw["cards"][0], "claim": "another supported claim", "proposed_test": None}
    first = service.validate_analysis({"cards": [raw["cards"][0], another], "missing_conditions": []}, sources)
    second = service.validate_analysis({"cards": [another, raw["cards"][0]], "missing_conditions": []}, sources)
    assert first.cards[0].evidence_id == second.cards[1].evidence_id
    assert first.proposed_tests[0].evidence_id == second.proposed_tests[0].evidence_id


def test_real_time_retrieval_mode_calls_provider_and_preserves_ids(monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "europepmc")
    sources = service.load_sources()
    captured = []
    monkeypatch.setattr(papers, "retrieve_papers", lambda query: captured.append(query) or sources)
    monkeypatch.setattr(llm, "analyze", lambda payload: output())
    gateway = Gateway()
    try:
        result = service.review_evidence(NewRequest(command=Command(target_pct=60)), gateway.adapter.read_state())
        assert captured and "실시간 Europe PMC" in result.limitation
        assert result.proposed_tests[0].evidence_id == result.cards[0].evidence_id
    finally:
        gateway.close()


def test_paper_mismatch_is_insufficient_and_not_a_counterexample(monkeypatch):
    sources = service.load_sources(Path("data/sources/paper-sources.json"))
    raw = {"cards": [{"source_id": sources[0]["source_id"], "claim": "Different equipment conditions",
        "stance": "limitation", "excerpt": sources[0]["text"].split("\n\n")[0][:200],
        "applicability": "mismatch", "matched_conditions": [],
        "missing_conditions": ["rpm to percent mapping and same fluid not verified"], "proposed_test": None}],
        "missing_conditions": []}
    review = service.validate_analysis(raw, sources)
    assert review.status == "insufficient" and not review.proposed_tests
    assert "공개 논문" in review.limitation and "rpm to percent" in review.limitation


def test_fixture_example_preserves_v3_values_and_is_not_live_claim():
    import json
    from backend.contracts import EvidenceReview
    example = json.loads(Path("fixtures/evidence-v3-example.json").read_text(encoding="utf-8"))
    assert example["example_only"] is True and example["llm_executed"] is False
    snapshot = Snapshot.model_validate(example["snapshot"])
    assert snapshot.temperature_c > 60 and snapshot.pump_speed_pct > snapshot.target_pump_speed_pct
    review = EvidenceReview.model_validate(example["evidence"])
    assert review.mock is True
    assert "기존 목표 60%" in review.limitation and "요청 목표 80%" in review.limitation
