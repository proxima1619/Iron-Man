# 긴 평가 작업 분리

## API 동작 변경

`POST /requests/{id}/evaluate`는 완료를 기다리지 않고 **202 Accepted**와 `evaluating` 상태를 반환합니다. 이후 `GET /requests/{id}`를 조회하세요. React 화면은 약 1초 간격으로 결과를 자동 갱신합니다. HTTP 202나 작업 완료를 안전 승인으로 해석하지 않습니다.

```text
요청 접수 → DB에 evaluating·작업 ID·revision 저장 → HTTP 202
                    ↓
         별도 프로세스에서 근거 검토·계산
                    ↓
       입력·작업·revision·상태·버전·시간 재확인
                    ↓
            DB 보고서·최종 판정 저장
                    ↓
             화면의 GET 조회로 확인
```

작업 정보는 `RequestRecord.evaluation`에 포함됩니다. 기존 DB JSON에 없는 경우 null로 반환합니다. SQL 테이블 변경은 없고 스키마 버전은 1을 유지합니다.

| 필드 | 의미 |
|---|---|
| id | 평가 작업 UUID |
| revision | 평가 대상 요청 revision |
| status | running / completed / failed / timed_out / cancelled / interrupted |
| started_at | 접수 시각, Unix 초 |
| deadline_at | 결과 반영 제한 시각, Unix 초 |
| finished_at | 종료 시각, 진행 중 null |

`evaluation.status=completed`는 계산·검토 작업이 끝났다는 뜻입니다. 최종 판정은 `report.verdict`와 `can_approve`를 확인하세요. 근거 부족이나 상태 변경으로 보고서가 보류되어도 작업 자체는 완료일 수 있습니다.

## 동시에 할 수 있는 것

- 같은 요청의 상태·기록 조회.
- 가상 설비 상태 조회.
- 새 요청 생성·다른 요청 평가.
- 별도 요청의 승인·가상 실행. 이 동작으로 상태가 변하면 진행 중 평가 결과는 보류될 수 있습니다.
- 진행 중 평가 취소.

실제 모듈 계산은 DB 잠금 밖의 자식 프로세스에서 수행합니다. SQLite와 가상 어댑터 접근은 서버 프로세스에만 있습니다. 접수·결과 저장·승인·실행에는 짧은 잠금을 사용합니다. 실제 장비나 느린 외부 어댑터 실행을 비동기로 분리한 단계는 아닙니다.

## 개수·시간 제한

- 기본 동시 평가 **2개**. 긴 대기열을 만들지 않습니다.
- 작업이 모두 사용 중이면 **429**, `Retry-After: 1`. 요청은 이전 상태를 유지하므로 잠시 후 재접수합니다.
- 같은 요청이 이미 평가 중이면 **409**. 같은 작업을 중복 생성하지 않습니다.
- 기본 제한 시간 **90초**. 시간 초과 시 자식 프로세스를 종료하고 보류 보고서를 남깁니다.
- 상태 snapshot의 유효 시간은 **60초**입니다. 60초를 넘긴 계산이 완료되어도 상태가 오래되었으면 보류합니다. 90초 작업 제한과는 별도입니다.
- 외부 API 라이브러리 자체에도 더 짧은 연결·응답 제한 시간을 설정하세요. 원격 서비스의 이미 접수된 작업까지 취소되었다고 보장하지 않습니다.

환경변수:

```bash
IRON_MAN_EVALUATION_WORKERS=2
IRON_MAN_EVALUATION_TIMEOUT_S=90
```

workers는 1~4, timeout은 0초 초과~300초입니다. Docker Compose에도 전달됩니다. API 서버 worker는 기존처럼 **1개**이며 평가 프로세스 수와 별개입니다. 현재 AWS 권장 2vCPU/4GB 시작 사양에서는 기본값으로 먼저 검증하세요.

## 취소·실패·종료

`POST /requests/{id}/evaluation/cancel`은 인증된 사용자에게 허용됩니다. 현재는 데모 역할 기반 인증으로, 요청 소유자별 권한은 후속입니다.

| 경우 | 처리 |
|---|---|
| 사용자 취소 | cancelled, hold / EVALUATION_CANCELLED, 프로세스 종료 |
| 제한 시간 초과 | timed_out, hold / EVALUATION_TIMEOUT |
| 시작 실패 | failed, hold / WORKER_FAILURE, 접수 API 503 |
| 프로세스 중단·잘못된 보고서 | failed, hold / WORKER_FAILURE |
| 모듈이 검토 실패 반환 | failed, hold / MODULE_FAILURE |
| 검토 중 상태·모델·정책·snapshot 유효 시간 변경 | completed, hold / EVALUATION_CONTEXT_CHANGED |
| 정상 서버 종료 | 실행 중인 평가를 취소하고 프로세스를 정리한 뒤 DB 닫음 |
| 비정상 서버 종료 후 재시작 | interrupted, hold, report=null, 중단 이벤트 기록; 자동 재접수 없음 |

취소한 작업과 시간 초과 작업의 늦은 결과는 반영하지 않습니다. 결과 저장 전 request ID, 작업 ID, revision, 요청 입력, 보고서의 입력 digest·snapshot·버전을 다시 확인합니다. 새 상태를 이전 결과로 덮어쓰지 않습니다.

DB 장애로 결과를 저장하지 못하면 로그를 남기고 DB의 진행 중 상태가 유지될 수 있습니다. 저장소 복구 후 서버 재시작으로 중단 상태를 정리합니다. 성공 보고서로 대체하지 않습니다.

## 팀원 연동

- 2·3번 함수 계약은 그대로입니다. 작업 프로세스가 해당 Python 모듈을 import하고 호출합니다.
- 3번이 호출하는 외부 API 키는 서버 실행 환경변수로 제공하며 프런트나 이미지에 넣지 않습니다. 실제 키 연결은 배포 단계에 추가합니다.
- 모듈의 전역 메모리 캐시는 작업 간 유지된다고 가정하지 마세요. 프로세스별로 모듈을 새로 로드합니다.
- 자식 프로세스 안에서 별도 하위 프로세스를 띄우는 라이브러리를 도입한다면 현재 daemon 작업 설정과 호환되는지 1번과 먼저 확인하세요.
- 4번은 202 응답 뒤 조회를 반복하고, 진행 중 승인·실행을 활성화하지 않습니다. 취소 후에는 새 평가 revision으로 재접수합니다.
- 내부 `Gateway.evaluate()`는 테스트·예시 내보내기용 동기 함수입니다. HTTP 경로는 `submit_evaluation()`을 사용합니다.

## 검증

```bash
.venv/bin/pytest -q tests/test_async_evaluation.py
.venv/bin/pytest -q
```

spawn 방식의 실제 프로세스를 사용해 첫 작업을 지연시키고 조회·다른 요청을 확인합니다. 동시 중복 접수, 용량 제한, 취소·시간 초과, 자식 오류, 오래된 입력·작업 결과, 종료·재시작 상태를 검사합니다. 기존 승인·저장 테스트는 동기 헬퍼로 계속 검사하고 비동기 경로를 별도 테스트합니다.

장기 작업의 승인 정책은 바꾸지 않았습니다. 현재 합성 모델의 60% 요청은 위험 차단, 80% 요청은 비모의 모듈 승인 정책 미설정 보류입니다.
