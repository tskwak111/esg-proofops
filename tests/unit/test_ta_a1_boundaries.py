"""A1 pre-refactor goldens: policy/wire bytes, replay and paid-attempt guards."""

import inspect
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options

from tests.integration.test_upstage_extraction import (
    TEXT,
    FakeProbe,
    _extraction_context_graph,
    packet,
)

# Captured on 525186d2 before moving implementation code. Do not regenerate to
# accommodate a refactor: changes to these contracts need separate authorization.
PROFILE_GOLDEN = "1d0858a9ca9109e40c1346a4c674e0f82e7c88bcc63412ef5d4b09e4951910e2"
PILOT_GOLDENS = {
    "legacy": "199db6208508f62b1710c841350d5757f7a6091375a7f70291633c6dc27e0a8e",
    "rich": "5c46f26bb7d5c0b12f105966bd27fa1c5ec62e657496857042cfbc06b5d28f32",
    "source_context": "38c51a1bc8b8ebbf6c983b2c51739a2f17abdf4b2912ab9085a535b27a952ced",
}
RECEIPT_GOLDENS = {
    "context": "97dc22a47e1a9f50c2c2389f32f3fa61447e914a4e8ef56ca94630e21f77ae2f",
    "invalid": "10beebc986a3d6bf145dfa6ec820ed840b5a63f2ebbb9a6aaeb8079b03bd1c48",
    "quote": "76810f6c18a65cecefcd2e6a85a548816201b0a6a6b1b439ced9fe9d0a700e22",
    "source": "9c1be36beeb2b75e1419c11ddfd7576a7c53ad436bd78cd15495817b3a20b345",
    "source_context": "1738fb5820caf246d65e5bd5120af64002666d2d98d06c7a6ee55a66e48cc569",
}
ATTEMPT_GOLDEN = {
    "accounting": {
        "cost_with_vat_reserve_usd": "0.000059400",
        "input_tokens": 200,
        "model_calls": 4,
        "output_tokens": 40,
        "reserved_calls": 4,
        "settled_calls": 4,
        "unsettled_calls": 0,
    },
    "continuation": [
        "time",
        "fence",
        "time",
        "authorize",
        "reserve",
        "provider",
        "settle",
        "fence",
        "time",
        "authorize",
        "reserve",
        "provider",
        "settle",
    ],
    "first": [
        "fence",
        "time",
        "authorize",
        "reserve",
        "provider",
        "settle",
        "fence",
        "time",
        "authorize",
        "reserve",
        "provider",
        "settle",
        "fence",
        "fence",
        "fence",
    ],
}


def profile_matrix():
    flags = [
        name
        for name, parameter in inspect.signature(_profile_with_options).parameters.items()
        if parameter.default is False
    ]
    rich = dict.fromkeys(flags, True)
    rich.update(extraction_atomic=False, extraction_atomic_v3=False)
    cases = [{}] + [{flag: True} for flag in flags]
    cases += [rich | {flag: False} for flag in flags]
    cases += [
        dict(source_ids=True, extraction_atomic=True, extraction_atomic_v3=True),
        dict(display_text_profile="glyph-joined-display-v1"),
        dict(display_text_profile="invalid"),
    ]
    cases += [
        options | dict(model=model, wire_policy_version=version)
        for model in ("solar-pro3", "solar-pro4", "openai/gpt-6-luna", "gpt-6-luna")
        for version in (1, 2)
        for options in ({}, rich)
    ]
    outcomes = []
    for options in cases:
        try:
            outcome = asdict(_profile_with_options(**options))
        except ValueError as error:
            outcome = str(error)
        outcomes.append(dict(options=options, outcome=outcome))
    return outcomes


def test_profile_options_hashes_suffix_order_and_invalid_codes_are_frozen():
    assert canonical_hash(profile_matrix()) == PROFILE_GOLDEN


def test_legacy_module_import_surface_is_preserved():
    from proofops_agent import upstage_extraction
    from proofops_agent.extraction_parts import contracts, profiles

    # These names were also exposed by the original facade, even though the
    # implementation now uses them in the policy/wire modules.
    names = {
        "re",
        "Callable",
        "MODEL_PRO4",
        "FAILURE_DIAGNOSTICS_POLICY",
        "ATOMIC_POLICY",
        "ATOMIC_POLICY_V3",
        "ATOMIC_PROFILE",
        "ATOMIC_PROFILE_V3",
        "atomic_candidates",
        "ROW_POLICY",
        "ROW_PROFILE",
        "row_candidates",
        "sentence_spans",
        "_require_sha256",
        "_require_uuid",
    }
    assert names <= vars(upstage_extraction).keys()
    assert upstage_extraction._profile_with_options is profiles._profile_with_options
    assert upstage_extraction._PROVIDER_METADATA_KEYS is contracts._PROVIDER_METADATA_KEYS


