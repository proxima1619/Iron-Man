import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.main import app
from backend.contracts import EvidenceReview, SimulationResult, NewRequest, Snapshot, Scenario, RequestRecord
from backend.evidence.service import review_evidence
from backend.simulator.service import simulate
from tests.test_gateway import client, evaluated, execute
from backend.evidence import service as evidence
from backend.simulator import service as simulator

@pytest.fixture
def result_data():
    command = NewRequest(command={'target_pct':80})
    state = Snapshot(revision=1, temperature_c=60, load_ratio=1, pump_speed_pct=100, observed_at=1)
    return simulate(command.command, state, [Scenario(kind='normal')]).model_dump()

@pytest.mark.parametrize('problem', ['empty', 'nan', 'wrong_flag', 'extra', 'duplicate'])
def test_malformed_result_rejected(result_data, problem):
    if problem == 'empty':
        result_data['scenarios'] = []
    elif problem == 'nan':
        result_data['scenarios'][0]['candidate_peak_c'] = float('nan')
    elif problem == 'wrong_flag':
        result_data['scenarios'][0]['exceeded'] = True
    elif problem == 'extra':
        result_data['approve'] = True
    else:
        result_data['scenarios'] *= 2
    with pytest.raises(ValidationError):
        SimulationResult.model_validate(result_data)

def test_test_proposal_requires_existing_source():
    with pytest.raises(ValidationError):
        EvidenceReview(mock=True, status='demo_fixture', cards=[],
            proposed_tests=[Scenario(kind='degraded_cooling', evidence_id='invented')], limitation='fixture')

@pytest.mark.parametrize('status', ['insufficient', 'failed'])
def test_evidence_unavailable_holds(client, monkeypatch, status):
    monkeypatch.setattr(evidence, 'review_evidence', lambda *args: EvidenceReview(
        mock=False, status=status, limitation='unavailable'))
    def must_not_run(*args):
        pytest.fail('simulation must not run without required evidence')
    monkeypatch.setattr(simulator, 'simulate', must_not_run)
    row = evaluated(client)
    assert row['status'] == 'hold'
    assert row['report']['reason_code'] == 'EVIDENCE_INCOMPLETE'
    assert execute(client, row).status_code == 409

@pytest.mark.parametrize('status', ['out_of_domain', 'failed'])
def test_calculation_unavailable_holds(client, monkeypatch, status):
    monkeypatch.setattr(simulator, 'simulate', lambda *args: SimulationResult(
        mock=False, status=status, model_version=simulator.MODEL_VERSION, limitation='unavailable'))
    row = evaluated(client)
    assert row['status'] == 'hold'
    assert row['report']['simulation']['scenarios'] == []
    assert row['report']['reason_code'] == 'SIMULATION_INCOMPLETE'

def test_missing_counterexample_result_holds(client, monkeypatch):
    original = simulator.simulate
    monkeypatch.setattr(simulator, 'simulate', lambda command, snapshot, scenarios:
        original(command, snapshot, scenarios[:1]))
    row = evaluated(client)
    assert row['status'] == 'hold'
    assert row['report']['reason_code'] == 'MODULE_FAILURE'

def test_invalid_boundary_dictionary_holds(client, monkeypatch):
    monkeypatch.setattr(evidence, 'review_evidence', lambda *args: {'approved': True})
    assert evaluated(client)['report']['reason_code'] == 'MODULE_FAILURE'

def test_non_mock_module_does_not_implicitly_enable_execution(client, monkeypatch):
    original = simulator.simulate
    def real_shape(*args):
        data = original(*args).model_dump()
        data['mock'] = False
        for row in data['scenarios']:
            row['value_origin'] = 'model_calculation'
        return data
    monkeypatch.setattr(simulator, 'simulate', real_shape)
    row = evaluated(client)
    assert row['status'] == 'hold'
    assert row['report']['reason_code'] == 'LIVE_POLICY_NOT_CONFIGURED'

def test_published_schema_matches_backend():
    assert json.loads(Path('contracts/openapi.json').read_text(encoding='utf-8')) == app.openapi()

@pytest.mark.parametrize('path, model', [
    ('request-record-demo', RequestRecord), ('evidence-demo', EvidenceReview), ('evidence-insufficient', EvidenceReview),
    ('simulation-demo', SimulationResult), ('simulation-out-of-domain', SimulationResult),
])
def test_shared_example_validates(path, model):
    model.model_validate_json(Path(f'contracts/examples/{path}.json').read_text(encoding='utf-8'))
