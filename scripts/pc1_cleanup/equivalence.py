"""Offline observable contract for analysis-profile relocation (no model I/O)."""

import ast
import hashlib
import importlib
import inspect
import json
import sys
from argparse import Namespace
from dataclasses import asdict, is_dataclass


def fingerprint(value):
    from proofops.domain.provenance import canonical_hash

    wire = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {
        "canonical_sha256": canonical_hash(value),
        "ordered_utf8_sha256": hashlib.sha256(wire.encode()).hexdigest(),
        "bytes": len(wire.encode()),
    }


def outcome(function, *args, **kwargs):
    try:
        return {"result": fingerprint(function(*args, **kwargs))}
    except (ValueError, TypeError) as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


def snapshot():
    from proofops.application import analysis_profile as profiles
    from proofops.domain.provenance import canonical_hash

    exports = {name: value for name, value in vars(profiles).items() if not name.startswith("_")}
    values = {}
    policies = []
    profile_names = set()

    def collect(value):
        if isinstance(value, dict):
            policies.append(value)
            if isinstance(value.get("profile"), str):
                profile_names.add(value["profile"])
        elif isinstance(value, tuple | list):
            for item in value:
                collect(item)

    for name, value in exports.items():
        if callable(value):
            continue
        serializable = asdict(value) if is_dataclass(value) else value
        values[name] = fingerprint(serializable)
        collect(serializable)
        if name.endswith("PROFILE") and isinstance(value, str):
            profile_names.add(value)

    # Include local delegated imports, including C2's deliberately disabled publication.
    for node in ast.walk(ast.parse(inspect.getsource(profiles.policy_for))):
        if isinstance(node, ast.ImportFrom):
            module = importlib.import_module(node.module)
            for alias in node.names:
                value = getattr(module, alias.name)
                collect(value)
                if alias.name == "PROFILE":
                    profile_names.add(value)
                if hasattr(module, "POLICY"):
                    collect(module.POLICY)

    known_profiles = []
    choices = {}
    for profile in sorted(profile_names):
        captured = []

        def trace(frame, event, arg):
            if frame.f_code is profiles.policy_for.__code__ and event == "return":
                captured.extend(frame.f_locals.get("choices", ()))
            return trace

        previous_trace = sys.gettrace()
        try:
            sys.settrace(trace)
            selected = profiles.policy_for(profile)
        except ValueError:
            continue
        finally:
            sys.settrace(previous_trace)
        known_profiles.append(profile)
        collect(selected)
        for value in captured:
            collect(value)
        choices[profile] = [fingerprint(value) for value in captured]

    pins = sorted({canonical_hash(policy) for policy in policies})
    # Cross-profile pins and malformed pins must continue to fail closed.
    inputs = [None, "", "not-a-hash", "0" * 64, "F" * 64, *pins]
    lookups = {}
    pilot = {}
    for profile in [None, "pc1-unknown-profile", *known_profiles]:
        lookups[str(profile)] = {}
        for pin in inputs:
            lookups[str(profile)][str(pin)] = {
                "replay": outcome(profiles.policy_for, profile, pinned_hash=pin),
                "hosted": outcome(profiles.publication_policy_for, profile, pinned_hash=pin),
            }
        # Every accepted replay pin exercises the public CLI mutation API.
        for pin in inputs:
            if "error" in lookups[str(profile)][str(pin)]["replay"] and pin is not None:
                continue
            for source in (None, "claim-source-v3", "upstage-ocr-page-v1", "glyph-alignment-v1"):
                args = Namespace(
                    analysis_profile=profile,
                    analysis_policy_sha256=pin,
                    claim_source_profile=source,
                )
                result = outcome(profiles.apply_pilot_profile, args)
                pilot[json.dumps([profile, pin, source])] = {
                    "return": result,
                    "args": fingerprint(vars(args)),
                }
        for mode in ("resume", "pipeline_fallback", "invalid_pin"):
            args = Namespace(analysis_profile=profile)
            if mode == "resume":
                args.resume = True
                args.analysis_policy_sha256 = "invalid"
            elif mode == "pipeline_fallback":
                args.analysis_profile = None
                args.pipeline_profile = profile
            else:
                args.analysis_policy_sha256 = "invalid"
            result = outcome(profiles.apply_pilot_profile, args)
            pilot[json.dumps([profile, mode])] = {"return": result, "args": fingerprint(vars(args))}

    # Cover all source-selector branches on each default as well.
    for profile in known_profiles:
        for source in sorted({*profiles.PAGE_OCR_PROFILES, "claim-source-v4", "invalid"}):
            args = Namespace(analysis_profile=profile, claim_source_profile=source)
            result = outcome(profiles.apply_pilot_profile, args)
            pilot[json.dumps([profile, "source", source])] = {
                "return": result,
                "args": fingerprint(vars(args)),
            }

    identities = [{}, profiles.C3_IDENTITY, profiles.C3_IDENTITY | {"extra": "preserved"}]
    identities.extend(profiles.C3_IDENTITY | {key: "wrong"} for key in profiles.C3_IDENTITY)
    certification = {
        str(pin): [
            outcome(profiles.certification_profile_for, identity, pinned_hash=pin)
            for identity in identities
        ]
        for pin in inputs
    }
    aliases = {}
    for name, value in exports.items():
        if isinstance(value, dict | list | tuple):
            aliases.setdefault(id(value), []).append(name)
    return {
        "public_names": sorted(exports),
        "api_signatures": {
            name: str(inspect.signature(getattr(profiles, name)))
            for name in (
                "policy_for",
                "publication_policy_for",
                "apply_pilot_profile",
                "certification_profile_for",
            )
        },
        "unchanged_api_ast": {
            name: fingerprint(ast.dump(ast.parse(inspect.getsource(getattr(profiles, name)))))
            for name in ("apply_pilot_profile", "certification_profile_for")
        },
        "exports": values,
        "policy_hashes": pins,
        "replay_order": choices,
        "lookups": lookups,
        "pilot": pilot,
        "certification": certification,
        "aliases": sorted(sorted(names) for names in aliases.values() if len(names) > 1),
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
