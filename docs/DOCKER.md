# Docker Compose 실행

## 준비

Docker Engine/Desktop와 Compose v2가 필요합니다. Docker Desktop을 사용하는 경우 엔진이 실행 중이어야 합니다. Python·Node를 호스트에 별도 설치하지 않고 앱을 빌드·실행할 수 있습니다.

저장소 루트에서:

```bash
docker compose up -d --build --wait
```

화면: http://localhost:8080
API 상태: http://localhost:8080/api/health

처음에는 베이스 이미지·의존성을 다운로드합니다. 같은 명령을 팀원 컴퓨터와 Linux 서버에서 사용합니다. macOS ARM 환경에서 만든 이미지를 x86 서버로 직접 복사하지 말고, 그 서버에서 빌드하거나 추후 다중 아키텍처 이미지를 사용하세요.

## 구성

- web: Node 빌드 단계에서 React를 빌드하고 Nginx로 정적 파일 제공.
- api: Python 3.12, FastAPI/Uvicorn 한 worker, 비root 사용자 실행.
- `/api/...`는 Nginx가 API 컨테이너의 `/...`로 전달합니다. 브라우저와 API가 같은 출처이므로 별도 CORS 설정이 필요 없습니다.
- API 포트는 호스트에 공개하지 않습니다. 웹만 기본 127.0.0.1:8080에 바인딩합니다.
- API 컨테이너 재생성 후 IP가 달라져도 프록시는 Docker DNS를 재조회합니다.
- `gateway-data` named volume이 `/data`에 연결되어 SQLite 파일·WAL·잠금 파일을 함께 보관합니다. 기본 프로젝트 이름에서는 `iron-man_gateway-data`입니다.
- 이미지에는 호스트 `.env`, DB, node_modules, .venv가 들어가지 않습니다.
- 프로세스 실패 시 재시작 정책을 사용합니다. healthcheck 실패 자체가 컨테이너 자동 재시작을 의미하지는 않습니다.

## 데이터 유지

```bash
# 중지·컨테이너 제거 (데이터 볼륨은 유지)
docker compose down

# 다시 생성
docker compose up -d --wait

# 코드 업데이트 후 재빌드
docker compose up -d --build --wait
```

**기록을 보존하려면 `docker compose down -v`를 사용하지 마세요.** `-v`는 볼륨도 삭제합니다. 프로젝트 이름을 바꾸면 다른 볼륨을 사용하므로 데이터가 사라진 것처럼 보일 수 있습니다.

호스트의 기존 `data/ironman.sqlite3`와 Compose 볼륨은 별도 저장소입니다. 자동 이관하지 않습니다. 기존 자료 이전은 정상 종료·백업 후 별도 작업으로 수행합니다.

## 설정

선택적으로 `.env.example`을 `.env`로 복사해 값을 수정할 수 있습니다. Compose는 이 파일을 읽지만, 일반 Python 실행은 여전히 자동 로딩하지 않습니다.

- `IRON_MAN_HTTP_PORT`: 기본 8080. 다른 서비스가 사용 중이면 변경.
- `IRON_MAN_BIND_HOST`: 기본 127.0.0.1. 외부 공개는 배포 단계에서 HTTPS·접근 인증과 함께 구성.
- `IRON_MAN_OPERATOR_TOKEN`, `IRON_MAN_APPROVER_TOKEN`: API 데모 토큰. 초기값은 로컬용 공개 값이며 외부 배포 전에 변경.
- Compose 내부 DB 경로는 `/data/ironman.sqlite3`로 고정합니다. 호스트용 `IRON_MAN_DB_PATH`를 바꿔도 Compose 볼륨 위치를 바꾸지 않습니다.

API 키는 이미지·프런트 빌드 인자에 넣지 않습니다. 실제 근거 API의 비밀키 연결은 해당 모듈과 외부 배포 단계에서 추가합니다. HTTPS·실서비스 로그인·외부 도메인은 이번 단계에 포함하지 않습니다.

## 확인·문제 해결

```bash
docker compose ps
docker compose logs --tail=100 api web
# Compose 구조만 검증, 토큰 값은 출력하지 않음
docker compose config --quiet
```

- Docker daemon 연결 오류: Docker Desktop/Engine 실행 확인.
- 포트 충돌: `.env`에서 `IRON_MAN_HTTP_PORT` 변경.
- DB already in use: 같은 볼륨을 사용하는 다른 API 서버가 있는지 확인. API를 여러 worker/replica로 늘리지 않습니다.
- 60% 요청은 위험 차단, 80% 요청은 현재 승인 정책 미설정 보류입니다. Docker로 감쌌다고 승인 정책이 바뀌지는 않습니다.

## 격리된 통합 시험

호스트에 Python 3.11 이상이 있을 때 실행합니다. 기존 개발 데이터를 건드리지 않도록 별도 프로젝트 이름과 포트를 사용하세요.

```bash
export COMPOSE_PROJECT_NAME=iron-man-smoke
export IRON_MAN_HTTP_PORT=18080
docker compose up -d --build --wait
python3 -m scripts.compose_smoke http://127.0.0.1:18080
docker compose down
```

`.env`에서 토큰을 바꿨다면 시험 셸에도 같은 `IRON_MAN_OPERATOR_TOKEN`을 export하세요.

시험은 웹 페이지·인증·프록시·API 컨테이너 교체·전체 스택 재생성 이후 기록 보존을 확인합니다. 실제 시뮬레이터의 60% 위험 사례를 사용하며 승인 정책을 우회하지 않습니다. 시험용 볼륨은 확인을 위해 남깁니다.
