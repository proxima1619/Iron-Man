# TEP 외부 시뮬레이터 연동 v1

3번 후속 연동: 새 `report.tep_evidence` 계약·근거 패널·지원 시험 제안은 [TEP 근거 인계](tep_evidence_handoff.md)를 참고한다. 기존 냉각 evidence는 null로 유지하며 TEP 승인·실행 보류 정책은 변경하지 않았다. 아래 초기 구현/배포 기록을 실제 LLM 검토 완료 근거로 해석하지 않는다.

2026-10-09. **실측 데이터는 없다.** 이 작업은 공개 TEP 모델을 실제로 실행하여 생성한 **시뮬레이션 데이터**를 요청·검토 이력에 연결한다. 실측 오차 평가와 실제 설비 적용성 검증은 미완료다.

## 구현 선택과 출처

| 확인한 구현 | 프로그램 연동 수단 | 반복 실행·출력 | 선택 판단 |
|---|---|---|---|
| [NIST TESIM](https://github.com/rcandell/tesim/tree/81a7ac9dc04f91bc0898c36f8522372e0e437fc1) | `c/teprob.cpp`의 `teinit`, `set_curr_xmv`, `set_curr_idv`, `tefunc`, `get_curr_xmeas` | 별도 프로세스마다 초기화, 12 XMV와 41 XMEAS 추출 가능 | **선택. 실제 g++ 빌드·입력 변경·시계열·독립 반복 실행 확인** |
| [pyTEP / SoftwareX 배포 소스](https://github.com/ElsevierSoftwareX/SOFTX-D-21-00069) | Python API → MATLAB Engine → Simulink | `setup/reset`, 입력·외란 변경, simulate, 데이터 저장 지원 | BSD-3-Clause API지만 라이선스가 활성화된 MATLAB/Simulink와 호환 Python이 필요. 현재 환경에서 해당 실행 환경을 확인하지 못해 채택하지 않음 |
| [Ricker 원본 인터페이스](https://github.com/rcandell/tesim/blob/81a7ac9dc04f91bc0898c36f8522372e0e437fc1/README_ricker_original.txt) | MATLAB/Simulink S-function | 초기 상태·12 MV·20 외란·41 측정값 | 원형·초기화/샘플 지연 확인에 사용. 현재 실행은 MATLAB 없이 NIST C++ 코어를 사용 |

선정은 OpenModelica나 MATLAB을 먼저 정해 놓고 한 것이 아니다. 실제 입력 설정·실행·시계열 추출이 가능한 공개 코어와 현재 환경의 C++ 컴파일러를 확인한 뒤 결정했다. TEP 실행에 OpenModelica, MATLAB, Simulink, PLC, Beckhoff ADS, Boost, 대형 공개 데이터 다운로드는 필요하지 않다.

출처:

- [NIST의 코드 공개 설명](https://www.nist.gov/publications/computer-code-tennessee-eastman-industrial-wireless-systems-performance-evaluation).
- 원저 Downs & Vogel (1993), *A plant-wide industrial process control problem*, [DOI](https://doi.org/10.1016/0098-1354(93)80018-I), [논문 사본](https://users.abo.fi/khaggblo/RS/Downs.pdf). 초기 관측값·변수·정규화 입력은 Tables 3–5와 TEINIT 설명을 대조했다. 원래 실제 공정의 구성·반응·조건을 수정한 연구 모델이므로 특정 현장 설비와 동일하다고 가정하지 않는다.
- 코어 고정 커밋: `81a7ac9dc04f91bc0898c36f8522372e0e437fc1` (2022-08-08). `backend/simulator/tep/source.lock.json`에 파일별 SHA-256을 보존한다.
- `vendor/teprob.cpp`, `teprob.h`는 **바이트 변경 없이** 포함했다. 원본의 NIST 사용·복제·수정·배포 허가와 보증 부인, 비추천·비보증 안내를 `vendor/LICENSE.md`, `DISCLAIMER.md`로 함께 보존한다. 미국에서는 NIST 직원 저작물이 public domain이며 해외 권리 범위의 허가 문구도 포함되어 있다. 상용 MATLAB 라이선스는 필요 없다. NIST의 제품 보증이나 공식 검증을 뜻하지 않는다.

네 vendored 파일은 고정 커밋의 **Git blob 바이트**와 대조했다. Windows 체크아웃의 자동 줄바꿈 변환을 제거했고 `.gitattributes`로 이후 변환을 막는다. lock과 모델 사전의 SHA는 해당 원본 바이트 기준이다.

**전체 NIST TESIM 프로그램을 그대로 실행하는 것은 아니다.** 공정 방정식 코어는 그대로 쓰고 Iron-Man의 `runner.cpp`가 CLI·CSV·적분 루프를 제공한다. NIST `TEPlant`의 다른 초기 상태, `TEController`, 무선 채널, HIL, 비용 모듈은 사용하지 않는다. 따라서 전체 TESIM 제어기 포함 실험이나 Harvard 데이터와 수치가 동일하다는 주장은 하지 않는다.

## 실행 설정과 지원 범위

| 항목 | 현재 값·의미 |
|---|---|
| 모델 버전 | `nist-tep-81a7ac9-ironman-v1` |
| 초기 프로필 | `nist-teinit-base-case-v1`; 원본 `teinit`의 50 내부 상태와 12 초기 XMV |
| 운전 모드 | 원본 base case (논문의 Mode 1 대응). 다른 모드·사용자 초기 상태 복원은 지원하지 않음 |
| 제어기 | `none_open_loop_hold`: 자동 제어기 없음. 기준은 초기 12 MV 유지, 변경은 선택한 냉각수 MV 하나만 변경 |
| 랜덤 시드 | 원본 `teinit`이 설정하는 **1431655765**. 임의 시드 변경 미지원. 각 분기는 새 OS 프로세스에서 다시 초기화 |
| 외란 | IDV(1)..IDV(20) 모두 0. `degraded_cooling`이나 효율 0.65를 가져오지 않음 |
| 노이즈·분석기 | 원본 측정 노이즈·샘플 지연 유지. XMEAS(1..22)는 각 모델 호출에서 관측, 23..36은 360초, 37..41은 900초 분석기 샘플/지연 구조를 유지. 출력 간격이 짧아도 새 분석기 측정이 생긴다는 뜻이 아님 |
| 코어 시간·도함수 | h. 외부 결과와 요청은 s. 래퍼에서 `time_s/3600`과 `dt_s/3600` 변환 |
| 적분 | 고정 0.1초 forward Euler, 상태 있는 코어를 단계당 한 번 호출. 초기 명령 적용을 위한 t=0 호출도 양쪽에서 동일하게 수행 |
| 출력 관측 주기 | 1..60초 정수, 기본 10초. 시험 구간은 이 주기의 정수 배수 |
| 시험 구간 | 1..1800초, 기본 600초. 원본 개루프 공정이 불안정할 수 있어 장시간 정상 운전 보장은 하지 않음 |
| 명령 시점 | t=0 초기 관측을 먼저 기록하고 직후 입력 변경. t=0 관측·상태는 두 분기 동일 |
| 프로세스 제한 | 분기별 Linux GNU `timeout` 25초, Python 대기 30초. 관문 기본 90초. 취소 후에도 외부 자식은 25초 이내 제한으로 종료되며 즉시 종료를 보장하지 않음 |

모든 실행은 **기본 초기 상태에서의 오프라인 시험**이다. `/state`의 가상 냉각 탱크 관측이나 현장 센서값을 TEP에 이식하지 않는다. `TEPState.configured_at`은 초기화 프로필을 캡처한 시각이며 계측 시각이 아니다. 내부 50 상태는 조성·재고·에너지·냉각수·액추에이터를 포함한 코어 전용 벡터다. 보고서에 수치·해시·초기화 소스를 보존하되 동일한 단위를 가진 물리 측정 배열로 해석하지 않는다.

### 냉각수 입력

| 1부터 시작하는 번호 | 정의 | 입력 단위·범위 | 기준값 (원본 float 상수 → double) |
|---|---|---|---|
| XMV(10), API `XMV10` | 반응기 냉각수 유량 설정 | `percent_full_scale`, 0..100 | 41.105812072753906 |
| XMV(11), API `XMV11` | 응축기 냉각수 유량 설정 | `percent_full_scale`, 0..100 | 18.113491058349609 |

**펌프 RPM 또는 펌프 속도 %가 아니다.** 코어는 정규화 입력을 자체 범위 계수로 변환하고 5초 액추에이터 응답을 포함한다. 정규화 설정과 실제 액추에이터 상태도 분리한다 (`ACTUAL_XMV10/11`, 내부 상태 48/49). 현재 API는 물리 냉각수 유량이나 펌프 RPM으로 변환하는 매핑을 제공하지 않는다. 예제 42와 19는 연동 확인용 작은 입력 변경이며 운전 권고가 아니다.

원본 `teinit`의 전체 기준 MV:

```text
[63.052631378173828, 53.979705810546875, 24.643558502197266,
 61.301921844482422, 22.209999084472656, 40.063747406005859,
 38.100341796875, 46.534156799316406, 47.445735931396484,
 41.105812072753906, 18.113491058349609, 50.0]
```

### 측정값과 단위

사전 원본: [고정 커밋 TENames.cpp](https://github.com/rcandell/tesim/blob/81a7ac9dc04f91bc0898c36f8522372e0e437fc1/c/TENames.cpp), `teprob.cpp` 계산 및 원저 Tables 4–5. 런타임 사전은 `tep/variables.py`, 보고서의 `variables`에 모든 정의가 들어간다.

| XMEAS 번호 | 측정값 | 단위 |
|---|---|---|
| 1 | A 공급 | kscm/h (1000 표준 m³/h) |
| 2, 3 | D, E 공급 | kg/h |
| 4, 5, 6 | A+C 공급, 재순환, 반응기 공급 | kscm/h |
| 7, 13, 16 | 반응기, 분리기, 스트리퍼 압력 | kPa_gauge; 절대압이 아님 |
| 8, 12, 15 | 반응기, 분리기, 스트리퍼 액위 | percent |
| 9, 11, 18 | 반응기, 분리기, 스트리퍼 온도 | degC |
| 10 | 퍼지 유량 | kscm/h |
| 14, 17 | 분리기, 스트리퍼 액체 배출 | m3/h |
| 19, 20 | 스팀 유량, 압축기 동력 | kg/h, kW |
| 21, 22 | 반응기, 응축기 냉각수 출구 온도 | degC |
| 23..28 | 공급 A..F 조성 | mole_percent |
| 29..36 | 퍼지 A..H 조성 | mole_percent |
| 37..41 | 제품 D..H 조성 | mole_percent |

### 코어 정지 조건과 승인 정책은 구분한다

선택 코어가 실제로 검사하는 정지 조건을 결과 `core_shutdown_rules`에 보존한다. 반응기 압력 3000 kPa gauge 초과, 온도 175°C 초과, 반응기 액체 부피 2..24 m³ 밖, 분리기 1..12 m³ 밖, 스트리퍼 1..8 m³ 밖이다. 소스의 엄격한 `<`/`>` 비교이며 소스 내부의 노이즈 추가 전 검사다. 액위 percent와 액체 부피 m³를 혼동하지 않는다.

이 값은 선택 구현의 계산 중단 조건이다. 정상 운전 제한·현장 안전 기준·승인 기준으로 등록하지 않았다. **기존 탱크의 80°C 제한, 60/80% 명령, 0.65 효율, 16개 계수 조합은 TEP 경로에 적용하지 않는다.**

## 재현 가능한 실행

### Windows + 기존 Ubuntu WSL

현재 확인 환경: Windows 11, Python 3.12.14, Ubuntu 24.04.4 WSL, g++ 13.3.0, Linux x86_64. 기존 WSL 배포와 `g++`, GNU `timeout`이 필요하다. WSL 설치/배포 생성은 아래 명령이 자동 수행하지 않는다.

```powershell
# 저장소 루트; 프로젝트 Python 환경/의존성이 준비되어 있어야 함
.\.venv\Scripts\python.exe -m backend.simulator.tep.build
.\.venv\Scripts\python.exe -m scripts.run_tep --variable XMV10 --value 42 --duration 600 --sample 10 --repeat
.\.venv\Scripts\python.exe -m scripts.run_tep --variable XMV11 --value 19 --duration 600 --sample 10 --repeat --output data/tep-condenser.json
$env:IRON_MAN_TEST_TEP='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q
```

배포 이름이 다르면 `IRON_MAN_TEP_WSL_DISTRO`로 지정한다. 빌드는 저장소 내부 `.tep-cache/engine/tep-runner`와 `build.json`에 생성된다. HTTP 요청 중 다운로드·설치·컴파일은 하지 않는다. 소스·래퍼·바이너리 해시가 달라지면 실행을 보류하고 명시적으로 다시 빌드한다.

### Linux / CI / Docker

Python >=3.11과 프로젝트 의존성, C++17 지원 GNU g++, GNU coreutils의 `timeout`, 런타임 libstdc++가 필요하다. Ubuntu/Debian에서 `g++` 설치 후:

```bash
python -m backend.simulator.tep.build
python -m scripts.run_tep --repeat
IRON_MAN_TEST_TEP=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Docker API 이미지는 builder에서 컴파일하고 런타임에는 실행 파일·manifest와 libstdc++만 포함한다. `IRON_MAN_TEP_ENGINE_DIR=/opt/tep`, 실행 원본은 `/data/tep-runs`에 저장한다. 최초 2번 인계의 확인 범위는 WSL 외부 모델 + Windows API/테스트 + 프런트 빌드였다. 이후 **1번이 Docker·CI·실제 HTTP 평가·저장·재시작·공개 HTTPS 브라우저 검증 완료를 기록했다.** 해당 실행 버전과 확인 범위는 [공개 TEP 배포 검증](codex-log/tep-public-deployment-validation.md)을 따른다. 이번 로컬 `archive/TEP_data` 참조 탐색 기능은 그 배포 뒤 추가한 선택 기능이며 서버 데이터 마운트·재배포는 아직 확인하지 않았다.

### 1번 관문·배포 담당에게 인계와 현재 상태

2번 완료 범위는 엔진 소스 고정·변수/지원 시험 사전·입출력 계약·빌드/실행 인터페이스·로컬 반복 검증이다. **`deploy/Dockerfile.api`, Compose와 CI의 최종 검토·통합·배포 판정은 1번이 담당하며 기존 TEP 코어의 배포 검증은 완료됐다.** 현재 1번에 남은 것은 TEP 전용 위험·승인·재검증 기준 결정이다. 계산 성공도 전부 보류하는 경계는 유지한다.

| 인계 항목 | 준비 내용 / 1번이 확인할 것 |
|---|---|
| builder 패키지 | GNU g++ (C++17), coreutils `timeout`; Python 표준 라이브러리로 `python -m backend.simulator.tep.build --output /opt/tep`. 소스·라이선스·래퍼·lock이 COPY되어야 함 |
| runtime 패키지 | libstdc++6·libgcc/libm·GNU coreutils `timeout`. g++·MATLAB·OpenModelica는 런타임에 필요 없음 |
| 아티팩트 | `/opt/tep/tep-runner`, `build.json`; wheel에 `runner.cpp`, `source.lock.json`, `reference.lock.json`, `vendor/*` 포함. 런타임에서 소스/래퍼/바이너리 SHA 검증. 참조 원본 `.dat`·Fortran 코드·README는 wheel에 미포함 |
| 환경변수 | `IRON_MAN_TEP_ENGINE_DIR=/opt/tep`, `IRON_MAN_TEP_RUN_DIR=/data/tep-runs`; 기존 evaluation 기본 2 workers/90s. Linux에서는 WSL 변수 사용 안 함 |
| 볼륨·권한 | 기존 `gateway-data:/data`에 SQLite와 TEP 원본 CSV/진단 파일이 함께 남음. 비root UID 10001의 생성/읽기·백업·용량/보존 정책 확인 |
| CI | backend job에 명시적 엔진 빌드와 `IRON_MAN_TEST_TEP=1` 추가. 브라우저 smoke는 기존 탱크를 명시 선택하고 마지막에 TEP 완료 결과·보류·승인 비활성화를 확인하도록 준비 |
| 확인된 결과 | 2번: Windows→WSL 실제 외부 실행·재현, 이번 참조 통합 포함 전체 307 테스트와 프런트 타입/빌드 통과. 1번: 배포한 `4de39be` 버전의 Docker·CI·Linux 런타임·HTTP 평가·보류/승인 거절·SQLite 재시작 보존·공개 HTTPS와 Chrome 검증 기록 |
| 새 선택 기능 배포 | 이번 참조 API/화면을 배포할 경우 원본 자료와 고지를 읽기 전용 마운트하고 `IRON_MAN_TEP_REFERENCE_DIR` 지정. 출처/라이선스 적용 범위 확인과 해당 마운트의 API/UI 검증은 별도 필요 |

최신 [TEP Docker 검증 기록](codex-log/tep-docker-update-validation.md)과 [공개 배포 기록](codex-log/tep-public-deployment-validation.md)에 배포 버전·실행 결과를 남겼다. 이번 참조 파일 탐색은 **코어 실행 데모에 필수가 아닌 선택 기능**이며 시뮬레이션 참조 자료다. 실측 또는 현재 개루프 모델의 독립 정확도 검증 자료로 처리하지 않는다. 다음으로 2·3번의 근거→반례/추가 시험 매핑 확정, 3번 TEP 근거 연동, 4번 해당 근거/불확실성 표시가 남았다. 실측 오차·현장 적용성 검증도 계속 미완료다.

출력 `data/tep-result.json`은 실제 실행 결과다. `--repeat`는 새 프로세스들로 다시 계산하여 전체 결과를 비교한다. `.tep-cache/runs/<uuid>/`에 기준/변경 CSV·stderr·설정을 남긴다. 기준이 성공하고 변경이 실패해도 보고서에는 부분 성공 수치를 넣지 않는다. 성공 보고서는 모든 시계열·변수 사전·차이 지표·50 초기 상태·12 초기 입력·시드·적분/관측 간격·시험 구간·출처 커밋과 해시·빌드 컴파일러/플랫폼/옵션/바이너리 해시를 보존한다. 원본 CSV는 실행 디렉터리를 따로 백업하며 자동 삭제하지 않는다.

## 기존 API와 연결

2·3번이 함께 읽을 구현/변수/지원 시험 사전은 `contracts/tep-model.json`이다. 현재 시험 ID는 `base_case_cooling_step_v1` 하나이며 외란·고장 레지스트리는 비어 있다. 정상 운전 범위와 안전 허용 범위는 null로 보존하고 입력 지원 범위·코어 정지 조건과 구분한다. 팀의 [근거 계약 초안](tep_evidence_contract_draft.md)은 후속 근거/시험 매핑을 위한 것이며 현재 실행에 적용하지 않는다.

UI 기본 요청은 TEP, 기존 합성 탱크는 별도 선택이다. 다음 입력은 기존 `POST /requests`로 접수한다.

```json
{
  "equipment_id": "tep-sim-01",
  "purpose": "TEP 반응기 냉각수 입력 변경 비교",
  "command": {
    "type": "set_tep_cooling_water", "variable": "XMV10", "value": 42,
    "duration_s": 600, "sample_period_s": 10
  }
}
```

`POST /requests/{id}/evaluate`는 기존처럼 202, 별도 작업 실행 후 `GET /requests/{id}`와 `/history`에서 보고서를 읽는다.

- `report.snapshot`은 TEP 초기화 프로필이다. 탱크 온도/부하/센서 품질을 만들지 않는다.
- `report.tep_simulation`은 `tep-1.0` 계약, `baseline/candidate.points`는 동일 시간축의 12 XMV·41 XMEAS·두 냉각수 액추에이터 상태다. 번호는 1부터, 배열 인덱스는 0부터 시작한다.
- 4번 화면은 이번 요청에서 외부 엔진이 새로 계산한 기준/변경 결과와 사전 생성 참조 기록을 구역별로 분리한다. 현재 요청 보고서에 참조 기록이 없으면 미연결로 표시하며, 참조 데이터가 없어도 TEP 실행은 가능하다. 참조 통계는 정상 운전 범위나 안전 한계로 승격하지 않는다.
- `comparison`은 변수마다 min/max, 종료 차이(candidate−baseline), 최대 절대 차이. **실측 잔차나 정확도 점수가 아니다.**
- TEP 보고서의 기존 `simulation`, `assessment`, `evidence`는 null이다. 기존 펌프 규칙과 근거 fixture를 TEP 검토로 재사용하지 않는다.
- 평가 완료 후 화면의 **AI 피드백 받기**는 `POST /requests/{id}/feedback`을 호출한다. 이 요청은 SQLite에 저장된 TEP 명령·시뮬레이션 결과를 그대로 전달해 `OPENAI_API_KEY`와 `IRON_MAN_EVIDENCE_MODEL`로 사후 설명을 생성한다. TEP 전용 지침은 XMV 입력을 펌프 RPM으로 부르지 않고, 모델·운전 범위의 한계와 문헌의 적용 불일치를 표시하도록 한다. 문헌 카드는 기존 출처 설정에서 검증하며 맞는 근거가 없으면 부족 조건으로 보고한다.
- AI 피드백은 저장된 결과를 설명할 뿐이며 새 시뮬레이션을 실행하거나 TEP의 `hold / TEP_POLICY_NOT_CONFIGURED` 판정·승인 권한을 바꾸지 않는다. 키/모델 오류와 네트워크 실패는 화면에 오류로 표시하고 저장된 TEP 수치 결과는 유지한다.
- API 보고서의 `report.tep_evidence`에는 3번 전용 TEP 근거 계약이 연결되어 있다. 모델 정의·물리 기전·시뮬레이션 관측·안전 근거의 역할과 지원/미지원 시험 제안을 구분하며, 기존 사후 AI 피드백과 별도로 표시한다. 구체적인 동작과 아직 확인되지 않은 실제 LLM 검토는 [TEP 근거 인계](tep_evidence_handoff.md)를 따른다.
- 성공해도 `hold / TEP_POLICY_NOT_CONFIGURED / can_approve=false / execution_scope=unconfigured`. 실패·누락·범위 밖은 `hold / SIMULATION_INCOMPLETE`. 원본 코드·변수 정의 변경은 재검증을 요구한다.
- 승인과 실행 API는 409로 거절하고 알림을 자동 큐에 넣지 않는다. 재시험은 기존 경로로 가능하다. 승인 가능한 척하는 TEP 보고서는 계약에서도 거절한다.
- 잘못된 변수 이름·대상 조합·타입·알 수 없는 필드는 HTTP 422로 접수 거절된다. 유한하지만 0..100 밖 값·지원 시험 구간 밖·주기 불일치 등 접수 가능한 미지원 조건은 평가 보류한다. 런타임은 잘못된 CSV 열/개수/시간축/NaN/초기 상태/적용 입력/누락 결과/불명 단위/비정상 종료를 성공으로 처리하지 않는다.

## 현재 검증 결과: 1단계

실제 외부 코어 및 최신 팀원 근거 인계 변경을 포함한 전체 테스트 **290 passed**, 프런트 타입 검사·Vite 빌드 통과 (2026-10-09). 기존 Starlette/httpx 호환 경고 1개. 추가 TEP 시험은 프로토콜·정책·실제 반복 실행·변경 없음·XMV10/XMV11 효과·원본 정지·비동기 HTTP·SQLite 저장·승인 차단을 다룬다. 합성 CSV는 파서 오류 시험에만 사용하고 실행 성공의 근거로 삼지 않았다.

- 600초, XMV10 41.105812072753906 → 42, 관측 10초, 두 번의 독립 기준/변경 실행에서 시계열과 CSV 해시 동일.
- 종료 시 변경−기준: XMEAS7 약 +22.331547 kPa gauge, XMEAS9 약 −3.9079987°C. 연동 확인 수치이며 안전하거나 바람직한 운전이라는 뜻이 아니다.
- 변경 값을 원래 기준과 같게 설정하면 두 CSV와 모든 비교 차이가 동일/0.
- XMV11 변경 시 해당 냉각수 관측이 변화하고 XMV10 유지 확인.
- XMV10=0, 600초 시험에서 **원본 반응기 압력 정지 코드 1** 발생 → `failed / PROCESS_SHUTDOWN`, 성공 시계열·비교 수치 없음, 원본 부분 CSV는 진단용만 남음.
- 초깃값 관측 약 120.4°C, 2705 kPa gauge 등은 원저 base case와 대조한다. 이는 모델 입출력 확인이며 현장 검증이 아니다.

현재 재현성은 같은 실행 환경·빌드·설정에서 확인했다. 다른 컴파일러·CPU·libm 간 비트 단위 동일성, 적분 수렴/장시간 오차, 다른 제어기·모드·외란·고장 시나리오, 실제 설비 상태 복원은 검증하지 않았다. 고정 0.1초 Euler와 출력 표본의 최고값을 연속 시간 최댓값 보장으로 해석하지 않는다.

공개 기록 데이터는 이번 최소 통합에 필요 없어 다운로드하지 않았다. [Rieth et al. Harvard Dataverse](https://doi.org/10.7910/DVN/6C3JR1)는 후속 비교 후보일 뿐이며 라이선스·파일·변수·시드·제어기가 확인되기 전 사용/재배포하지 않는다. 사용하게 되더라도 simulation data로 표시하고 실측으로 취급하지 않는다.

## 실측 데이터 수신 후: 2단계 (미완료)

실측 도착 전 준비한 기능은 [냉각수 액추에이터 응답시간의 오프라인 보정 도구](TEP_CALIBRATION.md)다. 입력/단위·학습/독립 검증·후보 거절·해시 저장을 구현했고 시뮬레이션 자료와 실제 기본 엔진의 해당 성분식으로 기능을 확인했다. 전체 공정 계수 추정이나 현장 정확도 검증을 수행한 상태는 아니며 런타임에는 후보를 적용하지 않는다. 실측 데이터의 물리적 공정 대응·전체 초기 상태·열전달 등의 보정은 아래 절차를 따르는 후속 단계다.

먼저 실제 설비의 공정 구조가 TEP와 대응하는지 판단한다. 단일 탱크·냉각 펌프 데이터만으로 다단 TEP 공정이 현장 설비를 재현한다고 주장하지 않는다. 대응하지 않으면 별도 모델 또는 명시적 부분 모델이 필요하다.

필요한 입력:

| 구분 | 필요한 데이터·메타데이터 |
|---|---|
| 출처 | 설비/센서 태그, 수집 일시, 수집기·원본 파일 버전·해시, 사용 권한/라이선스, 센서 교정·품질 플래그 |
| 시간 | 타임존을 포함한 timestamp, 원래 관측 간격·누락·지연·시계 동기화, 명령 적용/액추에이터 응답 시각. 고속 측정은 현재 비교축 10초에 맞출 수 있는 원본 간격이 필요하며 더 느리면 원래 간격으로 평가 |
| 제어 입력 | 목표와 실제 밸브 설정/냉각수 유량, 정규화 기준·포화·deadband·속도 제한. 실제 펌프 RPM은 별도 태그와 펌프/밸브/유량 매핑이 필요 |
| 물리 관측 | 공정 및 냉각수 입·출구 온도 °C, 압력 kPa (gauge/absolute 구분), 액체 부피 m³ 또는 교정된 액위 %, 공급·제품·퍼지 유량 kg/h 또는 표준/실제 m³/h 구분, 조성 mol%/mass% 구분 |
| 운전 조건 | 제어기 종류·게인·설정값·auto/manual·루프 주기, 운전 모드·제품비율·부하, 공급 조성/온도/압력, 냉각수 조건, 외란·정비·고장 이벤트 |
| 초기 상태 | 가능한 물질 재고·조성·에너지·액추에이터 상태와 초기화/추정 근거. 측정 41개만으로 내부 50개를 완전히 복원할 수 있다고 가정하지 않음 |

절차:

1. 공정/태그 대응·단위 변환·품질·시간/이벤트 정렬을 승인된 변수 사전으로 검증한다. 분석기 지연을 보존하고 결측값을 실제 계측처럼 채우지 않는다.
2. 초기 상태 추정·warm-up과 제어기/외란 조건을 정한다. 복원 불가능한 상태·조건은 지원 불가로 기록하고 결과를 보류한다.
3. 정상·과도·고장 구간을 분리하고 시간 순서의 학습/보정과 **독립 검증 구간**을 둔다. 원본 단위·정렬·해시와 제외 사유를 남긴다.
4. 변수별 bias, MAE, RMSE, 최대/상위 분위 오차, 시간 지연, 한계 위반 재현·누락, 조건별 오차를 계산한다. 같은 시간축/관측 방식과 단위에서 비교한다.
5. 설비 담당자가 센서 정확도·위험 분석을 근거로 변수별 허용 오차·지원 운전 범위·초기화 조건을 사전에 정한다. 데이터가 들어왔다는 이유만으로 검증 완료 또는 자동 승인으로 바꾸지 않는다.
6. 1번의 TEP 전용 위험/재검증/권한 정책, 3번의 공정에 맞는 실제 근거·반례, 4번의 불확실성·검증 범위 표시를 검토한다. 실제 설비 적용에는 별도의 실행 어댑터와 현장 검증이 필요하다.

**이번 완료 범위는 1단계 연동·반복성·계약·보류 확인이다. 2단계 실측 정확도와 실제 설비 적용성은 계속 미완료로 남긴다.**
