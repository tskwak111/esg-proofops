# CI1 관리자 설정 — 콘솔에서만 활성화

CI1은 파일과 로컬 검증만 제공한다. 아래 설정·서버 설치·첫 배포는 조정자/관리자가 수행한다. 저장소 `tskwak111/esg-proofops`, 기존 Sydney 계정 `000000000000`는 `deploy/ec2/common.sh` 기준이다. 콘솔의 실제 계정이 다르면 진행을 중단하고 모든 ARN을 다시 검토한다. 장기 AWS 키와 서버 비밀값을 GitHub에 등록하지 않는다.

## 1. 먼저 GitHub 승인 게이트 만들기

1. 저장소 Settings → Environments → **production** 생성. Required reviewers에 운영 승인자를 지정하고 Prevent self-review를 켠다. 관리자 우회도 끈다.
2. Deployment branches and tags → Selected branches and tags → **Branch: main**만 허용한다. Tag 규칙은 추가하지 않는다. main의 PR 검토·기존 CI 필수 검사도 유지한다.
3. 비공개 저장소에서는 요금제에 따라 Required reviewers가 지원되지 않는다. 해당 기능을 실제로 저장할 수 없다면 자동 배포를 활성화하지 않고 기존 수동 경로를 유지한다. 이름만 production인 환경은 승인 게이트가 아니다. [GitHub 환경 설정](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
4. Settings → Secrets and variables → Actions → **Repository variables**에 `BACKEND_DEPLOY_ENABLED=false`를 만든다. 이 값은 job 시작 전에 평가되므로 environment 변수가 아닌 repository 변수여야 한다. 최종 점검 후에만 `true`로 바꾼다.

## 2. AWS ECR 저장소 만들기

AWS 콘솔 → 리전 **ap-southeast-2 (Sydney)** → ECR → Private repositories → Create repository → 이름 **proofops-r108**. 태그는 **Immutable**, 제외 규칙 없음, 암호화는 기본 AES-256을 사용한다. 최소 현재/직전 릴리스 태그는 삭제하지 않으며 본선 동결 중 lifecycle 자동 삭제를 추가하지 않는다. URI는 `000000000000.dkr.ecr.ap-southeast-2.amazonaws.com/proofops-r108`이다.

SHA 태그를 다시 덮어쓰지 않는다. 같은 SHA의 workflow 재실행은 push에서 실패할 수 있다. 기존 SHA를 재배포하려면 아래 서버 명령을 관리자가 사용하고, 코드 변경은 새 commit SHA로 배포한다. 이미지 자동 롤백을 위해 EC2의 직전 로컬 이미지도 보존한다.

## 3. GitHub OIDC 공급자와 배포 역할

IAM → Identity providers → Add provider → OpenID Connect, Provider URL `https://token.actions.githubusercontent.com`, Audience `sts.amazonaws.com`. 이미 정확한 공급자가 있으면 중복 생성하지 않는다.

IAM → Roles → Create role → Custom trust policy, 이름 **proofops-github-deploy**, 최대 세션 1시간. 아래 신뢰 정책을 붙인다. `sub`에 wildcard·다른 repo·브랜치 subject를 추가하지 않는다.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:tskwak111/esg-proofops:environment:production"
    }}
  }]
}
```

환경 subject는 브랜치를 포함하지 않으므로 1단계의 main 제한이 필수다. 실제 저장소가 immutable/custom OIDC subject를 사용한다면 위의 요청된 exact subject와 다를 수 있다. 관리자만 subject 설정을 확인하고 조정자와 불일치를 해결한다. 토큰을 로그에 출력하거나 `sub`를 wildcard로 완화하지 않는다. [GitHub OIDC subject](https://docs.github.com/en/actions/reference/security/oidc)

역할 Permissions → Add permissions → Create inline policy → JSON. 아래 정책을 `proofops-github-deploy-minimal`로 저장한다. ECR 쓰기는 단일 저장소, Run Command는 지정 인스턴스와 AWS 문서로 한정한다. `GetAuthorizationToken`, `GetCommandInvocation`은 리소스 단위 범위를 지원하지 않아 `*`가 필요하다. 후자는 명령 결과 읽기 권한이므로 이 역할의 사용자는 엄격히 제한한다. [SSM IAM 동작 정의](https://servicereference.us-east-1.amazonaws.com/v1/ssm/ssm.json)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PushOneRepository",
      "Effect": "Allow",
      "Action": ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage"],
      "Resource": "arn:aws:ecr:ap-southeast-2:000000000000:repository/proofops-r108"
    },
    {
      "Sid": "DeployOneInstance",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": ["arn:aws:ec2:ap-southeast-2:000000000000:instance/i-01fec46ef85815a17", "arn:aws:ssm:ap-southeast-2::document/AWS-RunShellScript"]
    },
    {
      "Sid": "ReadCommandResult",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

`AWS-RunShellScript`는 대상 서버에서 root 명령을 실행할 수 있는 권한이다. IAM은 그 문서의 명령 문자열을 이 스크립트로 제한하지 않는다. 따라서 workflow 편집·main 병합·환경 승인 권한이 운영 서버의 신뢰 경계다. IAM/EC2 변경, S3 업로드, Secrets Manager 읽기, `iam:PassRole`, ECR 삭제 권한은 이 역할에 추가하지 않는다. [ECR push 권한](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html), [SSM Run Command 권한](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command-setting-up.html)

## 4. 인스턴스 역할에 단일 ECR 읽기 추가

EC2 → 해당 인스턴스 → Security → IAM role이 **proofops-ssm-instance**인지 확인한다. 기존 SSM 권한을 유지하고 IAM 역할에 다음 inline policy만 추가한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
    {
      "Effect": "Allow",
      "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
      "Resource": "arn:aws:ecr:ap-southeast-2:000000000000:repository/proofops-r108"
    }
  ]
}
```

