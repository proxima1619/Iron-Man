# 2·3번 TEP 인터페이스 계약 초안

3번 구현 추가: [TEP 근거 인계](tep_evidence_handoff.md)에 현재 확정된 변수·초기화·시험 사전 기반의 검토 입력과 `tep-evidence-1.0` 반환을 정리했다. 기본 냉각수 변경 시험과의 근거 ID 매핑은 제공하며 고장/교란 시험과 안전 기준은 계속 미확정이다. 아래 초안의 미선정 설명은 작성 당시 상태이며 현재 구현 기준은 후속 인계 문서를 따른다.

2026-10-09 추가: 2번의 실행 가능한 최소 연동은 [TEP_INTEGRATION.md](TEP_INTEGRATION.md), [선정 모델·변수·지원 시험 사전](../contracts/tep-model.json), `TEPResult.schema.json`으로 제공된다. 아래는 **근거 검토 확장의 협의 초안**이며 런타임 실행 계약이 아니다. 현재 지원 시험은 기본 초기 상태의 개루프 냉각수 step 비교 하나이며 고장/외란 시험과 근거→시험 매핑은 아직 지원하지 않는다. 기존 펌프 근거 검토를 TEP에 적용하지 않으며 TEP 승인 정책은 미설정이다.

상태: **협의용 초안, 실행 계약 아님**. TEP 구현·버전·변수·지원 시험은 아직 확정되지 않았다. 아래 필드명은 제안이며 현재 EvidenceReview v1.0이나 런타임에 추가한 필드가 아니다. 미정 값은 null로 표현하고 실행 대상에서 제외한다. 현재 냉각 모델의 온도·펌프 속도·부하·degraded_cooling·효율 0.65·온도 한계를 TEP에 자동 승계하지 않는다.

## 담당과 확정 순서

| 담당 | 확정하거나 반환할 내용 |
|---|---|
| 2번 | TEP 구현 저장소/라이선스/버전, 변수 사전, 제어 요청 의미, 지원 시험 레지스트리, 초기 상태·시뮬레이션 재현 조건 |
| 3번 | 출처·인용 검증, 출처 용도, 변수별 적용 조건 비교, evidence_id → 지원 시험 제안, 미확인·미지원 사유 |
| 1번 | 서버 출처 등록, 시험 채택, 안전 허용 범위와 차단 규칙의 근거·버전, 승인·실행 직전 재검사 |
| 4번 | 단위·범위 의미·불확실성 표시, 재정의된 제어 요청 화면, 검증 불가와 담당자 검토 필요 표시 |

2번이 구현과 변수/시험 레지스트리를 제시 → 2·3번이 매핑 합의 → 1번이 정책 확정 → 4번과 요청/보고서 계약 합의 → 새 계약 버전과 통합 검증 후 전환한다. 과거 냉각 모델의 기록은 해당 모델·계약 버전으로 남긴다.

## 변수 사전: 2번 → 3번

변수마다 한 행을 채운다. 실제 TEP 변수 ID·개수·값·단위는 선택한 구현의 원문 정의로 확인한다.

| 필드 | 의미 | 결정/검증 주체 |
|---|---|---|
| model_id / model_version / contract_version | 구현·버전·계약 식별자 | 2번 |
| variable_id / implementation_key | 합의된 ID와 구현 배열 인덱스/키 대응 | 2번 |
| role / meaning | manipulated / measured / state / disturbance, 물리적 의미 | 2번 |
| native_unit / display_unit / conversion | 원래 단위, 표시 단위, 명시적 환산식·출처 | 2번; 3번 인용 검토 |
| current_value / observed_at / quality | 값·관측 시각·유효/결측/범위 밖 상태 | 2번 |
| data_origin / dataset_id / dataset_version | simulated / field_measured, 데이터 출처·버전 | 2번 |
| definition_source_id / locator | 변수 정의 원문과 위치 | 2번; 3번 출처 검증 |
| normal_operating_range | 지정 운전 모드의 정상 시뮬레이션 범위·단위·근거 | 2번 |
| model_validity_range | 계산 가능한 모델 범위와 경계 포함 여부 | 2번 |
| safety_allowed_range / safety_basis_id | 안전 허용 범위·단위·근거·정책 버전 | 1번 확정; 미확정은 null |

