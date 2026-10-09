# 로컬 .env와 실제 논문 검토

저장소 루트에서 `.env.example`을 `.env`로 복사하고 빈 두 값을 채웁니다.
기존 `.env`가 있다면 덮어쓰지 말고 필요한 항목만 편집합니다.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

필수 값:

```dotenv
OPENAI_API_KEY=본인의_API_키
IRON_MAN_EVIDENCE_MODEL=본인_계정에서_사용_가능한_모델_ID
```

템플릿은 `MODE=live`, `SOURCE_MODE=local`, 수집 파일
`data/sources/paper-sources.json`으로 준비했습니다. 현재 세 논문이 들어 있습니다.
실시간 검색은 `IRON_MAN_EVIDENCE_SOURCE_MODE=europepmc`로 바꿉니다.
API 없이 모의 검토를 실행하려면 `IRON_MAN_EVIDENCE_MODE=fixture`로 설정합니다.

기존 백엔드 터미널에서 Ctrl+C로 서버를 종료하고, 저장소 루트에서:

```powershell
..\.venv\Scripts\python.exe scripts/start_api.py
```

이 워크스페이스의 Python 환경은 저장소 한 단계 위에 준비돼 있습니다.
별도 `.venv`를 사용한다면 해당 Python으로 같은 스크립트를 실행하세요.

기존 `python -m uvicorn backend.main:app ...`은 `.env`를 읽지 않습니다.
`start_api.py`는 추가 패키지 없이 루트 `.env`를 읽은 뒤 localhost:8000으로
서버 하나를 실행합니다. 같은 DB를 쓰는 이전 서버가 켜져 있으면 먼저 종료해야 합니다.

지원 문법은 한 줄 `KEY=value`, 단일/이중 인용 값, 별도 `#` 주석 줄입니다.
인라인 주석·여러 줄·변수 치환·명령 실행은 지원하지 않습니다. 키나 값에 `export`
문법을 넣지 않습니다. 파일에는 OPENAI_API_KEY와 IRON_MAN_* 설정만 반영하며
셸에 이미 있는 환경변수가 우선합니다. 시작 메시지는 선택된 모드만 표시합니다.

화면에는 저장된 과거 모의 보고서가 그대로 남습니다. 실제 논문을 검토하려면
서버 재시작 후 데모에서 초기 상태를 준비하고 **새 요청을 평가**해야 합니다.
실제 문헌 검토는 보류일 수도 있습니다. 기존 정책은 팀 작성 문서만 승인 근거로
등록해두었으며 외부 문헌의 허용 출처·범위 채택은 1번 담당의 연결 작업입니다.

최신 정책은 초기 부하 1.0의 80%도 장기 위험으로 차단합니다. 가상 승인 흐름은
부하 0.6 조건으로 준비한 뒤 검토하되, 실제 논문 적용 조건 부족은 별도로 보류합니다.
`.env`는 Git에서 제외돼 있고, `.env.example`에는 비밀값을 넣지 않습니다.
