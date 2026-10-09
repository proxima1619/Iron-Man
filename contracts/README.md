# 팀 연동 계약 v1.0

**1번이 먼저 제공하는 공동 개발 기준**입니다. 이 계약을 기준으로 2·3번은 반환값을 만들고, 4번은 샘플 응답으로 화면을 개발할 수 있습니다. 실제 계산·검색·LLM 구현은 포함하지 않습니다.

## 어디부터 볼까?

| 담당 | 먼저 볼 파일 | 구현할 경계 |
|---|---|---|
| 2번 | `SimulationResult.schema.json`, `examples/simulation-demo.json`, `examples/simulation-out-of-domain.json` | `simulate(command, snapshot, scenarios) -> SimulationResult` |
| 3번 | `EvidenceReview.schema.json`, `examples/evidence-demo.json`, `examples/evidence-insufficient.json` | `review_evidence(request, snapshot) -> EvidenceReview` |
| 4번 | `openapi.json`, `examples/request-record-demo.json`, `frontend/src/api.generated.ts` | 요청·보고서·승인·실행 API |

Python 타입 원본은 `backend/contracts.py`입니다. 위 경로는 저장소 루트 또는 이 문서가 있는 `contracts/` 기준으로 확인하세요. 실제 모듈은 Pydantic 객체 또는 같은 형태의 dict를 반환할 수 있습니다. 서버는 모듈 응답을 다시 검증합니다.

## 공통 규칙

- `schema_version`: `1.0`. 알 수 없는 필드는 거절합니다. 이름·의미·단위를 바꾸기 전에 1번과 합의하세요.
- 온도는 °C, 속도는 %, 예측 구간과 가상 경과 시간은 s, 관측·계산 시각은 Unix 초입니다. NaN·무한대는 거절합니다. 명령의 `duration_s`는 예측 구간이며 적용 목표값의 자동 만료 시간이 아닙니다.
- `mock`는 필수 boolean입니다. 실제 계산 값/문서로 바뀌었을 때만 false로 설정하세요.
- 실패를 정상 값 0, 빈 성공 결과, 가짜 출처로 대신하지 않습니다.
- `limitation`은 필수입니다. 계산 범위, 부족한 근거 또는 실패 이유를 설명합니다.
- 요청의 수정은 현재 새 요청 생성으로 처리합니다. 이전 승인을 재사용하지 않습니다.

## 2번: 계산 결과

### v3 상태 입력

`Snapshot.pump_speed_pct`는 실제 속도이며 `target_pump_speed_pct`는 유지 중인 목표 속도입니다. `simulation_time_s`는 수동으로 진행한 가상 경과 시간, `calculated_at`은 마지막 계산의 벽시계 시각, `observed_at`은 마지막 합성 관측 시각입니다. `model_version`, `domain_status`(`ready` / `out_of_domain`), `domain_reason`으로 모델과 지원 상태를 전달합니다. 현재 모델은 `cooling-demo-v3`입니다.

기존 보고서 파싱을 위해 추가 필드는 기본값을 갖습니다. 목표 속도가 null인 과거 스냅샷은 실제 속도를 기존 목표로 사용합니다. 현재 어댑터는 모든 상태 필드를 저장·반환합니다. 기존 설정 분기는 기존 목표를 유지하며, 요청 분기와 동일한 실제 속도·온도에서 시작합니다. 저장된 이전 모델의 승인은 새 모델로 재검증해야 합니다.

| status | scenarios | 서버 처리 |
|---|---|---|
| `completed` | 요청한 모든 시나리오 결과 | 온도 한계 검사 |
| `out_of_domain` | 빈 배열 | `hold / SIMULATION_INCOMPLETE` |
| `failed` | 빈 배열 | `hold / SIMULATION_INCOMPLETE` |

시나리오마다 `kind`, `evidence_id`, `baseline_peak_c`, `candidate_peak_c`, `limit_c`, `exceeded`, `value_origin`을 반환합니다. `exceeded`는 변경 후 최고 온도가 한계보다 **클 때** true입니다. 한계와 같은 경우 false인 MVP 정의이며, 안전 여유·시간별 판정 등 확장은 별도 합의합니다.

`value_origin`은 `hardcoded_demo_fixture` 또는 `model_calculation`입니다. 입력으로 받은 시나리오를 모두 반환해야 하며, 누락·추가·중복·근거 ID 불일치는 보류됩니다. `model_version`은 모듈의 `MODEL_VERSION`과 일치해야 합니다.

