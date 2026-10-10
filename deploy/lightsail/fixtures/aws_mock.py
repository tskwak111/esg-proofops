import json
import os
import sys
from pathlib import Path

root = Path(os.environ["MOCK_ROOT"])
p = root / "resources.json"
data = json.loads(p.read_text())
a = sys.argv[1:]
i = next(i for i, v in enumerate(a) if v in ("sts", "lightsail", "budgets"))
service, action = a[i : i + 2]
args = a[i + 2 :]


def arg(k):
    return args[args.index(k) + 1]


with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps([service, action, args]) + "\n")
result = {}
if action == "get-caller-identity":
    result = {"Account": os.environ.get("MOCK_ACCOUNT", "123456789012")}
    if "--query" in args:
        print(result["Account"])
        sys.exit()
elif action == "get-regions":
    result = {
        "regions": [
            {"name": "ap-northeast-2", "availabilityZones": [{"zoneName": "ap-northeast-2a"}]}
        ]
    }
elif action == "get-blueprints":
    result = {
        "blueprints": [
            {
                "blueprintId": "ubuntu_24_04",
                "isActive": True,
                "platform": "LINUX_UNIX",
                "minPower": 300,
            }
        ]
    }
elif action == "get-bundles":
    result = {
        "bundles": [
            {
                "bundleId": "medium-fixture",
                "isActive": True,
                "ramSizeInGb": 4,
                "cpuCount": 2,
                "supportedPlatforms": ["LINUX_UNIX"],
                "publicIpv4AddressCount": 1,
                "power": 1000,
                "price": 24,
            }
        ]
    }
elif action == "get-instances":
    result = {"instances": data["instances"]}
elif action == "get-static-ips":
    result = {"staticIps": data["ips"]}
elif action == "get-key-pairs":
    result = {"keyPairs": data["keys"]}
elif action == "get-instance-snapshots":
    result = {"instanceSnapshots": data["snapshots"]}
elif action == "get-static-ip":
    result = {"staticIp": next(v for v in data["ips"] if v["name"] == arg("--static-ip-name"))}
elif action == "get-auto-snapshots":
    result = {"autoSnapshots": data["auto"]}
elif action == "get-operation":
    if "--query" in args:
        print("Succeeded")
        sys.exit()
    result = {"operation": {"status": "Succeeded"}}
elif action == "create-instances":
    assert (
        arg("--blueprint-id") == "ubuntu_24_04"
        and arg("--bundle-id") == "medium-fixture"
        and arg("--ip-address-type") == "ipv4"
    )
    user_data = Path(arg("--user-data").removeprefix("file://")).read_text()
    assert "__SSH_CIDR__" not in user_data and "203.0.113.7/32" in user_data
    data["instances"].append(
        {
            "name": arg("--instance-names"),
            "hardware": {"cpuCount": 2},
            "tags": [{"key": "Project", "value": "proofops-r108"}],
            "addOns": [],
        }
    )
elif action == "put-instance-public-ports":
    ports = json.loads(Path(arg("--port-infos").removeprefix("file://")).read_text())
    assert len(ports) == 3
    assert ports[0]["fromPort"] == 22 and ports[0]["cidrs"] == ["203.0.113.7/32"]
    assert all(v["ipv6Cidrs"] == [] for v in ports)
elif action == "import-key-pair":
    import base64

    encoded = Path(arg("--public-key-base64").removeprefix("file://")).read_text()
    assert base64.b64decode(encoded).startswith(b"ssh-rsa ")
    data["keys"].append({"name": arg("--key-pair-name")})
elif action == "allocate-static-ip":
    data["ips"].append(
        {"name": arg("--static-ip-name"), "ipAddress": "203.0.113.10", "isAttached": False}
    )
elif action == "attach-static-ip":
    data["ips"][0].update(isAttached=True, attachedTo=arg("--instance-name"))
elif action == "delete-instance":
    n = arg("--instance-name")
    data["instances"] = [v for v in data["instances"] if v["name"] != n]
    for ip in data["ips"]:
        if ip.get("attachedTo") == n:
            ip.update(isAttached=False, attachedTo="")
elif action == "delete-instance-snapshot":
    data["snapshots"] = [
        v for v in data["snapshots"] if v["name"] != arg("--instance-snapshot-name")
    ]
elif action == "delete-auto-snapshot":
    data["auto"] = [v for v in data["auto"] if v["date"] != arg("--date")]
elif action == "release-static-ip":
    data["ips"] = [v for v in data["ips"] if v["name"] != arg("--static-ip-name")]
elif action == "delete-key-pair":
    data["keys"] = [v for v in data["keys"] if v["name"] != arg("--key-pair-name")]
elif action == "create-budget":
    b = json.loads(Path(arg("--cli-input-json").removeprefix("file://")).read_text())
    assert (
        b["AccountId"] == "123456789012"
        and b["Budget"]["BudgetLimit"] == {"Amount": "20", "Unit": "USD"}
        and len(b["NotificationsWithSubscribers"]) == 3
    )
else:
    raise SystemExit("Unimplemented local mock: " + action)
p.write_text(json.dumps(data))
if service == "lightsail" and not action.startswith("get-"):
    result = (
        {"operation": {"id": "local-fixture"}}
        if action in ("import-key-pair", "delete-key-pair")
        else {"operations": [{"id": "local-fixture"}]}
    )
print(json.dumps(result))
