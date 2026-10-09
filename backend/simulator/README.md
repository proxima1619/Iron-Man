# 시뮬레이터 모듈 안내

이 폴더는 **2번 담당**의 TEP 외부 시뮬레이터 연동과 기존 합성 탱크 계산을 맡습니다. 현재 실제 설비·PLC·실측 센서 데이터는 없습니다. **공개 NIST TEP 모델을 실제 실행해 생성하는 시뮬레이션 데이터**를 제공합니다. 실측 오차 평가와 실제 설비 적용성 검증은 미완료입니다. 시뮬레이터 변경 시 이 문서도 함께 갱신합니다.

## 현재 기준: TEP 외부 연동 v1

### 추가된 로컬 데이터

`archive/TEP_data`를 **데모용 시뮬레이션 참조 데이터**로 연결했습니다. 현장 실측이 아닙니다. 44개 데이터 파일·31,700개 관측·52개 변수를 읽고 정상 학습 `d00.dat`는 52×500 배열을 전치합니다. 역할 토큰으로 연결한 화면의 **TEP 참조 데이터 · 정상/고장 기록 탐색**을 펼치면 기록·변수 선택, 그래프·통계·전체 값, 재현 메타데이터를 포함한 JSON 저장을 사용할 수 있습니다. 시간 기록이 없어 표본 번호로 표시합니다. 180초는 동봉 코드의 설정이며 파일별 간격·시드·초기 상태·고장 시작 표본은 미확인입니다.

참조 기록은 읽기 전용이며 외부 엔진의 기준/변경 실행 결과를 대체하거나 승인 보고서에 혼합하지 않습니다. 폐루프 참조 기록과 현재 개루프 실행의 조건 차이 때문에 RMSE·현장 오차·안전 한계를 계산하지 않습니다. 다운로드 출처·원본 버전·데이터 라이선스 적용 범위는 확인 중입니다. 원본 파일은 변경하거나 GitHub에 재배포하지 않았습니다. [로컬 자료 확인과 실행 방법](../../docs/TEP_LOCAL_DATA_AUDIT.md)을 참고하세요.

기본 위치는 저장소의 `archive/TEP_data`이고 다른 위치는 `IRON_MAN_TEP_REFERENCE_DIR`로 지정합니다. `/tep/reference/catalog`, `/tep/reference/series/{file_id}?variable=XMEAS9`로 읽습니다. `reference.lock.json`에 현재 업로드의 원본·설명/Fortran 파일 해시를 보존합니다. 파일/단위 불명·해시 불일치·관측 누락·NaN/무한대는 참조 성공 결과로 반환하지 않습니다. 자료가 없어도 외부 엔진은 실행 가능하며, 참조 API는 503을 반환합니다.

상세한 선정 근거·라이선스·전체 변수 사전·재현 설정·시험 결과·후속 실측 검증 절차는 [TEP_INTEGRATION.md](../../docs/TEP_INTEGRATION.md)를 먼저 읽으세요.

| 파일 | 역할 |
|---|---|
| `tep/vendor/teprob.cpp`, `teprob.h` | 고정 NIST 커밋의 원본 공정 방정식, 수정 없이 포함 |
| `tep/source.lock.json`, `vendor/LICENSE.md`, `DISCLAIMER.md` | 소스 커밋·SHA-256·사용/배포 허가·보증 부인 |
| `tep/runner.cpp` | 독립 실행 C++ 프로세스: 입력 설정, 원본 초기화, 적분, CSV 출력 |
| `tep/build.py` | Linux g++ 또는 Windows→Ubuntu WSL에서 명시적 빌드, manifest 생성 |
| `tep/variables.py` | 12 XMV·41 XMEAS·실제 냉각수 설정의 정의·단위 |
| `tep/service.py` | 기준/변경 분리 실행, 엄격한 결과 확인, 같은 시간축의 비교 |
| `tep/reference.py`, `reference_contracts.py`, `reference.lock.json` | 사전 생성 참조 기록의 읽기 전용 로더·계약·로컬 업로드 해시 프로필 |
| `../../../scripts/run_tep.py` | 실제 실행·반복 재현성 확인·JSON 저장 CLI |

