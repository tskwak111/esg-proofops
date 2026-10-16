"""Offline EC2 CLI contract: no real AWS, SSH, HTTP or Docker commands."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCOUNT = "000000000000"


class Kit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        mock = "#!/usr/bin/env python3\n" + (HERE / "fixtures/aws_mock.py").read_text()
        p = self.root / "bin/aws"
        p.write_text(mock)
        p.chmod(0o755)
        for name in ("ssh", "scp", "docker", "curl"):
            p = self.root / "bin" / name
            p.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$0" >> "$MOCK_ROOT/remote-calls.txt"\nexit 97\n'
            )
            p.chmod(0o755)
        self.resources = self.root / "resources.json"
        self.resources.write_text(
            json.dumps(dict(instances=[], addresses=[], groups=[], keys=[], volumes=[]))
        )
        pub = self.root / "ssh.pub"
        pub.write_text(
            "ssh-ed25519 "
            "AAAAC3NzaC1lZDI1NTE5AAAAICBgdHJhY2tlZDAtb2ZmbGluZS10ZXN0LWZpeHR1cmU= offline\n"
        )
        self.env = os.environ | dict(
            PATH=str(self.root / "bin") + ":" + os.environ["PATH"],
            MOCK_ROOT=str(self.root),
            STATE_DIR=str(self.root / "state"),
            ACCOUNT_ID=ACCOUNT,
            REGION="ap-southeast-2",
            PROFILE="proofops-deploy",
            NAME="proofops-r108",
            IMAGE="proofops-r108-public:ec1-arm64",
            ALERT_EMAIL="operator@example.invalid",
            ARCH="arm64",
            SSH_PUBLIC_KEY=str(pub),
            SSH_CIDR="203.0.113.7/32",
            CONFIRM_DELETE="proofops-r108",
            LEDGER_ARCHIVED="true",
        )

    def run_script(self, name, *args, changes=None, ok=True):
        r = subprocess.run(
            [str(HERE / name), *args],
            env=self.env | (changes or {}),
            text=True,
            capture_output=True,
        )
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def calls(self):
        p = self.root / "calls.jsonl"
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []

    def data(self):
        return json.loads(self.resources.read_text())

    def write_data(self, d):
        self.resources.write_text(json.dumps(d))

    def test_every_script_defaults_to_zero_remote_calls(self):
        for script in (
            "preflight.sh",
            "create.sh",
            "deploy.sh",
            "keys.sh",
            "smoke.sh",
            "budget.sh",
            "cost.sh",
            "teardown.sh",
            "pack.sh",
        ):
            with self.subTest(script=script):
                self.assertIn("DRY RUN", self.run_script(script).stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / "remote-calls.txt").exists())

    def test_create_and_teardown_are_exact_and_rerunnable(self):
        self.run_script("create.sh", "--apply")
        state = json.loads((self.root / "state/owned.json").read_text())
        self.assertEqual(state["status"], "created")
        selection = json.loads((self.root / "state/selection.json").read_text())
        self.assertEqual(selection["az"], "ap-southeast-2a")
        self.run_script("create.sh", "--apply", ok=False)
        self.assertEqual(sum(c[1] == "run-instances" for c in self.calls()), 1)
        d = self.data()
        d["groups"].append(dict(GroupId="sg-foreign", GroupName="foreign", Tags=[]))
        self.write_data(d)
        self.run_script("teardown.sh", "--apply")
        self.run_script("teardown.sh", "--apply")
        self.assertEqual(self.data()["groups"][0]["GroupId"], "sg-foreign")
        self.assertEqual(self.data()["addresses"], [])
        self.assertEqual(self.data()["keys"], [])
        self.assertEqual(self.data()["volumes"], [])

    def test_preflight_guards_before_any_mutation(self):
        for change in (
            {"MOCK_ACCOUNT": "999999999999"},
            {"MOCK_NO_VPC": "1"},
            {"MOCK_NO_AZ": "1"},
            {"MOCK_BAD_IMAGE": "1"},
            {"MOCK_NO_ROUTE": "1"},
            {"MOCK_QUOTA": "1"},
            {"MOCK_USED_VCPU": "2", "MOCK_QUOTA": "2"},
            {"SSH_CIDR": "0.0.0.0/0"},
            {"ARCH": "amd64"},
            {"REGION": "ap-northeast-2"},
        ):
            with self.subTest(change=change):
                self.run_script("create.sh", "--apply", changes=change, ok=False)
        self.assertFalse(
            any(
                c[1]
                in ("import-key-pair", "create-security-group", "run-instances", "allocate-address")
                for c in self.calls()
            )
        )

    def test_collision_for_each_named_resource(self):
        for kind, item in [
            (
                "instances",
                dict(
                    InstanceId="i-foreign",
                    State={"Name": "running"},
                    Tags=[{"Key": "Name", "Value": "proofops-r108"}],
                ),
            ),
            (
                "addresses",
                dict(
                    AllocationId="eipalloc-foreign",
                    Tags=[{"Key": "Name", "Value": "proofops-r108"}],
                ),
            ),
            ("keys", dict(KeyPairId="key-foreign", KeyName="proofops-r108")),
            ("groups", dict(GroupId="sg-foreign", GroupName="proofops-r108")),
        ]:
            d = dict(instances=[], addresses=[], groups=[], keys=[], volumes=[])
            d[kind].append(item)
            self.write_data(d)
            self.run_script("create.sh", "--apply", ok=False)
        self.assertFalse(any(c[1] == "import-key-pair" for c in self.calls()))

    def test_quota_permission_failure_requires_operator_confirmation(self):
        self.run_script("preflight.sh", "--apply", changes={"MOCK_QUOTA_DENIED": "1"}, ok=False)
        self.run_script(
            "preflight.sh", "--apply", changes={"MOCK_QUOTA_DENIED": "1", "VCPU_QUOTA": "8"}
        )
        s = json.loads((self.root / "state/selection.json").read_text())
        self.assertEqual(s["quota_source"], "operator-confirmed")

    def test_foreign_tags_or_eip_attachment_block_all_deletes(self):
        self.run_script("create.sh", "--apply")
        clean = self.data()
        for kind in ("instances", "addresses", "groups", "keys"):
            d = json.loads(json.dumps(clean))
            d[kind][0]["Tags"][0]["Value"] = "foreign"
            self.write_data(d)
            self.run_script("teardown.sh", "--apply", ok=False)
        d = json.loads(json.dumps(clean))
        d["addresses"][0]["InstanceId"] = "i-foreign"
        self.write_data(d)
        self.run_script("teardown.sh", "--apply", ok=False)
        self.assertFalse(
            any(
                c[1]
                in (
                    "terminate-instances",
                    "release-address",
                    "delete-security-group",
                    "delete-key-pair",
                    "disassociate-address",
                )
                for c in self.calls()
            )
        )

    def test_partial_create_failure_is_recorded_and_never_recreated(self):
        self.run_script("create.sh", "--apply", changes={"MOCK_FAIL": "allocate-address"}, ok=False)
        owned = json.loads((self.root / "state/owned.json").read_text())
        self.assertEqual(owned["status"], "creating")
        self.assertIn("instance_id", owned)
        self.run_script("create.sh", "--apply", ok=False)
        self.run_script("teardown.sh", "--apply")

    def test_runtime_check_reuses_private_guard_and_arm64_contract(self):
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
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(
            ["python3", str(HERE / "check-config.py"), str(runtime)], capture_output=True
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        runtime.chmod(0o644)
        r = subprocess.run(
            ["python3", str(HERE / "check-config.py"), str(runtime)], capture_output=True
        )
        self.assertNotEqual(r.returncode, 0)
        self.run_script("pack.sh", "--arch", "amd64", ok=False)

    def test_local_iam_schema_and_recorded_operations(self):
        self.run_script("create.sh", "--apply")
        cost = self.run_script("cost.sh", "--apply")
        self.assertIn("USD13.55513", cost.stdout)
        self.assertIn("USD20/month pauses at limit", cost.stdout)
        self.assertIn("separate external-provider", cost.stdout)
        self.run_script("budget.sh", "--apply")
        self.run_script("teardown.sh", "--apply")
        r = subprocess.run(["python3", str(HERE / "check-config.py"), "--kit"], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = json.loads((HERE / "iam-policy.json").read_text())
        allowed = {a for s in p["Statement"] for a in s["Action"]}
        for service, op, args in self.calls():
            if service == "sts" or op == "wait":
                continue
            action = service + ":" + "".join(t[0].upper() + t[1:] for t in op.split("-"))
            if service == "budgets":
                action = "budgets:ModifyBudget" if op == "create-budget" else "budgets:ViewBudget"
            if service == "service-quotas":
                action = "servicequotas:GetServiceQuota"
            self.assertIn(action, allowed)
        self.assertFalse(
            any(a.startswith(("lightsail:", "iam:", "sts:")) or "*" in a for a in allowed)
        )

    def test_foreign_storage_and_delete_confirmation_are_guarded(self):
        self.run_script("create.sh", "--apply")
        clean = self.data()
        for changes in ({"CONFIRM_DELETE": "other"}, {"LEDGER_ARCHIVED": "false"}):
            self.run_script("teardown.sh", "--apply", changes=changes, ok=False)
        d = json.loads(json.dumps(clean))
        d["volumes"][0]["Tags"][0]["Value"] = "foreign"
        self.write_data(d)
        self.run_script("teardown.sh", "--apply", ok=False)
        self.write_data(clean)
        d = json.loads(json.dumps(clean))
        d["instances"][0]["BlockDeviceMappings"].append(
            {"Ebs": {"VolumeId": "vol-aaaaaaaaaaaaaaaaa", "DeleteOnTermination": True}}
        )
        self.write_data(d)
        self.run_script("teardown.sh", "--apply", ok=False)
        self.assertFalse(any(c[1] == "terminate-instances" for c in self.calls()))

    def test_ssh_target_and_wrong_server_cpu_prevent_transfer(self):
        self.run_script("create.sh", "--apply")
        runtime = self.root / "runtime.env"
        subprocess.run(
            [
                "python3",
                str(HERE / "init-runtime.py"),
                "--origin",
                "https://production.example",
                "--output",
                str(runtime),
            ],
            check=True,
            capture_output=True,
        )
        archive = self.root / "image.tar"
        archive.write_bytes(b"offline fake image")
        import hashlib

        Path(str(archive) + ".json").write_text(
            json.dumps(
                dict(
                    image=self.env["IMAGE"],
                    arch="arm64",
                    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                )
            )
        )
        key = self.root / "ssh.key"
        key.write_text("not a real private key")
        ssh = self.root / "bin/ssh"
        ssh.write_text('#!/bin/sh\ncase "$*" in *"uname -m"*) echo x86_64;; esac\n')
        ssh.chmod(0o755)
        inputs = dict(
            STATIC_IP="203.0.113.10",
            SSH_KEY=str(key),
            IMAGE_ARCHIVE=str(archive),
            RUNTIME_ENV=str(runtime),
            ACME_EMAIL="operator@example.invalid",
        )
        r = self.run_script("deploy.sh", "--apply", changes=inputs, ok=False)
        self.assertIn("CPU mismatch", r.stderr)
        r = self.run_script("keys.sh", "--apply", changes=inputs, ok=False)
        self.assertIn("aarch64", r.stderr)
        r = self.run_script(
            "deploy.sh", "--apply", changes=inputs | {"STATIC_IP": "203.0.113.11"}, ok=False
        )
        self.assertIn("owned Elastic IP", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
