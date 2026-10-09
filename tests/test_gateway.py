import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.gateway.service import Gateway
from backend.simulator import service as simulator
from backend.evidence import service as evidence

OP = {"Authorization": "Bearer local-operator"}
APP = {"Authorization": "Bearer local-approver"}

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "local-operator")
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "local-approver")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    gateway = Gateway(tmp_path / "test.sqlite3")
    gateway.adapter.update_demo_state(.6, "valid")  # Explicit safe load for approval lifecycle tests.
    # Existing module/policy tests use the synchronous helper; real async API tests are separate.
    monkeypatch.setattr(gateway, "submit_evaluation", gateway.evaluate)
    monkeypatch.setattr(main, "gateway", gateway)
    yield TestClient(main.app)
    gateway.close()

def evaluated(client, speed=80):
    response = client.post('/requests', headers=OP, json={"command": {"target_pct": speed}})
    assert response.status_code == 201
    row = response.json()
    return client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={}).json()

def approve(client, row):
    response = client.post(f'/requests/{row["id"]}/decisions', headers=APP,
        json={"decision": "approve", "reason": "demo only", "report_digest": row['report']['digest']})
    assert response.status_code == 200
    return response.json()

def execute(client, row):
    return client.post(f'/requests/{row["id"]}/execute', headers=OP,
        json={"report_digest": row['report']['digest']})

def test_approved_virtual_execution_and_retry(client):
    row = approve(client, evaluated(client))
    first = execute(client, row)
    second = execute(client, row)
    assert first.status_code == second.status_code == 200
    assert first.json()['status'] == 'completed'
    assert first.json()['execution'] == second.json()['execution']
    assert len(main.gateway.adapter.executions) == 1

def test_execution_without_approval(client):
    assert execute(client, evaluated(client)).status_code == 409
    assert not main.gateway.adapter.executions

def test_counterexample_blocks_and_cannot_be_approved(client):
    main.gateway.adapter.update_demo_state(1, "valid")
    row = evaluated(client, 60)
    scenarios = row['report']['simulation']['scenarios']
    assert scenarios[0]['exceeded'] is False
    assert scenarios[1]['exceeded'] is True
    assert row['status'] == 'blocked'
    response = client.post(f'/requests/{row["id"]}/decisions', headers=APP,
        json={"decision": "approve", "reason": "override", "report_digest": row['report']['digest']})
    assert response.status_code == 409
    assert not main.gateway.adapter.executions

def test_server_checks_approver_role(client):
    row = evaluated(client)
    response = client.post(f'/requests/{row["id"]}/decisions', headers=OP,
        json={"decision": "approve", "reason": "try", "report_digest": row['report']['digest']})
    assert response.status_code == 403
    assert client.post('/requests', json={"command":{"target_pct":80}}).status_code == 401

@pytest.mark.parametrize('change', ['state', 'command', 'model', 'expiry', 'report'])
def test_changed_approval_context_denies_execution(client, monkeypatch, change):
    row = approve(client, evaluated(client))
    stored = main.gateway.get(row['id'])
    if change == 'state':
        main.gateway.adapter.update_demo_state(1.2, 'valid')
    elif change == 'command':
        stored['request']['command']['target_pct'] = 30
    elif change == 'model':
        monkeypatch.setattr(simulator, 'MODEL_VERSION', 'v2')
    elif change == 'expiry':
        stored['approval']['expires_at'] = time.time() - 1
    else:
        stored['report']['reason'] = 'tampered'
    main.gateway.store.save(stored)
    assert execute(client, row).status_code == 409
    assert main.gateway.get(row['id'])['status'] == 'revalidation_required'
    assert not main.gateway.adapter.executions

def test_invalid_sensor_holds(client):
    main.gateway.adapter.update_demo_state(1, 'invalid')
    assert evaluated(client)['status'] == 'hold'

@pytest.mark.parametrize('module', [evidence, simulator])
def test_dependency_failure_holds(client, monkeypatch, module):
    def fail(*args):
        raise RuntimeError('fixture outage')
    name = 'review_evidence' if module is evidence else 'simulate'
    monkeypatch.setattr(module, name, fail)
    row = evaluated(client)
    assert row['status'] == 'hold'
    assert execute(client, row).status_code == 409
    assert not main.gateway.adapter.executions

def test_uncertain_execution_is_not_retried(client, monkeypatch):
    row = approve(client, evaluated(client))
    calls = []
    def fail(*args):
        calls.append(args)
        raise TimeoutError('lost response')
    monkeypatch.setattr(main.gateway.adapter, 'apply_command', fail)
    assert execute(client, row).json()['status'] == 'execution_unknown'
    assert execute(client, row).status_code == 409
    assert len(calls) == 1

def test_concurrent_duplicate_execution_applies_once(client):
    row = approve(client, evaluated(client))
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: execute(client, row), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert len(main.gateway.adapter.executions) == 1

@pytest.mark.parametrize('speed', [-1, 101])
def test_invalid_command(client, speed):
    assert client.post('/requests', headers=OP, json={'command': {'target_pct': speed}}).status_code == 422

def test_re_evaluation_invalidates_old_report(client):
    row = evaluated(client)
    client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={})
    response = client.post(f'/requests/{row["id"]}/decisions', headers=APP,
        json={"decision": "approve", "reason": "stale", "report_digest": row['report']['digest']})
    assert response.status_code == 409