세 범위는 별도 항목이다. 정상 기록의 최솟값·최댓값을 안전 한계로 간주하지 않는다. 미정 범위나 단위는 추측하지 않고 담당자 검토 필요로 반환한다. 단위 환산식이 없으면 기존 %나 부하 비율로 치환하지 않는다.

## 시연 제어 요청과 재현 조건: 1·2·4번 → 3번

| 항목 | 필수 합의 내용 |
|---|---|
| 제어 요청 | request_type, variable_id, 조작변수 직접 변경 또는 제어기 설정값 변경 여부, open_loop/closed_loop 의미 |
| 변경값 | 기준값·요청값·단위·변경량, absolute/delta 의미; 제어기 설정값과 실제 조작값 구분 |
| 입력 형상 | step/ramp 등 지원 방식, 적용 시각·유지/종료 조건; 미지원 방식은 제외 |
| 초기 조건 | initial_state_id, 상태/체크포인트 해시, 운전 모드, 안정화 조건·구간, 제어기 설정·상태 |
| 시간 | time_unit, start_time, horizon, integration_step, measurement_interval; 평가 구간과 입력 유지 시간 구분 |
| 확률 조건 | 잡음/교란 설정, random_seed 또는 동일 잡음 경로 재사용 방식, 반복 횟수 |
| 비교 | baseline은 기존 제어 유지, candidate는 합의된 변경; 두 분기의 초기 상태·외생 입력·난수 경로 일치 |
| 기록 | run_id, 구현/설정/데이터 버전과 해시, 실행 상태, 중단 시각·사유, 지표 정의와 단위 |

현재 set_pump_speed 요청을 TEP 요청으로 직접 이름만 바꾸지 않는다. 시연할 제어 요청을 선정한 뒤 의미를 확정한다. 장기 예측·평형·민감도 등 어떤 지표를 TEP에서 지원할지는 별도 합의하며 기존 지표의 자동 승계를 가정하지 않는다.

## 지원 고장·교란 레지스트리: 2번 → 3번

| 필드 | 합의 내용 |
|---|---|
| test_id / implementation_fault_id | 내부 지원 시험 ID와 구현 고장/교란 ID의 명시적 대응 |
| kind / physical_meaning | 정상/고장/교란 구분, 모델에서 재현하는 현상과 재현하지 못하는 현상 |
| supported / supported_model_versions | 실제 호출·검증 가능한지, 대상 모델 버전 |
| configuration | 설정 스키마, 단위·허용 범위·기본값, 시작 시각·지속 시간·지원 조합 |
| parameter_origin / source_id / locator | 모델 기본값·데모 가정·실측 기반 구분과 정의 출처 |
| affected_variables / required_conditions | 영향을 받는 변수 ID, 운전 모드·초기 조건 등 적용 전제 |
| expected_observations / limitations | 확인 지표·단위, 모델의 제한과 미검증 조건 |

3번은 레지스트리의 test_id를 제안하며 임의 코드·함수명·모델 계수·허용 범위를 생성하지 않는다. 설정값 제안 허용 여부도 별도 계약 사항이며 초안의 기본은 **서버/2번이 확정한 설정 프로필 ID만 참조**하는 것이다. degraded_cooling과 TEP 고장 사이의 대응은 현재 미정이다. ID의 이름이 비슷하거나 열교환 관련이라는 이유만으로 매핑하지 않는다.

## 근거 용도와 시험 매핑: 3번 → 1·2·4번

출처의 데이터 유형과 근거 용도는 별도로 기록한다. 같은 논문도 용도에 따라 적용 범위가 다르다.

| 근거 용도 초안 | 사용 범위 |
|---|---|
| model_definition | 선정한 TEP 구현·변수·지원 고장 정의 확인; 구현 버전 대응 필요 |
| physical_mechanism | 일반적인 물리 현상·반례 가능성 제기; TEP 특정 조작 범위나 안전 기준을 직접 정하지 않음 |
| simulation_observation | 시뮬레이션 운전 기록·시험 결과; 현장 실측이나 실제 설비 검증으로 표시하지 않음 |
| safety_basis | 적용 대상·조건이 확인되고 1번이 채택한 한계 근거; 문헌/LLM 자체가 정책을 수정하지 않음 |