현재 시험은 `normal`, `degraded_cooling` 두 종류입니다. 효율 수치·부하 등 임의 파라미터 제안은 아직 계약에 없습니다. 2·3번이 필요한 변수·단위·범위를 합의한 뒤 확장하세요.

## 3번: 근거 검토

| status | 뜻 | 서버 처리 |
|---|---|---|
| `demo_fixture` | 팀 작성 모의 응답, 반드시 mock=true | 가상 설비 데모 경로 |
| `completed` | 출처를 갖춘 검토 결과 | 적용 조건과 후속 계산 확인 |
| `insufficient` | 근거 부족·필수 조건 미확인 | `hold / EVIDENCE_INCOMPLETE` |
| `failed` | 검색·검토 처리 실패 | `hold / EVIDENCE_INCOMPLETE` |

각 카드에 출처 ID, 주장, 지지/반례/한계, 원문 위치, 출처 종류와 적용 가능성을 넣습니다. 원문 URL은 없으면 null입니다. `matched_conditions`와 `missing_conditions`로 확인·미확인 조건을 구분하세요.

`proposed_tests`는 최대 3개이며 카드의 실제 `evidence_id`를 참조해야 합니다. 같은 종류의 시험은 서버가 첫 제안을 사용합니다. 현재는 모든 비모의 카드의 적용 조건이 확인되어야 다음 단계로 갑니다. 필수·참고 근거의 정책 구분은 후속 과제입니다.

## 1번: 판정 의미

| reason_code | verdict | 의미 |
|---|---|---|
| `INVALID_STATE` | hold | 상태 품질·유효 시간 문제 |
| `POLICY_VIOLATION` | blocked | 데모 정책 위반 |
| `LIMIT_EXCEEDED` | blocked | 채택한 계산에서 한계 초과 |
| `EVIDENCE_INCOMPLETE` | hold | 필수 근거·적용 조건 미완료 |
| `SIMULATION_INCOMPLETE` | hold | 범위 밖·계산 실패 |
| `MODULE_FAILURE` | hold | 모듈 예외·잘못된 형식·필수 결과 누락 |
| `LIVE_POLICY_NOT_CONFIGURED` | hold | 비모의 모듈을 연결했지만 승인 정책 미설정 |
| `DEMO_PASS` | awaiting_approval | 모의 모듈끼리의 가상 설비 승인 가능 |
| `EVALUATION_CONTEXT_CHANGED` | hold | 검토 도중 상태·버전·snapshot 유효 시간 변경 |
| `EVALUATION_TIMEOUT` | hold | 제한 시간 초과 |
| `EVALUATION_CANCELLED` | hold | 사용자 취소 또는 정상 서버 종료 |
| `WORKER_FAILURE` | hold | 평가 프로세스 시작·실행·출력 오류 |

**실제 모듈을 연결했다고 자동으로 승인 가능해지지는 않습니다.** 현 단계에는 검증된 실제 모델·필수 근거 정책이 없으므로 비모의 결과는 위험 시 차단, 그 외에는 보류합니다. 실제 연동 승인 정책은 1·2·3번이 모델 범위·안전 기준·필수 근거를 합의한 뒤 구현합니다.

## 4번: API 순서

1. `POST /requests` — `examples/request.json` 입력, 201과 `RequestRecord` 반환.
2. `POST /requests/{id}/evaluate` — **202**와 `evaluating` 상태 반환. `GET /requests/{id}`로 완료를 조회합니다.
3. `GET /requests/{id}` — 현재 상태·evaluation 작업 정보 조회. `POST /requests/{id}/evaluation/cancel`로 취소합니다.
4. `POST /requests/{id}/decisions` — `{ "report_digest": "보고서 digest", "decision": "approve 또는 reject", "reason": "판단 이유" }`.
5. `POST /requests/{id}/execute` — `{ "report_digest": "보고서 digest" }`.

저장된 요청 목록은 `GET /requests`, 이전 보고서·승인 이력은 `GET /requests/{id}/history`에서 조회합니다. 목록은 현재 데모용 전체 반환이며 페이지네이션은 후속입니다. 비정상 종료 후 재시작으로 검토가 중단되면 `hold`와 report=null, evaluation은 `interrupted`로 복구됩니다. 정상 종료는 진행 중 평가를 취소하고 보류 보고서를 저장합니다. 실행이 중단되면 `execution_unknown`으로 복구됩니다. 비정상 종료의 이유는 events의 `evaluation_interrupted` 또는 `execution_interrupted`에 기록됩니다.

