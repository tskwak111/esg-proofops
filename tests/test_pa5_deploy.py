"""Exercise the remote restart gate with commands replaced, never SSH/cloud."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "deploy/public/drain-restart.sh"


@pytest.mark.parametrize(
    "force,wait_rc,drain_rc,expected,restart",
    [
        ("false", 0, 0, 0, True),
        ("false", 3, 0, 3, False),
        ("true", 3, 0, 0, True),
        ("true", 2, 0, 2, False),
        ("true", 0, 1, 1, False),
    ],
)
def test_restart_requires_idle_or_explicit_timeout_override(
    force, wait_rc, drain_rc, expected, restart
):
    code = """set -euo pipefail
source "$1"
WAIT_RC=$3 DRAIN_RC=$4
hosted_control() {
  printf '%s\\n' "$*"
  case "$1" in drain) return "$DRAIN_RC";; wait-idle) return "$WAIT_RC";; esac
}
drain_and_wait "$2" 0
printf 'restart\\n'
hosted_control resume
"""
    result = subprocess.run(
        ["bash", "-c", code, "pa5-test", str(HELPER), force, str(wait_rc), str(drain_rc)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stderr
    calls = result.stdout.splitlines()
    assert calls[0] == "drain"
    assert ("restart" in calls) is restart
    assert ("resume" in calls) is restart
    if drain_rc == 0:
        assert calls[:2] == ["drain", "wait-idle --timeout 0"]


@pytest.mark.parametrize("provider", ["ec2", "lightsail"])
def test_deploy_dry_run_has_no_cloud_calls_and_validates_restart_options(provider, tmp_path):
    script = ROOT / "deploy" / provider / "deploy.sh"
    for args in ([], ["--force-restart", "--drain-timeout", "0"]):
        result = subprocess.run(
            ["bash", str(script), *args],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "STATE_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        assert "drain" in result.stdout and "wait-idle" in result.stdout
    bad = subprocess.run(["bash", str(script), "--drain-timeout", "-1"], capture_output=True)
    assert bad.returncode == 2
    assert "drain-restart.sh" in script.read_text()


@pytest.mark.parametrize(
    "health,restart_rc,ready_rc,expected,resumed",
    [
        ("healthy", 0, 0, 0, True),
        ("unhealthy", 0, 0, 1, False),
        ("healthy", 9, 0, 9, False),
        ("healthy", 0, 7, 7, False),
    ],
)
def test_remote_restart_orders_gate_and_resumes_only_healthy_release(
    tmp_path, health, restart_rc, ready_rc, expected, resumed
):
    (tmp_path / "stage").mkdir()
    (tmp_path / "compose.yaml").touch()
    (tmp_path / "compose.env").touch()
    log = tmp_path / "commands.log"
    code = """set -euo pipefail
source "$1"
TEST_DIR=$2 COMMAND_LOG=$3 HEALTH=$4 RESTART_RC=$5 READY_RC=$6
cd() { builtin cd "$TEST_DIR"; }
flock() { return 0; }
sleep() { return 0; }
hosted_control() { printf 'control %s\\n' "$*" >> "$COMMAND_LOG"; }
sudo() {
  printf '%s\\n' "$*" >> "$COMMAND_LOG"
  case "$*" in
    *'ps -q api') printf 'api-id\\n';;
    'docker inspect'*) printf '%s\\n' "$HEALTH";;
    'systemctl restart proofops.service') return "$RESTART_RC";;
    *'/v1/health/ready'*) return "$READY_RC";;
  esac
}
deploy_release "$TEST_DIR/stage" false 0
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            code,
            "pa5-test",
            str(HELPER),
            str(tmp_path),
            str(log),
            health,
            str(restart_rc),
            str(ready_rc),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stderr
    calls = log.read_text().splitlines()
    assert calls.index("control drain") < calls.index("control wait-idle --timeout 0")
    assert calls.index("control wait-idle --timeout 0") < next(
        i for i, c in enumerate(calls) if c.startswith("install ")
    )
    init = next(
        i
        for i, c in enumerate(calls)
        if "run --rm --no-deps api python scripts/hosted_control.py drain" in c
    )
    assert init < calls.index("systemctl restart proofops.service")
    assert ("control resume" in calls) is resumed
