"""Strict local AWS CLI fixture, deliberately rejects unimplemented calls."""

import json
import os
import sys
from pathlib import Path

root = Path(os.environ["MOCK_ROOT"])
p = root / "resources.json"
d = json.loads(p.read_text())
a = sys.argv[1:]
i = next(i for i, v in enumerate(a) if v in ("ec2", "sts", "ssm", "service-quotas", "budgets"))
service, op = a[i : i + 2]
a = a[i + 2 :]
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps([service, op, a]) + "\n")
if os.environ.get("MOCK_FAIL") == op:
    sys.stderr.write("Fixture failure\n")
    sys.exit(1)


def arg(k):
    return a[a.index(k) + 1]


def filearg(k):
    return json.loads(Path(arg(k).removeprefix("file://")).read_text())


def tags(kind):
    return next(
        x["Tags"] for x in json.loads(arg("--tag-specifications")) if x["ResourceType"] == kind
    )


r = {}
if op == "get-caller-identity":
    r = {"Account": os.environ.get("MOCK_ACCOUNT", "753036488189")}
    if "--query" in a:
        print(r["Account"])
        sys.exit()
elif op == "describe-regions":
    r = {"Regions": [{"RegionName": "ap-northeast-2"}]}
elif op == "describe-availability-zones":
    r = {
        "AvailabilityZones": [
            {"ZoneName": "ap-northeast-2a", "State": "available", "ZoneType": "availability-zone"}
        ]
    }
elif op == "get-parameter":
    r = {"Parameter": {"Value": "ami-0123456789abcdef0"}}
elif op == "describe-images":
    r = {
        "Images": [
            dict(
                ImageId="ami-0123456789abcdef0",
                OwnerId="099720109477",
                Name="ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-fixture",
                Architecture="amd64" if os.environ.get("MOCK_BAD_IMAGE") else "arm64",
                State="available",
                RootDeviceType="ebs",
                RootDeviceName="/dev/sda1",
                VirtualizationType="hvm",
            )
        ]
    }
elif op == "describe-instance-type-offerings":
    r = {
        "InstanceTypeOfferings": []
        if os.environ.get("MOCK_NO_AZ")
        else [{"Location": "ap-northeast-2a", "InstanceType": "t4g.medium"}]
    }
elif op == "describe-instance-types":
    r = {
        "InstanceTypes": [
            {
                "InstanceType": "t4g.medium",
                "VCpuInfo": {"DefaultVCpus": 2},
                "MemoryInfo": {"SizeInMiB": 4096},
                "ProcessorInfo": {"SupportedArchitectures": ["arm64"]},
            }
        ]
    }
elif op == "describe-vpcs":
    r = {
        "Vpcs": []
        if os.environ.get("MOCK_NO_VPC")
        else [{"VpcId": "vpc-0123456789abcdef0", "IsDefault": True, "State": "available"}]
    }
elif op == "describe-subnets":
    r = {
        "Subnets": [
            {
                "SubnetId": "subnet-0123456789abcdef0",
                "VpcId": "vpc-0123456789abcdef0",
                "AvailabilityZone": "ap-northeast-2a",
                "DefaultForAz": True,
                "State": "available",
                "AssignIpv6AddressOnCreation": False,
                "AvailableIpAddressCount": 100,
            }
        ]
    }
elif op == "describe-route-tables":
    r = {
        "RouteTables": [
            {
                "Associations": [{"Main": True}],
                "Routes": []
                if os.environ.get("MOCK_NO_ROUTE")
                else [
                    {
                        "DestinationCidrBlock": "0.0.0.0/0",
                        "GatewayId": "igw-0123456789abcdef0",
                        "State": "active",
                    }
                ],
            }
        ]
    }
elif op == "describe-instances":
    instances = d["instances"]
    if "--instance-ids" in a:
        instances = [v for v in instances if v["InstanceId"] == arg("--instance-ids")]
    elif os.environ.get("MOCK_USED_VCPU"):
        instances = instances + [
            dict(InstanceId="i-used", InstanceType="t4g.medium", State={"Name": "running"}, Tags=[])
        ]
    r = {"Reservations": [{"Instances": instances}]}
elif op == "describe-addresses":
    r = {"Addresses": d["addresses"]}
elif op == "describe-security-groups":
    r = {"SecurityGroups": d["groups"]}
elif op == "describe-key-pairs":
    r = {"KeyPairs": d["keys"]}
elif op == "describe-volumes":
    volumes = d["volumes"]
    if "--filters" in a:
        value = arg("--filters")
        if value.startswith("Name=volume-id,Values="):
            ids = value.split("Values=", 1)[1].split(",")
            volumes = [v for v in volumes if v["VolumeId"] in ids]
    r = {"Volumes": volumes}
