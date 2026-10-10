"""Lossless, scoped export-only sharing; stored search artifacts remain untouched."""

from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

ELEMENT_EVIDENCE_INLINE = "inline_element_evidence_v1"
ELEMENT_EVIDENCE_V1 = "shared_search_lists_quotes_sha256_v1"
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
SCOPE_KEYS = ("tenant_id", "run_id", "document_version_id", "parse_manifest_id", "source_sha256")
SEARCH_KEYS = ("profile_sha256", "document_search_sha256")
TABLE_KEYS = ("element_evidence_lists", "element_evidence_quotes", "element_evidence_records")
SEARCH_ENVELOPE = "__shared_search__"
QUOTE_ENVELOPE = "__shared_quote__"
LIST_FIELDS = ("hits", "native_candidates")


class ElementEvidenceExpansionLimit(ValueError):
    """Restored evidence exceeds the per-claim export byte limit."""


def _scope(identity):
    scope = {key: identity.get(key) for key in SCOPE_KEYS}
    if any(not isinstance(value, str) or not value for value in scope.values()):
        raise ValueError("element evidence scope is incomplete")
    return scope


def _search_scope(search, scope):
    pins = {key: search.get(key) for key in SEARCH_KEYS}
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
        for value in pins.values()
    ):
        raise ValueError("element evidence search pins are incomplete")
    return scope | pins


def _binding(record, claim_id, scope):
    if record.get("claim_id") != claim_id or any(
        record.get(key) != scope[key] for key in SCOPE_KEYS if key != "run_id"
    ):
        raise ValueError("element evidence claim scope mismatch")
    if "run_id" in record and record["run_id"] != scope["run_id"]:
        raise ValueError("element evidence run scope mismatch")
    revisions = {key: record.get(key) for key in ("tag_revision", "decision_revision")}
    if any(type(value) is not int or value < 0 for value in revisions.values()):
        raise ValueError("element evidence revision is invalid")
    return {"scope": scope, "claim_id": claim_id, **revisions}


def _put(table, scope, original, compact):
    digest = canonical_hash({"scope": scope, "value": original})
    entry = {"scope": dict(scope), "value": compact}
    if digest in table and canonical_json(table[digest]) != canonical_json(entry):
        raise ValueError("element evidence table hash collision")
    table[digest] = entry
    return "sha256:" + digest


def _envelope(value, name, refs):
    envelope = {"refs": refs}
    if name in value:
        envelope["original_value"] = value[name]
    return envelope


def _unpack(value, name, fields):
    compact = dict(value)
    envelope = compact.pop(name, None)
    if (
        not isinstance(envelope, dict)
        or set(envelope) not in ({"refs"}, {"refs", "original_value"})
        or not isinstance(envelope["refs"], dict)
        or set(envelope["refs"]) - set(fields)
        or set(envelope["refs"]) & set(compact)
    ):
        raise ValueError("invalid element evidence reference envelope")
    if "original_value" in envelope:
        compact[name] = envelope["original_value"]
    return compact, envelope["refs"]


def encode_element_evidence(record, manifest):
    """Encode a single captured claim and add only unique entries to the manifest."""
    scope = _scope(manifest)
    claim_id = record.get("claim_id")
    binding = _binding(record, claim_id, scope)
    evidence = record.get("element_evidence")
    if not isinstance(evidence, list):
        raise ValueError("element evidence must be an array")
    encoded = []
    for element in evidence:
        if not isinstance(element, dict) or not isinstance(element.get("search"), dict):
            raise ValueError("element evidence search is missing")
        search = element["search"]
        search_scope = _search_scope(search, scope)
        compact_search, references = dict(search), {}
        for field in LIST_FIELDS:
            if field not in search:
                continue
            items = search[field]
            if not isinstance(items, list):
                raise ValueError("element evidence search list is invalid")
            compact_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("element evidence search item is invalid")
                compact_item = dict(item)
                refs = {}
                if "quote" in item:
                    quote = item["quote"]
                    if not isinstance(quote, str):
                        raise ValueError("element evidence quote must be text")
                    refs["quote"] = _put(
                        manifest["element_evidence_quotes"], search_scope, quote, quote
                    )
                    del compact_item["quote"]
                compact_item[QUOTE_ENVELOPE] = _envelope(item, QUOTE_ENVELOPE, refs)
                compact_items.append(compact_item)
            references[field] = _put(
                manifest["element_evidence_lists"], search_scope, items, compact_items
            )
            del compact_search[field]
        compact_search[SEARCH_ENVELOPE] = _envelope(search, SEARCH_ENVELOPE, references)
        encoded.append(element | {"search": compact_search})
    binding["evidence_sha256"] = canonical_hash(evidence)
    manifest["element_evidence_records"][claim_id] = binding
    return record | {"element_evidence": encoded}


def _resolve(reference, table, scope, used):
    if (
        not isinstance(reference, str)
        or len(reference) != 71
        or not reference.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in reference[7:])
    ):
        raise ValueError("malformed element evidence reference")
    digest = reference[7:]
    entry = table.get(digest)
    if not isinstance(entry, dict) or set(entry) != {"scope", "value"}:
        raise ValueError("missing element evidence table entry")
    if entry["scope"] != scope:
        raise ValueError("element evidence table scope mismatch")
    used.add(digest)
    return digest, entry["value"]


