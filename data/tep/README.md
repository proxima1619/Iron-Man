# TEP 원본 데이터 받기와 공유

대상: Rieth et al. (2017), *Additional Tennessee Eastman Process Simulation Data
for Anomaly Detection Evaluation*, Harvard Dataverse V1.0.

원본 제공처: https://doi.org/10.7910/DVN/6C3JR1

현재 원본 파일은 아직 이 저장소에 포함되지 않았다. Codex 환경에서 원본 제공처에
연결하지 못했다. 아래 명령은 네트워크 접근이 가능한 VS Code 터미널에서 실행한다.
스크립트는 게시된 V1.0 파일 목록·CC0 조건을 확인하고 다운로드 크기와 제공자의
체크섬을 검증한다. 실제 조회에 실패하면 파일 ID·라이선스·해시를 만들어내지 않는다.

```powershell
..\.venv\Scripts\python.exe scripts/download_tep.py
```

기본은 아래 네 원본을 변환하지 않고 `data/tep/raw/`에 저장한다.

- `TEP_FaultFree_Training.RData`
- `TEP_FaultFree_Testing.RData`
- `TEP_Faulty_Training.RData`
- `TEP_Faulty_Testing.RData`

정상 운전 원본 두 개만 필요하면 `--normal-only`를 붙인다.
다운로드 완료 시 `data/tep/manifest.json`에 제공자의 체크섬, SHA256, 크기,
파일 ID, 원본 URL과 실제 확인한 이용 조건을 기록한다.

## GitHub에 원본 올리기

`.gitattributes`에 RData용 Git LFS 설정을 추가했다. Git LFS로 원본을 올리면
저장소는 포인터를 추적하고 실제 파일은 LFS 저장소에 업로드된다.
게시자가 제공한 크기를 확인하고 GitHub 계정의 LFS 저장 공간·전송 한도를 확인한다.

```powershell
git lfs install --local
git add .gitattributes .gitignore scripts/download_tep.py data/tep
git commit -m "Add verified original TEP dataset through Git LFS"
git push origin codex/module4-review-integration-v3
```

팀원은 내려받은 뒤 `git lfs pull`로 원본을 받는다. 체크섬 검증에 실패한 파일은
그대로 업로드하지 않는다. 원본 파일이 없으면 다운로드가 완료된 것이 아니다.

## 시연 모델과 구분

이 자료는 현장 실측 데이터가 아닌 TEP 시뮬레이션 이력이다. 원본 다운로드만으로
현재 `cooling-demo-v3` 모델이나 홈페이지 DB 데이터가 TEP 기반으로 바뀌지는 않는다.
TEP 변수·단위와 제어 입력 매핑, 정상 구간 선택, 초기 상태와 시뮬레이터 연결은
2번 담당의 후속 작업이다. 현재 펌프 속도 %와 80°C 제한을 TEP 변수에 직접 적용하지 않는다.
