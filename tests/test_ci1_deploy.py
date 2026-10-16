"""CI1 deployment failure paths using only local shell command replacements."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "deploy/ec2/deploy-from-ecr.sh"
IMAGE = "123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/proofops-r108:" + "a" * 40
OLD = "proofops-r108-public:previous"
ENV = (
    f"# server config\r\nIMAGE={OLD}\r\nWORKER_CPUS=6.0\r\n"
    "WORKER_MEMORY=12g\r\nOCR_PROCESSES=2\r\nCUSTOM=value\r\n"
).encode()

# Call the same sourced helper as production; replace only external command boundaries.
HARNESS = r"""
source "$1"
TEST_DIR=$2 SCENARIO=$3 LOG="$2/calls"
log() { printf '%s\n' "$*" >> "$LOG"; }
flock() { log 'lock'; [[ $SCENARIO != locked ]]; }
sleep() { :; }
env() {
  log "aws $*"
  [[ $SCENARIO != login ]] || return 1
  printf 'mock-token\n'
}
timeout() { shift; "$@"; }
systemctl() {
  log "restart $(head -n 2 compose.env | tail -n 1)"
  [[ $SCENARIO != restart || $(cat "$TEST_DIR/restarts" 2>/dev/null) == done ]] || {
    echo done > "$TEST_DIR/restarts"; return 1;
  }
}
docker() {
  local current=old
  grep -q ':aaaa' compose.env && current=new
  case "$*" in
    login*) cat >/dev/null; log login;;
    pull*) log pull; [[ $SCENARIO != pull ]];;
    'image inspect --format {{.Architecture}}'*)
      if [[ $SCENARIO == arch ]]; then echo amd64; else echo arm64; fi;;
    'image inspect --format {{.Id}}'*)
      if [[ $* == *:aaaa* ]]; then echo new-id; else echo old-id; fi;;
    *'ps -q api') echo api-id;;
    *'ps -q worker') echo worker-id;;
    inspect*)
      if [[ $SCENARIO == rollback_failed || ( $SCENARIO == unhealthy && $current == new ) ||
            ( $SCENARIO == worker && $current == new && $* == *worker-id ) ]]; then
        echo "$current-id unhealthy"
      elif [[ $SCENARIO == wrong_image && $current == new ]]; then echo 'unexpected-id healthy'
      else echo "$current-id healthy"; fi;;
    *'hosted_control.py drain')
      log drain
      [[ $SCENARIO != drain && ( $SCENARIO != resume_redrain || $current != new ) ]];;
    *'hosted_control.py wait-idle --timeout 600') log wait; [[ $SCENARIO != wait ]] || return 3;;
    *'hosted_control.py resume')
      log "resume $current"
      [[ ( $SCENARIO != resume && $SCENARIO != resume_redrain ) || $current != new ]];;
    *'/v1/health/ready'*) log "ready $current"; [[ $SCENARIO != ready || $current != new ]];;
    *'config --quiet') log config; [[ $SCENARIO != config ]];;
    *) echo "Unexpected docker command: $*" >&2; return 99;;
  esac
}
deploy_from_ecr "$4" ap-southeast-2 "$TEST_DIR"
"""


def run_mock(tmp_path, scenario):
    (tmp_path / "compose.env").write_bytes(ENV)
    (tmp_path / "compose.env").chmod(0o640)
    (tmp_path / "compose.yaml").write_text("unchanged compose")
    (tmp_path / "runtime.env").write_text("unchanged server runtime")
    (tmp_path / "private").mkdir()
    (tmp_path / "private/fixture").write_text("unchanged server private file")
    result = subprocess.run(
        ["bash", "-c", HARNESS, "ci1-test", str(SCRIPT), str(tmp_path), scenario, IMAGE],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert (tmp_path / "runtime.env").read_text() == "unchanged server runtime"
    assert (tmp_path / "private/fixture").read_text() == "unchanged server private file"
    assert (tmp_path / "compose.yaml").read_text() == "unchanged compose"
    assert (tmp_path / "compose.env").stat().st_mode & 0o777 == 0o640
    return result, (tmp_path / "calls").read_text().splitlines()


def test_success_only_replaces_image_and_preserves_resource_and_private_files(tmp_path):
    result, calls = run_mock(tmp_path, "success")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "compose.env").read_bytes() == ENV.replace(OLD.encode(), IMAGE.encode())
    assert (tmp_path / ".previous-image").read_text() == OLD + "\n"
    assert calls.index("lock") < calls.index("pull") < calls.index("drain")
    assert calls.index("drain") < calls.index("wait") < calls.index("config")
    assert calls.index("ready new") < calls.index("resume new")
    assert "api=healthy worker=healthy ready=ok resumed=true" in result.stdout
    assert not list(tmp_path.glob(".deploy-ecr.*"))
    assert "AWS_SHARED_CREDENTIALS_FILE=/dev/null" in next(c for c in calls if c.startswith("aws "))


@pytest.mark.parametrize(
    "scenario", ["unhealthy", "worker", "wrong_image", "ready", "restart", "config", "resume"]
)
def test_failure_restores_exact_config_and_resumes_previous_healthy_image(tmp_path, scenario):
    result, calls = run_mock(tmp_path, scenario)
    assert result.returncode != 0
    assert (tmp_path / "compose.env").read_bytes() == ENV
    assert calls[-1] == "resume old"
    if scenario == "resume":
        assert calls.count("drain") == 2
        assert calls.index("resume new") < max(i for i, c in enumerate(calls) if c == "drain")
    assert "ROLLED_BACK" in result.stdout
    assert "DEPLOYED" not in result.stdout
    assert not list(tmp_path.glob(".deploy-ecr.*"))


def test_failed_rollback_keeps_maintenance_and_recovery_backup(tmp_path):
    result, calls = run_mock(tmp_path, "rollback_failed")
    assert result.returncode != 0
    assert not any(c.startswith("resume") for c in calls)
    assert "Rollback failed" in result.stderr
    backups = list(tmp_path.glob(".deploy-ecr.*/compose.env"))
    assert len(backups) == 1 and backups[0].read_bytes() == ENV
    assert not list(tmp_path.glob(".deploy-ecr.*/docker"))


@pytest.mark.parametrize("scenario", ["locked", "login", "pull", "arch", "drain", "wait"])
def test_failure_before_switch_never_restarts_or_resumes(tmp_path, scenario):
    result, calls = run_mock(tmp_path, scenario)
    assert result.returncode != 0
    assert (tmp_path / "compose.env").read_bytes() == ENV
    assert not any(c.startswith(("restart", "resume")) for c in calls)
    assert not (tmp_path / ".previous-image").exists()


@pytest.mark.parametrize("image", [IMAGE, IMAGE + ";touch /tmp/ci1-bad", IMAGE[:-40] + "latest"])
def test_dry_run_and_invalid_input_never_call_cloud(tmp_path, image):
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--dry-run", image, "ap-southeast-2"],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if image == IMAGE else 2)
    if image == IMAGE:
        assert "No AWS/Docker calls" in result.stdout


def test_workflow_gates_pin_actions_and_smoke_before_oidc_and_push():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-backend.yml").read_text())
    job = workflow["jobs"]["deploy"]
    assert job["environment"] == "production"
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert "refs/heads/main" in job["if"] and "BACKEND_DEPLOY_ENABLED" in job["if"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    steps = job["steps"]
    for step in steps:
        if "uses" in step:
            assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", step["uses"])
    smoke = next(i for i, s in enumerate(steps) if "hosted_pipeline_smoke.py" in s.get("run", ""))
    oidc = next(i for i, s in enumerate(steps) if "configure-aws-credentials@" in s.get("uses", ""))
    push = next(i for i, s in enumerate(steps) if "docker push" in s.get("run", ""))
    assert smoke < oidc < push
    assert "secrets." not in json.dumps(workflow)


@pytest.mark.parametrize(
    "status,code,marker,expected",
    [
        ("Success", 0, True, 0),
        ("Success", 1, True, 1),
        ("Success", 0, False, 1),
        ("Failed", 1, False, 1),
        ("TimedOut", -1, False, 1),
        ("Cancelled", -1, False, 1),
    ],
)
def test_ssm_result_requires_success_exit_code_and_exact_health_marker(
    tmp_path, status, code, marker, expected
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-backend.yml").read_text())
    step = next(
        s["run"]
        for s in workflow["jobs"]["deploy"]["steps"]
        if "aws ssm send-command" in s.get("run", "")
    )
    response = dict(
        Status=status,
        ResponseCode=code,
        StandardOutputContent=(
            f"DEPLOYED image={IMAGE} api=healthy worker=healthy ready=ok resumed=true\n"
            if marker
            else ""
        ),
    )
    (tmp_path / "result.json").write_text(json.dumps(response))
    harness = (
        r"""