인스턴스에 AWS CLI v2(arm64), Python 3, Docker Compose v2, `flock`, `timeout`이 있어야 한다. SSM Online, IMDS 인스턴스 자격 증명 사용 가능, ECR API·registry·이미지 레이어 S3·SSM으로 HTTPS 통신 가능 여부를 관리자가 확인한다. 정적 키/사용자 프로필은 서버 배포 스크립트가 사용하지 않는다. [ECR 리소스 권한](https://docs.aws.amazon.com/AmazonECR/latest/userguide/security_iam_id-based-policy-examples.html)

## 5. 서버에 승인된 두 파일 설치 — 첫 자동 실행 전에

EC2 콘솔 → Connect → Session Manager 등 기존 관리자 경로로 접속한다. 검토한 commit의 `deploy/ec2/deploy-from-ecr.sh`, `deploy/public/drain-restart.sh` 두 파일을 기존 승인된 전송 경로로 `/home/ubuntu/ci1-reviewed/`에 둔다. 서버에서 파일 SHA-256을 검토본과 비교한다. 다음은 **관리자 실행 예시**이며 CI1 에이전트는 실행하지 않았다.

```bash
sudo install -o root -g root -m 755 /home/ubuntu/ci1-reviewed/deploy-from-ecr.sh /srv/proofops/deploy-from-ecr.sh
sudo install -o root -g root -m 644 /home/ubuntu/ci1-reviewed/drain-restart.sh /srv/proofops/drain-restart.sh
sudo /srv/proofops/deploy-from-ecr.sh --dry-run \
  000000000000.dkr.ecr.ap-southeast-2.amazonaws.com/proofops-r108:REPLACE_WITH_40_HEX_COMMIT_SHA ap-southeast-2
```

예시의 SHA 자리표시자는 실제 검토된 40자리 소문자 SHA로 바꾼다. 검토되지 않은 외부 스크립트를 curl로 실행하지 않는다. `/srv/proofops`와 두 스크립트는 일반 사용자/컨테이너가 쓰지 못하도록 한다. 기존 `compose.yaml`, `compose.env`, `runtime.env`, `private/`, `data/`, Caddy, `proofops.service`를 유지한다. `compose.env`는 정확히 한 줄의 따옴표 없는 `IMAGE=...`가 있어야 한다. 현재 IMAGE가 로컬에 남아 있고 API/worker가 정상인지 확인한다. 현재 서비스는 stop 대신 down을 하도록 바꾸지 않는다.

이 경로는 **이미 운영 중인 서버의 이미지 교체 전용**이다. compose·systemd·runtime 설정이나 호환되지 않는 데이터 형식 변경은 자동 설치하지 않는다. 서버 helper 업데이트는 별도 관리자 검토·설치 대상이다.

## 6. GitHub 변수와 최종 활성화

production → Environment variables에 다음 값을 등록한다. Secret이 아닌 Variable이다.

| 이름 | 값 |
|---|---|
| AWS_ROLE_ARN | `arn:aws:iam::000000000000:role/proofops-github-deploy` |
| ECR_REPO | `000000000000.dkr.ecr.ap-southeast-2.amazonaws.com/proofops-r108` (전체 URI, 태그 제외) |
| INSTANCE_ID | `i-01fec46ef85815a17` |
| REGION | `ap-southeast-2` |

Actions 정책에서 SHA 고정 checkout/upload-artifact/aws-actions를 허용한다. `ubuntu-24.04-arm` 사용 가능 여부와 runner의 Docker·AWS CLI·Python·jq를 확인한다. 스모크는 runner용 worker 2 CPU/5 GiB를 사용하며 운영 compose 자원값은 바꾸지 않는다. [GitHub runner 사양](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

관리자가 환경 승인 설정, IAM JSON 콘솔 검증, 서버 설치, 기존 CI 통과, 본선 동결 여부를 확인한 뒤 repository 변수 `BACKEND_DEPLOY_ENABLED=true`를 설정한다. Actions → Deploy backend → Run workflow → main을 선택하고 production 승인 대기가 실제로 발생하는지 확인한 뒤 승인한다. 성공은 GitHub summary의 SSM command ID 및 `api=healthy worker=healthy ready=ok resumed=true`로 확인한다. SSM 실패 시 AWS 콘솔의 개별 invocation 출력에서 `ROLLED_BACK` 여부를 확인한다. 처음 실행된 AWS/GitHub 통합 결과는 관리자가 별도로 기록한다.
