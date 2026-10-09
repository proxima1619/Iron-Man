"""TEP evidence contract tests; scripted model output is not live LLM inference."""
import json
from types import SimpleNamespace
import pytest
from backend.contracts import NewRequest, TEPEvidenceReview, RequestRecord, DecisionInput, ExecutionInput
from backend.evidence import tep as evidence
from backend.evidence import llm
from backend.evidence.feedback import review_record
from backend.simulator.tep import service as simulator
from backend.gateway.service import Gateway
from fastapi import HTTPException


def request():
    return NewRequest(equipment_id="tep-sim-01", command={"type": "set_tep_cooling_water", "variable": "XMV10", "value": 42,
                                                      "duration_s": 60, "sample_period_s": 10})


def inputs():
    data = evidence.registry()
    context = {"model_version": simulator.MODEL_VERSION, "initial_profile": "nist-teinit-base-case-v1",
               "configuration": simulator.configuration(request().command).model_dump(),
               "requested_variable": "XMV10", "variables": data["variables"]}
    return evidence.model_sources(data), context


def analysis():
    sources, _ = inputs()
    support = {"source_id": "tep-variable-contract", "claim": "선정한 TEP 변수·시험 정의를 확인했다.",
        "stance": "support", "excerpt": '"model_version": "' + simulator.MODEL_VERSION + '"',
        "applicability": "applicable", "matched_conditions": ["XMV10 percent_full_scale, 원래 초기화와 외란 없는 시험"],
        "missing_conditions": [], "proposed_test": None, "evidence_purpose": "model_definition", "variable_ids": ["XMV10"]}
    counter = {**support, "source_id": "tep-wrapper", "stance": "counter", "claim": "설정 변경을 기준 유지와 비교하되 고장 시험으로 간주하지 않는다.",
        "excerpt": "inputs[index - 1] = value;", "proposed_test": evidence.TEST_ID}
    assert support["excerpt"] in sources[0]["text"]
    return {"cards": [support, counter], "missing_conditions": []}


def result_stub():
    # Only unit-test orchestration; these empty point stubs are never a TEPResult or physics proof.
    point = SimpleNamespace(model_dump=lambda: {"unit_test_stub": True})
    return SimpleNamespace(status="completed", model_version=simulator.MODEL_VERSION,
        configuration=simulator.configuration(request().command), variables=simulator.VARIABLES,
        data_origin="simulation", field_validation="not_performed_no_measured_data", provenance=None,
        baseline=SimpleNamespace(points=[point]), candidate=SimpleNamespace(points=[point]), comparison={})


def test_tep_context_uses_native_units_and_no_pump_assumptions():
    context = evidence.review_context(request(), simulator.snapshot(1), result_stub(), evidence.registry())
    assert context["variable_definition"]["unit"] == "percent_full_scale"
    assert context["baseline_value"] == simulator.INITIAL_XMV[9]
    assert context["delta"] == 42 - simulator.INITIAL_XMV[9]
    assert context["normal_operating_range"] is None and context["safety_allowed_range"] is None
    assert context["configuration"]["controller"] == "none_open_loop_hold"
    assert "efficiency" not in json.dumps(context) and "degraded_cooling" not in json.dumps(context)


def test_supported_mapping_copies_server_configuration_and_checks_sources():
    sources, context = inputs()
    review = evidence.validate_analysis(analysis(), sources, context)
    assert review.status == "completed" and len(review.proposed_tests) == 1
    test = review.proposed_tests[0]
    assert test.configuration == simulator.configuration(request().command)
    assert test.evidence_id == review.cards[1].evidence_id
    assert not evidence.verify_review_sources(review, sources, context)


@pytest.mark.parametrize("name", ["degraded_cooling", "pump_failure", "idv_1"])
def test_unregistered_faults_are_unverified_not_executable(name):
    sources, context = inputs()
    raw = analysis()
    raw["cards"][1]["proposed_test"] = name
    review = evidence.validate_analysis(raw, sources, context)
    assert review.status == "insufficient" and not review.proposed_tests
    assert review.unsupported_tests[0].requested_test == name
    assert "검증하지 못함" in review.unsupported_tests[0].reason


@pytest.mark.parametrize("mutation", ["quote", "variable", "purpose", "parameter", "source", "no_conditions"])
def test_forged_quote_definition_or_parameter_rejected(mutation):
    sources, context = inputs()
    raw = analysis()
    card = raw["cards"][1]
    if mutation == "quote": card["excerpt"] = "not found"
    if mutation == "variable": card["variable_ids"] = ["PUMP_SPEED"]
    if mutation == "purpose": card["evidence_purpose"] = "safety_basis"
    if mutation == "parameter": card["efficiency"] = 0.65
    if mutation == "source": card["source_id"] = "team-demo-note"
    if mutation == "no_conditions": card["matched_conditions"] = []
    with pytest.raises(ValueError): evidence.validate_analysis(raw, sources, context)


