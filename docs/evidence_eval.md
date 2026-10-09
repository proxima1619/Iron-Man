# 3번 근거·역근거 에이전트 인계

`review_evidence(request: NewRequest, snapshot: Snapshot) -> EvidenceReview`를 유지한다.
현재 main에서 작업하며 별도 브랜치는 만들지 않는다. 팀원 최신 main과 통합했다.

## 실행

근거 검토 기본 모드는 `IRON_MAN_EVIDENCE_MODE=fixture`다. 시뮬레이터는 v3 물리 계산과 수동 가상 상태를 사용한다. 자세한 상태·계산 의미는 `backend/simulator/README.md`를 참조한다.
실제 LLM 검토는 백엔드 PowerShell에서 다음 환경변수를 설정하고 서버를 실행한다.
`.env` 파일은 자동으로 읽지 않는다.

```powershell
$env:IRON_MAN_EVIDENCE_MODE = 'live'
$env:OPENAI_API_KEY = '본인의 API 키'
$env:IRON_MAN_EVIDENCE_MODEL = '계정에서 사용 가능한 Structured Outputs 지원 모델 ID'
$env:IRON_MAN_EVIDENCE_TIMEOUT_S = '20'
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

API 호출은 OpenAI Responses API의 JSON Schema Structured Outputs를 사용한다.
공식 참고: https://developers.openai.com/api/docs/guides/structured-outputs
API 키·모델 미설정, 오류·시간 초과, 거부·미완료, 잘못된 출력은 `failed`이며 모의 응답으로 대체하지 않는다.

## 출처와 검증

`data/sources/cooling-demo.json`의 팀 작성 데모 규정 3개를 한 번의 호출로 검토한다.
소규모 고정 문서 전체를 사용하며 실시간 인터넷 검색·외부 문헌 검색·캐시는 구현하지 않았다.
각 문서는 출처 ID, 제목, 발행처, 버전·날짜, 사용 조건, 위치, 원문을 가진다.
제조사 매뉴얼·논문이나 현실 설비의 안전 근거가 아니다. 문서 묶음 해시를 limitation에 기록한다.
실제 LLM 검토이므로 `mock=false`이지만 자료·설비 자체는 데모다.

지지·반례·한계, 적용 가능·부분 일치·불일치·확인 불가, 일치·누락 조건을 구분한다.
출처와 위치는 서버가 붙인다. 존재하지 않는 source ID, 원문에 없는 연속 인용,
허용되지 않은 필드·시험, 적용 조건과 모순되는 시험을 거부한다.
주장의 의미가 원문과 일치하는지까지 결정론적으로 보증하지는 않는다. 담당자 원문 확인이 필요하다.

## 팀 연결

- 1번: 최신 v1.0 공통 계약을 사용한다. status는 demo_fixture/completed/insufficient/failed다.
  카드에 원문 인용·발행 정보·시험 후보 필드를 추가하고 공통 JSON Schema와 UI 타입을 재생성했다.
  팀 작성 데모 규정은 team_authored_demo이며 모의 고정 응답인 team_authored_fixture와 구분한다.
  report.mock은 evidence.mock 또는 simulation.mock이다. 부족·실패·미확인 조건은 보류한다.
  현재 서버는 지정 v3 모델과 팀 문서/fixture를 가상 전용 정책으로 확인하며 통과 시 담당자 승인 대기로 보낸다. 다른 계산·출처·범위는 보류한다.
- 2번: 기존 `Scenario(kind='degraded_cooling', evidence_id=...)` 그대로 전달한다.
  효율 수치나 자유 변수를 생성하지 않는다. 수치는 시뮬레이터가 결정하며 카드에는 demo_assumption으로 표시한다.
- 4번: 기존 title/claim/locator/limitation 필드 유지. 카드의 stance, excerpt, applicability,
  matched_conditions, missing_conditions, source_type을 표시할 수 있다.
  evidence.mock/status가 검토 방식이며 report.mock과 구분한다.

문서 검토자는 실행·승인·정책 변경 도구를 갖지 않는다. 보류 보고서에도 검토 결과를 보존한다.
API timeout은 네트워크 호출 제한이며 전체 요청의 엄격한 벽시계 제한은 아니다.
현재 gateway의 동기 평가·공유 lock 구조는 유지했다. 비동기 조율은 1번 담당이다.

## 평가 범위

`tests/test_evidence.py`: 반례→추가 시험→차단, 출처·인용 조작, 금지 필드·시험,
불일치, 필수 조건 부족, 시간 초과, 악성 문서/승인 출력, Responses 요청 형식을 검사한다.
LLM 응답을 대체한 자동 시험이며 실제 모델의 추출 정확도·프롬프트 공격 저항 평가가 아니다.
API 키를 사용한 라이브 호출과 실제 모델 품질 평가는 아직 수행하지 않았다.

2026-10-09 실행 결과: Python 3.13 가상환경에서 기존 gateway 시험을 포함해
최신 SQLite·물리 시뮬레이터·계약과 통합 후 `pytest -q` 82개 통과.
TestClient 관련 의존성 deprecation warning 1개.
프런트 `npm run build`의 TypeScript 검사와 Vite 빌드 통과. `git diff --check` 통과.

```powershell
.venv/Scripts/python.exe -m pytest -q
```
