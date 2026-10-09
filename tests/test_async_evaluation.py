"""Real spawn-process jobs and responsive API tests (no synchronous endpoint override)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import time
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import main
from backend.contracts import NewRequest, DecisionInput
from backend.gateway.evaluation import calculate, process_worker
from backend.gateway.service import Gateway
from tests.test_gateway import OP, APP

# Spawn targets must be module-level functions. File gates make test order deterministic.
def gated_worker(context, output):
    directory = Path(context['request']['purpose'])
    (directory / 'started').touch()
    while not (directory / 'release').exists():
        time.sleep(0.01)
    process_worker(context, output)

def crash_worker(context, output):
    os._exit(17)

def invalid_worker(context, output):
    output.send({'approved': True})
    output.close()

def wrong_input_worker(context, output):
    report = calculate(context)
    report['command_digest'] = 'wrong-command'
    output.send(report)
    output.close()

def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    pytest.fail('Timed out waiting for process condition')

def finished(gateway, request_id):
    row = gateway.get(request_id)
    return row if row['status'] != 'evaluating' else None

@pytest.fixture
def setup(tmp_path, monkeypatch):
    gateway = Gateway(tmp_path / 'async.sqlite3', worker_target=gated_worker)
    monkeypatch.setattr(main, 'gateway', gateway)
    monkeypatch.setenv('IRON_MAN_OPERATOR_TOKEN', 'local-operator')
    monkeypatch.setenv('IRON_MAN_APPROVER_TOKEN', 'local-approver')
    client = TestClient(main.app)
    yield gateway, client, tmp_path
    gateway.close()

def start(setup, name='one'):
    gateway, client, root = setup
    gate = root / name
    gate.mkdir()
    row = client.post('/requests', headers=OP, json={'command':{'target_pct':60}, 'purpose':str(gate)}).json()
    response = client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={})
    assert response.status_code == 202
    running = response.json()
    assert running['status'] == 'evaluating' and running['report'] is None
    assert running['evaluation']['status'] == 'running'
    wait_for(lambda: (gate / 'started').exists())
    return running, gate

def test_read_create_other_evaluation_while_worker_is_blocked(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    # Independent HTTP operations finish before we release the first worker.
    with ThreadPoolExecutor() as pool:
        response = pool.submit(client.get, f'/requests/{row["id"]}', headers=OP).result(timeout=2)
        assert response.json()['status'] == 'evaluating'
        assert pool.submit(client.get, '/state', headers=OP).result(timeout=2).status_code == 200
        assert pool.submit(client.get, '/requests', headers=OP).result(timeout=2).status_code == 200
    second, second_gate = start(setup, 'two')
    assert gateway.get(row['id'])['status'] == 'evaluating'
    second_gate.joinpath('release').touch()
    wait_for(lambda: finished(gateway, second['id']))
    assert gateway.get(row['id'])['status'] == 'evaluating'
    gate.joinpath('release').touch()
    final = wait_for(lambda: finished(gateway, row['id']))
    assert final['status'] == 'blocked'
    assert final['evaluation']['status'] == 'completed'

def test_duplicate_evaluation_and_decision_are_rejected(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    assert client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={}).status_code == 409
    assert client.post(f'/requests/{row["id"]}/decisions', headers=APP,
        json={'decision':'approve','report_digest':'old','reason':'try'}).status_code == 409
    assert client.post(f'/requests/{row["id"]}/execute', headers=OP,
        json={'report_digest':'old'}).status_code == 409
    assert gateway.get(row['id'])['revision'] == row['revision']

@pytest.mark.parametrize('change', ['state', 'model', 'policy', 'snapshot_age'])
def test_context_change_cannot_produce_approval(setup, monkeypatch, change):
    gateway, client, root = setup
    row, gate = start(setup)
    if change == 'state':
        client.post('/demo/state', headers=APP, json={'load_ratio':1.2})
    elif change == 'model':
        monkeypatch.setattr('backend.gateway.service.simulator.MODEL_VERSION', 'changed')
    elif change == 'policy':
        monkeypatch.setattr('backend.gateway.service.POLICY_VERSION', 'changed')
    else:
        monkeypatch.setattr('backend.gateway.service.SNAPSHOT_TTL_S', 0)
    gate.joinpath('release').touch()
    final = wait_for(lambda: finished(gateway, row['id']))
    assert final['status'] == 'hold'
    assert final['report']['reason_code'] == 'EVALUATION_CONTEXT_CHANGED'
    assert final['report']['can_approve'] is False

def test_capacity_is_bounded_and_rejects_without_changing_request(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    second, other = start(setup, 'two')
    third = gateway.create(NewRequest(command={'target_pct':60}))
    response = client.post(f'/requests/{third["id"]}/evaluate', headers=OP, json={})
    assert response.status_code == 429 and response.headers['retry-after'] == '1'
    assert gateway.get(third['id'])['status'] == 'draft'
    assert len(gateway.evaluations.jobs) == 2

def test_cancel_releases_worker_and_next_evaluation_runs(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    response = client.post(f'/requests/{row["id"]}/evaluation/cancel', headers=OP, json={})
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled['evaluation']['status'] == 'cancelled'
    assert cancelled['report']['reason_code'] == 'EVALUATION_CANCELLED'
    assert not gateway.evaluations.jobs
    gate.joinpath('release').touch()
    fresh = client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={})
    assert fresh.status_code == 202
    final = wait_for(lambda: finished(gateway, row['id']))
    assert final['revision'] > cancelled['revision']
    assert final['status'] == 'blocked'
    assert len(gateway.history(row['id'])['reports']) == 2

def test_late_result_does_not_overwrite_newer_revision(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    context = dict(next(iter(gateway.evaluations.jobs.values())).context)
    client.post(f'/requests/{row["id"]}/evaluation/cancel', headers=OP, json={})
    new = gateway.get(row['id'])
    new['revision'] += 1
    new['status'] = 'draft'
    gateway.store.save(new)
    gateway._finish_evaluation(context, calculate(context))
    assert gateway.get(row['id']) == new

@pytest.mark.parametrize('target,code', [(crash_worker,'WORKER_FAILURE'),
    (invalid_worker,'WORKER_FAILURE'), (wrong_input_worker,'WORKER_FAILURE')])
def test_process_failure_or_bad_report_holds(tmp_path, target, code):
    gateway = Gateway(tmp_path / 'failure.sqlite3', worker_target=target)
    try:
        row = gateway.create(NewRequest(command={'target_pct':60}))
        gateway.submit_evaluation(row['id'])
        final = wait_for(lambda: finished(gateway, row['id']))
        assert final['evaluation']['status'] == 'failed'
        assert final['report']['reason_code'] == code
    finally:
        gateway.close()

def test_timeout_terminates_child_and_capacity_is_reusable(tmp_path):
    gate = tmp_path / 'gate'
    gate.mkdir()
    gateway = Gateway(tmp_path / 'timeout.sqlite3', evaluation_timeout_s=1,
                      worker_target=gated_worker, max_evaluations=1)
    try:
        row = gateway.create(NewRequest(command={'target_pct':60}, purpose=str(gate)))
        with gateway.lock:
            running = gateway.submit_evaluation(row['id'])
            job = gateway.evaluations.jobs[running['evaluation']['id']]
            assert job.process.pid is not None
        # The deadline includes Windows spawn startup; the child need not reach
        # its marker before a one-second timeout correctly terminates it.
        final = wait_for(lambda: finished(gateway, row['id']))
        assert final['evaluation']['status'] == 'timed_out'
        assert final['report']['reason_code'] == 'EVALUATION_TIMEOUT'
        wait_for(lambda: not gateway.evaluations.jobs)
        gateway.evaluations.worker_target = process_worker
        # Capacity reuse is independent of the preceding deliberately short deadline.
        gateway.evaluations.timeout_s = 90
        gateway.submit_evaluation(row['id'])
        assert wait_for(lambda: finished(gateway, row['id']))['status'] == 'blocked'
    finally:
        gateway.close()

def test_shutdown_reaps_workers_and_records_cancelled_job(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    path = gateway.store.path
    gateway.close()
    assert not gateway.evaluations.jobs
    reopened = Gateway(path)
    try:
        final = reopened.get(row['id'])
        assert final['status'] == 'hold'
        assert final['evaluation']['status'] == 'cancelled'
    finally:
        reopened.close()

def test_abrupt_restart_marks_job_interrupted(tmp_path):
    gateway = Gateway(tmp_path / 'interrupted.sqlite3')
    row = gateway.create(NewRequest(command={'target_pct':60}))
    # Durable running record with no live worker, as left by a killed server.
    gateway._prepare_evaluation(row['id'], {'id':'interrupted-job', 'revision':0,
        'status':'running', 'started_at':time.time(), 'deadline_at':time.time()+90, 'finished_at':None})
    gateway.close()
    gateway = Gateway(tmp_path / 'interrupted.sqlite3')
    try:
        restored = gateway.get(row['id'])
        assert restored['evaluation']['status'] == 'interrupted'
        assert restored['status'] == 'hold'
        assert restored['report'] is None
    finally:
        gateway.close()

def test_spawn_failure_is_persisted_as_hold(setup, monkeypatch):
    gateway, client, root = setup
    def fail(*args, **kwargs):
        raise OSError('spawn unavailable')
    monkeypatch.setattr(gateway.evaluations.context, 'Process', fail)
    row = gateway.create(NewRequest(command={'target_pct':60}))
    response = client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={})
    assert response.status_code == 503
    assert gateway.get(row['id'])['evaluation']['status'] == 'failed'
    assert not gateway.evaluations.jobs

def test_concurrent_submissions_start_only_one_job(setup):
    gateway, client, root = setup
    gate = root / 'concurrent'
    gate.mkdir()
    row = gateway.create(NewRequest(command={'target_pct':60}, purpose=str(gate)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={}), range(2)))
    assert sorted(r.status_code for r in results) == [202, 409]
    assert gateway.get(row['id'])['revision'] == 2
    assert len(gateway.evaluations.jobs) == 1

def test_stale_task_id_cannot_replace_same_revision(setup):
    gateway, client, root = setup
    row, gate = start(setup)
    context = dict(next(iter(gateway.evaluations.jobs.values())).context)
    client.post(f'/requests/{row["id"]}/evaluation/cancel', headers=OP, json={})
    newer = gateway.get(row['id'])
    newer['status'] = 'evaluating'
    newer['evaluation']['id'] = 'different-task'
    gateway.store.save(newer)
    gateway._finish_evaluation(context, calculate(context))
    assert gateway.get(row['id']) == newer
