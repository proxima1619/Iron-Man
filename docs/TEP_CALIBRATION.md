# TEP 냉각수 액추에이터 응답시간 보정 시제품

2026-10-09. 실측 데이터가 들어오기 전에 사용할 **오프라인 보정 후보 생성 기능**이다. 현재 시험 자료는 팀이 생성한 시뮬레이션 데이터이며 실측 보정 결과가 아니다. 입력 파싱·계수 추정·독립 검증·후보 거절·출처 보존을 확인한다.

## 구현 범위

| 보정 변수 | 원본 위치 | 기본값 | 보정 입력 |
|---|---|---|---|
| XMV10 반응기 냉각수 액추에이터 응답시간 | TEINIT `vtau[9]`, TEFUNC 1-based `YP(48)` | 5초 | 정규화 명령값과 실제 액추에이터 설정 피드백 |
| XMV11 응축기 냉각수 액추에이터 응답시간 | TEINIT `vtau[10]`, TEFUNC 1-based `YP(49)` | 5초 | 정규화 명령값과 실제 액추에이터 설정 피드백 |

근거는 고정 NIST 소스 `81a7ac9dc04f91bc0898c36f8522372e0e437fc1`의 `teprob.cpp`다. TEINIT의 5초는 코어 내부에서 3600으로 나누어 시간 단위로 변환된다. 액추에이터 상태는 전체 50 상태의 Python 인덱스 47/48이며 기존 외부 실행 결과의 `actual_cooling_setting` 두 값과 대응한다. 기존 `XMV10/11`은 명령값이고 실제 응답 피드백과 구분한다. 두 값의 단위는 `percent_full_scale`이며 펌프 RPM이나 실제 물 유량의 단위가 아니다. 다른 태그라면 물리적으로 동일한 설정을 나타내는지와 정규화 기준을 먼저 확인해야 한다.

보정 모델은 `d(actual)/dt = (target − actual) / tau`다. 외란·고착·데드밴드 없는 TEFUNC 액추에이터의 1차 응답에 대응한다. 시간 간격 0.1초의 Euler를 닫힌식으로 계산한다:

```text
actual_next = target + (actual − target) × (1 − 0.1 / tau_s)^steps
```

각 기록의 처음 실제 피드백으로 액추에이터 상태를 시작하고 이후 전체 궤적을 계산한다. 중간 관측값으로 상태를 매번 재설정하지 않는다. 명령값은 해당 표본 시각 직후부터 다음 표본까지 유지된다고 정의한다. 구간 중간에 명령이 바뀌었다면 해당 이벤트 시각도 입력에 포함해야 한다. 이 도구는 액추에이터 성분식을 사용하며 전체 C++ 공정을 반복 실행하는 최적화 도구는 아니다. 실제 C++ 엔진과 기본 5초 응답의 수치 일치를 별도 시험으로 확인했다.

온도·압력·반응속도·열전달·냉각수 열용량 등 전체 공정 계수의 추정, 센서 편향·순수 지연·고착, 정상/고장 운전 상태의 자동 식별, 전체 초기 상태 복원은 후속 범위다. 전체 TEP 또는 실제 설비에 대한 보정 완료로 표시하지 않는다.

## 재현 가능한 실행

Python과 프로젝트의 기존 Pydantic 의존성만 필요하다. 최적화에 MATLAB·OpenModelica·추가 최적화 패키지는 사용하지 않는다. 실제 코어 대조 시험에는 기존 TEP 실행 환경이 필요하다.

저장소 루트에서:

```powershell
# 도구 확인용 시뮬레이션 기록 생성. 현장 실측이 아님.
.\.venv\Scripts\python.exe -m scripts.generate_tep_calibration_example

# 후보 생성과 별도 기록의 오차 평가
.\.venv\Scripts\python.exe -m scripts.calibrate_tep `
  --input data/tep-actuator-calibration-simulation.json `
  --output data/tep-actuator-calibration-candidate.json
```

예제의 가정 응답시간은 XMV10=12초, XMV11=8초이며 생성 시 명시적 Euler 적분으로 피드백을 만든다. 가정값은 테스트용이고 실제 TEP·현장 계수가 아니다. 명령 변경과 서로 다른 학습/검증 기록을 포함한다. 생성된 입력·출력은 Git에서 제외한다.