현재 펌프·열교환기 논문은 우선 physical_mechanism 후보로 취급한다. TEP 구현 정의 자료나 안전 기준으로 자동 채택하지 않는다. 실제 현장 데이터가 없으면 보고서에 **현장 실측 없음, 시뮬레이션 기반, 실제 설비 검증 미수행**을 계속 표시한다. 문헌 적용성 확인과 설비 안전성 검증은 별개다.

| 제안 반환 필드 | 의미 |
|---|---|
| evidence_id / source_id / source_type / evidence_purpose | 근거·출처 ID, 문서 유형, 위 용도 |
| title / source_url / doi / excerpt / locator / version | 원문·서지·인용·위치·버전; 공개 계약에서 DOI 별도 필드 여부는 추후 합의 |
| variable_ids / compared_conditions | 관련 변수, 현재값/요청값·단위와 문헌 조건, 환산 근거 |
| applicability / missing_conditions | applicable / partial / mismatch / unknown 및 미확인 조건 |
| proposed_test_id / configuration_profile_id | 레지스트리에 등록된 지원 시험·설정 프로필만 참조; 대응 없으면 null |
| mapping_status / mapping_basis | proposed / unsupported / needs_review, 현상과 지원 시험의 대응 근거·한계 |
| hold_reasons / validation_scope | 보류 사유 목록, 무엇을 확인했고 확인하지 못했는지 |

제안은 실행 명령이 아니다. 1번이 출처·인용·적용 조건·지원 버전·설정 프로필을 확인한 뒤 시험을 채택한다. 적용 조건이 맞더라도 서버 안전 정책과 담당자 승인까지 통과한 것으로 표시하지 않는다.

## 미확정·미지원 처리와 전환 확인

| 사유 코드 초안 | 반환 의미 |
|---|---|
| MODEL_NOT_SELECTED | TEP 구현/버전 미선정 |
| VARIABLE_MAPPING_UNCONFIRMED | 변수 의미·키·단위·환산 미확정 |
| SOURCE_UNAVAILABLE / QUOTE_UNVERIFIED | 원문 미확보 또는 인용 검증 실패 |
| APPLICABILITY_UNKNOWN / CONDITION_MISMATCH | 적용 조건 미확인 또는 불일치 |
| TEST_UNSUPPORTED / TEST_MAPPING_UNCONFIRMED | 대응 시험 미지원 또는 매핑 합의 없음 |
| REPRODUCIBILITY_INCOMPLETE | 초기 상태·시간·제어기·난수 조건 불충분 |
| SAFETY_BASIS_UNCONFIRMED | 안전 범위/차단 기준의 서버 채택 근거 미확정 |

위 코드는 아직 기존 API 상태에 추가하지 않은 협의용 값이다. 현재 계약에서는 insufficient/failed와 missing_conditions/limitation으로 표현하고, TEP 계약 확정 후 일관된 구조로 합의한다. 현장 실측 부재는 항상 제한으로 보고하며 가상 시험 전체를 무조건 실패시키는 것과 실제 설비 실행 승인을 구분한다.

전환 검증에는 변수·단위·버전 불일치, 정상 범위와 안전 범위 혼동, 미지원 시험 제외, evidence_id 연결, 원문 인용 검증, 동일 초기 조건 재현, 실패·부분 결과 보류, 이전 냉각 기록과의 버전 구분, 서버 승인 권한 유지가 포함되어야 한다. 확정 전에는 TEP 적합성·시험 통과·실제 안전성을 주장하지 않는다.

## 2번에게 전달할 요청

TEP 구현이 선정되면 구현/버전과 출처, 시연 제어 요청, 변수 ID·의미·단위·세 범위, 지원 고장/교란 ID·설정 프로필·적용 조건, 초기 상태·제어기·난수·시뮬레이션 시간 조건을 이 표에 채워 주세요. 3번은 이 레지스트리를 기준으로 문헌 적용성과 evidence_id → 시험 매핑을 검토하겠습니다. 대응되지 않는 항목은 검증 불가/담당자 검토 필요로 유지하고, 안전 범위와 차단 기준은 1번의 정책 확정을 기다리겠습니다.
