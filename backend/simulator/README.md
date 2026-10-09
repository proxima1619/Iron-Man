# 시뮬레이터 모듈 안내

이 폴더는 **2번 담당**의 가상 냉각 탱크 계산과 데모 설비 상태를 맡습니다. 현재 구현은 합성 상태와 데모 계수로 작동하며 실제 설비, PLC, 실측 센서와 연결되지 않습니다.

## 파일과 호출 경계

| 파일 | 역할 |
|---|---|
| `service.py` | `simulate(command, snapshot, scenarios, model_version=MODEL_VERSION)`로 변경 전·후 온도를 계산 |
| `adapter.py` | SQLite에 저장된 가상 설비 상태를 읽고 승인된 명령을 적용하는 `DemoAdapter` |
| `../../contracts/README.md` | 팀 공통 API v1.0의 필드와 상태 정의 |
| `../../docs/model_card.md` | 계산식, 계수, 입력 범위와 모델 한계 |
| `../../docs/STORAGE.md` | SQLite 경로, 재시작 복구, 백업과 운영 제약 |

관문 서버(`backend/gateway/service.py`)가 모듈을 호출하고 최종 `blocked`·`hold`·`awaiting_approval`을 판정합니다. 시뮬레이터는 승인이나 실행 권한을 결정하지 않습니다.

## 입력과 반환값

`Command`에는 목표 펌프 속도(%)와 유지 시간(s)이 들어갑니다. `Snapshot`에는 초기 온도(°C), 부하 비율, 기존 펌프 속도(%), 관측 시각, 센서 품질이 들어갑니다. `Scenario`는 현재 `normal`과 `degraded_cooling`을 지원하며 `evidence_id`로 근거 카드와 연결할 수 있습니다. 타입 원본은 `backend/contracts.py`입니다.

같은 초기 상태와 같은 시나리오 조건에서 **기존 속도 유지**와 **요청 속도 적용**을 각각 계산합니다. `completed`일 때 시나리오마다 기존·변경 후 최고 온도, 80°C 제한, 초과 여부, `value_origin=model_calculation`을 반환합니다. 센서 불량·입력 범위 밖은 `out_of_domain`과 빈 `scenarios`, 사유가 담긴 `limitation`을 반환합니다. 시나리오가 없으면 `failed`입니다. 호출자가 지원하지 않는 모델 버전을 지정하면 예외가 발생해 관문 서버에서 보류합니다.

모델은 내부적으로 1초 간격 온도 변화를 계산합니다. **현재 공통 API v1.0은 시계열과 최초 초과 시각 필드를 정의하지 않아 외부 결과에 포함하지 않습니다.** 화면에 그래프가 필요하면 1·2·4번이 계약 필드와 단위를 합의한 뒤 `backend/contracts.py`, 생성된 스키마·타입, 테스트를 함께 갱신해야 합니다.

## 가상 어댑터

`DemoAdapter`는 관문 서버와 같은 `SQLiteStore`를 사용합니다. 기본 DB 경로와 서버 재시작 동작은 `docs/STORAGE.md`를 따릅니다. `read_state()`는 DB에 저장된 가상 상태의 스냅샷을 반환하고, `update_demo_state()`는 데모 전용 부하·센서 품질을 저장합니다. 상태의 `observed_at`은 읽을 때마다 현재 시각으로 생성하므로 실제 센서 관측 시각이 아닙니다.

`apply_command(execution_id, command)`는 가상 펌프 속도와 적용 영수증을 **하나의 SQLite 트랜잭션**으로 저장합니다. 같은 `execution_id`와 같은 명령은 이전 결과를 반환하고, 다른 명령으로 재사용하면 오류를 냅니다. `get_execution(execution_id)`는 저장된 영수증을 조회합니다. 관문 서버는 실행 예약을 먼저 저장하며, 실행 중 재시작해 결과가 불명확하면 자동으로 재전송하지 않습니다.

`simulate()`는 어댑터 상태를 변경하지 않습니다. 실제 적용은 관문 서버의 승인·재검증 절차에서만 어댑터를 호출합니다. 어댑터 온도는 현재 60°C 합성 고정값이고 명령 후 실제 물리 반응을 관측한 값이 아닙니다.

## 현재 판정과 검증

현재 계산 결과는 `mock=false`입니다. 관문 서버의 v1.0 정책은 한계 초과를 `blocked`로 처리하고, 한계를 넘지 않아도 비모의 계산 승인 정책이 아직 없어 `hold / LIVE_POLICY_NOT_CONFIGURED`로 처리합니다. 합성 모델 통과를 현실 설비의 안전 승인으로 해석하면 안 됩니다.

저장소 루트에서 개발 의존성을 설치한 가상환경으로 실행합니다.

```bash
python -m pytest tests/test_simulator.py -q
python -m pytest tests/test_persistence.py -q
python -m pytest -q
```

시뮬레이터 테스트는 반복 실행의 재현성, 같은 초기 상태 비교, 펌프 속도 방향성, 입력 범위 밖 처리, 모델 버전 검사, 비모의 결과의 승인 보류를 확인합니다. 저장 테스트는 가상 상태·적용 영수증의 재시작 후 유지, 중복 실행 방지, 저장 실패 시 원자적 취소를 확인합니다. Windows 로컬 환경에서도 전체 테스트를 실행해 55개가 통과했습니다.

## 이 모듈을 수정할 때

`service.py` 또는 `adapter.py`의 입력·계수·상태·출력을 바꿀 때 이 README와 `docs/model_card.md`의 해당 설명을 함께 갱신합니다. 공통 API 필드 변경은 1번과 합의하고 `contracts/README.md`, 생성 스키마·타입, 소비 모듈과 테스트를 같이 확인합니다. 계산값·제한값을 바꿨다면 시연 사례와 문서의 숫자도 실제 테스트 결과로 다시 확인합니다.
