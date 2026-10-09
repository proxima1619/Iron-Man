# 3번 — v3 현재 상태 및 실제 논문 연결 인계

## 구현과 현재 동작

동일 함수 `review_evidence(request, snapshot)`와 EvidenceReview v1.0 형식을 유지한다.
최신 main의 SQLite, 가상 상태 v3, 비동기 평가 프로세스, 인증·배포 변경을 통합했다.
평가 API는 202를 반환하므로 GET /requests/{id}로 완료를 확인한다.

`backend/evidence/context.py`에서 아래 네 값을 분리한다.

| 검토 입력 | 필드 | 단위 |
|---|---|---|
| 변화한 현재 온도 | snapshot.temperature_c | °C |
| 실제 펌프 속도 | snapshot.pump_speed_pct | % |
| 기존 목표 속도 | snapshot.target_pump_speed_pct | % |
| 이번 요청 목표 속도 | request.command.target_pct | % |
| 실제와 기존 목표 차이 | speed_gap_percentage_points | 퍼센트포인트 |
| 부하 | snapshot.load_ratio | 무차원 비율 |
| 가상 경과 시간 | snapshot.simulation_time_s | 초 |
| 예측 구간 | command.duration_s | 초 |

LLM에 이 값과 단위를 명시적으로 전달하고, 문서의 유체·설비·운전 범위·온도와 비교하도록 한다.
원문의 rpm·유량을 %로 임의 환산하지 않는다. 기존 목표 유지가 기준 시험이며 actual 속도는 초기 상태다.
기존 목표가 없는 과거 snapshot은 실제 속도로 대체하되 legacy_actual_speed_fallback을 기록한다.
2번의 domain_reasons를 공유해 지원 범위 밖이면 LLM 호출 전에 insufficient로 반환한다.
각 검토 limitation에 온도·속도·시각·모델 버전을 기록한다. 센서 최신성·검토 중 상태 변화 판정은 1번이 유지한다.

## 반례와 2번 계약

허용된 반례 출력은 아래 형식 하나다.

```json
{"kind": "degraded_cooling", "evidence_id": "evidence-<출처·버전·주장·인용의 해시>"}
```

근거 ID는 카드 순서가 바뀌어도 유지된다. 카드에 원문 위치·인용·출처를 연결한다.
효율은 2번의 `simulator.DEGRADED_EFFICIENCY`에서 읽으며 현재 0.65(무차원)다.
문헌에서 가져온 값이 아닌 demo_assumption이며 3번은 값을 수정하거나 시나리오에 임의 파라미터를 추가하지 않는다.
새 고장·새 효율값은 출력 검증에서 거부한다. 필요하면 LLM이 missing_conditions에
"2번 계약 합의 필요"를 기록하도록 지시한다. 해당 요청은 근거 부족으로 보류한다.
현재 필요한 시험은 기존 degraded_cooling으로 표현할 수 있어 새 고장 종류나 공통 계약 변경은 하지 않았다.
다른 팀원에게 메시지를 보내 합의를 얻은 상태를 주장하지 않는다.

## 실제 외부 논문

`papers.py`는 Europe PMC API에서 검색하고 공개 JATS XML 원문을 가져온다.
지정 PMCID·원문 PMCID 일치, 라이선스, 크기와 문단을 검사한다.
CC BY / CC BY-SA / CC0를 확인한 문서만 사용하고, 그림·표·참고문헌은 수집 대상에서 제외한다.
전체 XML에서 최대 6개 완전한 문단(초록 및 관련 본문)을 선택한다.
출처에 저자·저널·DOI·날짜·XML 해시·원문 URL·문단 위치·사용 조건을 기록한다.
수집 문단은 실제 원문이며 LLM이 작성한 요약이 아니다. 공백만 정규화했다.

실제로 내려받아 `data/sources/paper-sources.json`에 저장한 논문:

