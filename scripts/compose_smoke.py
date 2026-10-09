"""Verify HTTP proxy, auth, persistence and API replacement against an isolated Compose stack.
Run: python3 -m scripts.compose_smoke [base_url]
The caller starts Compose first. Records remain in this test stack for inspection.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8080').rstrip('/')
TOKEN = os.environ.get('IRON_MAN_OPERATOR_TOKEN', 'local-operator')
APPROVER = os.environ.get('IRON_MAN_APPROVER_TOKEN', 'local-approver')

def api(path, body=None, token=TOKEN):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = None if body is None else json.dumps(body).encode()
    with urllib.request.urlopen(urllib.request.Request(BASE + '/api' + path, data=data, headers=headers), timeout=15) as response:
        return json.load(response)

def wait_ready():
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            return api('/health')
        except (OSError, ValueError):
            time.sleep(1)
    raise RuntimeError('API did not become healthy through the web proxy')

def compose(*args):
    subprocess.run(['docker', 'compose', *args], check=True)

if __name__ == '__main__':
    assert wait_ready()['storage'] == 'sqlite'
    compose('exec', '-T', 'api', 'python', '-c',
            'from backend.evidence.service import load_sources; assert load_sources()')
    with urllib.request.urlopen(BASE, timeout=10) as response:
        assert b'<div id="root"></div>' in response.read()
    try:
        api('/requests', token=None)
        raise AssertionError('Unauthenticated request was accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    row = api('/requests', {'command': {'target_pct': 60}, 'purpose': 'Compose persistence smoke test'})
    report = api(f'/requests/{row["id"]}/evaluate', {})
    deadline = time.monotonic() + 100
    while report['status'] == 'evaluating' and time.monotonic() < deadline:
        time.sleep(0.2)
        report = api(f'/requests/{row["id"]}')
    assert report['status'] == 'blocked'
    api('/demo/state', {'load_ratio': .6, 'sensor_quality': 'valid'}, token=APPROVER)
    approved = api('/requests', {'command': {'target_pct': 80}, 'purpose': 'Virtual approval persistence smoke'})
    approved = api(f'/requests/{approved["id"]}/evaluate', {})
    deadline = time.monotonic() + 100
    while approved['status'] == 'evaluating' and time.monotonic() < deadline:
        time.sleep(0.2)
        approved = api(f'/requests/{approved["id"]}')
    assert approved['status'] == 'awaiting_approval'
    request_path = f'/requests/{approved["id"]}'
    api(request_path + '/decisions', {'decision': 'approve', 'reason': 'virtual-only policy check',
        'report_digest': approved['report']['digest']}, token=APPROVER)
    applied = api(request_path + '/execute', {'report_digest': approved['report']['digest']})
    assert applied['status'] == 'completed' and applied['execution']['virtual'] is True
    before_state = api('/state')
    before_state.pop('observed_at')
    compose('up', '-d', '--no-deps', '--force-recreate', 'api')
    wait_ready()
    assert api(f'/requests/{row["id"]}') == report
    assert api(request_path) == applied
    after_state = api('/state')
    after_state.pop('observed_at')
    assert after_state == before_state
    compose('down')  # Intentionally no -v: data must survive complete stack recreation.
    compose('up', '-d', '--wait', '--wait-timeout', '90')
    wait_ready()
    assert api(f'/requests/{row["id"]}') == report
    assert api(request_path + '/execute', {'report_digest': approved['report']['digest']}) == applied
    assert api(f'/requests/{row["id"]}/history')['reports']
    print('PASS: web, proxy, auth, API replacement, full stack recreation, persistent request/report/state')
