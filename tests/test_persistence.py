"""SQLite restart/crash tests. Approval scenarios deliberately use a test-only mock policy."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import main
from backend.contracts import NewRequest, DecisionInput, ExecutionInput, RequestRecord
from backend.gateway.service import Gateway
from backend.simulator import service as simulator
from tests.test_gateway import OP, APP

@pytest.fixture
def approved_db(tmp_path, monkeypatch):
    calculation = simulator.simulate
    monkeypatch.setattr(simulator, 'simulate', lambda *args: calculation(*args).model_copy(update={'mock': True}))
    path = tmp_path / 'persistent.sqlite3'
    gateway = Gateway(path)
    row = gateway.create(NewRequest(command={'target_pct':80}))
    row = gateway.evaluate(row['id'])
    row = gateway.decide(row['id'], DecisionInput(report_digest=row['report']['digest'],
        decision='approve', reason='test-only mock approval'), 'approver')
    gateway.close()
    return path, row

def execute(gateway, row):
    return gateway.execute(row['id'], ExecutionInput(report_digest=row['report']['digest']))

def test_approval_and_execution_survive_restart(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    assert gateway.get(row['id']) == row
    result = execute(gateway, row)
    state = gateway.adapter.read_state().model_dump(exclude={'observed_at'})
    history = gateway.history(row['id'])
    gateway.close()
    gateway = Gateway(path)
    try:
        assert gateway.get(row['id']) == result
        assert gateway.adapter.read_state().model_dump(exclude={'observed_at'}) == state
        assert gateway.history(row['id']) == history
        assert execute(gateway, row) == result
        assert len(gateway.adapter.executions) == 1
    finally:
        gateway.close()

def test_approval_expiry_is_checked_after_restart(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    row['approval']['expires_at'] = time.time() - 1
    gateway.store.save(row)
    gateway.close()
    gateway = Gateway(path)
    try:
        with pytest.raises(HTTPException) as error:
            execute(gateway, row)
        assert error.value.status_code == 409
        assert gateway.get(row['id'])['status'] == 'revalidation_required'
        assert not gateway.adapter.executions
        assert len(gateway.history(row['id'])['approvals']) == 1
    finally:
        gateway.close()

def test_state_change_persists_and_invalidates_approval(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    gateway.adapter.update_demo_state(1.3, 'valid')
    gateway.close()
    gateway = Gateway(path)
    try:
        assert gateway.adapter.read_state().load_ratio == 1.3
        with pytest.raises(HTTPException):
            execute(gateway, row)
        assert not gateway.adapter.executions
    finally:
        gateway.close()

def test_previous_report_and_approval_history_preserved(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    updated = gateway.evaluate(row['id'])
    assert updated['approval'] is None
    gateway.close()
    gateway = Gateway(path)
    try:
        history = gateway.history(row['id'])
        assert len(history['reports']) == 2
        assert len(history['approvals']) == 1
        assert history['reports'][0]['digest'] == row['report']['digest']
    finally:
        gateway.close()

@pytest.mark.parametrize('crash', ['before_apply', 'after_apply', 'evaluating'])
def test_abrupt_process_death_recovers_without_replay(approved_db, crash):
    path, row = approved_db
    # A real child process exits without cleanup at the selected operation boundary.
    script = '''
import os, sys
from backend.gateway.service import Gateway
from backend.contracts import ExecutionInput
from backend.evidence import service as evidence
path, request_id, digest, crash = sys.argv[1:]
gateway = Gateway(path)
if crash == 'evaluating':
    evidence.review_evidence = lambda *args: os._exit(17)
    gateway.evaluate(request_id)
else:
    original = gateway.adapter.apply_command
    def interrupt(*args):
        if crash == 'after_apply':
            original(*args)
        os._exit(17)
    gateway.adapter.apply_command = interrupt
    gateway.execute(request_id, ExecutionInput(report_digest=digest))
'''
    process = subprocess.run([sys.executable, '-c', script, str(path), row['id'], row['report']['digest'], crash],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert process.returncode == 17, process.stderr
    gateway = Gateway(path)
    try:
        restored = gateway.get(row['id'])
        RequestRecord.model_validate(restored)
        if crash == 'evaluating':
            assert restored['status'] == 'hold'
            assert restored['report'] is None and restored['approval'] is None
            assert restored['events'][-1]['kind'] == 'evaluation_interrupted'
        else:
            assert restored['status'] == 'execution_unknown'
            assert restored['events'][-1]['kind'] == 'execution_interrupted'
        before = len(gateway.adapter.executions)
        assert before == (1 if crash == 'after_apply' else 0)
        with pytest.raises(HTTPException):
            execute(gateway, row)
        assert len(gateway.adapter.executions) == before
    finally:
        gateway.close()

def test_second_server_is_rejected(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    try:
        process = subprocess.run([sys.executable, '-c',
            'from backend.gateway.service import Gateway; import sys; Gateway(sys.argv[1])', str(path)],
            capture_output=True, text=True, timeout=20)
        assert process.returncode != 0
        assert 'already in use' in process.stderr
    finally:
        gateway.close()

def test_adapter_receipt_and_state_are_atomic(approved_db):
    path, row = approved_db
    gateway = Gateway(path)
    try:
        before = gateway.adapter.read_state().model_dump(exclude={'observed_at'})
        gateway.store.connection.execute('''CREATE TRIGGER fail_receipt BEFORE INSERT ON adapter_executions
            BEGIN SELECT RAISE(ABORT, 'test disk failure'); END''')
        result = execute(gateway, row)
        assert result['status'] == 'execution_unknown'
        assert gateway.adapter.read_state().model_dump(exclude={'observed_at'}) == before
        assert not gateway.adapter.executions
    finally:
        gateway.close()

def test_reservation_failure_never_calls_adapter(approved_db, monkeypatch):
    path, row = approved_db
    gateway = Gateway(path)
    try:
        calls = []
        monkeypatch.setattr(gateway.adapter, 'apply_command', lambda *args: calls.append(args))
        gateway.store.connection.execute('''CREATE TRIGGER fail_reservation BEFORE UPDATE ON requests
            WHEN json_extract(NEW.record_json, '$.status') = 'executing'
            BEGIN SELECT RAISE(ABORT, 'test disk failure'); END''')
        with pytest.raises(sqlite3.Error):
            execute(gateway, row)
        assert calls == []
        assert gateway.get(row['id'])['status'] == 'approved'
    finally:
        gateway.close()

def test_api_lifespan_reopens_database(tmp_path, monkeypatch):
    path = tmp_path / 'api.sqlite3'
    monkeypatch.setenv('IRON_MAN_DB_PATH', str(path))
    monkeypatch.setenv('IRON_MAN_OPERATOR_TOKEN', 'local-operator')
    with TestClient(main.app) as client:
        row = client.post('/requests', headers=OP, json={'command':{'target_pct':60}}).json()
        result = client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={}).json()
        assert result['status'] == 'blocked'
    with TestClient(main.app) as client:
        assert client.get('/health').json()['storage'] == 'sqlite'
        assert client.get(f'/requests/{row["id"]}', headers=OP).json() == result
        assert client.get('/requests', headers=OP).json()[0]['id'] == row['id']
        assert len(client.get(f'/requests/{row["id"]}/history', headers=OP).json()['reports']) == 1
        assert client.get('/requests').status_code == 401

def test_unavailable_database_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv('IRON_MAN_DB_PATH', str(tmp_path / 'errors.sqlite3'))
    monkeypatch.setenv('IRON_MAN_OPERATOR_TOKEN', 'local-operator')
    with TestClient(main.app) as client:
        main.gateway.store.connection.execute('''CREATE TRIGGER fail_write BEFORE INSERT ON requests
            BEGIN SELECT RAISE(ABORT, 'test disk failure'); END''')
        result = client.post('/requests', headers=OP, json={'command':{'target_pct':80}})
        assert result.status_code == 503
        assert client.get('/requests', headers=OP).json() == []
