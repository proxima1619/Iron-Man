# 외부 데모 배포

## 현재 상태

2026-10-09에 EC2의 기존 합성 냉각 탱크 데모를 HTTPS로 배포하고 인증·브라우저 시연·API 재시작 후 기록 보존을 확인했습니다. 접속 정보는 `.deploy-private/access.json`에 비공개로 보관합니다. 아래 `demo.example.com` 등은 설정 예시입니다.

TEP를 포함한 이미지는 별도 Compose 프로젝트에서 비root 실행·XMV10/XMV11 HTTP 평가·승인/실행 거절·API 및 전체 스택 재생성 후 보고서 보존을 검증했습니다. 공개 데모 업데이트는 해당 커밋의 CI가 통과한 뒤 수행하고, 업데이트 후 `https_smoke`와 `browser_smoke`로 다시 확인합니다.

현재 EC2는 콘솔에서 직접 생성했으며 Elastic IP가 없는 자동 할당 IPv4를 사용합니다. 아래 CloudFormation 생성 계획은 기존 서버에 적용한 구성이 아닙니다. 인스턴스를 중지 후 다시 시작하면 IP·DNS·HTTPS 설정 확인이 필요합니다.

```text
브라우저 → HTTPS + 사이트 비밀번호(Caddy) → React / Nginx
                                            ↓ X-Iron-Man-Token
                                        FastAPI 1 worker
                                          ├─ SQLite volume
                                          └─ 평가 프로세스 최대 2개
```

공개 포트는 TCP 80(인증서 발급·HTTPS 전환), 443(시연), 관리자 IP의 22(SSH)입니다. API 8000·웹 8080은 호스트에 공개하지 않습니다. 실제 설비는 연결하지 않습니다. 초기 부하 1의 60%·80% 요청은 차단됩니다. 승인 시연은 부하 0.6의 80% 요청이 장기·평형·민감도 등 가상 정책을 통과한 뒤 진행합니다.

UI의 기본 모델은 TEP입니다. TEP 계산은 성공해도 `hold / TEP_POLICY_NOT_CONFIGURED`이며 승인·실행하지 않습니다. 승인 흐름을 시연할 때는 **모델 → 기존 합성 냉각 탱크**를 명시적으로 선택합니다.

## TEP 이미지와 검사

`deploy/Dockerfile.api`는 builder의 `g++`로 고정 코어를 컴파일하고, runtime에는 `libstdc++6`·GNU `timeout`을 제공하는 `coreutils`와 빌드 산출물을 넣습니다. runtime은 UID 10001이며 컴파일러를 포함하지 않습니다. Compose는 `IRON_MAN_TEP_ENGINE_DIR=/opt/tep`, `IRON_MAN_TEP_RUN_DIR=/data/tep-runs`를 지정합니다. 기존 `gateway-data` 볼륨을 유지하며 루트 소유 볼륨으로 바꾸지 않습니다.

`scripts.tep_smoke`는 실제 HTTP에서 600초 XMV10=42·XMV11=19의 기준/변경 결과, XMV10=0의 코어 정지, 101의 지원 범위 밖 보류를 확인합니다. 출처·바이너리 해시·초기 프로필·단위·시계열을 검사하고 모든 경우 승인·실행 거절과 탱크 상태 미변경을 확인합니다. `compose_smoke`와 `https_smoke`가 이 검사를 호출합니다. Compose 검사는 비root·실행 파일·볼륨 쓰기 권한과 재생성 후 TEP 보고서 보존도 확인합니다. 브라우저 검사는 두 냉각수 입력의 그래프와 비활성 승인·적용 버튼을 확인합니다.

TEP의 초기화 프로필은 실측 snapshot이 아닙니다. 탱크의 80°C·최소 펌프 속도·효율 저하 규칙은 TEP 경로에 적용하지 않습니다. 별도 위험·근거·재검증 기준과 현장 검증이 마련될 때까지 보류를 유지합니다. [TEP 인계와 모델 한계](TEP_INTEGRATION.md).

