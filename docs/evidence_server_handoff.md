# 3번 → 1번 서버 연동 인계

2번과 1번이 전달한 기준에 맞춘 인계 자료입니다. `EvidenceReview` v1.0 공개 계약과 서버 승인 정책은 변경하지 않았습니다.

## 예시 JSON

| 파일 | 상태 | 의미 |
|---|---|---|
| [normal.json](../contracts/examples/evidence-handoff/normal.json) | completed | 팀 문서의 원문 인용·적용 조건이 맞는 정상 검증 경로. degraded_cooling 제안과 근거 ID 연결 |
| [insufficient.json](../contracts/examples/evidence-handoff/insufficient.json) | insufficient | 실제 외부 논문 인용이 있으나 유체·설비·운전 범위 동일성을 확인하지 못함 |
| [failed.json](../contracts/examples/evidence-handoff/failed.json) | failed | LLM 시간 초과를 주입한 실패 경로. 카드·시험 없이 실패 단계만 반환 |
| [unsupported-test.json](../contracts/examples/evidence-handoff/unsupported-test.json) | insufficient | elevated_coolant_temperature는 검증하지 못한 시험으로 표시하고 실행 후보에서 제외 |

모두 **자동 시험 예시이며 실제 LLM 호출 결과가 아닙니다**. 각 limitation과 [manifest.json](../contracts/examples/evidence-handoff/manifest.json)에 표시했습니다. 정상 예시는 팀 문서를 사용합니다. 외부 논문이 현재 설비에 적용된다고 임의로 주장하는 성공 예시는 만들지 않았습니다. 고정 snapshot도 승인·실행용 입력이 아닙니다.

반환 항목은 `cards[].source_id`, `evidence_id`, `title`, `source_url`, `excerpt`, `locator`, `version`, `publisher`, `published_at`, `usage`, `applicability`, `matched_conditions`, `missing_conditions`, `proposed_test`, `parameter_origin`입니다. 논문의 DOI는 기존 계약을 유지하여 `version`에 포함하고 원문 링크는 `source_url`에 반환합니다. 원문은 확보했어도 적용 조건이 partial/mismatch/unknown이거나 확인된 조건이 비어 있으면 insufficient입니다. 원문 확보 실패·검토 오류는 failed 또는 insufficient로 반환하며 조용히 팀 문서로 대체하지 않습니다.

## 서버 연결 지점과 권한

- [service.py](../backend/evidence/service.py): `review_evidence(request, snapshot)` 호출, 원문 인용 검증, 카드/시험 반환. 임의 효율값이나 실행 코드는 계약에 넣지 않습니다.
- [validation.py](../backend/evidence/validation.py): 서버가 신뢰하는 원문 목록으로 `verify_review_sources(review, trusted_sources)`를 호출할 수 있습니다. 출처 ID, 메타데이터, 원문 인용 포함 여부, 시험과 근거 ID 연결을 재확인합니다. 오류 코드 목록이 비어 있는지는 **기계적 검증 결과**이며 승인 결과가 아닙니다.
- [context.py](../backend/evidence/context.py): 변화한 현재 온도(°C), 실제·기존 목표·요청 목표 속도(%), 부하(무차원), 경과·예측 시간(s), 지원 시험 가정을 LLM에 전달합니다.
- [papers.py](../backend/evidence/papers.py): Europe PMC 검색 및 공개 원문 수집. 세 논문에 고정된 구조가 아니며 검색어를 설정할 수 있습니다. 한 평가에서 수집량은 제한합니다. 모든 논문의 원문 확보나 적용 가능성을 보장하지 않습니다.

서버의 trusted_sources는 에이전트 응답에서 그대로 받은 문서가 아니라 서버가 검증한 원문이어야 합니다. 로컬 수집본은 `source_bundle_digest`로 버전을 고정할 수 있습니다. 실시간 검색은 서버가 해당 수집본을 독립적으로 등록·검증하거나 고정된 제공자에서 원문을 재확인하는 연결 작업이 필요합니다. 에이전트가 반환한 임의 URL을 그대로 요청하는 방식은 사용하지 않습니다.

