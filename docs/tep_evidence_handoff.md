# 3번 TEP 근거·역근거 연동

## 구현 범위와 책임

TEP 계산 후 `report.tep_evidence`에 `tep-evidence-1.0` 검토를 저장한다. 기존 냉각 `report.evidence`, `simulation`, `assessment`는 TEP에서 계속 null이다. 기존 펌프 근거·degraded_cooling·0.65·80°C 규칙을 재사용하지 않는다. TEP 전용 위험/승인/재검증 정책은 여전히 1번 미확정 사항이며 계산·근거 검토 성공도 **hold / can_approve=false / execution_scope=unconfigured**로 유지한다.

## 입력과 검토

[tep.py](../backend/evidence/tep.py)는 2번의 [변수·시험 사전](../contracts/tep-model.json)을 선택된 모델 버전·원본 해시·런타임 변수 의미/단위와 대조한다. XMV10 반응기/XMV11 응축기 냉각수 설정은 percent_full_scale이며 기존 펌프 속도와 다르다. 입력에는 기존/요청 값과 변경량, 원래 초기화 프로필, 초기 상태 해시·12개 입력, 개루프 제어, 시드·외란 없음, 적분·관측 주기·예측 구간, 실제 계산의 초기/종료 관측·41개 변수별 비교가 포함된다. 초기화 프로필은 센서 상태 복원이 아니다.

정상 운전 범위와 안전 허용 범위는 현재 null이다. 입력 지원 범위나 코어 내부 정지 조건을 안전 기준으로 승격하지 않는다. 결과는 시뮬레이션 데이터이며 현장 실측 없음·현장 검증 미수행을 계속 표시한다. 공개 정상 운전 데이터셋은 이번 연결의 필수 의존성이 아니다.

LLM은 냉각 에이전트와 다른 TEP 전용 지시·출력 스키마를 사용한다. `source_id`, 원문 인용, 변수 ID, 근거 용도, 적용 조건, 제안 시험을 검증한다. 모르는 출처·인용·변수, 임의 효율값/코드 필드, 문헌을 안전 기준으로 등록하려는 출력은 검증에서 거절한다. 문헌 적용성의 의미 판단은 LLM/담당자 검토이며 원문 문자열 일치가 과학적 적용성이나 안전성을 입증하지 않는다.

## 출처 용도와 반환 계약

| source_type / evidence_purpose | 현재 처리 |
|---|---|
| model_source / model_definition | 2번의 검증된 변수·지원 시험 사전과 실행 래퍼. 실제 수집한 논문으로 표시하지 않음 |
| paper / physical_mechanism | 공개 원문 논문. 일반 물리 현상·반례 검토이며 TEP 변수 정의/안전 기준으로 자동 채택하지 않음 |
| simulation_record / simulation_observation | 반환 계약에 구분 마련. 현장 실측이 아니며 이번 원문 수집 목록에는 자동 추가하지 않음 |
| safety_basis | 현재 등록된 출처 없음. 1번이 기준을 채택하기 전 출력 주장으로 안전 범위를 변경할 수 없음 |

카드는 출처 ID·제목·URL·DOI가 포함된 version·원문 excerpt·locator·출처 버전, stance, evidence_purpose, variable_ids, applicability, matched_conditions, missing_conditions, evidence_id를 반환한다. 모델 정의 출처는 검증된 팀 사전/래퍼이므로 URL이 null일 수 있고 로컬 원문 위치·해시를 반환한다. upstream 소스 버전은 source_commit으로 추적한다.

## 반례와 시험 매핑

현재 레지스트리의 `base_case_cooling_step_v1`만 제안할 수 있다. 변수는 현재 요청의 XMV10/XMV11이어야 하며 configuration은 서버가 접수·계산한 값의 복사본이다. 에이전트가 값·시간·시드·외란을 새로 생성하지 않는다. `evidence_id → test_id + variable + initial_profile + configuration`으로 연결하며 자동 실행은 하지 않는다. 현재 이미 계산한 기준/변경 시험과의 연결이다. **고장/교란 레지스트리가 비어 있어 고장 추가 시뮬레이션은 미구현**이며 대응 시험 정의는 2번과 다음 합의가 필요하다.

degraded_cooling·미등록 고장·다른 변수의 시험 제안은 `unsupported_tests`에 TEST_UNSUPPORTED와 검증하지 못함/2번 합의 필요를 기록하고 후보에서 제외한다. 근거/조건이 부족하면 insufficient, 원문·LLM·출력 검증 실패는 failed와 단계만 반환한다. 실제 모델 계산 실패는 SIMULATION_INCOMPLETE를 표시하고 LLM을 호출하지 않는다. 근거 실패가 성공한 모델 계산을 승인으로 바꾸거나 덮어쓰지 않는다.