Windows의 기존 Ubuntu WSL, g++ 및 GNU `timeout`이 필요합니다. Linux에서도 같은 소스를 빌드합니다. MATLAB·OpenModelica·공개 이력 데이터 파일은 필요 없습니다. 저장소 루트에서:

```powershell
.\.venv\Scripts\python.exe -m backend.simulator.tep.build
.\.venv\Scripts\python.exe -m scripts.run_tep --repeat
$env:IRON_MAN_TEST_TEP='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q
```

`set_tep_cooling_water`, 대상 `tep-sim-01`, 변수 `XMV10/11`, 단위 `percent_full_scale`, 입력 0..100을 사용합니다. **펌프 속도 %가 아닙니다.** 기본 초기 상태·원본 시드 1431655765·제어기 없음·외란 없음, 0.1초 Euler, 기본 600초/10초 관측으로 실행합니다. 지원 구간은 1..1800초이며 관측 주기의 정수 배수입니다. 같은 초기 상태를 새 프로세스마다 구성하고 기준 MV 유지와 선택 MV 변경을 비교합니다.

기존 `/requests` 흐름은 `report.tep_simulation`에 결과를 저장합니다. `baseline/candidate.points`는 같은 시간축의 입력·관측이며 `comparison`은 변수별 차이입니다. 초기 50 내부 상태·12 입력, 출처·컴파일러·바이너리/CSV 해시 등도 보존합니다. 모델 정지·실행 실패·결과 누락·불명 단위·입력 범위 밖은 완료로 처리하지 않습니다. 부분 CSV는 진단용이며 성공 수치를 보고서에 섞지 않습니다.

TEP 계산이 성공해도 **TEP 승인 정책 미설정으로 hold**, `can_approve=false`, `execution_scope=unconfigured`입니다. 기존 탱크의 80°C·60/80%·0.65 효율·근거 fixture를 TEP에 적용하지 않습니다. 실제 설비 적용은 구현하지 않았습니다.

2026-10-09 확인: 최신 팀원 근거 인계 변경을 포함하여 전체 **290 tests passed**, 프런트 타입 검사·빌드 통과. 600초 기준/변경 반복 결과·CSV 해시 일치, 변경 없음 차이 0, XMV10/XMV11 변경, 원본 압력 정지와 승인 차단 확인. Docker/HTTPS 브라우저 실행은 로컬 환경에서 미검증입니다. 실측 검증은 별도 미완료 단계입니다.

## 기존 합성 냉각 탱크 (별도 경로)

