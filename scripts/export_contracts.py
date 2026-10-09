"""Run from repo root: .venv/bin/python -m scripts.export_contracts"""
import json
from pathlib import Path
from backend.main import app
from backend.gateway.service import Gateway
from unittest.mock import patch
from uuid import UUID
from backend.contracts import NewRequest, Snapshot, SimulationResult, EvidenceReview, RequestRecord
from backend.simulator.service import simulate
from backend.evidence.service import review_evidence

ROOT = Path(__file__).resolve().parents[1]

def write(relative, value):
    (ROOT / relative).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

if __name__ == '__main__':
    write('contracts/openapi.json', app.openapi())
    for model in (SimulationResult, EvidenceReview, RequestRecord):
        write(f'contracts/{model.__name__}.schema.json', model.model_json_schema())
    request = NewRequest(command={'target_pct': 80})
    snapshot = Snapshot(revision=1, temperature_c=60, load_ratio=1, pump_speed_pct=100, observed_at=1700000000)
    review = review_evidence(request, snapshot)
    from backend.contracts import Scenario
    result = simulate(request.command, snapshot, [Scenario(kind='normal'), *review.proposed_tests])
    write('contracts/examples/request.json', request.model_dump())
    write('contracts/examples/snapshot.json', snapshot.model_dump())
    write('contracts/examples/evidence-demo.json', review.model_dump())
    write('contracts/examples/simulation-demo.json', result.model_dump())
    write('contracts/examples/evidence-insufficient.json', EvidenceReview(
        mock=False, status='insufficient', limitation='필수 적용 조건에 맞는 출처를 확보하지 못했습니다.').model_dump())
    write('contracts/examples/simulation-out-of-domain.json', SimulationResult(
        mock=False, status='out_of_domain', model_version='example-model-v1',
        limitation='입력 부하가 모델 검증 범위를 벗어납니다.').model_dump())

    # Deterministic demo response for frontend development; never a real run record.
    with patch('backend.gateway.service.time.time', return_value=1700000000.0), patch(
        'backend.gateway.service.uuid.uuid4', return_value=UUID('00000000-0000-4000-8000-000000000001')
    ):
        gateway = Gateway()
        row = gateway.create(request)
        record = RequestRecord.model_validate(gateway.evaluate(row['id']))
        write('contracts/examples/request-record-demo.json', record.model_dump())
        gateway.close()