def receipt_case(tmp_path, mode):
    context = "context" in mode
    source_ids = "source" in mode
    probe = FakeProbe()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_context=context, extraction_source_ids=source_ids
    )
    data = packet()
    data["extraction_profile"] = asdict(extractor.profile)
    graph = None
    if context:
        graph, source_id = _extraction_context_graph(source_sha=data["source_sha256"])
        data["untrusted_document_data"]["source_id"] = source_id
    if source_ids:
        selected = extractor._sentence_index(TEXT, data["untrusted_document_data"]["source_id"])
        content = {"sentence_ids": [selected[0][0]]}
    else:
        content = {
            "claims": ["missing quote" if mode == "invalid" else "배출량을 20% 줄이기로 했다"]
        }
    probe.content = json.dumps(content, ensure_ascii=False)

    def invoke(target):
        try:
            return target.extract(data, context_graph=graph)
        except ValueError as error:
            return {"error": str(error)}

    output = invoke(extractor)
    files = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.json")}
    assert len(probe.calls) == 1
    second_probe = FakeProbe(error=AssertionError("replay must not call provider"))
    restarted = UpstageClaimExtractor(
        second_probe, tmp_path, extraction_context=context, extraction_source_ids=source_ids
    )
    assert invoke(restarted) == output
    assert not second_probe.calls
    assert files == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.json")}
    return dict(
        output=output,
        request=probe.calls[0],
        receipt_bytes={
            name: sha256(content).hexdigest() for name, content in sorted(files.items())
        },
    )


@pytest.mark.parametrize("mode", ["quote", "source", "context", "source_context", "invalid"])
def test_request_uuid_receipt_bytes_offsets_and_failed_replay_are_frozen(tmp_path, mode):
    assert canonical_hash(receipt_case(tmp_path, mode)) == RECEIPT_GOLDENS[mode]


def attempt_trace(tmp_path, monkeypatch):
    from proofops_worker import extract_runner

    from tests.acceptance.test_upload import TENANT
    from tests.integration.test_extract_batch_continuation import setup_run

    service, run_id, runner, _, probe, _ = setup_run(tmp_path, monkeypatch, paragraphs=4, limit=2)
    events = []

    def observe(owner, name, label):
        original = getattr(owner, name)

        def call(*args, **kwargs):
            events.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, call)

    observe(extract_runner, "fence_provider_call", "fence")
    observe(extract_runner, "rb3_admit", "time")
    observe(extract_runner, "check_local_upstage_binding", "authorize")
    observe(probe._client, "_reserve", "reserve")
    observe(probe._client, "_post", "provider")
    observe(probe._client, "_settle", "settle")
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    first = list(events)
    events.clear()
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "pending_downstream"
    assert events == []
    summary = runner.run_batch(tenant_id=TENANT, run_id=run_id)
    assert summary["status"] == "committed"
    assert len(summary["processed"]) == len(summary["replayed"]) == 2
    assert len(probe.calls) == 4
    usage = runner.extractor.usage
    return dict(
        first=first,
        continuation=events,
        accounting={
            key: usage[key]
            for key in (
                "model_calls",
                "reserved_calls",
                "settled_calls",
                "unsettled_calls",
                "input_tokens",
                "output_tokens",
                "cost_with_vat_reserve_usd",
            )
        },
    )


def test_first_and_continuation_guard_order_and_reserve_settle_counts(tmp_path, monkeypatch):
    assert attempt_trace(tmp_path, monkeypatch) == ATTEMPT_GOLDEN


def pilot_case(tmp_path, monkeypatch, mode):
    from evaluation import local_upstage_pilot as pilot

    parser = pilot._build_parser()
    args = parser.parse_args(["--state", str(tmp_path), "--parser", "local"])
    for name in ("j8", "i3_wire", "i4_identity", "qc_native_figures", "k6", "q1", "qt1"):
        setattr(args, "extraction_" + name, False)
    args.model = "solar-pro3" if mode == "legacy" else "gpt-6-luna"
    args.vision_parse = "auto"
    args.max_calls = 2
    if mode != "legacy":
        args.extraction_source_ids = args.extraction_context = True
    if mode == "rich":
        aliases = dict(
            year_notation="extraction_year_notation",
            source_ids="extraction_source_ids",
            assertion_prompt="extraction_assertion_prompt",
            complete_selection="extraction_complete_selection",
            position_order="position_context_order",
        )
        for name, parameter in inspect.signature(_profile_with_options).parameters.items():
            if parameter.default is False and name not in (
                "extraction_atomic",
                "extraction_atomic_v3",
            ):
                setattr(args, aliases.get(name, name), True)
    monkeypatch.setattr(pilot, "ROOT", Path("/a1-fixture"))
    manifest = tmp_path / "pilot.json"
    tmp_path.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        state=tmp_path,
        manifest_path=manifest,
        pages=[1, 2],
        claim_pages=[1],
        extraction_budget=pilot.extraction_budget_settings(2, 4),
        raster={},
    )
    settings, profile = pilot._prepare_run_settings(args, parser, **kwargs)
    assert settings["extraction_profile"] == profile
    saved = (tmp_path / "settings.json").read_bytes()
    assert json.loads(saved) == settings
    parser_bytes = (tmp_path / "parser.json").read_bytes()
    manifest.write_text('{"frozen": true}')
    args.extraction_source_ids = not args.extraction_source_ids
    assert pilot._prepare_run_settings(args, parser, **kwargs) == (None, None)
    assert (tmp_path / "settings.json").read_bytes() == saved
    assert (tmp_path / "parser.json").read_bytes() == parser_bytes
    assert manifest.read_bytes() == b'{"frozen": true}'
    return sha256(saved).hexdigest()


@pytest.mark.parametrize("mode", ["legacy", "source_context", "rich"])
def test_pilot_settings_bytes_and_resume_pins_are_frozen(tmp_path, monkeypatch, mode):
    assert pilot_case(tmp_path, monkeypatch, mode) == PILOT_GOLDENS[mode]
