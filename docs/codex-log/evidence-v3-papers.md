# 3번 v3 및 실제 논문 작업 기록

- 요청: 최신 main 패치를 통합하고 변화한 온도·실제/목표 속도의 적용 조건 검토와 반례 연결 구현.
- Git: 로컬 재검증 수정 보존 후 origin/main 8b7e703, 작업 중 추가된 1a59bb3까지 fetch/pull --rebase로 반영.
  충돌에서 양쪽 변경과 최신 가상 승인 정책을 보존했다.
- 결과: review_context, 모델 공유 범위 검사, 안정적 근거 ID, 기존 효율 저하 시험 연결,
  Europe PMC 검색·공개 원문 수집, 실제 논문 3개, 원문 UI 링크, 실행·단위·계약 인계 문서.
- 발견·수정: Compose 자동 병합의 중복 환경변수, 202 비동기 API 테스트,
  Windows 저자명 UTF-8 출력, 기존 목표와 실제 속도 구분.
- 검증: 전체 pytest 219개 통과, TypeScript·Vite 빌드와 Compose 설정 검사 통과.
  실제 외부 논문 검색 및 XML 수집 수행.
- 미검증: API 키·모델 미설정으로 실제 LLM 호출 품질 미평가. Docker 엔진 미실행.
- 범위: 새 고장·효율값은 만들지 않음. 2번 기존 시험 계약과 값을 읽으며 승인 정책 변경 없음.
- 출처: Europe PMC REST API 및 각 논문의 CC BY 4.0 원문. provenance와 v3 인계 문서 참조.
