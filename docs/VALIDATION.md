# 골격 검증 기록

2026-10-09 로컬 확인.

- Python 3.12.4, Node 24.3.0 환경.
- `.venv/bin/pytest -q`: 17 passed. HTTPX 기반 TestClient 지원 중단 예고 경고 1건.
- `npm run build`: TypeScript 검사와 Vite production build 통과.
- `npm install`: 의존성 감사 결과 0 vulnerabilities (설치 시점 보고).
- 브라우저에서 로컬 React 초기 화면과 모의 구현 표시 확인. 브라우저 클릭 전체 흐름은 미검증; API 흐름은 위 통합 테스트에서 확인.
- 기존 두 Markdown 문서의 원본과 복사본 바이트 일치 확인.

검증하지 않은 것: 실제 AI 검토, 실제 물리 모델, PLC, 외부 배포, 현장 안전성. GitHub Actions 원격 실행 결과는 별도 확인 필요.

## 공통 계약 v1.0 추가 검증

- 백엔드 전체 36 tests passed. 기존 TestClient 지원 중단 예고 경고는 동일.
- 근거 부족·계산 범위 밖·필수 시험 누락·형식 불일치·NaN·출처 ID 오류·비모의 모듈 정책 미설정 처리 확인.
- 공유 JSON 예시의 스키마 적합성과 저장된 OpenAPI의 현재 서버 일치 확인.
- OpenAPI 기반 TypeScript 생성 후 프런트 타입 검사·빌드 통과.
- 실제 모듈과 DB·비동기 작업 구현은 다음 단계.