모든 요청/상태 API는 `X-Iron-Man-Token` 역할 토큰 또는 기존 `Authorization: Bearer ...`가 필요합니다. 공개 HTTPS 배포에서는 사이트 Basic 인증도 별도로 필요하므로 브라우저/API 클라이언트는 역할 토큰을 `X-Iron-Man-Token`으로 전달합니다. 승인·거절과 `/demo/*`는 승인자 토큰이 필요합니다. 평가 취소는 인증된 사용자에게 허용됩니다. 인증 실패 401, 역할 부족 403, 없는 요청 404, 상태·승인 충돌 409, 요청 스키마 위반 422, 평가 용량 초과 429, DB·작업 시작 오류 503입니다. 평가 접수의 HTTP 202는 완료를 뜻하지 않습니다. 모듈 문제는 이후 HTTP 200 조회 응답의 보고서에서 `hold`로 표시하므로 HTTP 성공을 승인 가능으로 해석하지 마세요.

### 가상 설비 API

| API | 입력 | 동작 |
|---|---|---|
| `GET /state` | 없음 | 저장 상태 조회; 시간·관측 시각 유지 |
| `POST /demo/advance` | `{"seconds_s":10}` (1~3600 정수) | 수동 가상 시간 진행; `Snapshot` 반환 |
| `POST /demo/sample` | 없음 | 물리 상태를 유지하고 합성 관측 시각 갱신 |
| `POST /demo/state` | `{"load_ratio":1.2,"sensor_quality":"valid"}` | 부하·센서 품질 변경 |
| `POST /demo/reset` | 없음 | 초기 합성 상태로 복구; 이력 보존 |

시간 진행 도중 모델 범위를 벗어나면 HTTP 200으로 마지막 유효 상태와 `domain_status=out_of_domain`, 사유를 반환합니다. 요청한 시간 전체를 진행했다는 뜻이 아니며 실제 진행 시간은 `simulation_time_s`로 확인합니다. 지원 불가 상태에서 다시 진행하면 409이며 명시적인 초기화가 필요합니다. 관측 갱신·부하 변경만으로 지원 불가를 해제하지 않습니다. 시간 진행·부하 변경·초기화는 기존 승인과 상태가 달라지므로 실행 시 재검증을 요구합니다. 관측 시각만 갱신한 경우 상태 digest는 유지되지만 승인 만료 검사는 계속 적용됩니다.

승인 버튼은 `status == awaiting_approval`이고 `report.can_approve == true`일 때 활성화합니다. 실행 버튼은 `status == approved`일 때 활성화합니다. `report.verdict`는 검토 당시 판정, `status`는 이후 승인·실행까지 포함하는 현재 상태입니다.

에러 본문은 FastAPI 기본 `detail`이며 문자열 또는 검증 오류 배열입니다. 프런트에서 둘 다 처리합니다.

## 계약 갱신·검증

```bash
# 저장소 루트
.venv/bin/python -m scripts.export_contracts
.venv/bin/pytest -q

cd frontend
npm run generate:api
npm run build
```

JSON Schema/OpenAPI와 TypeScript 생성 파일을 직접 수정하지 마세요. 원본 Python 타입을 바꾸고 다시 생성합니다. 테스트는 서버와 저장된 OpenAPI의 일치를 확인하고, CI는 생성된 TypeScript 차이를 확인합니다.


평가 작업의 필드·취소·시간 초과·재시작 동작은 [평가 안내](../docs/EVALUATION.md)에 있습니다. `evaluation`은 기존 기록에서 null일 수 있습니다. `examples/request-evaluating.json`, `examples/request-timed-out.json`으로 진행·실패 화면을 개발할 수 있습니다.

## 가상 승인 정책

보고서의 `execution_scope`는 `virtual` 또는 `unconfigured`입니다. 과거 보고서의 누락 필드는 unconfigured로 해석합니다. `virtual-cooling-policy-v2`를 통과한 요청만 승인 대기로 전환되며 승인·적용 시 현재 상태와 원래 보고서 유효 시간을 다시 검사합니다. `DEMO_POLICY_OUT_OF_SCOPE`는 지정 모델·어댑터·합성 상태·300초 예측 범위 이외의 요청을 보류한 상태입니다. [정책 조건](../docs/VIRTUAL_POLICY.md)을 참고하세요.
