"""Run from repo root: .venv/bin/python -m scripts.export_contracts"""
import json
from pathlib import Path
from backend.main import app
from backend.gateway.service import Gateway
from backend.gateway.evaluation import failure_report
from unittest.mock import patch
from uuid import UUID
from backend.contracts import NewRequest, Snapshot, SimulationResult, EvidenceReview, RequestRecord, TEPResult, TEPEvidenceReview
from backend.simulator.service import MODEL_VERSION, simulate
from backend.evidence.service import review_evidence
from backend.simulator.tep import service as tep
from backend.simulator.tep.build import source_lock
from backend.simulator.tep.reference_contracts import ReferenceCatalog, ReferenceSeries
from backend.simulator.tep.calibration import TEPActuatorCalibrationDataset, TEPActuatorCalibrationResult

ROOT = Path(__file__).resolve().parents[1]

def write(relative, value):
    (ROOT / relative).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    write('contracts/openapi.json', app.openapi())
    for model in (SimulationResult, EvidenceReview, RequestRecord, TEPResult, ReferenceCatalog, ReferenceSeries,
                  TEPEvidenceReview, TEPActuatorCalibrationDataset, TEPActuatorCalibrationResult):
        write(f'contracts/{model.__name__}.schema.json', model.model_json_schema())
    request = NewRequest(command={'target_pct': 80})
    snapshot = Snapshot(revision=1, temperature_c=60, load_ratio=1, pump_speed_pct=100,
        target_pump_speed_pct=100, simulation_time_s=0, model_version=MODEL_VERSION,
        calculated_at=1700000000, observed_at=1700000000)
    review = review_evidence(request, snapshot)
    from backend.contracts import Scenario
    result = simulate(request.command, snapshot, [Scenario(kind='normal'), *review.proposed_tests])
    write('contracts/examples/request.json', request.model_dump())
    write('contracts/examples/request-tep.json', NewRequest(equipment_id='tep-sim-01',
        purpose='TEP 냉각수 입력 변경 비교', command={'type':'set_tep_cooling_water',
        'variable':'XMV10', 'value':42, 'duration_s':600, 'sample_period_s':10}).model_dump())
    lock = source_lock()
    write('contracts/tep-model.json', {
        'schema_version':'tep-model-1.0', 'model_version':tep.MODEL_VERSION,
        'source_url':lock['repository'], 'source_commit':lock['commit'],
        'source_files_sha256':lock['files'], 'data_origin':'simulation',
        'field_validation':'not_performed_no_measured_data',
        'variable_number_base':1, 'array_index_base':0,
        'variables': {key:{**definition.model_dump(),
            'role': 'manipulated' if key.startswith('XMV') else 'measured' if key.startswith('XMEAS') else 'actuator_state',
            'request_writable': key in {'XMV10','XMV11'},
            'model_input_range': {'minimum':0,'maximum':100,'unit':'percent_full_scale'} if key.startswith('XMV') else None,
            'normal_operating_range':None, 'safety_allowed_range':None,
            'definition_source':f"{lock['repository']}/blob/{lock['commit']}/c/" + ('teprob.cpp' if key.startswith('ACTUAL') else 'TENames.cpp')}
            for key,definition in tep.VARIABLES.items()},
        'core_shutdown_rules':[rule.model_dump() for rule in tep.SHUTDOWN_RULES],
        'supported_tests':[{'test_id':'base_case_cooling_step_v1',
            'command_type':'set_tep_cooling_water','variables':['XMV10','XMV11'],
            'configuration':tep.configuration(NewRequest(equipment_id='tep-sim-01',command={
                'type':'set_tep_cooling_water','variable':'XMV10','value':42,'duration_s':600,'sample_period_s':10}).command).model_dump(),
            'initial_profile':'nist-teinit-base-case-v1','parameter_origin':'upstream_model_default',
            'horizon_range_s':[1,1800],'sample_period_range_s':[1,60],
            'constraint':'horizon must be an integer multiple of sample period',
            'supported_faults':[], 'limitation':'Only base-case open-loop MV step; evidence proposals may reference this test, never introduce faults or execute it.'}],
    })
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
        task = {"id": "eval-example-001", "revision": 0, "status": "running",
                "started_at": 1700000000, "deadline_at": 1700000090, "finished_at": None}
        running, context = gateway._prepare_evaluation(row['id'], task)
        write('contracts/examples/request-evaluating.json', RequestRecord.model_validate(running).model_dump())
        with patch('backend.gateway.service.time.time', return_value=1700000090.0):
            timed_out = gateway._finish_evaluation(context, failure_report(context,
                'EVALUATION_TIMEOUT', '예시: 평가 제한 시간 초과'), 'timed_out')
        write('contracts/examples/request-timed-out.json', RequestRecord.model_validate(timed_out).model_dump())
        gateway.close()
