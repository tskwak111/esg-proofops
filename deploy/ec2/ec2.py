"""EC2 CLI orchestration. Only --apply invokes AWS; credentials never enter output."""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = "proofops-r108"
REGION = "ap-northeast-2"
ACCOUNT = "753036488189"
AMI_PARAMETER = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
QUOTA = "L-1216C47A"


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def save(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def tag_value(resource, key):
    return next((t["Value"] for t in resource.get("Tags", []) if t["Key"] == key), None)


class EC2:
    def __init__(self, apply):
        self.apply = apply
        self.name = os.environ.get("NAME", PROJECT)
        self.state = Path(os.environ.get("STATE_DIR", str(HERE / ".state")))
        require(os.environ.get("REGION", REGION) == REGION, "Only Seoul is authorized.")
        require(
            os.environ.get("ACCOUNT_ID", ACCOUNT) == ACCOUNT, "Only the EC1 account is authorized."
        )
        require(os.environ.get("ARCH", "arm64") == "arm64", "EC2 requires linux/arm64.")
        require(re.fullmatch(r"proofops-r108[-a-zA-Z0-9]*", self.name), "Invalid resource name.")
        self.aws = [
            "aws",
            "--profile",
            os.environ.get("PROFILE", "proofops-deploy"),
            "--region",
            REGION,
            "--no-cli-pager",
        ]

    def call(self, service, operation, *args, optional_quota=False):
        require(self.apply, "Internal guard: AWS call without --apply.")
        r = subprocess.run(
            self.aws + [service, operation, *map(str, args)], capture_output=True, text=True
        )
        if r.returncode:
            # Do not echo command arguments or CLI stderr: either can contain private data.
            if optional_quota and ("AccessDenied" in r.stderr or "Unauthorized" in r.stderr):
                return None
            raise SystemExit(
                f"{service} {operation} failed (exit {r.returncode}); inspect private "
                "AWS audit/state, do not recreate."
            )
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def preview(self, service, operation, *args):
        print("DRY RUN: " + shlex.join(self.aws + [service, operation, *map(str, args)]))

    def tags(self, *kinds):
        return json.dumps(
            [
                dict(
                    ResourceType=k,
                    Tags=[dict(Key="Project", Value=PROJECT), dict(Key="Name", Value=self.name)],
                )
                for k in kinds
            ]
        )

    def identity(self):
        require(
            self.call("sts", "get-caller-identity")["Account"] == ACCOUNT,
            "Wrong AWS account; stopped.",
        )

    def inventory(self):
        instances = self.call("ec2", "describe-instances")
        return dict(
            instances=[i for r in instances["Reservations"] for i in r["Instances"]],
            addresses=self.call("ec2", "describe-addresses")["Addresses"],
            groups=self.call("ec2", "describe-security-groups")["SecurityGroups"],
            keys=self.call("ec2", "describe-key-pairs")["KeyPairs"],
        )

    def preflight(self):
        if not self.apply:
            for op, args in [
                ("describe-regions", ["--region-names", REGION]),
                ("describe-availability-zones", []),
                (
                    "describe-instance-type-offerings",
                    [
                        "--location-type",
                        "availability-zone",
                        "--filters",
                        "Name=instance-type,Values=t4g.medium",
                    ],
                ),
                ("describe-instance-types", ["--instance-types", "t4g.medium"]),
                ("describe-images", ["--image-ids", "<SSM-arm64-AMI>"]),
                ("describe-vpcs", ["--filters", "Name=is-default,Values=true"]),
                ("describe-subnets", []),
                ("describe-route-tables", []),
                ("describe-instances", []),
                ("describe-addresses", []),
                ("describe-security-groups", []),
                ("describe-key-pairs", []),
            ]:
                self.preview("ec2", op, *args)
            self.preview("sts", "get-caller-identity")
            self.preview("ssm", "get-parameter", "--name", AMI_PARAMETER)
            self.preview(
                "service-quotas",
                "get-service-quota",
                "--service-code",
                "ec2",
                "--quota-code",
                QUOTA,
            )
            print(
                "DRY RUN: verify account, Canonical Ubuntu24.04 arm64, t4g AZ/default "
                "public subnet, named collisions and available Standard vCPU quota. No AWS calls."
            )
            return
        self.identity()
        require(
            any(
                r["RegionName"] == REGION
                for r in self.call("ec2", "describe-regions", "--region-names", REGION)["Regions"]
            ),
            "Seoul unavailable.",
        )
        zones = {
            z["ZoneName"]
            for z in self.call("ec2", "describe-availability-zones")["AvailabilityZones"]
            if z["State"] == "available" and z.get("ZoneType") == "availability-zone"
        }
        offered = {
            o["Location"]
            for o in self.call(
                "ec2",
                "describe-instance-type-offerings",
                "--location-type",
                "availability-zone",
                "--filters",
                "Name=instance-type,Values=t4g.medium",
            )["InstanceTypeOfferings"]
        }
        ami = self.call("ssm", "get-parameter", "--name", AMI_PARAMETER)["Parameter"]["Value"]
        require(re.fullmatch(r"ami-[0-9a-f]{8,17}", ami), "Invalid AMI from SSM.")
        images = self.call("ec2", "describe-images", "--image-ids", ami)["Images"]
        require(len(images) == 1, "AMI unavailable.")
        image = images[0]
        require(
            image["OwnerId"] == "099720109477"
            and image["Architecture"] == "arm64"
            and image["State"] == "available"
            and image["RootDeviceType"] == "ebs"
            and image["VirtualizationType"] == "hvm"
            and image["Name"].startswith(
                "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-"
            ),
            "AMI must be Canonical Ubuntu24.04 LTS arm64 server.",
        )
        vpcs = self.call("ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true")["Vpcs"]
        require(
            len(vpcs) == 1 and vpcs[0]["IsDefault"] and vpcs[0]["State"] == "available",
            "No available default VPC; stop and report, never create a VPC.",
        )
        vpc = vpcs[0]["VpcId"]
        subnets = self.call(
            "ec2",
            "describe-subnets",
            "--filters",
            f"Name=vpc-id,Values={vpc}",
            "Name=default-for-az,Values=true",
        )["Subnets"]
        routes = self.call(
            "ec2", "describe-route-tables", "--filters", f"Name=vpc-id,Values={vpc}"
        )["RouteTables"]
        candidates = []
        for s in subnets:
            if (
                s["VpcId"] != vpc
                or s["AvailabilityZone"] not in zones & offered
                or not s.get("DefaultForAz")
                or s["State"] != "available"
                or s.get("Ipv6Native")
                or s.get("AssignIpv6AddressOnCreation")
                or s["AvailableIpAddressCount"] < 1
            ):
                continue
            associated = [
                r
                for r in routes
                if any(a.get("SubnetId") == s["SubnetId"] for a in r["Associations"])
            ]
            effective = associated or [
                r for r in routes if any(a.get("Main") for a in r["Associations"])
            ]
            if len(effective) == 1 and any(
                r.get("DestinationCidrBlock") == "0.0.0.0/0"
                and r.get("GatewayId", "").startswith("igw-")
                and r.get("State") == "active"
                for r in effective[0]["Routes"]
            ):
                candidates.append(s)
        require(candidates, "No default IPv4 public subnet in an available t4g.medium AZ; stop.")
        preferred = os.environ.get("AZ")
        candidates = [s for s in candidates if not preferred or s["AvailabilityZone"] == preferred]
        require(candidates, "Requested AZ is not eligible.")
        subnet = sorted(candidates, key=lambda s: s["AvailabilityZone"])[0]
        inv = self.inventory()
        require(
            not any(
                tag_value(i, "Name") == self.name and i["State"]["Name"] != "terminated"
                for i in inv["instances"]
            ),
            "Instance name collision; use deploy or explicit teardown.",
        )
        require(
            not any(tag_value(a, "Name") == self.name for a in inv["addresses"]),
            "EIP name collision.",
        )
        require(not any(k["KeyName"] == self.name for k in inv["keys"]), "Key name collision.")
        require(
            not any(g["GroupName"] == self.name for g in inv["groups"]),
            "Security-group name collision.",
        )
        running = [
            i
            for i in inv["instances"]
            if i["State"]["Name"] in ("pending", "running")
            and i.get("InstanceLifecycle") != "spot"
            and re.match(
                r"^(a\d|c\d|d\d|h\d|hpc|i\d|im\d|is\d|m\d|mac|r\d|t\d|z\d)", i["InstanceType"]
            )
        ]
        types = sorted({"t4g.medium"} | {i["InstanceType"] for i in running})
        specs = self.call("ec2", "describe-instance-types", "--instance-types", *types)[
            "InstanceTypes"
        ]
        bytype = {s["InstanceType"]: s for s in specs}
        require(all(t in bytype for t in types), "Instance-type quota usage unavailable.")
        medium = bytype["t4g.medium"]
        require(
            medium["VCpuInfo"]["DefaultVCpus"] == 2
            and medium["MemoryInfo"]["SizeInMiB"] == 4096
            and "arm64" in medium["ProcessorInfo"]["SupportedArchitectures"],
            "Unexpected t4g.medium specification.",
        )
        used = sum(bytype[i["InstanceType"]]["VCpuInfo"]["DefaultVCpus"] for i in running)
        quota = self.call(
            "service-quotas",
            "get-service-quota",
            "--service-code",
            "ec2",
            "--quota-code",
            QUOTA,
            optional_quota=True,
        )
        quota_source = "service-quotas"
        if quota is None:
            value = os.environ.get("VCPU_QUOTA", "")
            require(
                re.fullmatch(r"[0-9]+", value),
                "Quota read denied: operator must confirm current Seoul Running "
                "On-Demand Standard vCPU quota and set VCPU_QUOTA; not_run until then.",
            )
            limit = int(value)
            quota_source = "operator-confirmed"
        else:
            limit = quota["Quota"]["Value"]
        require(
            used + 2 <= limit,
            "Insufficient Running On-Demand Standard vCPU quota (need two additional vCPUs).",
        )
        selection = dict(
            account=ACCOUNT,
            region=REGION,
            name=self.name,
            ami=ami,
            ami_parameter=AMI_PARAMETER,
            root_device=image["RootDeviceName"],
            vpc_id=vpc,
            subnet_id=subnet["SubnetId"],
            az=subnet["AvailabilityZone"],
            used_standard_vcpus=used,
            vcpu_quota=limit,
            quota_source=quota_source,
        )
        save(self.state / "selection.json", selection)
        print(
            "Preflight: verified EC1 account/Seoul, Canonical arm64 AMI, available "
            "AZ/default VPC/public subnet, no collisions, vCPU headroom. "
            "EIP capacity is checked by allocation; failures remain recorded."
        )
        return selection

    def create(self):
        if not self.apply:
            self.preflight()
            self.preview(
                "ec2",
                "import-key-pair",
                "--key-name",
                self.name,
                "--public-key-material",
                "fileb://<ed25519-or-RSA-public-key>",
                "--tag-specifications",
                self.tags("key-pair"),
            )
            self.preview(
                "ec2",
                "create-security-group",
                "--group-name",
                self.name,
                "--vpc-id",
                "<default-VPC>",
                "--description",
                "ProofOps R108",
                "--tag-specifications",
                self.tags("security-group"),
            )
            self.preview(
                "ec2",
                "authorize-security-group-ingress",
                "--group-id",
                "<owned-SG>",
                "--ip-permissions",
                "file://<22-operator-IPv4-/32+80+443-IPv4.json>",
            )
            self.preview(
                "ec2",
                "run-instances",
                "--image-id",
                "<verified-Ubuntu-arm64-AMI>",
                "--instance-type",
                "t4g.medium",
                "--count",
                "1",
                "--credit-specification",
                "CpuCredits=standard",
                "--metadata-options",
                "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1",
                "--no-disable-api-termination",
                "--network-interfaces",
                "file://<owned-SG-default-subnet-no-public-IP-no-IPv6.json>",
                "--block-device-mappings",
                "file://<encrypted-gp3-30GiB-delete-on-termination.json>",
                "--key-name",
                self.name,
                "--user-data",
                f"file://{HERE}/cloud-init.sh",
                "--tag-specifications",
                self.tags("instance", "volume", "network-interface"),
            )
            self.preview(
                "ec2",
                "allocate-address",
                "--domain",
                "vpc",
                "--tag-specifications",
                self.tags("elastic-ip"),
            )
            self.preview(
                "ec2",
                "associate-address",
                "--allocation-id",
                "<owned-EIP>",
                "--instance-id",
                "<owned-instance>",
                "--no-allow-reassociation",
            )
            print(
                "DRY RUN: record every successful resource ID in private .state; stop "
                "on partial/uncertain failures, never recreate automatically."
            )
            return
        require(
            not (self.state / "owned.json").exists(),
            "Existing creation journal; no automatic recreation. Inspect or teardown "
            "with that state.",
        )
        key = Path(os.environ.get("SSH_PUBLIC_KEY", ""))
        require(
            key.is_file() and not key.is_symlink(),
            "SSH_PUBLIC_KEY must be a local regular public-key file.",
        )
        require(
            key.read_text().startswith(("ssh-ed25519 ", "ssh-rsa "))
            and len(key.read_text().splitlines()) == 1,
            "Only ed25519/RSA OpenSSH public keys are accepted.",
        )
        try:
            cidr = ipaddress.ip_network(os.environ.get("SSH_CIDR", ""), strict=True)
        except ValueError:
            raise SystemExit("SSH_CIDR requires operator IPv4 /32.")
        require(
            cidr.version == 4
            and cidr.prefixlen == 32
            and not cidr.network_address.is_unspecified
            and not cidr.network_address.is_multicast,
            "SSH requires operator IPv4 /32.",
        )
        s = self.preflight()
        self.owned = dict(
            account=ACCOUNT,
            region=REGION,
            name=self.name,
            project=PROJECT,
            status="creating",
            vpc_id=s["vpc_id"],
            client_token=str(uuid.uuid4()),
        )
        self.record()
        # An intent precedes every mutation. Ambiguous failure must be inspected, never retried
        # as create.
        self.intent("import-key-pair")
        k = self.call(
            "ec2",
            "import-key-pair",
            "--key-name",
            self.name,
            "--public-key-material",
            f"fileb://{key.resolve()}",
            "--tag-specifications",
            self.tags("key-pair"),
        )
        self.owned.update(key_pair_id=k["KeyPairId"])
        self.record()
        self.intent("create-security-group")
        g = self.call(
            "ec2",
            "create-security-group",
            "--group-name",
            self.name,
            "--description",
            "ProofOps R108 IPv4 only",
            "--vpc-id",
            s["vpc_id"],
            "--tag-specifications",
            self.tags("security-group"),
        )
        self.owned.update(group_id=g["GroupId"])
        self.record()
        rules = [
            dict(
                IpProtocol="tcp",
                FromPort=p,
                ToPort=p,
                IpRanges=[dict(CidrIp=str(cidr) if p == 22 else "0.0.0.0/0")],
            )
            for p in (22, 80, 443)
        ]
        save(self.state / "ingress.json", rules)
        self.intent("authorize-security-group-ingress")
        self.call(
            "ec2",
            "authorize-security-group-ingress",
            "--group-id",
            g["GroupId"],
            "--ip-permissions",
            f"file://{self.state}/ingress.json",
        )
        # Preserve required IPv4 egress (apt, ACME, approved providers); remove any automatic
        # IPv6 egress.
        groups = self.call("ec2", "describe-security-groups")["SecurityGroups"]
        group = next(x for x in groups if x["GroupId"] == g["GroupId"])
        ipv6 = [
            dict(
                IpProtocol=r["IpProtocol"],
                **({k: r[k] for k in ("FromPort", "ToPort") if k in r}),
                Ipv6Ranges=r["Ipv6Ranges"],
            )
            for r in group.get("IpPermissionsEgress", [])
            if r.get("Ipv6Ranges")
        ]
        if ipv6:
            save(self.state / "ipv6-egress.json", ipv6)
            self.call(
                "ec2",
                "revoke-security-group-egress",
                "--group-id",
                g["GroupId"],
                "--ip-permissions",
                f"file://{self.state}/ipv6-egress.json",
            )
        save(
            self.state / "disk.json",
            [
                dict(
                    DeviceName=s["root_device"],
                    Ebs=dict(
                        VolumeType="gp3", VolumeSize=30, Encrypted=True, DeleteOnTermination=True
                    ),
                )
            ],
        )
        save(
            self.state / "network.json",
            [
                dict(
                    DeviceIndex=0,
                    SubnetId=s["subnet_id"],
                    Groups=[g["GroupId"]],
                    AssociatePublicIpAddress=False,
                    Ipv6AddressCount=0,
                    DeleteOnTermination=True,
                )
            ],
        )
        (self.state / "cloud-init.sh").write_text(
            (HERE / "cloud-init.sh").read_text().replace("__SSH_CIDR__", str(cidr))
        )
        self.intent("run-instances")
        r = self.call(
            "ec2",
            "run-instances",
            "--image-id",
            s["ami"],
            "--instance-type",
            "t4g.medium",
            "--count",
            "1",
            "--key-name",
            self.name,
            "--client-token",
            self.owned["client_token"],
            "--credit-specification",
            "CpuCredits=standard",
            "--metadata-options",
            "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1",
            "--no-disable-api-termination",
            "--network-interfaces",
            f"file://{self.state}/network.json",
            "--block-device-mappings",
            f"file://{self.state}/disk.json",
            "--user-data",
            f"file://{self.state}/cloud-init.sh",
            "--tag-specifications",
            self.tags("instance", "volume", "network-interface"),
        )
        require(len(r["Instances"]) == 1, "Unexpected instance response; inspect journal.")
        self.owned.update(
            instance_id=r["Instances"][0]["InstanceId"],
            volume_ids=[
                b["Ebs"]["VolumeId"]
                for b in r["Instances"][0].get("BlockDeviceMappings", [])
                if "Ebs" in b
            ],
        )
        self.record()
        self.call("ec2", "wait", "instance-running", "--instance-ids", self.owned["instance_id"])
        current = self.call(
            "ec2", "describe-instances", "--instance-ids", self.owned["instance_id"]
        )["Reservations"][0]["Instances"][0]
        devices = current.get("BlockDeviceMappings", [])
        require(
            len(devices) == 1
            and devices[0]["DeviceName"] == s["root_device"]
            and devices[0]["Ebs"]["DeleteOnTermination"],
            "Unexpected disk layout; stop and inspect private state.",
        )
        self.owned.update(volume_ids=[devices[0]["Ebs"]["VolumeId"]])
        self.record()
        self.intent("allocate-address")
        eip = self.call(
            "ec2",
            "allocate-address",
            "--domain",
            "vpc",
            "--tag-specifications",
            self.tags("elastic-ip"),
        )
        self.owned.update(allocation_id=eip["AllocationId"], static_ip=eip["PublicIp"])
        self.record()
        self.intent("associate-address")
        a = self.call(
            "ec2",
            "associate-address",
            "--allocation-id",
            eip["AllocationId"],
            "--instance-id",
            self.owned["instance_id"],
            "--no-allow-reassociation",
        )
        self.owned.update(association_id=a["AssociationId"], status="created", intent=None)
        self.record()
        print(f"STATIC_IP={eip['PublicIp']}")
        print(
            "Created exact owned EC2 resources. Verify SSH host fingerprint out of "
            "band; wait for cloud-init, then transfer keys/image. No app or live provider enabled."
        )

    def record(self):
        save(self.state / "owned.json", self.owned)

    def intent(self, operation):
        self.owned["intent"] = operation
        self.record()

    def load_owned(self):
        require(
            (self.state / "owned.json").is_file(),
            "Missing .state/owned.json; manual inspection required.",
        )
        owned = json.loads((self.state / "owned.json").read_text())
        require(
            all(
                owned.get(k) == v
                for k, v in dict(
                    account=ACCOUNT, region=REGION, name=self.name, project=PROJECT
                ).items()
            ),
            "Local ownership/account/name mismatch.",
        )
        for field, prefix in [
            ("instance_id", "i"),
            ("group_id", "sg"),
            ("key_pair_id", "key"),
            ("allocation_id", "eipalloc"),
        ]:
            require(
                field not in owned or re.fullmatch(prefix + r"-[0-9a-f]{8,17}", owned[field]),
                "Invalid resource ID in state.",
            )
        return owned

    def target(self):
        owned = self.load_owned()
        require(
            owned.get("status") == "created"
            and owned.get("static_ip") == os.environ.get("STATIC_IP"),
            "SSH target must equal successfully created owned Elastic IP in EC2 state.",
        )
        require(ipaddress.ip_address(owned["static_ip"]).version == 4, "IPv4 SSH target required.")
        print("Owned EC2 SSH target and arm64 configuration validated (private values redacted).")

    def teardown(self):
        if not self.apply:
            ids = dict(
                instance_id="<state-instance>",
                allocation_id="<state-EIP>",
                group_id="<state-SG>",
                key_pair_id="<state-key>",
            )
            if (self.state / "owned.json").exists():
                ids.update(self.load_owned())
            print(
                "DRY RUN: verify account + exact .state IDs + Project/Name tags + no "
                "foreign attachment/use before deleting anything. "
                "Archive current independent ledger first."
            )
            for op, args in [
                ("terminate-instances", ["--instance-ids", ids["instance_id"]]),
                ("wait", ["instance-terminated", "--instance-ids", ids["instance_id"]]),
                ("disassociate-address", ["--association-id", "<verified-owned-association>"]),
                ("release-address", ["--allocation-id", ids["allocation_id"]]),
                ("delete-security-group", ["--group-id", ids["group_id"]]),
                ("delete-key-pair", ["--key-pair-id", ids["key_pair_id"]]),
            ]:
                self.preview("ec2", op, *args)
            return
        require(
            os.environ.get("CONFIRM_DELETE") == self.name
            and os.environ.get("LEDGER_ARCHIVED") == "true",
            "Require CONFIRM_DELETE=NAME and LEDGER_ARCHIVED=true.",
        )
        self.owned = self.load_owned()
        self.identity()
        inv = self.inventory()
        items = {}
        for kind, field, idkey in [
            ("instances", "instance_id", "InstanceId"),
            ("addresses", "allocation_id", "AllocationId"),
            ("groups", "group_id", "GroupId"),
            ("keys", "key_pair_id", "KeyPairId"),
        ]:
            matches = [r for r in inv[kind] if r.get(idkey) == self.owned.get(field)]
            require(len(matches) <= 1, "Ambiguous exact resource ID.")
            item = matches[0] if matches else None
            if item:
                require(
                    tag_value(item, "Project") == PROJECT and tag_value(item, "Name") == self.name,
                    "Ownership tag mismatch; nothing deleted.",
                )
            items[kind] = item
        # A named resource without a recorded ID could be an ambiguous failed create: do not
        # adopt it.
        for kind, field in [
            ("instances", "instance_id"),
            ("addresses", "allocation_id"),
            ("groups", "group_id"),
            ("keys", "key_pair_id"),
        ]:
            require(
                field in self.owned
                or not any(
                    tag_value(r, "Name") == self.name
                    or r.get("GroupName") == self.name
                    or r.get("KeyName") == self.name
                    for r in inv[kind]
                ),
                "Unrecorded matching resource; inspect uncertain creation manually, "
                "do not adopt/delete.",
            )
        instance = items["instances"]
        active = instance and instance["State"]["Name"] != "terminated"
        if instance:
            if active:
                require(
                    {
                        b["Ebs"]["VolumeId"]
                        for b in instance.get("BlockDeviceMappings", [])
                        if "Ebs" in b
                    }
                    == set(self.owned.get("volume_ids", []))
                    and len(self.owned.get("volume_ids", [])) == 1,
                    "Disk IDs differ from creation state; stop before deleting any "
                    "attached storage.",
                )
                volumes = self.call(
                    "ec2",
                    "describe-volumes",
                    "--filters",
                    "Name=volume-id,Values=" + ",".join(self.owned["volume_ids"]),
                )["Volumes"]
                require(
                    len(volumes) == 1
                    and tag_value(volumes[0], "Project") == PROJECT
                    and tag_value(volumes[0], "Name") == self.name,
                    "Root volume ownership mismatch.",
                )
            require(instance.get("VpcId") == self.owned["vpc_id"], "Instance VPC mismatch.")
            require(
                all(
                    x.get("Ebs", {}).get("DeleteOnTermination") is True
                    for x in instance.get("BlockDeviceMappings", [])
                ),
                "Unexpected retained volume; stop for manual storage review.",
            )
        eip = items["addresses"]
        if eip:
            require(
                eip.get("InstanceId") in (None, self.owned.get("instance_id")),
                "EIP attached to foreign instance; nothing deleted.",
            )
            nic_ids = {
                n["NetworkInterfaceId"] for n in (instance or {}).get("NetworkInterfaces", [])
            }
            require(
                not eip.get("NetworkInterfaceId") or eip["NetworkInterfaceId"] in nic_ids,
                "EIP attached to foreign interface; nothing deleted.",
            )
            require(
                eip.get("AssociationId") in (None, self.owned.get("association_id"))
                or (
                    self.owned.get("intent") == "associate-address"
                    and eip.get("InstanceId") == self.owned.get("instance_id")
                ),
                "EIP association mismatch.",
            )
        group = items["groups"]
        if group:
            require(
                group.get("VpcId") == self.owned["vpc_id"] and group["GroupName"] == self.name,
                "SG ownership mismatch.",
            )
            require(
                not any(
                    i["InstanceId"] != self.owned.get("instance_id")
                    and i["State"]["Name"] != "terminated"
                    and any(g["GroupId"] == group["GroupId"] for g in i.get("SecurityGroups", []))
                    for i in inv["instances"]
                ),
                "Owned SG is used by a foreign instance; nothing deleted.",
            )
        if items["keys"]:
            require(items["keys"]["KeyName"] == self.name, "Key ownership mismatch.")
        # All ownership checks precede the first destructive operation; no broad tag-filter deletes.
        if active:
            self.call("ec2", "terminate-instances", "--instance-ids", instance["InstanceId"])
            self.call(
                "ec2", "wait", "instance-terminated", "--instance-ids", instance["InstanceId"]
            )
        if eip:
            current = next(
                (
                    r
                    for r in self.call("ec2", "describe-addresses")["Addresses"]
                    if r["AllocationId"] == eip["AllocationId"]
                ),
                None,
            )
            if current:
                require(
                    tag_value(current, "Project") == PROJECT
                    and tag_value(current, "Name") == self.name
                    and current.get("InstanceId") in (None, self.owned.get("instance_id"))
                    and current.get("NetworkInterfaceId") in (None, eip.get("NetworkInterfaceId"))
                    and current.get("AssociationId") in (None, eip.get("AssociationId")),
                    "EIP changed during teardown; stop.",
                )
                if current.get("AssociationId"):
                    self.call(
                        "ec2", "disassociate-address", "--association-id", current["AssociationId"]
                    )
                self.call("ec2", "release-address", "--allocation-id", current["AllocationId"])
        if group:
            self.call("ec2", "delete-security-group", "--group-id", group["GroupId"])
        if items["keys"]:
            self.call("ec2", "delete-key-pair", "--key-pair-id", items["keys"]["KeyPairId"])
        final = self.inventory()
        require(
            not any(
                i["InstanceId"] == self.owned.get("instance_id")
                and i["State"]["Name"] != "terminated"
                for i in final["instances"]
            ),
            "Instance termination not verified.",
        )
        for kind, field, idkey in [
            ("addresses", "allocation_id", "AllocationId"),
            ("groups", "group_id", "GroupId"),
            ("keys", "key_pair_id", "KeyPairId"),
        ]:
            require(
                not any(i[idkey] == self.owned.get(field) for i in final[kind]),
                "Teardown absence not verified.",
            )
        volumes = (
            self.call(
                "ec2",
                "describe-volumes",
                "--filters",
                "Name=volume-id,Values=" + ",".join(self.owned["volume_ids"]),
            )["Volumes"]
            if self.owned.get("volume_ids")
            else []
        )
        require(
            not volumes,
            "Owned root volume deletion not yet verified; retain journal and rerun "
            "teardown after inspection.",
        )
        self.owned.update(status="deleted", intent=None)
        self.record()
        print(
            "Exact owned instance/EIP/SG/imported key removed and absence verified; "
            "budget alert retained. Keep private creation/deletion journal and archived ledger."
        )

    def cost(self):
        if self.apply:
            self.identity()
        invoke = self.call if self.apply else self.preview
        invoke(
            "budgets",
            "describe-budget",
            "--account-id",
            ACCOUNT,
            "--budget-name",
            "proofops-r108-monthly-20",
        )
        for op in ("describe-instances", "describe-addresses", "describe-volumes"):
            result = invoke("ec2", op, "--filters", f"Name=tag:Project,Values={PROJECT}")
            if self.apply:
                save(self.state / (op + ".json"), result)
        print(
            "Account budget is delayed and covers all services; resource inventory "
            "saved privately on apply. Stopped EC2 still incurs EBS/EIP cost. "
            "Provider ledger is separate."
        )


def main():
    os.umask(0o077)
    os.environ.update(AWS_PAGER="", AWS_EC2_METADATA_DISABLED="true")
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["preflight", "create", "teardown", "cost", "target"])
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    kit = EC2(a.apply)
    if a.operation == "target":
        kit.target()
        return
    if not a.apply:
        getattr(kit, a.operation)()
        return
    kit.state.mkdir(parents=True, exist_ok=True)
    require(not kit.state.is_symlink(), "State directory must not be a symlink.")
    with (kit.state / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another EC2 operation is using this state; stop.")
        getattr(kit, a.operation)()


if __name__ == "__main__":
    main()