서버가 신뢰하는 원문 목록과 캡처 조건으로 `verify_review_sources(review, trusted_sources, context)`를 호출할 수 있다. 원문 목록 해시·메타데이터·인용·용도·변수·설정 일치를 확인하며 출처 등록·시험 채택·승인은 별개다. 이 함수는 네트워크나 코드를 실행하지 않는다.

## 설정·화면·후속 작업

- `IRON_MAN_EVIDENCE_MODE=fixture` 기본: TEP demo_fixture와 실제 LLM 미호출 표시. 냉각 fixture 카드/시험 반환 안 함.
- 실제 검토: MODE=live, OPENAI_API_KEY, IRON_MAN_EVIDENCE_MODEL 필요. 키는 배포 환경에서 설정하며 Git에 저장하지 않음.
- TEP 로컬 문헌은 `IRON_MAN_TEP_EVIDENCE_SOURCE_PATH`, 검색어는 `IRON_MAN_TEP_EVIDENCE_QUERY`. 기본 파일은 paper-sources.json이며 저장된 논문의 TEP 직접 적용성은 미확인이다. SOURCE_MODE=europepmc는 검색과 원문 수집을 실제 수행한다. 사전 수집 논문과 모델 정의만 있어도 조건 부족이면 보류한다.
- Docker에는 `/app/contracts/tep-model.json`을 포함하고 IRON_MAN_TEP_CONTRACT_PATH로 읽는다. 기존 배포 compose도 환경을 상속한다. 최신 이미지 재빌드와 새 요청 평가가 필요하며 과거 DB 보고서를 수정하지 않는다.
- [TepEvidencePanel.tsx](../frontend/src/TepEvidencePanel.tsx)가 보고서 검토 상태·카드·근거 용도·지원/미지원 시험·부족 조건을 표시한다. 최신 4번 패치의 TEP 전용 과거 기록 설명도 유지한다. 사후 설명은 별도 기능이며 시험 채택이나 승인 권한이 없다.

1번은 출처 등록·시험 채택과 TEP 정책을 결정해야 하고, 2번은 고장·교란 추가 시험과 측정 가능한 조건을 정의해야 한다. 4번에는 새 tep_evidence 계약과 패널을 전달한다. 이번에 배포 서버 자체나 승인 정책은 변경하지 않았다.

## 예시·검증

[정상](../contracts/examples/tep-evidence/normal.json), [근거 부족](../contracts/examples/tep-evidence/insufficient.json), [미지원 반례](../contracts/examples/tep-evidence/unsupported.json), [실패](../contracts/examples/tep-evidence/failed.json), [manifest](../contracts/examples/tep-evidence/manifest.json). 모두 **자동 계약 검증 예시·실제 LLM 미호출·시뮬레이션 미실행**으로 표시했다. 정상 예시는 모델 정의 자료 매핑 검증이며 외부 논문의 TEP 적용성·안전성 성공 예시가 아니다.

[test_tep_evidence.py](../tests/test_tep_evidence.py)는 단위/조건 분리, 위조 인용/변수/안전 용도/효율값 거절, 미지원 고장 제외, 원문 재검증, 별도 프롬프트, 실패 단계, 계산 실패 시 승인/실행 거절을 검증한다. 실제 LLM 품질은 키·모델이 설정된 환경에서 별도 확인해야 한다.

이번 검증: 전체 pytest 298 passed / 12 skipped(실제 엔진 opt-in), 추가 시험을 포함한 전용 테스트 24 passed. TypeScript·Vite·Docker 빌드 통과. 실제 Docker HTTP에서 TEP XMV10/XMV11 완료·코어 정지·범위 밖·근거 필드·승인/실행 거절·재시작 후 기록 보존 통과. Chromium에서 새 근거 패널과 기존 승인/TEP/데모 기록 흐름 통과. 실제 LLM 호출은 수행하지 않았다.

최종 팀 참조 데이터 기능(460cca0까지)을 통합한 뒤 전체 pytest **318 passed / 13 skipped**, TypeScript·Vite·Docker 재빌드와 Chromium 재검증을 통과했다. 제외 13건은 실제 코어 opt-in 12건과 원본 참조 데이터 opt-in 1건이다. 실제 코어 HTTP/브라우저 실행은 위와 별도로 수행했다. 참조 데이터는 근거 원문·실측 자료로 자동 채택하지 않았다.
