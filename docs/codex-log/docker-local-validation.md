# 로컬 Docker 전체 실행 검증

2026-10-09, Windows / Docker Desktop Linux engine. 시작 시점 커밋 288e3de.

## 원격 변경과 실행

`git fetch origin` 결과 main에 추가 커밋이 없었으며 로컬/원격 차이는 0/0이었다. 실행 전 컨테이너가 없었고 새 로컬 Compose 스택을 시작했다. 실제 AWS 서버나 공인 HTTPS 주소는 생성하지 않았다.

```powershell
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m scripts.compose_smoke http://127.0.0.1:8080
```

- API와 웹 Docker 이미지 빌드 통과. 이미지 내부 TypeScript 검사와 Vite production build 통과.
- 전체 Python 테스트 **258 passed**, 기존 Starlette TestClient deprecation 경고 1건.
- 실제 HTTP 프록시·웹 페이지·미인증 401·비동기 평가 확인.
- 부하 1의 60% 요청 차단, 부하 0.6의 80% 요청 승인 대기, 담당자 승인 후 가상 실행 확인.
- API 컨테이너 교체와 전체 스택 down/up 후 SQLite 요청·보고서·가상 상태 보존 확인. 볼륨 삭제는 하지 않았다.
- 완료한 실행 재요청의 중복 적용 방지와 이력 조회 확인.
- Playwright 1.63.0과 Chromium을 검증 환경에 설치해 기존 browser_smoke.run을 로컬 HTTP 주소로 실행했다. 기본 로컬 역할 토큰을 사용했으며 공개 배포의 Basic 인증/TLS는 이번 검사 대상이 아니다.
- 브라우저에서 요청·결과 자동 조회·차단 표시·담당자 승인·가상 적용·가상 시간 진행·상태 변경 뒤 이전 승인 실행 409·저장 목록 확인 통과.

## 발견한 문제와 수정

첫 브라우저 검사는 역할 재연결 작업이 끝나기 전에 확인 체크박스를 체크했다. 연결 작업의 보고서 갱신이 체크를 초기화하여 승인 버튼이 비활성 상태로 남았고 검사에서 timeout이 발생했다.

`scripts/browser_smoke.py`에서 승인 역할 연결 후 연결 버튼이 다시 활성화될 때까지 기다리도록 수정했다. 이후 전체 브라우저 흐름이 통과했다. 승인 조건이나 서버 정책은 완화하지 않았다. 이 수정 이후 영향받은 실제 브라우저 검사를 다시 실행했으며 전체 258개 테스트는 수정 전 애플리케이션 코드와 동일한 상태에서 통과했다.

## 실행 상태와 남은 검증

로컬 접속 주소는 http://127.0.0.1:8080 이며 API와 웹을 실행 상태로 유지한다. 검증용 요청·이력은 로컬 Docker SQLite 볼륨에 남긴다. 검사가 끝난 뒤 가상 설비 상태만 초기화했다.

컨테이너 환경을 비밀값 출력 없이 확인했으며 evidence_mode=fixture, api_key_configured=False, model_configured=False였다. 실제 LLM 호출·외부 근거 승인 정책 연결·AWS 서버 생성·공인 HTTPS·외부 네트워크 접근·SMTP 발송·TEP 실행·현장 실측 안전성은 이번 통과 결과에 포함되지 않는다.
