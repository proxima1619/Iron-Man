# 최신 TEP 패치 로컬 반영 검증

2026-10-09. 원격 main에 ff92afd 이후 3개 커밋이 있어 `git pull --ff-only origin main`으로 819438d까지 반영했다. 이전 Docker 이미지가 실행 중이었으므로 TEP 엔진을 포함한 API·웹 이미지를 다시 빌드했다. SQLite 볼륨을 삭제하지 않았다.

- `docker compose up -d --build --wait --wait-timeout 180`: TEP C++ 엔진 빌드, 패키지 설치, TypeScript·Vite 빌드, API·웹 healthy 확인.
- 로컬 pytest: **278 passed, 12 skipped**, 기존 TestClient 경고 1건. 제외된 12건은 IRON_MAN_TEST_TEP=1 및 실제 엔진 구성이 필요한 통합 시험이며 통과로 계산하지 않았다.
- 실제 Chromium 검사에서 새 모델 선택기의 정확한 접근성 이름이 옵션 텍스트와 섞여 선택기를 찾지 못했다. frontend/src/main.tsx의 select에 `aria-label="모델"`을 추가하고 이미지를 다시 빌드했다.
- 수정 후 scripts.browser_smoke.run의 전체 흐름 통과: 기존 탱크 차단/승인/가상 실행/오래된 승인 거절/저장 목록, TEP 60초 요청의 실제 외부 엔진 completed 결과, TEP 정책 미설정 보류와 승인 비활성화.

TEP 보고서 보류는 시뮬레이션 실패와 다르다. 현재 TEP 전용 안전·승인 정책이 미설정이므로 성공 계산도 승인·실행 가능 상태로 바꾸지 않는다. 기존 냉각 근거나 0.65 가정을 TEP에 적용하지 않았다.

로컬 주소 http://127.0.0.1:8080 에 최신 컨테이너를 실행 상태로 유지했다. 친구가 만든 외부 팀 서버의 접속 실패 원인은 주소·오류 정보를 받지 못해 확인하지 못했다. 로컬 pull/build 결과가 외부 서버의 배포 완료를 의미하지 않는다.

## 검증 중 추가된 main 반영

공유 직전 원격에 15e123e까지 새 홈·데모·논문 설정·TEP 원본 보존 패치가 올라와 재반영했다. 해당 통합 상태에서 Docker 웹 빌드가 실패했다. main.tsx의 Home/DemoPage/EvidencePanel/RecordFeedback import 누락과 DemoExperience/EvidencePanel의 TEP/냉각 타입 혼용을 수정했다. TEP 설정 시각·변수/요청 값은 탱크 관측 시각·펌프 목표와 구분하고 TEP 기록의 근거 패널에 탱크 조건을 표시하지 않는다. TEP 결과의 중복 출력도 제거했다.

새 검토 문구 때문에 저장 예시 재생성 일치 시험이 실패하여 insufficient.json을 현 검증 함수로 재생성했다. 수정 이후 전체 pytest **278 passed, 12 skipped**, 프런트 TypeScript·Vite 빌드 및 Docker 빌드 통과. 브라우저 검사의 냉각수 입력 선택은 목적 텍스트와의 이름 충돌을 피하도록 combobox로 특정하고 데모의 저장 TEP 기록 표시 검사도 추가했다. 실제 LLM 호출과 외부 서버 확인은 이 검사에 포함하지 않는다.

최종 Chromium 검증 통과: 기존 탱크 승인·실행·상태 변경 후 거절, 실제 TEP XMV10/XMV11 600초 계산 완료와 승인 비활성화, 새 데모에서 저장 TEP 기록 조회 및 결과 표시. 데모 토큰 입력은 접힌 연결 설정을 펼친 후 조작하도록 검사 순서도 맞췄다.

동시에 팀도 같은 빌드 문제를 해결한 2584608/4de39be를 올렸다. 최종 통합에서는 이 팀 수정본을 유지하고 로컬 중복 수정을 제거했다. 팀 최종 데모는 냉각 기록만 표시하며 TEP 기록은 검토 화면에서 확인하는 구조다. 위 저장 TEP 데모 조회 통과는 통합 전 로컬 수정본의 결과이며 최종 UI의 지원 기능으로 간주하지 않는다. 최종 변경 커밋에는 이 검증 기록만 추가했다.
