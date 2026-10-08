"""Select from real CLI responses, or offline fixtures. Never calls AWS."""

import json
import sys
from pathlib import Path

root, arch, blueprint_id, vcpu_quota, ip_quota, price_cap = sys.argv[1:]
root = Path(root)


def load(name):
    return json.loads((root / f"{name}.json").read_text())


# Lightsail blueprint/bundle responses have no documented CPU architecture field.
# Standard Ubuntu 24.04 is x86_64. Reject speculative ARM IDs; verify uname again over SSH.
if arch != "amd64" or blueprint_id != "ubuntu_24_04":
    raise SystemExit("Only standard Ubuntu 24.04 x86_64 is supported; rebuild app linux/amd64.")
blueprint = next(
    (
        b
        for b in load("blueprints")["blueprints"]
        if b["blueprintId"] == blueprint_id and b["isActive"] and b["platform"] == "LINUX_UNIX"
    ),
    None,
)
if not blueprint:
    raise SystemExit(
        "Active Ubuntu 24.04 LTS blueprint unavailable; inspect catalog, do not guess."
    )
bundles = [
    b
    for b in load("bundles")["bundles"]
    if b["isActive"]
    and b["ramSizeInGb"] == 4
    and b["cpuCount"] == 2
    and "LINUX_UNIX" in b["supportedPlatforms"]
    and b.get("publicIpv4AddressCount") == 1
    and b["power"] >= blueprint["minPower"]
    and b["price"] <= float(price_cap)
]
if not bundles:
    raise SystemExit("No active <=price-cap 2vCPU/4GB Linux IPv4 bundle; inspect catalog.")
bundle = min(bundles, key=lambda b: (b["price"], b["bundleId"]))
used = sum(i["hardware"]["cpuCount"] for i in load("instances")["instances"])
if used + bundle["cpuCount"] > int(vcpu_quota) or len(load("ips")["staticIps"]) + 1 > int(ip_quota):
    raise SystemExit("Insufficient confirmed vCPU/static-IP quota.")
region = next(r for r in load("regions")["regions"] if r["name"] == "ap-northeast-2")
az = sorted(z["zoneName"] for z in region["availabilityZones"])[0]
selection = dict(
    region=region["name"],
    az=az,
    blueprint=blueprint_id,
    bundle=bundle["bundleId"],
    arch=arch,
    monthly_usd=bundle["price"],
    vcpus_used=used,
)
(root / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
print(json.dumps(selection))
