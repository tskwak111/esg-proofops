"""Stable public helper contracts and partial geometry before the TA-A5 split."""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from proofops.adapters.parsing import opendataloader as odl
from proofops.application.ingest.graph_fusion import ParserProfile, fuse_candidates
from proofops.application.uploads_security import HOSTED_NULL_NAVIGATION_PROFILE

from tests.acceptance.test_parsing import JAVA, MANIFEST, TENANT, pdf, source


def test_candidate_snapshot_and_unreadable_geometry_before_split(monkeypatch):
    monkeypatch.setattr(odl, "uuid4", lambda: UUID(int=7))
    item = source(pdf())
    profile = ParserProfile(
        MANIFEST, failure_policy="partial-v4", local_resource_policy="selected-pdf-h6-v2"
    )
    geometry = {"width_pt": 600.0, "height_pt": 800.0, "rotation": 0, "crop_box": [0, 0, 600, 800]}
    raw = {
        "kids": [
            {
                "id": 1,
                "type": "paragraph",
                "page number": 1,
                "bounding box": [72, 700, 200, 720],
                "content": "Emissions 1234",
            },
            {
                "id": 1,
                "type": "paragraph",
                "page number": 1,
                "bounding box": [200, 700, 72, 720],
                "content": "Unreadable location",
            },
        ]
    }
    batch = odl._batch(raw, {"1": {"crop": geometry}}, item, profile, "a" * 64)
    assert (
        sha256(odl._json(asdict(batch))).hexdigest()
        == "e1ee39fa76cba3d575f8b95f2f93958712e96305b678f40c3da628c4f08ef785"
    )
    graph = odl._with_quality_issues(fuse_candidates((batch,), tenant_id=TENANT), (1, 2), profile)
    assert {i.kind for i in graph.issues} >= {"source_geometry_invalid", "no_extractable_text"}
    assert all(
        i.state == "unreadable"
        for i in graph.issues
        if i.kind in {"source_geometry_invalid", "no_extractable_text"}
    )
    with pytest.raises(odl.ParseFailure, match="PARSER_GEOMETRY_INVALID"):
        odl._batch(
            raw,
            {"1": {"crop": geometry}},
            item,
            replace(profile, failure_policy=None, local_resource_policy=None),
            "a" * 64,
        )


def test_json_encoding_and_output_accounting_contract(tmp_path):
    assert odl._json({"한글": [1, True], "a": 0}) == '{"a":0,"한글":[1,true]}'.encode()
    with pytest.raises(ValueError):
        odl._json({"invalid": float("nan")})
    (tmp_path / "source.pdf").write_bytes(b"source")
    (tmp_path / "request.json").write_bytes(b"{}")
    (tmp_path / "source.json").write_bytes(b"output")
    (tmp_path / "directory").mkdir()
    assert odl._output_bytes(tmp_path) == 8


