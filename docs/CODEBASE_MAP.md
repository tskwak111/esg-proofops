# 코드베이스 실행 지도

디렉터리 이름만으로 운영 여부나 삭제 가능 여부를 판단하지 않습니다.

| 구분 | 실행 경로와 역할 |
| --- | --- |
| 현재 hosted | 웹 → `apps/api`의 hosted API/worker → `evaluation.hosted_r108` → `evaluation.local_upstage_pilot`. `scripts/hosted_control.py`는 운영 제어 진입점입니다. |
| 사용자 로컬 | `scripts/analyze_report.py`, `scripts/submission_demo.py`, `scripts/finals_demo.py`가 같은 pilot을 사용합니다. 기존 CLI·모듈 경로를 유지합니다. |
| 검증 | `tests/`, `scripts/test_core.sh`, `scripts/test_full.sh`; `verify_architecture.py`, `check_licenses.py`, `hosted_pipeline_smoke.py`는 `scripts/`의 CI/배포 검사이고 `predeploy_*`, `fresh_e2e_*`는 릴리스 검증 도구입니다. |
| 역사적 실험·재현 | `evaluation/pipeline_recovery.py`, `evaluation/r108_perf_q*.py` 등에는 테스트·상호 참조가 남아 있습니다. 실험 분류는 미사용이나 이동·삭제 허가를 뜻하지 않습니다. |

`evaluation/`에는 현재 hosted 실행기도 포함됩니다. 통째로 이동하거나 배포 패키지에서 제외하지 않습니다.
루트 `api/live-claim.py`, `api/live-report.py`는 위 hosted backend와 별도의 Vercel 함수 경로입니다.
**바이트 고정 파일은 수정 금지**입니다. 정책 해시·과거 replay에 사용되는 파일은 서식·import도 바꾸지 않으며, 편집 전 해시 호출부와 `pyproject.toml`의 보존 주석을 확인합니다.

새 파일 배치 규칙:

- 제품 로직은 `packages/proofops/`의 기존 계층에, HTTP·worker 진입점은 해당 `apps/`에 둡니다.
- pilot의 내부 분리 모듈은 `evaluation/`에 두고 기존 진입점·배포 포함 범위를 유지합니다. 독립 실행·검증 명령은 `scripts/`에 둡니다.
- 테스트는 `tests/`에, 명시적으로 가져다 쓰는 공용 테스트 helper는 `tests/helpers/`에 둡니다. 실험·재현 도구는 목적과 호출 경로를 기록합니다.
- 로컬 산출물은 루트 `outputs/`에 둡니다(신규 추적 제외). 공개 가능한 비식별 증거는 검토 후 `docs/evidence/`에 두며 원본·장부·운영 식별자·계정·호스트는 기록하지 않습니다.