def test_papers_cannot_define_model_or_safety_ranges():
    sources, context = inputs()
    paper = {**sources[0], "source_id": "paper-example", "source_type": "paper"}
    raw = analysis()
    raw["cards"][0]["source_id"] = paper["source_id"]
    with pytest.raises(ValueError): evidence.validate_analysis(raw, [*sources, paper], context)
    raw["cards"][0].update(evidence_purpose="physical_mechanism", applicability="partial",
                          missing_conditions=["설비·유체 대응 미확인"])
    assert evidence.validate_analysis(raw, [*sources, paper], context).status == "insufficient"


def test_wrong_requested_variable_has_no_mapping():
    sources, context = inputs()
    raw = analysis()
    raw["cards"][1]["variable_ids"] = ["XMV11"]
    assert not evidence.validate_analysis(raw, sources, context).proposed_tests


@pytest.mark.parametrize("field,value", [("excerpt", "invented"), ("title", "forged"), ("source_url", "https://example.com")])
def test_server_recheck_rejects_tampering(field, value):
    sources, context = inputs()
    data = evidence.validate_analysis(analysis(), sources, context).model_dump()
    data["cards"][0][field] = value
    assert evidence.verify_review_sources(TEPEvidenceReview.model_validate(data), sources, context)


def test_live_flow_uses_tep_prompt_not_pump_prompt(monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "live")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    captured = {}
    def analyze(payload, **kwargs):
        captured.update(payload=payload, kwargs=kwargs)
        return analysis()
    monkeypatch.setattr(llm, "analyze", analyze)
    result = evidence.review_evidence(request(), simulator.snapshot(1), result_stub())
    assert result.status == "completed"
    assert captured["kwargs"]["base_instructions"] == evidence.INSTRUCTIONS
    assert all(s["source_type"] in {"model_source", "paper"} for s in captured["payload"]["documents"])


def test_failure_and_fixture_never_reuse_cooling_review(monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    fixture = evidence.review_evidence(request(), simulator.snapshot(1), result_stub())
    assert fixture.mock and fixture.status == "demo_fixture" and not fixture.proposed_tests
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "live")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    def fail(*args, **kwargs): raise TimeoutError("private-provider-secret")
    monkeypatch.setattr(llm, "analyze", fail)
    failed = evidence.review_evidence(request(), simulator.snapshot(1), result_stub())
    assert failed.status == "failed" and "llm_review" in failed.limitation
    assert "private-provider-secret" not in failed.model_dump_json()


def test_failed_simulation_preserves_result_and_denies_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("IRON_MAN_TEP_ENGINE_DIR", str(tmp_path / "missing"))
    gateway = Gateway(tmp_path / "db.sqlite3")
    try:
        row = gateway.evaluate(gateway.create(request())["id"])
        record = RequestRecord.model_validate(row)
        assert record.report.tep_simulation.status == "failed"
        assert record.report.tep_evidence.status == "insufficient"
        assert record.status == "hold" and not record.report.can_approve and record.report.evidence is None
        with pytest.raises(HTTPException): gateway.decide(row["id"], DecisionInput(decision="approve", reason="test", report_digest=record.report.digest), "approver")
        with pytest.raises(HTTPException): gateway.execute(row["id"], ExecutionInput(report_digest=record.report.digest))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(HTTPException, match="409"): review_record(record)
    finally: gateway.close()


def test_registry_version_mismatch_is_rejected(monkeypatch, tmp_path):
    data = evidence.registry()
    data["variables"]["XMV10"]["unit"] = "rpm"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("IRON_MAN_TEP_CONTRACT_PATH", str(path))
    with pytest.raises(ValueError): evidence.registry()


def test_examples_are_reproducible_and_explicitly_not_live():
    from scripts.export_tep_evidence_examples import examples, OUTPUT
    for name, value in examples().items():
        assert json.loads((OUTPUT / name).read_text(encoding="utf-8")) == value
        if name != "manifest.json":
            review = TEPEvidenceReview.model_validate(value)
            assert "실제 LLM 미호출" in review.limitation


def test_independent_check_rejects_changed_proposal_setting():
    sources, context = inputs()
    data = evidence.validate_analysis(analysis(), sources, context).model_dump()
    data["proposed_tests"][0]["configuration"]["candidate_value"] = 43
    assert "proposal_configuration_mismatch" in evidence.verify_review_sources(TEPEvidenceReview.model_validate(data), sources, context)


def test_invalid_llm_quote_returns_output_validation_failure(monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "live")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    raw = analysis()
    raw["cards"][0]["excerpt"] = "fabricated"
    monkeypatch.setattr(llm, "analyze", lambda *args, **kwargs: raw)
    failed = evidence.review_evidence(request(), simulator.snapshot(1), result_stub())
    assert failed.status == "failed" and "output_validation" in failed.limitation
    assert not failed.cards and not failed.proposed_tests


def test_wrong_profile_identity_fails_before_llm(monkeypatch):
    monkeypatch.setattr(llm, "analyze", lambda *args, **kwargs: pytest.fail("must not call LLM"))
    snapshot = simulator.snapshot(1).model_copy(update={"model_version": "other-model"})
    failed = evidence.review_evidence(request(), snapshot, result_stub())
    assert failed.status == "failed" and "context_validation" in failed.limitation
