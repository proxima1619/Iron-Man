# 저장 기록 AI 피드백 배포 수정

## 변경

- `/feedback`는 관측 유효 시간을 검사하지 않습니다. 과거 `INVALID_STATE`는 당시 계산이 중단된 기록이며 현재 AI 호출 오류와 별개입니다.
- 관측 갱신 후 현재 화면의 이전 결과와 확인 체크를 닫습니다. 저장된 기록은 수정하지 않습니다. 새 계산은 새 요청으로 시작합니다.
- 과거 보고서에 포함된 이전 근거는 새 LLM 입력에서 제외합니다. 기존 명령, 결과, 당시 판정과 보고서 식별자는 유지합니다.
- TEP 사후 설명은 `IRON_MAN_TEP_EVIDENCE_SOURCE_PATH`, 냉각 탱크 사후 설명은 `IRON_MAN_FEEDBACK_SOURCE_PATH`를 사용합니다. 기본값은 사전 수집 논문 `paper-sources.json`입니다.
- 사후 설명에서는 검증 실패한 인용 카드를 제외하고 근거 부족을 표시합니다. 검증된 카드만 보여주며 시험 제안은 실행하지 않습니다. 명령 평가·승인 정책의 검사는 유지합니다.
- API 인증 실패, 연결 지연, 응답 형식 오류와 검증 제외 건수는 비밀값을 포함하지 않는 로그로 남깁니다.

## 기존 AWS 서버 반영

서버의 기존 저장소 및 `.env.deploy`가 있는 폴더에서 실행합니다. 기존 DB 볼륨과 역할 토큰을 유지합니다.

```bash
git fetch origin codex/fix-deployed-feedback
git checkout --detach origin/codex/fix-deployed-feedback
docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build --wait --wait-timeout 180 api web
docker compose --env-file .env.deploy -f compose.deploy.yaml logs --tail=80 api
```

배포 환경은 로컬 `.env`와 별개입니다. `.env.deploy`에 `OPENAI_API_KEY`, `IRON_MAN_EVIDENCE_MODEL`, `IRON_MAN_EVIDENCE_MODE=live`가 필요합니다. 키나 토큰을 로그·Git·채팅에 올리지 마세요. 모델 응답 대기가 길면 `IRON_MAN_EVIDENCE_TIMEOUT_S=60`으로 설정한 뒤 위 명령으로 API 컨테이너를 다시 생성할 수 있습니다.

브라우저에서 강력 새로고침 후 역할 토큰으로 접속하고, 저장 기록의 **AI 피드백 받기**를 선택합니다. `분석 완료 · 적용 근거 부족`은 실제 API 설명을 받았으나 문헌 적용성이 부족하다는 뜻입니다. TEP의 `TEP_POLICY_NOT_CONFIGURED` 보류는 API 호출 성공과 별개이며 유지됩니다.