현재 확인 결과:

| 변수 | 예제 가정 | 복원 값 | 검증 RMSE (percent_full_scale) | 원본 5초 사용 시 RMSE |
|---|---:|---:|---:|---:|
| XMV10 | 12초 | 약 12초 | 약 7.7×10⁻¹¹ | 약 0.881809 |
| XMV11 | 8초 | 약 8초 | 약 4.6×10⁻¹¹ | 약 0.434433 |

작은 오차는 같은 성분 방정식으로 만든 예제의 복원 시험 결과다. 현실 정확도나 전체 TEP 예측 정확도를 입증하지 않는다.

## 실측 입력에 필요한 값

입력 스키마: `contracts/TEPActuatorCalibrationDataset.schema.json`. 생성 예제로 전체 구조를 확인할 수 있다. 현재 `archive/TEP_data`의 52개 열에는 실제 액추에이터 상태와 기록 timestamp가 없으므로 이 보정 입력으로 자동 변환하지 않는다. 파일의 XMV10/11 명령값을 실제 피드백으로 복제하지 않는다.

| 필드 | 의미 / 조건 |
|---|---|
| `source_id`, `source_uri`, `asset_id` | 자료 출처와 대상 설비 식별. URI는 기록용이며 도구가 외부 자료를 가져오지 않음 |
| `data_origin` | 실측이면 `measured`, 모델 생성 자료면 `simulation`. 사용자가 선언한 분류이며 진위 인증은 아님 |
| `mapping_status` | `user_confirmed_actuator_mapping`: 태그/정규화 대응을 확인한 뒤 명시 |
| `actuator_faults` | 현재 지원은 `none`. 고착·히스테리시스·숨은 지연 등이 있으면 다른 모델/검토 필요 |
| `candidate_model_version` | 현재 모델과 다른 후보 버전 이름 |
| `channels.XMV10/XMV11.unit` | `percent_full_scale`만 지원 |
| `target_tag`, `actual_tag`, `normalization_reference` | 서로 다른 명령/실제 설정 태그와 정규화 기준. 동일 태그를 사용하면 거절 |
| `minimum_tau_s`, `maximum_tau_s` | 사용자가 정하는 탐색 범위. 도구의 수치 지원은 1..120초. 1초는 0.1초 적분과 분리한 하한이며 실제 설비 안전/운전 한계가 아님 |
| `max_validation_rmse`, `max_validation_abs_error` | 독립 검증의 허용 오차. 단위 percent_full_scale. 실측의 센서/운전 조건을 근거로 별도 정해야 함 |
| `actual_resolution` | 실제 피드백의 분해능, percent_full_scale. 작은 변화만으로 응답시간을 식별했다고 주장하지 않도록 사용 |
| `training`, `validation` | 각 보정 채널마다 별도의 실험 기록 필요. 검증은 계수 추정에 사용하지 않음 |
| `recording_id`, `source_recording_id`, `source_file_sha256` | 도구용 ID, 원본 실험 ID, 선언한 원본 파일 해시 |
| `started_at` | 타임존을 포함하는 실제 기록 시작 시각. 예제의 시각은 합성 메타데이터 |
| `samples[].time_s` | 시작 0초, 증가하는 상대 시각, 0.1초 그리드에 명시적으로 정렬. 실제 재정렬 시 방법/원본도 별도 보존 |
| `target_percent_full_scale`, `actual_percent_full_scale`, `quality` | 명령과 실제 피드백 0..100, 유한값, 품질 `valid`. 품질 불명·결측·지원 범위 밖은 보정 입력에서 거절 |

각 기록은 4..2000개 표본, 전체 최대 8000개 표본, 기록별 최대 3600초다. 두 채널 중 하나만 보정해도 된다. 시간 간격은 불규칙해도 0.1초 그리드에 있어야 하며 도구는 자동 보간·결측 채움·시간대 추정을 하지 않는다. 학습/검증의 실험 ID·동일 데이터 중복 및 같은 채널의 수집 시간 창 겹침을 거절한다.

## 추정·검증·거절

