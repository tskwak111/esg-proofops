#!/usr/bin/env python3
"""Validate documentation/contracts only. Does not run the application or call APIs."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:
    raise SystemExit("Install requirements-package-validation.txt before running: " + str(exc))

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    ".local",
    "dist",
    "build",
    "legacy_reference",
}


def project_files(suffix: str):
    """Inspect project contracts without traversing installed tools or runtime data."""
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in GENERATED_DIRECTORIES]
        for name in files:
            if name.endswith(suffix):
                yield Path(directory) / name


checks: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def valid(data, schema) -> bool:
    return not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data))


def resolve_pointer(doc, pointer: str):
    cur = doc
    for part in pointer.removeprefix("#/").split("/"):
        cur = cur[part.replace("~1", "/").replace("~0", "~")]
    return cur


def all_refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from all_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_refs(v)


numbered = sorted((ROOT / "docs").glob("[0-9][0-9]_*.md"))
check(
    "numbered_docs_00_to_33",
    {int(p.name[:2]) for p in numbered} == set(range(34)),
    str(len(numbered)),
)
for n in [
    "README.md",
    "AGENTS.md",
    "CODEX_START_PROMPT.md",
    ".env.example",
    "contracts/openapi.yaml",
]:
    check("required:" + n, (ROOT / n).is_file())
for p in project_files(".json"):
    if p.name == "package_validation.json":
        continue
    try:
        json.loads(p.read_text(encoding="utf-8"))
        check("json:" + p.relative_to(ROOT).as_posix(), True)
    except (ValueError, OSError) as exc:
        check("json:" + p.relative_to(ROOT).as_posix(), False, str(exc))
for p in project_files(".yaml"):
    try:
        val = yaml.safe_load(p.read_text(encoding="utf-8"))
        check("yaml:" + p.relative_to(ROOT).as_posix(), isinstance(val, dict))
        if p.is_relative_to(ROOT / "config"):
            check(
                "config_version:" + p.relative_to(ROOT).as_posix(),
                bool(val.get("version") and val.get("effective_date")),
            )
    except (ValueError, yaml.YAMLError, OSError) as exc:
        check("yaml:" + p.relative_to(ROOT).as_posix(), False, str(exc))

manifest = load("sources/source_manifest.json")
for k in ["domain_source", "package_request"]:
    item = manifest[k]
    actual = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
    check("source_sha256:" + k, actual == item["sha256"], actual)
check(
    "honest_legacy_execution_flag", manifest["legacy_repository"]["runtime_tests_executed"] is False
)

openapi = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text())
check("openapi_version", openapi.get("openapi") == "3.1.0")
for pointer in all_refs(openapi):
    try:
        resolve_pointer(openapi, pointer)
        check("openapi_ref:" + pointer, True)
    except (KeyError, TypeError):
        check("openapi_ref:" + pointer, False)
operations = []
for path, methods in openapi["paths"].items():
    for method, op in methods.items():
        operations.append((method.upper(), path, op["operationId"]))
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
        check("path_params:" + op["operationId"], declared == set(re.findall(r"\{([^}]+)\}", path)))
        if method == "post":
            headers = {p["name"] for p in op.get("parameters", []) if p["in"] == "header"}
            check("csrf:" + op["operationId"], "X-CSRF-Token" in headers)
            if op.get("x-idempotency-required"):
                check("idempotency:" + op["operationId"], "Idempotency-Key" in headers)
check("unique_operation_ids", len({o[2] for o in operations}) == len(operations))
operation_set = {(m, p) for m, p, _ in operations}
requirements = load("contracts/requirement_catalog.json")
tasks = load("contracts/task_catalog.json")
check("unique_requirement_ids", len({r["id"] for r in requirements}) == len(requirements))
check("unique_task_ids", len({t["id"] for t in tasks}) == len(tasks))
task_ids = {t["id"] for t in tasks}
requirement_ids = {r["id"] for r in requirements}
for r in requirements:
    check("requirement_task:" + r["id"], r["task"] in task_ids)
    for endpoint in r["api"].split(";"):
        method, path = endpoint.strip().split(" ", 1)
        check("requirement_api:" + r["id"] + ":" + path, (method, path) in operation_set)
    check("requirement_test:" + r["id"], bool(r["test"] and r["unit_path"]))
for t in tasks:
    check(
        "task_deps:" + t["id"],
        set(t["dependencies"]) <= task_ids and t["id"] not in t["dependencies"],
    )
    check("task_requirements:" + t["id"], set(t["requirements"]) <= requirement_ids)
    check(
        "task_contract:" + t["id"],
        all(t.get(k) for k in ["files", "interfaces", "test", "acceptance"]),
    )
order = load("contracts/task_execution_order.json")
seen = set()
by_id = {t["id"]: t for t in tasks}
check("task_order_membership", len(order) == len(tasks) and set(order) == task_ids)
for tid in order:
    check("task_topological:" + tid, set(by_id[tid]["dependencies"]) <= seen)
    seen.add(tid)
trace = (ROOT / "docs/32_REQUIREMENT_TRACEABILITY.md").read_text()
for r in requirements:
    check("trace_row:" + r["id"], r["id"] in trace and r["task"] in trace and r["test"] in trace)

schemas = {}
for p in (ROOT / "contracts/jsonschema").glob("*.schema.json"):
    s = json.loads(p.read_text())
    try:
        Draft202012Validator.check_schema(s)
        check("schema_meta:" + p.name, True)
        for pointer in all_refs(s):
            resolve_pointer(s, pointer)
        check("schema_refs:" + p.name, True)
    except Exception as exc:
        check("schema_meta_refs:" + p.name, False, str(exc))
    schemas[p.name] = s
api_schema = schemas["api_models.schema.json"]
for name, example in load("fixtures/api_examples.json").items():
    schema = {"$ref": "#/$defs/" + name, "$defs": api_schema["$defs"]}
    check("valid_example:" + name, valid(example, schema))
llm = load("fixtures/llm_tags_example.json")
check("valid_example:llm_tags", valid(llm, schemas["llm_tags.schema.json"]))
graph = load("fixtures/document_graph_example.json")
check("valid_example:document_graph", valid(graph, schemas["document_graph.schema.json"]))
blockids = {b["source_id"] for b in graph["blocks"]}
check(
    "graph_edge_integrity_example",
    all(e["source_id"] in blockids and e["target_id"] in blockids for e in graph["edges"]),
)
# Negative tests check actual validators reject bad contract instances.
bad = copy.deepcopy(llm)
bad["label"] = "SUBSTANTIATED"
check("negative:LLM_grade_field_rejected", not valid(bad, schemas["llm_tags.schema.json"]))
bad = copy.deepcopy(llm)
bad["elements"][0]["evidence_refs"] = []
check("negative:present_without_source_rejected", not valid(bad, schemas["llm_tags.schema.json"]))
bad = copy.deepcopy(llm)
bad["replicate_id"] = 4
check("negative:replicate_out_of_range_rejected", not valid(bad, schemas["llm_tags.schema.json"]))
decision = load("fixtures/api_examples.json")["Decision"]
ws = {"$ref": "#/$defs/Decision", "$defs": api_schema["$defs"]}
bad = copy.deepcopy(decision)
bad["decision_status"] = "blocked_rule_gap"
check("negative:blocked_decision_with_grade_rejected", not valid(bad, ws))
bad = copy.deepcopy(decision)
bad["label"] = "SUBSTANTIATED"
check("negative:grade_label_mismatch_rejected", not valid(bad, ws))
run = load("fixtures/api_examples.json")["RunCreate"]
ws = {"$ref": "#/$defs/RunCreate", "$defs": api_schema["$defs"]}
bad = copy.deepcopy(run)
bad["selected_pages"] = [1, 2]
check("negative:full_mode_subset_rejected", not valid(bad, ws))
bad = copy.deepcopy(run)
bad["scope"] = "declared_subset"
check("negative:subset_requires_pages", not valid(bad, ws))

rulecases = load("fixtures/rule_cases.json")["cases"]
labels = {"E0": "UNSUBSTANTIATED", "E1": "INCOMPLETE", "E2": "INCOMPLETE", "E3": "SUBSTANTIATED"}
check("rule_fixture_unique_ids", len({c["id"] for c in rulecases}) == len(rulecases))
for c in rulecases:
    e = c["expected"]
    check(
        "rule_fixture_shape:" + c["id"],
        c["synthetic"] is True and e["label"] == labels.get(e["evidence_grade"]),
    )
check(
    "rule_fixtures_not_claimed_runtime_tests",
    len(rulecases) > 0,
    "shape checks only, not execution of future rule engine",
)
pack = yaml.safe_load((ROOT / "config/rule_pack_manifest.yaml").read_text())
for f in pack["files"]:
    check("rulepack_path:" + f, (ROOT / "config" / f).is_file())
envs = load("contracts/environment_variables.json")
env_text = (ROOT / ".env.example").read_text()
for item in envs:
    check(
        "env_declared:" + item["name"],
        bool(re.search(r"^" + re.escape(item["name"]) + "=", env_text, re.M)),
    )
# Existing local Markdown links, excluding code fences and external URLs.
for p in [ROOT / "README.md", *numbered]:
    text = re.sub(r"```.*?```", "", p.read_text(), flags=re.S)
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if re.match(r"^[a-z]+://", target) or target.startswith("#"):
            continue
        candidate = (p.parent / unquote(target.split("#", 1)[0])).resolve()
        check("md_link:" + p.relative_to(ROOT).as_posix() + ":" + target, candidate.exists())

# De-duplicate repeated reference checks for a readable report.
checks = list({c["name"]: c for c in checks}.values())
failed = [c for c in checks if not c["passed"]]
report = {
    "checked_at": datetime.now(UTC).isoformat(),
    "scope": "documentation, structured contracts and synthetic schema examples only",
    "status": "passed" if not failed else "failed",
    "checks_total": len(checks),
    "passed": len(checks) - len(failed),
    "failed": len(failed),
    "counts": {
        "numbered_documents": len(numbered),
        "requirements": len(requirements),
        "tasks": len(tasks),
        "api_operations": len(operations),
        "rule_vectors": len(rulecases),
        "edge_vectors": len(load("fixtures/edge_cases.json")),
    },
    "not_executed": [
        "legacy_repository_test_suite",
        "PDF_parsing_benchmark",
        "implemented_rule_engine_tests",
        "live_Bedrock_inference",
        "AWS_deployment",
        "legal_clause_verification",
    ],
    "failures": failed,
    "checks": checks,
}
(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence/package_validation.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
lines = [
    f"Status: {report['status']}",
    f"Checks: {len(checks)} | passed: {len(checks)-len(failed)} | failed: {len(failed)}",
    json.dumps(report["counts"], ensure_ascii=False),
    "Scope: documentation/contracts only; no application/model/cloud/PDF benchmark execution.",
]
lines += ["FAIL " + str(f["name"]) + " " + str(f["detail"]) for f in failed]
(ROOT / "evidence/package_validation.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(1 if failed else 0)