def _restore_list(reference, scope, tables, used, byte_limit):
    digest, items = _resolve(reference, tables[0], scope, used[0])
    if not isinstance(items, list):
        raise ValueError("element evidence table must contain an array")
    restored, size = [], 2
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("element evidence search item is invalid")
        value, refs = _unpack(item, QUOTE_ENVELOPE, ("quote",))
        if "quote" in value:
            raise ValueError("inline quote under shared encoding")
        if "quote" in refs:
            quote_digest, quote = _resolve(refs["quote"], tables[1], scope, used[1])
            if (
                not isinstance(quote, str)
                or canonical_hash({"scope": scope, "value": quote}) != quote_digest
            ):
                raise ValueError("element evidence quote hash mismatch")
            value["quote"] = quote
        size += len(canonical_json(value).encode()) + bool(restored)
        if size > byte_limit:
            raise ElementEvidenceExpansionLimit("element evidence expansion exceeds 32 MiB")
        restored.append(value)
    if canonical_hash({"scope": scope, "value": restored}) != digest:
        raise ValueError("element evidence list hash mismatch")
    return restored, size


def iter_element_evidence(manifest, decisions):
    """Validate and restore one claim at a time; never expand the whole export."""
    encoding = manifest.get("element_evidence_encoding")
    if encoding not in (None, ELEMENT_EVIDENCE_V1):
        raise ValueError("unsupported element evidence encoding")
    if len(decisions) > 1000:
        raise ValueError("element evidence exceeds 1,000 claims")
    if encoding is None:
        if any(key in manifest for key in TABLE_KEYS):
            raise ValueError("element evidence tables have no encoding")
        for claim_id, record in decisions.items():
            if isinstance(record, dict) and "element_evidence" in record:
                evidence = record["element_evidence"]
                if not isinstance(evidence, list):
                    raise ValueError("element evidence must be an array")
                for item in evidence:
                    search = item.get("search") if isinstance(item, dict) else None
                    envelope = search.get(SEARCH_ENVELOPE) if isinstance(search, dict) else None
                    if (
                        isinstance(envelope, dict)
                        and isinstance(envelope.get("refs"), dict)
                        and set(envelope["refs"]) & set(LIST_FIELDS)
                        and not set(search) & set(LIST_FIELDS)
                    ):
                        raise ValueError("element evidence reference has no encoding")
                yield claim_id, evidence
        return
    scope = _scope(manifest)
    tables = tuple(manifest.get(key) for key in TABLE_KEYS)
    if any(not isinstance(table, dict) for table in tables):
        raise ValueError("element evidence tables are missing")
    used = (set(), set(), set())
    refs = {ref["claim_id"]: ref for ref in manifest["claim_revision_refs"]}
    for claim_id, record in decisions.items():
        if not isinstance(record, dict) or "element_evidence" not in record:
            continue
        expected = _binding(record, claim_id, scope)
        binding = tables[2].get(claim_id)
        if (
            not isinstance(binding, dict)
            or set(binding) != set(expected) | {"evidence_sha256"}
            or any(binding[key] != value for key, value in expected.items())
            or refs.get(claim_id)
            != {key: expected[key] for key in ("claim_id", "tag_revision", "decision_revision")}
        ):
            raise ValueError("element evidence claim/revision binding mismatch")
        used[2].add(claim_id)
        evidence = record["element_evidence"]
        if not isinstance(evidence, list):
            raise ValueError("element evidence must be an array")
        restored, expanded_bytes = [], 2
        for element in evidence:
            if not isinstance(element, dict) or not isinstance(element.get("search"), dict):
                raise ValueError("element evidence search is missing")
            search_scope = _search_scope(element["search"], scope)
            search, references = _unpack(element["search"], SEARCH_ENVELOPE, LIST_FIELDS)
            if set(search) & set(LIST_FIELDS):
                raise ValueError("inline search list under shared encoding")
            expanded_bytes += len(canonical_json(element | {"search": search}).encode()) + bool(
                restored
            )
            if expanded_bytes > MAX_EXPANDED_BYTES:
                raise ElementEvidenceExpansionLimit(
                    "element evidence claim expansion exceeds 32 MiB"
                )
            for field, reference in references.items():
                # Account for field name, colon and comma before materializing it.
                expanded_bytes += len(canonical_json(field).encode()) + 2
                value, size = _restore_list(
                    reference,
                    search_scope,
                    tables,
                    used,
                    MAX_EXPANDED_BYTES - expanded_bytes,
                )
                expanded_bytes += size
                search[field] = value
            restored.append(element | {"search": search})
        if len(canonical_json(restored).encode()) > MAX_EXPANDED_BYTES:
            raise ElementEvidenceExpansionLimit("element evidence claim expansion exceeds 32 MiB")
        if canonical_hash(restored) != binding["evidence_sha256"]:
            raise ValueError("element evidence restored hash mismatch")
        yield claim_id, restored
    if any(seen != set(table) for seen, table in zip(used, tables)):
        raise ValueError("unreferenced element evidence table entries")