## 서버 생성 계획과 비용

`deploy/aws/template.json`은 별도 VPC·공개 서브넷·인터넷 게이트웨이·보안 그룹·SSH 공개키·EC2·고정 IPv4를 생성합니다. 다른 기존 인프라를 변경하지 않습니다. IAM 역할·NAT Gateway·로드밸런서·RDS는 생성하지 않습니다.

- 서울 `ap-northeast-2`, Ubuntu 24.04 amd64, `t3.medium`, 2 vCPU / 4 GiB.
- 암호화된 gp3 30 GB, 기본 IOPS·처리량.
- CPU 크레딧 standard. 크레딧 소진 시 성능이 제한되며 Unlimited 추가 요금을 사용하지 않습니다.
- Elastic IP 1개. 중지 중에도 IP·디스크 요금은 유지됩니다.
- SSH는 관리자의 공인 IPv4 `/32`만 허용. IMDSv2 필수. AWS 자격증명을 인스턴스에 넣지 않습니다.
- cloud-init은 공식 Docker apt 저장소에서 Docker·Compose plugin과 Git/Python을 설치합니다. 앱·비밀값은 별도로 배포합니다.

**2026-10-09 AWS Pricing API 조회 기준**, EC2 $0.052/시간, gp3 $0.0912/GB-월, 공인 IPv4 $0.005/시간입니다. 730시간 가동하면 EC2 $37.96 + 디스크 $2.736 + IPv4 $3.65 = **약 $44.35/월**, 하루 가동 비례로 약 **$1.46/일**입니다. 세금·환율·트래픽·LLM API 비용과 무료 크레딧/할인은 제외했습니다. 실제 청구 상한이 아닙니다. [EC2 요금](https://aws.amazon.com/ec2/pricing/on-demand/), [EBS 요금](https://aws.amazon.com/ebs/pricing/), [공인 IPv4 요금](https://aws.amazon.com/vpc/pricing/).

템플릿 문법과 공식 Ubuntu AMI 파라미터 존재는 읽기 전용 AWS 호출로 확인합니다. EC2 부팅·설치는 생성 뒤 확인해야 합니다.

## 생성 명령 — 비용 발생, 실행 전 확인

AWS CLI가 설정된 관리자 컴퓨터에서 실행합니다. SSH 개인 키는 로컬에만 보관합니다.

```bash
mkdir -p .deploy-private
chmod 700 .deploy-private
ssh-keygen -t ed25519 -f .deploy-private/iron-man-ssh -N ''
```

`.deploy-private/parameters.json`을 다음 형태로 작성합니다. `AdminCidr`는 관리자 실제 공인 IPv4/32, `SshPublicKey`는 생성한 `.pub` 파일 전체 한 줄입니다. 개인 키를 넣지 마세요.

```json
[
  {"ParameterKey": "AdminCidr", "ParameterValue": "YOUR_PUBLIC_IPV4/32"},
  {"ParameterKey": "SshPublicKey", "ParameterValue": "ssh-ed25519 YOUR_PUBLIC_KEY"}
]
```

```bash
aws cloudformation create-stack --region ap-northeast-2 \
  --stack-name iron-man-demo --template-body file://deploy/aws/template.json \
  --parameters file://.deploy-private/parameters.json
aws cloudformation wait stack-create-complete --region ap-northeast-2 --stack-name iron-man-demo
aws cloudformation describe-stacks --region ap-northeast-2 --stack-name iron-man-demo \
  --query 'Stacks[0].Outputs' --output table
```

동일 이름의 기존 스택이 있으면 먼저 확인하세요. 생성 후 `ubuntu@PUBLIC_IP`로 SSH 접속합니다. 최초 호스트 키를 확인하며 `StrictHostKeyChecking=no`로 우회하지 않습니다. `sudo cloud-init status --wait` 성공 뒤 앱을 배포합니다.

## 도메인과 HTTPS

소유한 도메인이 있으면 A 레코드를 고정 IPv4로 연결합니다. AAAA는 실제 IPv6 경로가 있을 때만 설정합니다.

도메인이 없으면 `<공인IPv4>.sslip.io`를 사용할 수 있습니다. IP를 포함한 호스트명을 해당 IP로 응답하는 외부 DNS 서비스입니다. 자체 소유 도메인이 아니며 서비스 가용성·인증서 발급 제한에 영향을 받습니다. 발급과 외부 접속 검증을 통과한 주소만 제출하세요. [서비스 설명](https://sslip.io/).

Caddy는 호스트명과 외부 TCP 80/443 접근이 준비되면 인증서 발급·갱신과 HTTP→HTTPS 전환을 처리합니다. 인증서 자료는 `caddy-data` 볼륨에 보관합니다. 제출 주소에는 공인 인증서를 사용하며 자체 서명 인증서나 TLS 검증 우회를 사용하지 않습니다. [Caddy HTTPS 문서](https://caddyserver.com/docs/automatic-https).

## 서버에서 앱 배포

Ubuntu/Docker 설치 후 `ubuntu` 사용자로 실행합니다. 공개 저장소이므로 GitHub 비밀키는 필요하지 않습니다. 검증된 커밋 SHA로 버전을 고정하세요.

```bash
cd /opt/iron-man
git clone https://github.com/proxima1619/Iron-Man.git .
git checkout VERIFIED_COMMIT_SHA
docker compose version
python3 -m scripts.deploy_config --domain YOUR_DEMO_HOSTNAME
python3 -m scripts.deploy_check
docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build --wait --wait-timeout 180
```

Compose 2.24.4 이상이 필요합니다. 생성기는 `.env.deploy`(600)와 `.deploy-private/access.json`(600, 디렉터리 700)을 만들고 기존 파일은 덮어쓰지 않습니다. 비밀값은 터미널에 출력하지 않습니다.

- `.env.deploy`: 실행 토큰, 해시된 사이트 비밀번호, 선택적 LLM 설정. Git·Docker 이미지에서 제외.
- `.deploy-private/access.json`: 실제 사이트 계정·비밀번호와 역할 토큰. 소유자만 읽고 비공개 관리.
- 공개 모드에서 서로 다른 32~128자의 URL-safe 역할 토큰이 없으면 API가 시작되지 않음.
- 기본 근거 모드는 `fixture`. `live`는 서버 파일의 `OPENAI_API_KEY`, `IRON_MAN_EVIDENCE_MODEL` 설정·재시작이 필요. 실제 외부 API 비용·응답은 별도 확인.
- 셸에 export한 변수는 `--env-file`보다 우선할 수 있음. 기존 로컬 토큰을 export한 셸을 재사용하지 않고 `deploy_check`로 실제 설정을 확인. `docker compose config` 원문은 비밀값을 포함하므로 공유 금지.

## 두 단계 인증과 팀원 연동

1. 사이트 접속: 브라우저 Basic 인증 창에 사이트 계정·비밀번호 입력.
2. 요청·승인: 화면에 해당 역할 토큰 입력. 요청 토큰에는 승인 권한이 없음.

브라우저 `Authorization`은 사이트 Basic 인증에 사용합니다. 화면/API는 역할 토큰을 **`X-Iron-Man-Token`** 헤더로 전송합니다. Caddy는 인증 후 Basic 헤더를 제거하여 API로 전달하지 않습니다. 로컬 직접 API 호출의 기존 `Authorization: Bearer ...`도 유지합니다. 서로 다른 Bearer와 역할 헤더를 동시에 보내면 401입니다.

계정·토큰을 URL에 넣지 않습니다. 사이트 계정과 요청 토큰은 심사자에게 비공개 제출란 등 승인된 방법으로 전달하고, 승인 토큰은 담당자에게만 전달합니다. 현재는 공유 데모 계정·역할 인증이며 개인 계정·사용자별 요청 소유권·SSO가 아닙니다. 토큰은 브라우저 메모리에 보관하며 새로고침 후 다시 입력합니다. Basic 인증은 브라우저가 캐시하므로 공용 컴퓨터에서는 시크릿 창을 사용하고 종료하세요.

## 배포 확인과 5번 검증

```bash
python3 -m scripts.https_smoke
docker compose --env-file .env.deploy -f compose.deploy.yaml ps
```

검사는 공인 TLS 신뢰, 비인증/잘못된 비밀번호 401, 사이트 비밀번호만으로 API 접근 불가, 역할 토큰만으로 사이트 접근 불가, 평가 202·상태 조회를 확인합니다. TEP XMV10/XMV11의 실제 코어 실행, 코어 정지·범위 밖 입력의 보류와 승인·실행 409를 검사한 뒤, 탱크의 부하 1·60% 차단, 부하 0.6·80% 승인 대기·담당자 승인·가상 적용·가상 시간 진행·유효하지 않은 센서 보류를 확인합니다. 요청 기록 7건을 생성하며 가상 상태를 초기화합니다. 기본 fixture 설정을 전제로 하며 실제 장비·외부 LLM을 호출하지 않습니다.

**5번은 별도 검증**입니다. 다른 컴퓨터·휴대폰의 다른 네트워크에서 URL을 열고 계정→토큰→요청→자동 갱신을 확인하세요. 서버 재시작 후 기록 조회와 노트북 전원을 끈 상태의 접속을 확인하고 브라우저 시연 영상을 남깁니다. 가상 전용 정책과 실제 설비 미연결·모의 근거의 한계를 발표에 명시합니다.

GitHub Actions `https` job은 같은 공개 설정을 사용하되 localhost·테스트 CA로 검사합니다. CA를 명시적으로 신뢰하며 TLS 검증을 끄지 않습니다. Chromium에서도 사이트 인증→역할 토큰→요청→자동 결과 갱신→저장 목록을 검사합니다. 공인 DNS·인증서 발급·AWS 실서버 검증을 대신하지 않습니다.

## 업데이트·백업·삭제

검증된 새 SHA를 checkout한 뒤 같은 `.env.deploy`, 같은 Compose 프로젝트·볼륨으로 `up -d --build --wait`합니다. 비밀값을 다시 생성하거나 `down -v`를 사용하지 않습니다.

서버 볼륨은 인스턴스 삭제를 견디는 외부 백업이 아닙니다. SQLite 온라인 backup 후 관리자 컴퓨터로 가져오세요.

```bash
docker compose --env-file .env.deploy -f compose.deploy.yaml exec -T api python -c \
  'import sqlite3; a=sqlite3.connect("/data/ironman.sqlite3"); b=sqlite3.connect("/data/backup.sqlite3"); a.backup(b); b.close(); a.close()'
docker compose --env-file .env.deploy -f compose.deploy.yaml cp api:/data/backup.sqlite3 .deploy-private/backup.sqlite3
```

서버의 `.deploy-private/backup.sqlite3`를 SSH/SCP로 관리자 컴퓨터에 가져와 보관한 뒤 삭제합니다. **스택 삭제는 EC2·디스크·고정 IP를 삭제합니다.** 별도로 삭제하기로 결정한 경우에만 실행하세요.

```bash
aws cloudformation delete-stack --region ap-northeast-2 --stack-name iron-man-demo
aws cloudformation wait stack-delete-complete --region ap-northeast-2 --stack-name iron-man-demo
```

`bootstrap.sh`를 수정하면 `template.json`의 UserData도 함께 갱신합니다. 테스트에서 두 파일 일치를 검사합니다.
