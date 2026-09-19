"""Caller-authorized local Upstage tagging transport; never approves sources or grades.

The probe owns the only monetary reservation. This adapter is not implicitly
installed in LocalTagRunner (which still requires its synthetic runtime contract).
Receipts are immutable; a failed/unknown transport durably stops this operation.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from time import monotonic_ns

from proofops.adapters.local.upstage import UPSTAGE_TRANSPORT_STOP_CODES, UpstageProbe
from proofops.application.budget import TokenUsage
from proofops.application.preflight import Preflight, PreflightBlocked
from proofops.application.tagging.service import RawTagResponse, TaggingSettings
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.values import _require_sha256, _require_uuid, _source_ref_from_dict

from proofops_agent.upstage_extraction import UpstageClaimExtractor

MODEL_PROFILE = "upstage-compact-ids-frozen-unicode-v1"
COVERAGE_PROFILE = "upstage-compact-coverage-unicode-v2"
QUOTE_PROFILE = "upstage-compact-source-quotes-v3"


class UpstageTaggingTransport:
    synthetic = False
    MODEL_PROFILE = MODEL_PROFILE
    TRANSPORT_VERSION = "compact-evidence-ids-v1"

    def __init__(
        self,
        probe: UpstageProbe,
        receipts: Path,
        *,
        settings: TaggingSettings,
        tenant_id: str,
        authorize: Callable[[TaggingSettings, dict], Preflight],
    ):
        _require_uuid("tenant_id", tenant_id)
        if (
            not isinstance(probe, UpstageProbe)
            or not isinstance(settings, TaggingSettings)
            or settings.binding.synthetic
            or settings.model_id != probe.model
            or settings.model_profile
            not in (
                {MODEL_PROFILE, COVERAGE_PROFILE, QUOTE_PROFILE}
                if self.MODEL_PROFILE == MODEL_PROFILE
                else {self.MODEL_PROFILE}
            )
            or settings.region != "provider-managed-unverified"
        ):
            raise ValueError("UPSTAGE_TAGGING_BINDING_INVALID")
        if not callable(authorize):
            raise ValueError("UPSTAGE_TAGGING_AUTHORIZER_REQUIRED")
        if settings.model_profile == COVERAGE_PROFILE:
            self.TRANSPORT_VERSION = "compact-coverage-v2"
        elif settings.model_profile == QUOTE_PROFILE:
            self.TRANSPORT_VERSION = "compact-source-quotes-v3"
        self._authorize = authorize
        self._probe, self._settings, self._tenant = probe, settings, tenant_id
        self._receipts = Path(receipts)
        self._receipts.mkdir(parents=True, exist_ok=True, mode=0o700)

    def invoke(self, request: dict) -> RawTagResponse:
        # One operation per receipt root; the shared USD ledger also fences all roots.
        with (self._receipts / ".operation.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self._failed("UPSTREAM_UNAVAILABLE", 0)
            return self._invoke(request)

    def count_input_tokens(self, request: dict, *, counter: Callable[[str, str], int]) -> int:
        """Count exactly the sent messages, using a caller-pinned provider counter.

        The counter must include model chat framing; no character/byte estimate
        or tokenizer from another model is supplied here. No receipt or paid call.
        """
        system, user, _, _ = self._wire_request(request)
        self._probe.request_body(
            system,
            user,
            request_id=request["request_id"],
            max_tokens=request["max_tokens"],
            json_mode=True,
        )
        return counter(system, user)

    def _authorize_request(self, request: dict) -> Preflight:
        settings = self._settings
        authorization = self._authorize(settings, request)
        if (
            not isinstance(authorization, Preflight)
            or authorization.ready is not True
            or any(check.status == "fail" for check in authorization.checks)
            or not {
                "runtime_approval",
                "consent_approval",
                "model_binding",
                "document_scope",
                "document_rights",
                "data_consent",
                "tagging_settings",
                "selected_document_rights",
            }
            <= {check.name for check in authorization.checks if check.status == "pass"}
        ):
            raise PreflightBlocked("UPSTAGE_TAGGING_AUTHORIZATION_REQUIRED")
        for name in ("tenant_id", "claim_id", "request_id"):
            _require_uuid(name, request[name])
        for name in ("packet_sha256", "request_signature"):
            _require_sha256(name, request[name])
        if (
            request["tenant_id"] != self._tenant
            or request["binding"] != asdict(settings.binding)
            or request["model_id"] != settings.model_id
            or request["model_profile"] != settings.model_profile
            or request["region"] != settings.region
            or request["temperature"] != 0
            or type(request["replicate_id"]) is not int
            or request["replicate_id"] not in (1, 2, 3)
            or type(request["max_tokens"]) is not int
            or not 1 <= request["max_tokens"] <= settings.max_tokens
        ):
            raise ValueError("UPSTAGE_TAGGING_REQUEST_INVALID")
        return authorization

    def _wire_request(self, request: dict) -> tuple[str, str, dict[str, dict], Preflight]:
        settings = self._settings
        authorization = self._authorize_request(request)
        system = request["system_prompt"]
        prefix = settings.rendered_system + "\nValidated classification; tag only its elements: "
        if not isinstance(system, str) or not system.startswith(prefix):
            raise ValueError("UPSTAGE_TAGGING_CLASSIFICATION_REQUIRED")
        classification = json.loads(system[len(prefix) :])
        if (
            not isinstance(classification, dict)
            or set(classification) != {"track", "safe_harbor_category"}
            or classification["track"] not in ("goal", "performance", "management")
            or classification["safe_harbor_category"]
            not in (None, "forward_looking", "emissions_estimate", "third_party_information")
        ):
            raise ValueError("UPSTAGE_TAGGING_CLASSIFICATION_INVALID")
        user = json.loads(request["user_json"])
        if (
            not isinstance(user, dict)
            or any(user.get(k) != request[k] for k in ("claim_id", "packet_sha256", "replicate_id"))
            or not isinstance(user.get("untrusted_document_data"), dict)
        ):
            raise ValueError("UPSTAGE_TAGGING_PACKET_MISMATCH")
        if settings.model_profile in (COVERAGE_PROFILE, QUOTE_PROFILE):
            data = user["untrusted_document_data"]
            coverage = data.get("search_coverage", {})
            if (
                not isinstance(coverage, dict)
                or coverage.get("not_found_state", "unknown") != "unknown"
            ):
                raise ValueError("UPSTAGE_TAGGING_COVERAGE_INVALID")
            summary: dict[str, str | int] = {"not_found_state": "unknown"}
            for prefix in ("omitted", "unprocessed"):
                ids = coverage.get(f"{prefix}_source_ids", [])
                if not isinstance(ids, list):
                    raise ValueError("UPSTAGE_TAGGING_COVERAGE_INVALID")
                for identifier in ids:
                    _require_uuid("coverage source_id", identifier)
                summary[f"{prefix}_source_count"] = len(ids)
                summary[f"{prefix}_source_ids_sha256"] = canonical_hash(ids)
            data["search_coverage"] = summary
        refs: dict[str, dict] = {}
        for candidate in user["untrusted_document_data"].get("evidence_candidates", []):
            identifiers = []
            for raw_ref in candidate.get("source_refs", []):
                ref = asdict(_source_ref_from_dict(raw_ref))
                identifier = f"e{len(refs)}"
                refs[identifier] = ref
                identifiers.append(identifier)
            candidate["source_refs"] = identifiers
        user["untrusted_document_data"]["evidence_catalog"] = {
            key: {field: ref[field] for field in ("quote", "page_num", "verification_state")}
            for key, ref in refs.items()
        }
        schema = json.loads(settings.schema_json)
        schema["$defs"]["SourceRef"] = {"type": "string", "pattern": "^e[0-9]+$"}
        if settings.model_profile == QUOTE_PROFILE:
            schema["$defs"]["SourceRef"] = {
                "type": "object",
                "required": ["id", "quote"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "enum": list(refs)},
                    "quote": {"type": "string", "minLength": 1},
                },
            }
        allowed = user["untrusted_document_data"].get("allowed_elements")
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(element, str) for element in allowed)
            or len(set(allowed)) != len(allowed)
        ):
            raise ValueError("UPSTAGE_TAGGING_ELEMENTS_REQUIRED")
        schema["properties"]["track"] = {"const": classification["track"]}
        schema["properties"]["safe_harbor_category"] = {
            "const": classification["safe_harbor_category"]
        }
        schema["$defs"]["Element"]["properties"]["element_id"] = {"enum": allowed}
        schema["properties"]["elements"].update(minItems=len(allowed), maxItems=len(allowed))
        instructions = (
            "\nTransport contract compact-evidence-ids-v1: evidence_refs contains only "
            "evidence_catalog IDs such as e0. Select IDs; never repeat or alter source text, "
            "coordinates, offsets or verification state. The server restores those exactly."
        )
        if settings.model_profile == QUOTE_PROFILE:
            instructions = (
                "\nTransport contract compact-source-quotes-v3: each evidence_refs item is "
                '{"id":"e0","quote":"exact source substring"}. Select an evidence_catalog '
                "ID and a non-empty exact quote occurring only once within that catalog quote. "
                "Include enough context to disambiguate repeated text. Never supply offsets, "
                "coordinates or verification state; the server restores provenance. "
                "A non-null normalized_value must equal one selected quote (NFC/whitespace "
                "normalization only), never a paraphrase or summary. Use a precise value quote "
                "for numerical elements and additional context quotes as needed; qualitative "
                "elements may use null normalized_value while retaining literal evidence. "
                "Exact quotation does not establish claim attribution or semantic sufficiency."
            )
        wire_system = system.replace(settings.schema_json, canonical_json(schema), 1) + instructions
        if settings.model_profile in (COVERAGE_PROFILE, QUOTE_PROFILE):
            wire_system += (
                "\nCoverage v2: omitted/unprocessed source counts and list hashes summarize "
                "unseen identifiers retained by the server. Missing evidence remains unknown; "
                "neither a count nor a hash is evidence or proof of absence."
            )
        wire_user = json.dumps(user, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return wire_system, wire_user, refs, authorization

    def _restore_ref(self, selection, refs: dict[str, dict]) -> dict:
        if self._settings.model_profile != QUOTE_PROFILE:
            return refs[selection]
        if not isinstance(selection, dict) or set(selection) != {"id", "quote"}:
            raise ValueError("invalid source quote selection")
        quote = selection["quote"]
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("non-empty source quote required")
        original = refs[selection["id"]]
        span = UpstageClaimExtractor._locate(quote, original["quote"])
        return original | dict(
            quote=quote,
            char_start=original["char_start"] + span["char_start"],
            char_end=original["char_start"] + span["char_end"],
        )

    def _invoke(self, request: dict) -> RawTagResponse:
        settings = self._settings
        system = request["system_prompt"]
        wire_system, wire_user, refs, authorization = self._wire_request(request)
        stop = self._receipts / "transport-stop.json"
        # ponytail: bounded local operation; index receipts if ensembles grow large.
        incomplete = any(
            child.is_dir() and not (child / "response.json").exists()
            for child in self._receipts.iterdir()
        )
        if stop.exists() or incomplete:
            return self._failed("UPSTREAM_UNAVAILABLE", 0)
        directory = self._receipts / request["request_id"]
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            raise ValueError("TAGGING_RECEIPT_EXISTS") from None
        write = UpstageClaimExtractor._write
        write(
            directory / "request.json",
            canonical_json(
                dict(
                    request=request,
                    request_sha256=canonical_hash(request),
                    model_sha256=settings.model_sha256,
                    prompt_sha256=canonical_hash(system),
                    wire_system=wire_system,
                    wire_user_json=wire_user,
                    wire_prompt_sha256=canonical_hash(wire_system),
                    transport_version=self.TRANSPORT_VERSION,
                    evidence_refs=refs,
                    authorization=authorization.to_dict(),
                )
            ),
        )
        started = monotonic_ns()
        try:
            receipt = self._probe.complete(
                wire_system,
                wire_user,
                request_id=request["request_id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
            )
        except Exception as error:
            code = str(error)
            if code not in UPSTAGE_TRANSPORT_STOP_CODES:
                code = "UPSTREAM_UNAVAILABLE"
            # Exclusive creation prevents overwriting an earlier failure receipt.
            if not stop.exists():
                write(stop, canonical_json(dict(code=code, request_id=request["request_id"])))
            response = self._failed(code, (monotonic_ns() - started) // 1_000_000)
        else:
            try:
                payload = json.loads(receipt["content"])
                for element in payload.get("elements", []):
                    selected = element["evidence_refs"]
                    if not isinstance(selected, list):
                        raise ValueError("invalid references")
                    element["evidence_refs"] = [self._restore_ref(key, refs) for key in selected]
                expanded = canonical_json(payload)
            except (ValueError, KeyError, TypeError, AttributeError):
                expanded = None
                receipt = {**receipt, "validation_error": "TAGGING_EVIDENCE_ID_INVALID"}
            response = RawTagResponse(
                expanded,
                TokenUsage(
                    receipt["input_tokens"],
                    receipt["output_tokens"],
                    0,
                    0,
                    (monotonic_ns() - started) // 1_000_000,
                    "succeeded",
                    receipt["provider_request_id"],
                ),
                False,
                canonical_json(receipt),
            )
        write(directory / "response.json", canonical_json(asdict(response)))
        return response

    @staticmethod
    def _failed(code: str, latency: int) -> RawTagResponse:
        return RawTagResponse(
            None,
            TokenUsage(None, None, None, None, latency, "failed", None, code),
            False,
            canonical_json(dict(error_code=code)),
        )