탐색 범위를 먼저 33개 지점으로 훑고 가장 나은 주변 구간에서 골든 섹션 탐색을 한다. 학습 기록 전체 궤적의 실제 설정 RMSE를 최소화한다. 이 탐색이 전역 유일해나 통계적 신뢰구간을 보장하지 않는다. ±5% 주변 후보의 예측 변화는 국소 민감도 확인용이며 95% 신뢰구간이 아니다.

- **입력/출처/형식 실패:** `status=failed`, 오류 코드와 설명, 빈 `fitted_parameters`. 유효한 입력이 이미 읽혔다면 분류·입력 해시를 보존한다.
- **학습 변화 부족:** 실제 응답이 분해능보다 변하지 않는 등 응답시간을 추정할 정보가 없으면 실패한다.
- **후보 탈락:** 탐색 경계, 분해능보다 작은 민감도, 검증 오차 초과, 기본 5초보다 검증 오차가 분해능 이상 나빠지면 `candidate_rejected`다. 후보/진단은 검토용으로 남긴다.
- **후보 통과:** 설정한 모든 채널의 검증이 통과하면 `candidate_ready`다. 이는 해당 액추에이터 기록/가정에서의 오차 기준 통과다.

CLI 종료 코드는 후보 통과 0, 실패/탈락 2다. 입력 파일과 같은 출력 경로는 거절하고 입력 원본을 변경하지 않는다.

## 후보 저장과 팀 경계

결과는 `contracts/TEPActuatorCalibrationResult.schema.json`이다. 계수·단위·학습/검증/기본값 오차·탈락 사유, 원본/정규화 입력 해시, 모델 소스 커밋·파일/도구 해시, 태그/정규화/탐색 범위/오차 기준·기록 ID·시각·초기 실제 설정을 보존한다. 원본 해시·출처·품질은 사용자 선언이며 도구가 원본을 인증한 것은 아니다.

결과의 `usage=offline_candidate_only`, `activated=false`, `can_approve=false`, `validation_scope=cooling_actuator_response_only`, `whole_process_field_validation=not_performed`는 고정이다. 후보 JSON은 `TEPResult` 또는 승인 보고서가 아니며 런타임·DB·원본 NIST 소스를 변경하지 않는다. 현재 HTTP `/requests`는 계속 원본 5초 계수를 사용하고 TEP 요청은 전부 보류한다. 1번 배포/위험 정책과 3·4번 근거/화면의 기존 계약도 유지한다.

후보를 실제 TEP 실행에 채택하려면 1·2번이 실측 태그 대응·검증 기록·지원 조건을 검토하고, 명시적인 계수 주입 경로·별도 모델/빌드 버전·소스와 바이너리 해시·승인/재검증 정책을 연결해야 한다. 그 런타임 적용 기능과 전체 공정 계수 보정은 현재 구현 범위에 포함되지 않는다. 실측이 확보됐다는 이유만으로 현장 적용성 검증 완료로 바꾸지 않는다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m backend.simulator.tep.build
$env:IRON_MAN_TEST_TEP='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest tests/test_tep_calibration.py -q
```

24개 시험: 시뮬레이션 계수 복원, 검증 데이터 변경이 계수 추정에 영향 없음, 중복/시간 창 누출·불명 단위·태그 혼동·NaN·누락·범위 밖·품질 불명 거절, 변화 부족·탐색 경계·약한 민감도 탈락, 반복 결과 일치, CLI 원본 보존·실패 JSON, XMV10/XMV11의 실제 외부 코어 5초 응답과 성분식의 10⁻¹⁰ 이내 일치를 확인한다. 실제 코어 시험 두 건은 환경 변수 없으면 제외하며 통과로 계산하지 않는다.

2026-10-09: 팀원의 최신 TEP 근거·화면 변경을 병합하고 실제 코어와 로컬 참조 데이터 시험을 활성화한 전체 회귀 시험에서 **356 passed** (보정 24개 포함), 68.04초를 확인했다. 프런트 TypeScript 검사·Vite 빌드도 통과했다. 기존 FastAPI TestClient의 httpx 관련 deprecation 경고 1건이 남아 있다. **실측 계수 보정·전체 공정 정확도·현장 적용성 검증은 미완료다.**

전체 시험 대상은 `74bfe66`이다. 후속 배포 커밋 `5d6b42e` 병합 후에는 변경과 관련된 배포·자동 프런트 시험 20개와 TypeScript 검사·Vite 빌드를 다시 확인했다.