- [Energy saving analysis for pump-motor set in water purification plant using variable speed drive](https://pmc.ncbi.nlm.nih.gov/articles/PMC11557826/)
- [Estimation and sensitivity analysis of fouling resistance in phosphoric acid/steam heat exchanger using artificial neural networks and regression methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC10587106/)
- [Chemical Cleaning of Magnetite Deposits on the Flow Mini-Channels of a Printed Circuit Heat Exchanger in an EDTA-Based Solution](https://pmc.ncbi.nlm.nih.gov/articles/PMC8874691/)

이들은 우리 가상 탱크의 온도·펌프 %·계수를 검증한 자료가 아니다. 논문과 모델 조건이 다르면
partial/mismatch/unknown을 표시하고 보류한다. 효율 저하 일반 현상에서 시험 질문을 도출할 수 있지만
논문이 이번 요청의 안전성을 증명한다고 표시하지 않는다. 실제 적용 판단 품질은 LLM 라이브 평가가 필요하다.

## 실행 선택

통합 중 1번의 virtual-cooling-policy-v2 패치가 추가되었다. 현재 가상 승인 정책은
등록된 팀 작성 규정·fixture만 허용한다. 외부 논문 검토 카드는 보고서에 보존되지만
등록되지 않은 출처이므로 EVIDENCE_INCOMPLETE로 보류하며 추가 계산·승인 대상으로 이어지지 않는다.
외부 논문을 실행 정책에 채택하는 결정은 1번과 적용 조건·범위를 합의해야 한다.
3번이 승인 정책을 바꾸거나 이 보류를 우회하지 않았다. 기존 팀 문서 반례는 추가 시험으로 연결된다.

1. 기존 데모: `IRON_MAN_EVIDENCE_MODE=fixture` (기본). 실제 논문·LLM 호출 없음.
2. 수집된 실제 논문 검토: MODE=live, SOURCE_MODE=local, SOURCE_PATH=논문 JSON 경로.
3. 평가할 때 실제 검색·수집: MODE=live, SOURCE_MODE=europepmc. 검색 실패·라이선스 확인 실패는 failed로 보류.

PowerShell에서 수집된 논문으로 검토하려면:

```powershell
$env:IRON_MAN_EVIDENCE_MODE = 'live'
$env:IRON_MAN_EVIDENCE_SOURCE_MODE = 'local'
$env:IRON_MAN_EVIDENCE_SOURCE_PATH = (Resolve-Path data/sources/paper-sources.json).Path
$env:OPENAI_API_KEY = '본인의 API 키'
$env:IRON_MAN_EVIDENCE_MODEL = '사용 가능한 Structured Outputs 지원 모델 ID'
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

매 평가에서 검색하려면 SOURCE_MODE=europepmc로 바꾼다. 선택 환경변수 IRON_MAN_EVIDENCE_QUERY로
검색어를 설정할 수 있다. 한 번에 최대 3개 논문, 각 요청 timeout 10초이며 전체 평가는 1번 프로세스의
90초 기본 deadline으로 통제된다. 검색과 원문 수집 실패 시 기존 문서로 조용히 대체하지 않는다.
캐시 재생은 구현하지 않았다. local 모드는 버전이 고정된 사전 수집 원문 데이터셋이다.

검색만 확인하거나 원문을 다시 수집하는 명령:

```powershell
.venv/Scripts/python.exe -m scripts.collect_papers --search-only --query 'heat AND exchanger AND fouling' --limit 3
.venv/Scripts/python.exe -m scripts.collect_papers --pmcid PMC11557826 --pmcid PMC10587106 --pmcid PMC8874691
```

Docker에서는 SOURCE_PATH=/app/data/sources/paper-sources.json을 사용한다.
원문 데이터는 이미지에 포함되며 Compose는 MODE/SOURCE_MODE/SOURCE_PATH/QUERY/키/모델을 전달한다.

## 출력 예시·검증 범위

`fixtures/evidence-v3-example.json`은 격리된 가상 설비에서 목표 60% 적용 후 30초 진행한 snapshot으로
요청 목표 80%를 검토한 함수의 실제 fixture 출력이다. example_only=true, llm_executed=false다.
원문 논문으로 실제 LLM 호출을 수행한 결과처럼 제시하지 않는다.

`scripts.export_evidence_example`로 다시 만들 수 있다. 서버 DB나 승인 상태를 변경하지 않는다.
자동 시험은 가상 시간 진행 후 온도·실제 속도·기존 목표·요청 목표 전달, 과거 snapshot 호환,
지원 시험·근거 ID, 논문 조건 불일치, 실제 API 비동기 응답과 SQLite 복원을 확인한다.
외부 검색과 논문 3개 XML 다운로드는 실제 수행했다. 실제 LLM 호출은 API 키·모델 설정이 없어 미실행이다.
전체 pytest 192개, 프런트 TypeScript·Vite 빌드, Compose 설정 검사와 diff 공백 검사를 통과했다.
Docker 엔진이 꺼져 있어 컨테이너 실동작은 미검증이며 설정 구문만 검사했다.

API 참고: [Europe PMC RESTful API](https://europepmc.org/RestfulWebService).