elif op == "get-service-quota":
    if os.environ.get("MOCK_QUOTA_DENIED"):
        sys.stderr.write("AccessDeniedException: local fixture\n")
        sys.exit(254)
    r = {"Quota": {"Value": float(os.environ.get("MOCK_QUOTA", "8"))}}
elif op == "import-key-pair":
    assert (
        Path(arg("--public-key-material").removeprefix("fileb://"))
        .read_text()
        .startswith("ssh-ed25519 ")
    )
    r = dict(KeyPairId="key-0123456789abcdef0", KeyName=arg("--key-name"), Tags=tags("key-pair"))
    d["keys"].append(r)
elif op == "create-security-group":
    g = dict(
        GroupId="sg-0123456789abcdef0",
        GroupName=arg("--group-name"),
        VpcId=arg("--vpc-id"),
        Tags=tags("security-group"),
        IpPermissionsEgress=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
    )
    d["groups"].append(g)
    r = {"GroupId": g["GroupId"]}
elif op == "authorize-security-group-ingress":
    rules = filearg("--ip-permissions")
    assert [(v["FromPort"], v["IpRanges"][0]["CidrIp"]) for v in rules] == [
        (22, "203.0.113.7/32"),
        (80, "0.0.0.0/0"),
        (443, "0.0.0.0/0"),
    ]
    assert all(not v.get("Ipv6Ranges") for v in rules)
    d["groups"][0]["IpPermissions"] = rules
elif op == "revoke-security-group-egress":
    pass
elif op == "run-instances":
    assert arg("--instance-type") == "t4g.medium" and arg("--count") == "1"
    assert "--iam-instance-profile" not in a and "--no-disable-api-termination" in a
    assert "HttpTokens=required" in arg("--metadata-options")
    assert arg("--credit-specification") == "CpuCredits=standard"
    disk = filearg("--block-device-mappings")[0]["Ebs"]
    assert disk == dict(VolumeType="gp3", VolumeSize=30, Encrypted=True, DeleteOnTermination=True)
    nic = filearg("--network-interfaces")[0]
    assert nic["AssociatePublicIpAddress"] is False and nic["Ipv6AddressCount"] == 0
    text = Path(arg("--user-data").removeprefix("file://")).read_text()
    assert "__SSH_CIDR__" not in text and "203.0.113.7/32" in text and "aarch64" in text
    inst = dict(
        InstanceId="i-0123456789abcdef0",
        InstanceType="t4g.medium",
        VpcId="vpc-0123456789abcdef0",
        State={"Name": "running"},
        Tags=tags("instance"),
        NetworkInterfaces=[{"NetworkInterfaceId": "eni-0123456789abcdef0"}],
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {"VolumeId": "vol-0123456789abcdef0", "DeleteOnTermination": True},
            }
        ],
        SecurityGroups=[{"GroupId": "sg-0123456789abcdef0"}],
        KeyName="proofops-r108",
    )
    d["instances"].append(inst)
    d["volumes"].append(dict(VolumeId="vol-0123456789abcdef0", Tags=tags("volume")))
    r = {"Instances": [inst]}
elif op == "allocate-address":
    r = dict(
        AllocationId="eipalloc-0123456789abcdef0",
        PublicIp="203.0.113.10",
        Domain="vpc",
        Tags=tags("elastic-ip"),
    )
    d["addresses"].append(r)
elif op == "associate-address":
    d["addresses"][0].update(
        InstanceId=arg("--instance-id"),
        NetworkInterfaceId="eni-0123456789abcdef0",
        AssociationId="eipassoc-0123456789abcdef0",
    )
    r = {"AssociationId": "eipassoc-0123456789abcdef0"}
elif op == "disassociate-address":
    for k in ("InstanceId", "NetworkInterfaceId", "AssociationId"):
        d["addresses"][0].pop(k, None)
elif op == "release-address":
    d["addresses"] = [v for v in d["addresses"] if v["AllocationId"] != arg("--allocation-id")]
elif op == "terminate-instances":
    inst = next(v for v in d["instances"] if v["InstanceId"] == arg("--instance-ids"))
    inst["State"]["Name"] = "terminated"
    d["volumes"] = []
elif op == "delete-security-group":
    d["groups"] = [v for v in d["groups"] if v["GroupId"] != arg("--group-id")]
elif op == "delete-key-pair":
    d["keys"] = [v for v in d["keys"] if v["KeyPairId"] != arg("--key-pair-id")]
elif op == "wait":
    pass
elif op == "create-budget":
    budget = filearg("--cli-input-json")
    assert budget["AccountId"] == "753036488189"
    assert budget["Budget"]["BudgetLimit"] == {"Amount": "20", "Unit": "USD"}
    assert len(budget["NotificationsWithSubscribers"]) == 3
elif op == "describe-budget":
    r = {"Budget": {"BudgetName": "proofops-r108-monthly-20"}}
else:
    raise SystemExit("Unimplemented local fixture: " + service + " " + op)
p.write_text(json.dumps(d))
print(json.dumps(r))