aws() {
  if [[ $* == *send-command* ]]; then echo 12345678-1234-1234-1234-123456789012
  else cat "$RUNNER_TEMP/result.json"; fi
}
"""
        + step
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        env={
            **os.environ,
            "DEPLOY_IMAGE": IMAGE,
            "REGION": "ap-southeast-2",
            "INSTANCE_ID": "i-01fec46ef85815a17",
            "GITHUB_SHA": "a" * 40,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (expected == 0), result.stderr


def test_uncertain_resume_and_failed_redrain_never_restart_active_release(tmp_path):
    result, calls = run_mock(tmp_path, "resume_redrain")
    assert result.returncode != 0
    assert "Cannot re-drain" in result.stderr
    assert sum(c.startswith("restart") for c in calls) == 1
    assert "resume old" not in calls
    assert list(tmp_path.glob(".deploy-ecr.*/compose.env"))
    assert (tmp_path / "compose.env").read_bytes() == ENV.replace(OLD.encode(), IMAGE.encode())


def test_ambiguous_apply_and_dry_run_flags_are_rejected():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--apply", "--dry-run", IMAGE, "ap-southeast-2"],
        capture_output=True,
    )
    assert result.returncode == 2


def test_admin_iam_documents_are_valid_json_and_exactly_scoped():
    text = (ROOT / "deploy/ec2/admin-setup.md").read_text()
    trust, deploy, instance = [
        json.loads(s) for s in re.findall(r"```json\n(.*?)\n```", text, re.S)
    ]
    conditions = trust["Statement"][0]["Condition"]["StringEquals"]
    assert conditions["token.actions.githubusercontent.com:sub"] == (
        "repo:tskwak111/esg-proofops:environment:production"
    )
    assert conditions["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    for policy in [deploy, instance]:
        for statement in policy["Statement"]:
            if statement["Resource"] == "*":
                assert statement["Action"] in {
                    "ecr:GetAuthorizationToken",
                    "ssm:GetCommandInvocation",
                }
    command = next(s for s in deploy["Statement"] if s["Action"] == "ssm:SendCommand")
    assert command["Resource"] == [
        "arn:aws:ec2:ap-southeast-2:000000000000:instance/i-01fec46ef85815a17",
        "arn:aws:ssm:ap-southeast-2::document/AWS-RunShellScript",
    ]


@pytest.mark.parametrize("denied", [False, True])
def test_ssm_polling_retries_eventual_consistency_but_not_access_denied(tmp_path, denied):
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-backend.yml").read_text())
    step = next(
        s["run"]
        for s in workflow["jobs"]["deploy"]["steps"]
        if "aws ssm send-command" in s.get("run", "")
    )
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "Status": "Success",
                "ResponseCode": 0,
                "StandardOutputContent": (
                    f"DEPLOYED image={IMAGE} api=healthy worker=healthy ready=ok resumed=true\n"
                ),
            }
        )
    )
    harness = (
        r"""
sleep() { :; }
aws() {
  if [[ $* == *send-command* ]]; then
    echo send >> "$RUNNER_TEMP/send-count"
    echo 12345678-1234-1234-1234-123456789012
    return
  fi
  n=$(cat "$RUNNER_TEMP/count" 2>/dev/null || echo 0)
  echo $((n+1)) > "$RUNNER_TEMP/count"
  if [[ $DENIED == true ]]; then echo AccessDeniedException >&2; return 1; fi
  case $n in
    0) echo InvocationDoesNotExist >&2; return 1;;
    1) echo '{"Status":"Pending"}';;
    2) echo '{"Status":"InProgress"}';;
    *) cat "$RUNNER_TEMP/result.json";;
  esac
}
"""
        + step
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        env={
            **os.environ,
            "DEPLOY_IMAGE": IMAGE,
            "REGION": "ap-southeast-2",
            "INSTANCE_ID": "i-01fec46ef85815a17",
            "GITHUB_SHA": "a" * 40,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "DENIED": str(denied).lower(),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode != 0) is denied, result.stderr
    assert (tmp_path / "count").read_text().strip() == ("1" if denied else "4")
    assert (tmp_path / "send-count").read_text() == "send\n"
