"""Offline OpenAI strict-subset audit; never rewrites a production schema.

https://developers.openai.com/api/docs/guides/structured-outputs
Base-model rules checked on 2026-10-16 (not fine-tuned model restrictions).
"""

import re

from jsonschema import Draft202012Validator


def strict_schema_issues(schema, *, name):
    Draft202012Validator.check_schema(schema)
    issues = []
    properties = enums = strings = 0
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        issues.append("$:invalid_name")
    if schema.get("type") != "object" or "anyOf" in schema:
        issues.append("$:root_object_required")

    def visit(node, path, depth):
        nonlocal properties, enums, strings
        for keyword in (
            "allOf",
            "oneOf",
            "not",
            "if",
            "then",
            "else",
            "dependentRequired",
            "dependentSchemas",
            "patternProperties",
            "unevaluatedProperties",
            "prefixItems",
            "contains",
            "uniqueItems",
        ):
            if keyword in node:
                issues.append(f"{path}:{keyword}")
        kind = node.get("type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "object" in kinds:
            depth += 1
            props = node.get("properties", {})
            properties += len(props)
            strings += sum(map(len, props))
            if node.get("additionalProperties") is not False:
                issues.append(f"{path}:additionalProperties")
            if set(node.get("required", [])) != set(props):
                issues.append(f"{path}:required")
        if depth > 10:
            issues.append(f"{path}:depth_limit")
        values = node.get("enum", [])
        enums += len(values)
        string_values = [v for v in values if isinstance(v, str)]
        strings += sum(map(len, string_values))
        if len(values) > 250 and sum(map(len, string_values)) > 15000:
            issues.append(f"{path}:enum_string_limit")
        for value in values + ([node["const"]] if "const" in node else []):
            if kind and not Draft202012Validator({"type": kind}).is_valid(value):
                issues.append(f"{path}:enum_or_const_type")
        if isinstance(node.get("const"), str):
            strings += len(node["const"])
        if "$ref" in node:
            ref = node["$ref"]
            try:
                target = schema
                if not ref.startswith("#/"):
                    raise KeyError(ref)
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                issues.append(f"{path}:unresolved_ref")
        for key in ("properties", "$defs"):
            for label, child in node.get(key, {}).items():
                if key == "$defs":
                    strings += len(label)
                visit(child, f"{path}/{key}/{label}", depth)
        for key in ("items", "additionalProperties", "not", "if", "then", "else"):
            if isinstance(node.get(key), dict):
                visit(node[key], f"{path}/{key}", depth)
        for key in ("anyOf", "allOf", "oneOf"):
            for index, child in enumerate(node.get(key, [])):
                visit(child, f"{path}/{key}/{index}", depth)

    visit(schema, "$", 0)
    for count, limit, label in (
        (properties, 5000, "property_limit"),
        (enums, 1000, "enum_limit"),
        (strings, 120000, "string_limit"),
    ):
        if count > limit:
            issues.append(f"$:{label}")
    return sorted(set(issues))


def assert_json_mode_request(body, schema):
    """Provider admission and local schema validation are separate contracts."""
    Draft202012Validator.check_schema(schema)
    assert body["response_format"] == {"type": "json_object"}
    # Require the trusted instruction, not a coincidental word in source text.
    assert any(
        message["role"] in {"system", "developer"} and "json" in message["content"].lower()
        for message in body["messages"]
    )