def test_shared_helpers_do_not_import_orchestration_in_a_fresh_process():
    code = (
        "import sys\n"
        "from proofops.adapters.parsing import h6_local_pages,h6_local_pages_v2\n"
        "from proofops.adapters.parsing import spp_execution,rb2_output\n"
        "from proofops.adapters.parsing.odl_parts.common import ParseFailure,_json,_output_bytes\n"
        "assert _json({'a':1}) == b'{\"a\":1}'\n"
        "assert 'proofops.adapters.parsing.opendataloader' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True, timeout=10)
    from proofops.adapters.parsing.odl_parts import common

    assert odl.ParseFailure is common.ParseFailure
    assert odl._json is common._json
    assert odl._output_bytes is common._output_bytes


@pytest.mark.parametrize(
    "policy,strict", [(None, True), ("strict-v1", True), (HOSTED_NULL_NAVIGATION_PROFILE, False)]
)
def test_child_preserves_the_upload_security_pin(tmp_path, monkeypatch, policy, strict):
    import pypdf

    request = {"profile": {}, "selected": [1]}
    if policy is not None:
        request["upload_security_profile"] = policy
    (tmp_path / "request.json").write_bytes(odl._json(request))
    monkeypatch.setattr(odl, "_child_limits", lambda profile: None)

    class StopAfterReader(Exception):
        pass

    def reader(path, **kwargs):
        assert path == tmp_path / "source.pdf"
        assert kwargs == {"strict": strict}
        raise StopAfterReader

    monkeypatch.setattr(pypdf, "PdfReader", reader)
    with pytest.raises(StopAfterReader):
        odl._child_body(tmp_path)


@pytest.mark.parametrize(
    "code,changes,error",
    [
        ("pass", {}, None),
        (
            "open('large', 'wb').write(b'x' * 100000)",
            {"max_output_bytes": 1000},
            "PARSER_OUTPUT_LIMIT",
        ),
        (
            "import time; data = bytearray(128 * 1024**2); time.sleep(10)",
            {"memory_bytes": 32 * 1024**2},
            "PARSER_MEMORY_LIMIT",
        ),
    ],
)
def test_bounded_child_exit_output_and_rss(tmp_path, code, changes, error):
    profile = replace(ParserProfile(MANIFEST, timeout_seconds=5), **changes)
    command = [sys.executable, "-I", "-c", code]
    env = odl._child_environment(JAVA, tmp_path, profile)
    if error is None:
        odl.OpenDataLoaderParser._execute(command, tmp_path, env, profile)
    else:
        with pytest.raises(odl.ParseFailure, match=error):
            odl.OpenDataLoaderParser._execute(command, tmp_path, env, profile)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group and rlimit observations")
def test_timeout_kills_descendants_and_child_retains_hard_limits(tmp_path):
    profile = ParserProfile(MANIFEST, timeout_seconds=1)
    code = (
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)'])\n"
        "open('descendant','w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    env = odl._child_environment(JAVA, tmp_path, profile)
    with pytest.raises(odl.ParseFailure, match="PARSER_TIMEOUT"):
        odl.OpenDataLoaderParser._execute(
            [sys.executable, "-I", "-c", code], tmp_path, env, profile
        )
    pid = (tmp_path / "descendant").read_text()
    deadline = time.monotonic() + 3
    while True:
        status = subprocess.run(
            ["/bin/ps", "-o", "stat=", "-p", pid], capture_output=True, text=True
        ).stdout.strip()
        if not status or status.startswith("Z"):
            break
        assert time.monotonic() < deadline, "parser descendant survived timeout"
        time.sleep(0.02)
    code = (
        "import json,resource\n"
        "from proofops.adapters.parsing.opendataloader import _child_limits\n"
        "_child_limits({'timeout_seconds':2.5,'max_output_bytes':4096})\n"
        "limits=[resource.RLIMIT_CPU,resource.RLIMIT_FSIZE,resource.RLIMIT_CORE]\n"
        "print(json.dumps([resource.getrlimit(n) for n in limits]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == [[3, 3], [4096, 4096], [0, 0]]


# Filled from the unmodified 09ebf426 implementation, with fixed invocation IDs.
GOLDEN = {
    "table": {
        "artifacts": {
            "auxiliary.json": "8d34772e6d9238759acebed1fb248563290d7408e46758d208f873513639669d",
            "candidates.json": "38af2b98b23f152adf616598e6995c275295bcccafa81c8fe22722ef9fdc1bfb",
            "geometry.json": "a9287d288de6b1d56faca60655fe2b35e887b373801788ae91fd92da954152ee",
            "graph.json": "f4e334d09455745dd69c1a48b036e6400415017b6e72fdbdf4599552d496069e",
            "launcher-stderr.txt": (
                "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"
            ),
            "quality.json": "9cd062c0945db7c4764b84150303d32aacdae800c9af1368786e2e52b2eb0a00",
            "source-recovery.json": (
                "899b7b0b82f9fcb1fdab79ba8c133cea" "198d539262d73ca47183405c4da37419"
            ),
            "source.json": "5aebb9631be3eff132d58e33a37999268a23bed81ee7d7cb8dde84aa67448435",
            "source.md": "4bedd56b36e84f688386086f8e7070cd3d0076697a19609ba43342f7c71948e4",
        },
        "graph": "f4e334d09455745dd69c1a48b036e6400415017b6e72fdbdf4599552d496069e",
        "manifest": "19dee44056ff551ee2f6738d9383b343b25cdec32fc0fd0634cf1e0fc14a96f3",
    },
    "cropped": {
        "artifacts": {
            "auxiliary.json": "654701b91c0ff43966e503e08ee40e06430f8a08367dc038e570a72004c32d3f",
            "candidates.json": "0d1f5fcd6f1b7cd86127ddc9223d41ad9a5ff545014e7ade7b335e22ab5df4dd",
            "geometry.json": "99baff0fa427d9e3bb0eb1a3c7800ef698924d87a908dff489f1863633c55f20",
            "graph.json": "add22f80ba66f3acc849daf7be601ebc29f2b7c6ad9d517c5db1f06cf29eb607",
            "launcher-stderr.txt": (
                "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"
            ),
            "quality.json": "b0746a93eceb7e1a26de97bbc7a01ae96b1bf18de87394fe86d6d2f4f9cf92a3",
            "source.json": "56273a4d50ba58206863653bc89b16133ac3baabce75e9c0359f67f94e2fe85a",
            "source.md": "c795a1f13c14d0e7d41ef790e8bf80c6e4f6de40910a4db7e36965f2052ddf9a",
        },
        "graph": "add22f80ba66f3acc849daf7be601ebc29f2b7c6ad9d517c5db1f06cf29eb607",
        "manifest": "60b044813702fcde0663eb5eb41380a73b47f096f3fdeeb565e7cbb0c61b0861",
    },
    "selected": {
        "artifacts": {
            "auxiliary.json": "763234a63e2bfe9b45d2ac5ec668473077f69fddf75c15871fbd1550fe19cda7",
            "candidates.json": "d16187999c16c23d2999c657712b086580e8d779fe62b75d596194f03dfda15e",
            "geometry.json": "a9287d288de6b1d56faca60655fe2b35e887b373801788ae91fd92da954152ee",
            "graph.json": "b0c8b734d9df335af080be6bc6189ffd5d2c2e3f59ea259b8872c3974e3d88c3",
            "h6-b0-auxiliary.json": (
                "e247464a822b138a904643d0319d0fc4" "c4e5805b31bc4a8109106b144f9927b0"
            ),
            "h6-b0-geometry.json": (
                "a9287d288de6b1d56faca60655fe2b35" "e887b373801788ae91fd92da954152ee"
            ),
            "h6-b0-h6-selected.pdf": (
                "19023c61e7272357967b707a8c73a8d6" "602466c3fa6222f9884091ddd2c47030"
            ),
            "h6-b0-source.json": "e94c99ee89f894a57f93673bca67a58c5385f53ae3a5c6e8916fd09e82943196",
            "h6-local.json": "ca8ca75773ccc7f13207ffed280b7c4679bdc99e72c0da0aeff2f47fa9dff969",
            "quality.json": "90758aeec4a51ea4da93a71b256aaee833735fe7adb0ec038548ce54f43069c2",
            "source.json": "1c95561d780f714ec08728d903a5761ac76bcb9f0cb3aa53fae40bcaa9aa0c59",
            "source.md": "4bedd56b36e84f688386086f8e7070cd3d0076697a19609ba43342f7c71948e4",
        },
        "graph": "b0c8b734d9df335af080be6bc6189ffd5d2c2e3f59ea259b8872c3974e3d88c3",
        "manifest": "c48dc7a5007833bc56ae51a908327c59fd02b64f8d9f2c76762b10e7c01a2161",
    },
    "attested": {
        "artifacts": {
            "auxiliary.json": "8d34772e6d9238759acebed1fb248563290d7408e46758d208f873513639669d",
            "candidates.json": "6c9d3bbc99b8c485b2d53fabd5ff0b743ac7338b0a916243a08a131c39f0331f",
            "geometry.json": "a9287d288de6b1d56faca60655fe2b35e887b373801788ae91fd92da954152ee",
            "graph.json": "74e9266e6e1acf08b1470923b843982f79d9e8e4f431a35070a33d8ee6a22594",
            "launcher-stderr.txt": (
                "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"
            ),
            "quality.json": "568bc4d218593a9821d873f123429dfcae2c9c5d78408601f9c6e6e6fa8ccc78",
            "source.json": "5aebb9631be3eff132d58e33a37999268a23bed81ee7d7cb8dde84aa67448435",
            "source.md": "4bedd56b36e84f688386086f8e7070cd3d0076697a19609ba43342f7c71948e4",
            "table-source.json": "6954f4ccb1db847625062df79b1d0cb44d9c08b9e32c153ac073692bed5e9190",
        },
        "graph": "74e9266e6e1acf08b1470923b843982f79d9e8e4f431a35070a33d8ee6a22594",
        "manifest": "10ea10f381b1957a91f761544e73ef65d78aa3fafafead89928fab55bec4441f",
    },
}


@pytest.mark.parametrize("case", ["table", "cropped", "selected", "attested"])
def test_real_cli_artifacts_and_verified_graph_match_before_split(tmp_path, monkeypatch, case):
    # Keep the executable location out of the configuration hash; still execute
    # the real Java 21 selected by the project's existing test configuration.
    monkeypatch.setenv("PATH", str(Path(JAVA).parent) + os.pathsep + os.environ["PATH"])
    ids = iter(UUID(int=n) for n in range(1, 100))
    monkeypatch.setattr(odl, "uuid4", lambda: next(ids))
    item = replace(
        source(pdf(table=case != "cropped", crop_rotate=case == "cropped")),
        document_id="55555555-5555-4555-8555-555555555555",
    )
    from proofops.adapters.local import table_source_verification as verifier

    from tests.integration.test_native_table_admission import ocr

    # Freeze OCR transport only; real PDF table verification and receipt replay run.
    verifier._attest_json.cache_clear()
    monkeypatch.setattr(verifier, "_rendered_text", ocr)
    profile = ParserProfile(
        MANIFEST,
        physical_pages=(1, 2, 3, 4) if case == "cropped" else (2,),
        local_resource_policy="selected-pdf-h6-v2" if case == "selected" else None,
        source_recovery="ps1-v1" if case == "table" else None,
        failure_policy="partial-v4" if case == "selected" else None,
        table_source_policy_sha256=verifier.policy_sha256() if case == "attested" else None,
    )
    parser = odl.OpenDataLoaderParser(tmp_path)
    graph = parser.parse(item, profile, tenant_id=TENANT)
    directory = tmp_path / TENANT / item.document_version_id / MANIFEST
    manifest_path = directory / "manifest.json"
    raw_manifest = manifest_path.read_bytes()
    pin = sha256(raw_manifest).hexdigest()
    manifest = json.loads(raw_manifest)
    assert 'version "21.' in manifest["java_version"]
    assert manifest["parser_version"] == "2.5.7"
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert (
        odl.OpenDataLoaderParser(tmp_path).load_verified(
            item, profile, tenant_id=TENANT, manifest_sha256=pin
        )
        == graph
    )
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    for name, digest in manifest["artifacts"].items():
        assert sha256(before[name]).hexdigest() == digest
    if case == "selected":
        # PDFium creates a fresh trailer ID and timestamp for each subset.
        # Normalize metadata only, after validating the real saved bytes.
        name = "h6-b0-h6-selected.pdf"
        normalized, count = re.subn(
            rb"/ID\[<[0-9A-F]{32}><[0-9A-F]{32}>\]",
            b"/ID[<" + b"0" * 32 + b"><" + b"0" * 32 + b">]",
            before[name],
        )
        assert count == 1
        normalized, count = re.subn(
            rb"/CreationDate\(D:[^)]*\)",
            b"/CreationDate(D:20000101000000+00'00')",
            normalized,
        )
        assert count == 1
        digest = sha256(normalized).hexdigest()
        receipt = json.loads(before["h6-local.json"])
        receipt["batches"][0]["artifacts"][name] = digest
        manifest["artifacts"][name] = digest
        name = "h6-b0-source.json"
        raw = json.loads(before[name])
        raw["creation date"] = "D:20000101000000+00'00'"
        digest = sha256(odl._json(raw)).hexdigest()
        receipt["batches"][0]["artifacts"][name] = digest
        manifest["artifacts"][name] = digest
        manifest["artifacts"]["h6-local.json"] = sha256(odl._json(receipt)).hexdigest()
    # Vendor/build metadata varies across Java 21 installations; all parser,
    # source, candidate, geometry and artifact fields remain in the golden hash.
    manifest["java_version"] = "Java 21"
    snapshot = {
        "graph": sha256(odl._json(graph.to_dict())).hexdigest(),
        "manifest": sha256(odl._json(manifest)).hexdigest(),
        "artifacts": manifest["artifacts"],
    }
    assert snapshot == GOLDEN[case]

    with pytest.raises(odl.ParseFailure, match="NOT_FOUND"):
        parser.load_verified(item, profile, tenant_id=str(UUID(int=99)))
    with pytest.raises(odl.ParseFailure, match="SOURCE_INTEGRITY_MISMATCH"):
        parser.load_verified(
            replace(item, content=item.content + b"changed"), profile, tenant_id=TENANT
        )
    # Refuse both an outer manifest rewrite and an artifact whose outer digest
    # has been recomputed, including the corresponding graph/quality checks.
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(raw_manifest + b" ")
    with pytest.raises(odl.ParseFailure, match="PARSER_ARTIFACT_INTEGRITY_MISMATCH"):
        parser.load_verified(item, profile, tenant_id=TENANT, manifest_sha256=pin)
    manifest = json.loads(raw_manifest)
    path = directory / "candidates.json"
    path.chmod(0o600)
    path.write_bytes(b"[]")
    manifest["artifacts"][path.name] = sha256(path.read_bytes()).hexdigest()
    manifest_path.write_bytes(odl._json(manifest))
    with pytest.raises(odl.ParseFailure, match="PARSER_ARTIFACT_INTEGRITY_MISMATCH"):
        parser.load_verified(item, profile, tenant_id=TENANT)