Dockerfile·Compose·CI의 배포 변경은 1번의 최종 검토·통합 대상입니다. 시제품용 Dockerfile 변경은 보존했으며 배포 완료로 표시하지 않습니다. 패키지·빌드·환경변수·볼륨·확인/미확인 결과는 [배포 인계](../../docs/TEP_INTEGRATION.md#1번-관문배포-담당에게-인계-배포-미완료)에 있습니다.

아래 문단은 `cooling-demo-01 / set_pump_speed` 전용입니다. TEP 입력·모델·정책으로 사용하지 않습니다.

## 파일과 호출 경계

| 파일 | 역할 |
|---|---|
| `service.py` | `simulate(command, snapshot, scenarios, model_version=MODEL_VERSION)`로 변경 전·후 온도를 계산 |
| `model.py` | `cooling-demo-v3`의 열용량·발열·열전달·냉각수 온도·펌프 응답과 공통 계산 커널 |
| `assessment.py` | `cooling-assessment-v4`: 3600초·평형 온도 및 4개 계수의 16개 민감도 조합 |
| `calibration.py` | 기준 열용량을 고정한 오프라인 보정 후보 생성·독립 검증; 서버에 자동 적용하지 않음 |
| `adapter.py` | SQLite에 저장된 가상 설비 상태에 목표값을 적용하고 수동 가상 시간을 진행하는 `DemoAdapter` |
| `../../contracts/README.md` | 팀 공통 API v1.0의 필드와 상태 정의 |
| `../../docs/model_card.md` | 계산식, 계수, 입력 범위와 모델 한계 |
| `../../docs/STORAGE.md` | SQLite 경로, 재시작 복구, 백업과 운영 제약 |

관문 서버(`backend/gateway/service.py`)가 모듈을 호출하고 최종 `blocked`·`hold`·`awaiting_approval`을 판정합니다. 시뮬레이터는 승인이나 실행 권한을 결정하지 않습니다.

## 입력과 반환값

`Command`에는 목표 펌프 속도(%)와 예측 구간 `duration_s`가 들어갑니다. `Snapshot`에는 온도(°C), 부하 비율, 실제 펌프 속도 `pump_speed_pct`, 목표 속도 `target_pump_speed_pct`, 가상 경과 시간 `simulation_time_s`, 모델 버전, 계산 시각 `calculated_at`, 관측 시각 `observed_at`, 센서 품질과 `domain_status`·`domain_reason`이 들어갑니다. 두 시각은 Unix 초, 가상 경과 시간은 초입니다. `Scenario`는 현재 `normal`과 `degraded_cooling`을 지원하며 `evidence_id`로 근거 카드와 연결할 수 있습니다. 타입 원본은 `backend/contracts.py`입니다.

같은 초기 상태와 같은 시나리오 조건에서 **기존 목표 속도 유지**와 **요청 목표 속도 적용**을 각각 계산합니다. 목표값에 아직 도달하지 않은 상태라면 기존 설정 분기도 현재 실제 속도에서 기존 목표를 향해 계속 응답합니다. 과거 스냅샷에 목표 속도가 없으면 실제 속도를 기존 목표로 사용합니다. 현재 모델 버전은 `cooling-demo-v3`입니다. `completed`일 때 시나리오마다 기존·변경 후 최고 온도, 80°C 제한, 초과 여부, `value_origin=model_calculation`을 반환합니다. 센서 불량·입력 범위 밖뿐 아니라 **계산 도중 온도나 유효 펌프 속도가 범위를 벗어나는 경우**에도 `out_of_domain`과 빈 `scenarios`, 사유가 담긴 `limitation`을 반환합니다. 기존 설정과 요청 설정 중 하나라도 지원하지 못하면 전체 시나리오의 성공 수치를 반환하지 않습니다. 시나리오가 없으면 `failed`입니다. 호출자가 지원하지 않는 모델 버전을 지정하면 예외가 발생해 관문 서버에서 보류합니다.

모델은 기본 1초 간격의 RK4 적분으로 온도와 펌프 속도를 함께 계산합니다. 요청 구간 결과의 의미는 유지하고 `physical_assessment`에 3600초 최고 온도·최초 초과 표본 시각·평형 온도·열 시정수·계수 민감도를 추가했습니다. 상세 시계열은 공통 API에 포함하지 않습니다. 과거 보고서의 추가 필드는 null이며 새 승인 정책은 평가 누락을 보류합니다.

## 장기 검사와 계수 보정

물리 커널·기본 계수·SQLite 상태는 v3를 유지하고, 추가 평가는 `cooling-assessment-v4`, 승인 정책은 `virtual-cooling-policy-v3`로 구분합니다. 이전 정책의 승인은 새로 평가해야 합니다. [물리 보완 안내](../../docs/PHYSICAL_ASSESSMENT.md)에 계산 가정, 계수 범위, 지원 불가 처리, 데이터 형식과 인계 사항을 정리했습니다.

- 요청 구간 외에 3600초 예측과 일정 조건의 평형 온도를 확인합니다. 60°C·부하 1·현재 100%에서 80% 요청은 효율 저하 조건의 300초 최고값이 약 77.268°C여도 378초에 한계를 넘고 장기 최고값이 약 92.305°C여서 차단됩니다.
- 열용량·발열·열전달·펌프 응답 각각 ±10%의 16개 끝점 조합을 가정합니다. 실제 측정 범위·통계적 신뢰구간·모든 중간 조합의 보장이 아닙니다. 민감도 계산 일부가 범위를 벗어나면 민감도 성공 수치는 반환하지 않습니다.
- 실제 계측 기록이 없어 런타임은 `calibration_status=not_calibrated`입니다. `python -m scripts.calibrate_model --input measurements.json --output candidate.json`으로 학습/독립 검증 기록과 기준 열용량을 제공해 오프라인 후보를 만듭니다. 검증 오차·출처 해시를 남기며 기존 모델·DB를 자동 변경하지 않습니다. 합성 예제는 `examples/simulator/`에 있습니다.
- 시간에 따른 고장과 센서 관측/실제 상태 분리는 후속 과제로 남겨둡니다.

## v3 계산과 지원 범위

```text
200000 × dT/dt = 35000 × load_ratio − 1000 × (actual_speed_pct / 100) × efficiency × (T − 25)
d(actual_speed_pct)/dt = (target_pct − actual_speed_pct) / 20
```

온도는 °C, 시간은 s, 열용량은 J/K, 발생 열량은 W, 유효 열전달 계수는 W/K입니다. 정상 효율은 1.0, 효율 저하 조건은 0.65입니다. 모두 실측 보정 전의 데모 가정입니다. 냉각량이 탱크와 냉각수의 온도 차이에 비례하므로 무부하 냉각이 냉각수 온도에 접근합니다. 정상 조건에서 60°C·부하 1.0·속도 100%는 평형 상태입니다. 식의 근거와 가정은 `docs/model_card.md`에서 확인할 수 있습니다.

초기 온도와 각 적분 단계의 온도는 0~120°C, 유효 펌프 속도는 0~100%여야 합니다. 부하 비율은 0~1.5를 지원하며 명령 시간은 API가 허용하는 1~3,600초입니다. 계산 중 범위를 벗어나면 `limitation`에 시나리오·기존/요청 설정·발생 시각을 담아 계산을 중단합니다. 온도값을 잘라 지원 범위에 맞추지 않습니다. 최고 온도는 초기값과 각 단계의 반올림 전 계산값을 포함하고 80°C **초과**를 위반으로 판정합니다. 80°C 제한은 안전 판정 기준, 120°C는 모델 지원 범위의 상한입니다.

## 가상 어댑터

`DemoAdapter`는 관문 서버와 같은 `SQLiteStore`를 사용합니다. 기본 DB 경로와 서버 재시작 동작은 `docs/STORAGE.md`를 따릅니다. 온도·실제 속도·목표 속도·가상 경과 시간과 관측·계산 시각을 저장합니다. `read_state()`와 `GET /state`는 저장된 스냅샷을 반환하며, 읽는 것만으로 물리 상태나 관측 시각을 갱신하지 않습니다.

`apply_command(execution_id, command)`는 **목표 속도만 변경**하고 적용 영수증과 함께 하나의 SQLite 트랜잭션으로 저장합니다. 실제 속도와 온도는 이 호출에서 순간적으로 바뀌지 않습니다. 같은 `execution_id`와 같은 명령은 이전 결과를 반환하고, 다른 명령으로 재사용하면 오류를 냅니다. `get_execution(execution_id)`는 저장된 영수증을 조회합니다. 관문 서버는 실행 예약을 먼저 저장하며, 실행 중 재시작해 결과가 불명확하면 자동으로 재전송하지 않습니다.

가상 시간은 **수동 진행**입니다. 벽시계 시간이나 서버 종료 시간을 자동으로 따라잡지 않습니다. 승인자 토큰으로 다음 데모 API를 사용할 수 있습니다.

| API | 동작 |
|---|---|
| `POST /demo/advance` + `{"seconds_s": 10}` | 1~3,600 정수 초 동안 정상 효율의 공통 계산 커널로 실제 속도·온도를 갱신 |
| `POST /demo/sample` | 현재 저장 상태를 새로 관측하고 `observed_at` 갱신; 가상 시간과 물리 상태 유지 |
| `POST /demo/state` | 데모 부하·센서 품질 변경 |
| `POST /demo/reset` | 60°C·부하 1.0·실제/목표 100%·가상 시간 0으로 초기화; revision 증가, 요청·영수증 이력 보존 |

시간 진행 중 지원 범위를 벗어나면 마지막 유효 온도·속도를 보존하고 `domain_status=out_of_domain`과 사유를 저장합니다. 해당 상태는 센서 불량으로 표시되며 관측만 다시 하거나 부하를 바꿔도 지원 가능 상태로 복구되지 않습니다. 데모를 다시 시작하려면 명시적으로 초기화합니다. 80°C 초과와 모델 범위 이탈은 서로 다르며, 120°C 이하는 모델로 계산할 수 있어도 안전한 상태를 뜻하지 않습니다.

`simulate()`는 어댑터 상태를 변경하지 않습니다. 명령 적용은 관문 서버의 승인·재검증 절차에서만 어댑터를 호출합니다. `duration_s`는 요청을 시험할 **예측 구간**입니다. 적용된 목표값은 다음 명령이나 초기화까지 유지하며 예측 구간이 끝나도 자동 만료·되돌림하지 않습니다. 가상 상태에는 정상 효율을 사용하고 `degraded_cooling`은 별도 예측 시나리오입니다.

가상 시간 진행·부하 변경·초기화 후에는 상태 digest가 달라집니다. 기존 승인을 실행하면 관문이 `revalidation_required`로 전환하며 다시 검토·승인해야 합니다. 관측 시각은 digest에서 제외되지만 기존 관측 노후 검사와 승인 만료 검사는 유지합니다. 재검증 정책과 승인 허용 조건의 담당은 1번입니다.

## 현재 판정과 검증

현재 계산 결과는 `mock=false`입니다. 관문은 요청·장기·평형·민감도 시험의 기존/요청 분기에서 한계 위반을 확인하면 `blocked`, 확인된 위반 없이 지원을 완료하지 못하면 `hold`로 처리합니다. 모든 가상 정책 조건을 충족하면 담당자 승인 대기로 전환합니다. 부하 1의 80% 요청은 차단되며, 승인 흐름 예제는 부하 0.6의 80% 요청입니다. 합성 모델 통과를 현실 설비의 안전 승인으로 해석하면 안 됩니다.

저장소 루트에서 개발 의존성을 설치한 가상환경으로 실행합니다.

```bash
python -m pytest tests/test_simulator.py -q
python -m pytest tests/test_persistence.py -q
python -m pytest tests/test_virtual_plant.py -q
python -m pytest tests/test_physical_assessment.py tests/test_calibration.py -q
python -m pytest -q
```

시뮬레이터 검증에서는 반복 실행의 재현성, 같은 초기 상태 비교, 진행 중인 목표 속도의 기존 분기, 입력·계산 도중 범위 밖 처리, 모델 버전 검사, 비모의 결과의 승인 보류를 확인합니다. 물리적 성질은 무부하 냉각, 일정 속도의 평형 온도, 펌프가 멈춘 상태의 가열, 시간 간격을 줄였을 때의 수렴과 펌프 응답 지연으로 검증합니다. v3 어댑터와 저장 테스트는 목표/실제 속도 분리, 수동 시간 진행의 연속성, 재시작 후 온도·속도·시간 유지, 관측 갱신, 범위 이탈 처리, DB 이관, 중복 실행 방지와 저장 실패 시 원자적 취소를 확인합니다.

## 이 모듈을 수정할 때

`service.py`, `model.py` 또는 `adapter.py`의 입력·계수·상태·출력을 바꿀 때 이 README와 `docs/model_card.md`의 해당 설명을 함께 갱신합니다. 공통 API 필드 변경은 1번과 합의하고 `contracts/README.md`, 생성 스키마·타입, 소비 모듈과 테스트를 같이 확인합니다. 계산값·제한값을 바꿨다면 모델 버전과 시연 사례, 문서의 숫자도 실제 테스트 결과로 다시 확인합니다. 저장된 v1·v2 보고서와 승인은 새 모델 버전으로 재검증해야 합니다.
