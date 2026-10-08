"""Offline deployment contract tests. AWS/SSH/scp are replaced with local executables."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOCK = "#!/usr/bin/env python3\n" + (HERE / "fixtures/aws_mock.py").read_text()


class Kit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        (self.root / "bin/aws").write_text(MOCK)
        (self.root / "bin/aws").chmod(0o755)
        for name in ("ssh", "scp"):
            (self.root / f"bin/{name}").write_text("#!/bin/sh\nexit 97\n")
            (self.root / f"bin/{name}").chmod(0o755)
        self.resources = self.root / "resources.json"
        self.resources.write_text(
            json.dumps(dict(instances=[], ips=[], keys=[], snapshots=[], auto=[]))
        )
        pub = self.root / "ssh.pub"
        pub.write_text("ssh-rsa TEST_ONLY_NOT_A_REAL_KEY\n")
        self.env = os.environ | dict(
            PATH=str(self.root / "bin") + ":" + os.environ["PATH"],
            MOCK_ROOT=str(self.root),
            STATE_DIR=str(self.root / "state"),
            ACCOUNT_ID="123456789012",
            VCPU_QUOTA="20",
            STATIC_IP_QUOTA="5",
            SSH_PUBLIC_KEY=str(pub),
            SSH_CIDR="203.0.113.7/32",
            ALERT_EMAIL="operator@example.invalid",
            CONFIRM_DELETE="proofops-r108",
            LEDGER_ARCHIVED="true",
        )

    def run_script(self, script, *args, expected=0, env=None):
        r = subprocess.run(
            [str(HERE / script), *args], env=env or self.env, capture_output=True, text=True
        )
        if expected == 0:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0)
        return r

    def calls(self):
        p = self.root / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_all_remote_commands_default_to_no_calls(self):
        for script in (
            "preflight.sh",
            "create.sh",
            "deploy.sh",
            "keys.sh",
            "budget.sh",
            "cost.sh",
            "smoke.sh",
            "teardown.sh",
        ):
            with self.subTest(script=script):
                self.assertIn("DRY RUN", self.run_script(script).stdout)
        self.assertEqual(self.calls(), [])

    def test_provision_budget_teardown_exact_resources_and_rerun(self):
        self.run_script("create.sh", "--apply")
        self.run_script("budget.sh", "--apply")
        state = json.loads(self.resources.read_text())
        state["snapshots"] = [
            dict(name="owned-copy", fromInstanceName="proofops-r108"),
            dict(name="other-copy", fromInstanceName="other-instance"),
        ]
        state["instances"][0]["addOns"] = [dict(name="AutoSnapshot", status="Enabled")]
        state["auto"] = [dict(date="2026-10-09")]
        self.resources.write_text(json.dumps(state))
        self.run_script("teardown.sh", "--apply")
        final = json.loads(self.resources.read_text())
        self.assertEqual(
            final,
            dict(
                instances=[],
                ips=[],
                keys=[],
                snapshots=[dict(name="other-copy", fromInstanceName="other-instance")],
                auto=[],
            ),
        )
        self.run_script("teardown.sh", "--apply")
        delete_snapshots = [c for c in self.calls() if c[1] == "delete-instance-snapshot"]
        self.assertEqual(len(delete_snapshots), 1)
        self.assertIn("owned-copy", delete_snapshots[0][2])

    def test_wrong_account_and_quota_fail_before_create(self):
        for changes in (
            dict(MOCK_ACCOUNT="999999999999"),
            dict(VCPU_QUOTA="1"),
            dict(STATIC_IP_QUOTA="0"),
            dict(MAX_MONTHLY_USD="23"),
            dict(ARCH="arm64"),
        ):
            with self.subTest(changes=changes):
                self.run_script("create.sh", "--apply", expected=1, env=self.env | changes)
        self.assertFalse(any(c[1] == "create-instances" for c in self.calls()))

    def test_recreate_or_broad_ssh_is_refused(self):
        self.run_script(
            "create.sh", "--apply", expected=1, env=self.env | dict(SSH_CIDR="0.0.0.0/0")
        )
        self.run_script("create.sh", "--apply")
        self.run_script("create.sh", "--apply", expected=1)
        self.assertEqual(sum(c[1] == "create-instances" for c in self.calls()), 1)

    def test_foreign_ip_or_resource_tag_blocks_deletion(self):
        self.run_script("create.sh", "--apply")
        for foreign in ("ip", "tag"):
            state = json.loads(self.resources.read_text())
            state["ips"][0]["attachedTo"] = "other" if foreign == "ip" else "proofops-r108"
            state["instances"][0]["tags"][0]["value"] = (
                "other" if foreign == "tag" else "proofops-r108"
            )
            self.resources.write_text(json.dumps(state))
            self.run_script("teardown.sh", "--apply", expected=1)
        self.assertFalse(
            any(c[1].startswith("delete-") or c[1] == "release-static-ip" for c in self.calls())
        )

    def test_private_config_guard_and_local_web_patch(self):
        runtime = self.root / "runtime.env"
        r = subprocess.run(
            [
                "python3",
                str(HERE / "init-runtime.py"),
                "--origin",
                "https://production.example",
                "--output",
                str(runtime),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        secret = next(
            line.split("=", 1)[1]
            for line in runtime.read_text().splitlines()
            if line.startswith("HOSTED_SESSION_SECRET=")
        )
        self.assertNotIn(secret, r.stdout + r.stderr)

        def check():
            return subprocess.run(
                ["python3", str(HERE / "check-config.py"), str(runtime)], capture_output=True
            )

        self.assertEqual(check().returncode, 0)
        runtime.chmod(0o644)
        self.assertNotEqual(check().returncode, 0)
        runtime.chmod(0o600)
        runtime.write_text(runtime.read_text().replace("LIVE_DISABLED=true", "LIVE_DISABLED=false"))
        self.assertNotEqual(check().returncode, 0)
        web = self.root / "web"
        web.mkdir()
        config = dict(
            rewrites=[
                dict(source="/hosted-api/:path*", destination="https://placeholder.invalid/:path*"),
                dict(source="/(.*)", destination="/index.html"),
            ]
        )
        target = web / "vercel.json"
        target.write_text(json.dumps(config))
        command = [
            "python3",
            str(HERE / "configure-web.py"),
            "--checkout",
            str(web),
            "--static-ip",
            "8.8.8.8",
        ]
        subprocess.run(command, check=True, capture_output=True)
        self.assertEqual(json.loads(target.read_text()), config)
        subprocess.run(command + ["--apply"], check=True, capture_output=True)
        updated = json.loads(target.read_text())
        self.assertEqual(updated["rewrites"][0]["destination"], "https://8.8.8.8.sslip.io/:path*")
        self.assertEqual(updated["rewrites"][1], config["rewrites"][1])
        self.assertEqual(json.loads((web / "vercel.json.p3-backup").read_text()), config)

    def test_iam_actions_cover_recorded_aws_operations(self):
        self.run_script("create.sh", "--apply")
        self.run_script("budget.sh", "--apply")
        self.run_script("teardown.sh", "--apply")
        policy = json.loads((HERE / "iam-policy.json").read_text())
        allowed = {a for s in policy["Statement"] for a in s["Action"]}
        for service, operation, _ in self.calls():
            if service == "sts":
                continue  # GetCallerIdentity doesn't require explicit Allow.
            action = (
                "budgets:ModifyBudget"
                if service == "budgets"
                else service + ":" + "".join(v.capitalize() for v in operation.split("-"))
            )
            self.assertIn(action, allowed)
        self.assertFalse(any(a.endswith(":*") for a in allowed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