서버는 출처 허용 여부와 적용 조건을 확인하고 시험을 채택합니다. `completed`도 승인 허가는 아닙니다. insufficient/failed는 보류하고, 지원하지 않는 시험은 검증하지 못한 것으로 유지합니다. 정상·냉각 저하 필수 시험, 온도 한계, 최종 담당자 승인, 실행 직전 재검사는 1번이 계속 관리합니다. **현재 팀 문서만 허용하는 정책은 그대로이며 외부 출처 연결은 1번의 후속 작업입니다.**

최신 main의 `virtual-cooling-policy-v3`와 `cooling-assessment-v4`도 함께 반영했습니다. 서버는 기존 요청 예측 구간 외에 장기 예측·평형·계수 민감도 위험을 검사합니다. 위 정상 JSON은 근거 모듈이 completed를 반환하는 예시이며 이 물리 평가나 서버 승인이 통과했다는 의미가 아닙니다.

## 2번과 맞춘 시험 의미

지원 계약은 normal과 degraded_cooling뿐입니다. degraded_cooling은 유효 열전달량에 곱하는 무차원 efficiency를 정상 1.0에서 0.65로 낮추는 포괄적 냉각 저하 반례입니다. 펌프 응답·부하·냉각수 온도는 그대로입니다. 유량 부족·열교환기 오염 등의 영향을 단순화해 질문할 수 있으나 특정 고장을 식별하거나 재현하지 않습니다.

0.65는 실측·고장 이력으로 검증되지 않은 데모 가정이며 시험 통과는 실제 고장 안전성 입증이 아닙니다. 새로운 고장 이름은 검증하지 못함과 2번 계약 합의 필요를 표시하고 제안 시험에서 제외합니다. 추가 필드로 임의 효율값을 넣으면 출력 계약 검증이 실패합니다. elevated_coolant_temperature/coolant_temperature_c(°C)의 실제 구현·허용 범위는 설비 사양과 계측 자료에 근거한 별도 계약 합의 이후입니다.

## 배포 설정과 재현

1번이 배포 환경에 `OPENAI_API_KEY`, `IRON_MAN_EVIDENCE_MODEL`을 설정합니다. 키는 코드나 Git에 넣지 않습니다. 실제 검토는 `IRON_MAN_EVIDENCE_MODE=live`가 필요합니다. 수집본 검토는 `IRON_MAN_EVIDENCE_SOURCE_MODE=local`, `IRON_MAN_EVIDENCE_SOURCE_PATH=/app/data/sources/paper-sources.json`; 평가마다 검색하려면 SOURCE_MODE=europepmc 및 선택 사항 `IRON_MAN_EVIDENCE_QUERY`를 설정합니다. 기본 fixture는 모의 경로입니다.

```powershell
.venv/Scripts/python.exe -m scripts.export_evidence_handoff
.venv/Scripts/python.exe -m pytest -q
git log -1 --format="%h %s"
```

전용 검증은 [test_evidence_handoff.py](../tests/test_evidence_handoff.py)입니다. 네 예시의 공개 계약·재생성 일치, 출처/인용 변조, 미지원 시험 제외, 빈 적용 조건 보류, 실패 단계와 오류 정보 비노출, 2번의 효율 가정과 변경하지 않는 입력을 확인합니다. 이번 변경 이후 전체 pytest는 235 passed였고, 친구들의 최신 main을 통합한 뒤 **258 passed**를 확인했습니다. 전용 근거 관련 묶음은 **82 passed**입니다. 최신 프런트 TypeScript·Vite 빌드도 통과했습니다. 기존 Starlette TestClient deprecation 경고 1건이 있으며 실패는 없습니다. 커밋은 인계 메시지로 공유합니다. 실제 LLM 품질·배포 환경 검증은 API 설정 이후에 남아 있습니다.
