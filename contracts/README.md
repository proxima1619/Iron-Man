# 공통 계약

현재 계약의 원본은 `backend/contracts.py`와 FastAPI `/openapi.json`입니다.
서버 실행 후 `/docs`에서 확인하세요. 정적 사본을 별도 수정하지 않습니다.

1번이 계약 변경을 취합하고 2·3·4번과 합의합니다.
- 2번: `simulate(command, snapshot, scenarios)` / `DemoAdapter`
- 3번: `review_evidence(request, snapshot)`
- 4번: `/requests` → `/evaluate` → `/decisions` → `/execute`

이번 골격에는 수정 revision API가 없습니다. 수정은 새로운 요청을 생성하며 이전 승인을 재사용하지 않습니다.
