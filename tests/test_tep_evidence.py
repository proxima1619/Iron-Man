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
    paper = {"source_id": "paper-example", "title": "Unit-test paper source", "text":
             "XMV10 response is described in the model. Model mismatch limits transfer to field operation.",
             "locator": "Unit-test abstract paragraphs 1-2", "source_url": "https://example.org/paper",
             "source_type": "paper", "publisher": "Unit-test publisher", "version": "test-v1",
             "published_at": "not_recorded", "usage": "Test text only; not a real publication"}
    return [*evidence.model_sources(data), paper], context


def analysis(sources=None):
    sources = sources if sources is not None else inputs()[0]
    paper = next(source for source in sources if source["source_type"] == "paper")
    model = next(source for source in sources if source["source_type"] == "model_source")
    if paper["source_id"] == "paper-example":
        support_excerpt = paper["text"].split(" Model mismatch", 1)[0]
        counter_excerpt = "Model mismatch limits transfer to field operation."
    else:
        support_excerpt = paper["text"][:200]
        counter_excerpt = paper["text"][-200:]
    definition_excerpt = '"model_version": "' + simulator.MODEL_VERSION + '"'
    support = {"source_id": paper["source_id"], "claim": "The paper discusses the requested input response.",
        "stance": "support", "excerpt": support_excerpt, "applicability": "applicable",
        "matched_conditions": ["XMV10", "percent_full_scale", "open-loop TEP"], "missing_conditions": [],
        "proposed_test": None, "evidence_purpose": "physical_mechanism", "variable_ids": ["XMV10"]}
    counter = {**support, "claim": "The paper states transfer limitations.", "stance": "counter",
        "excerpt": counter_excerpt, "proposed_test": evidence.TEST_ID}
    definition = {"source_id": model["source_id"], "claim": "The model registry pins the TEP variable definition.",
        "stance": "limitation", "excerpt": definition_excerpt, "applicability": "applicable",
        "matched_conditions": ["pinned model version", "XMV10 unit definition"], "missing_conditions": [],
        "proposed_test": None, "evidence_purpose": "model_definition", "variable_ids": ["XMV10"]}
    return {"cards": [support, counter, definition], "missing_conditions": []}


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


def test_model_definition_source_cannot_be_cited_as_paper_mechanism():
    sources, context = inputs()
    raw = analysis(sources)
    raw["cards"][0]["source_id"] = next(source["source_id"] for source in sources
                                            if source["source_type"] == "model_source")
    with pytest.raises(ValueError): evidence.validate_analysis(raw, sources, context)


def test_model_definitions_cannot_replace_missing_paper_support_and_counter():
    sources, context = inputs()
    raw = analysis(sources)
    raw["cards"] = [raw["cards"][-1]]
    review = evidence.validate_analysis(raw, sources, context)
    assert review.status == "insufficient"
    assert any("support" in value for value in review.missing_conditions)
    assert any("counter" in value for value in review.missing_conditions)


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
        return analysis(payload["documents"])
    monkeypatch.setattr(llm, "analyze", analyze)
    result = evidence.review_evidence(request(), simulator.snapshot(1), result_stub())
    assert result.status == "completed"
    assert captured["kwargs"]["base_instructions"] == evidence.INSTRUCTIONS + "\n" + evidence.SOURCE_ROLE_INSTRUCTIONS
    source_types = {s["source_type"] for s in captured["payload"]["documents"]}
    assert {"model_source", "simulation_record"} <= source_types
    simulation = next(s for s in captured["payload"]["documents"] if s["source_type"] == "simulation_record")
    assert "comparison" in simulation["text"] and "baseline_value" in simulation["text"]
    assert "not field measurements" in simulation["usage"]


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
