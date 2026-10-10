"""Shared pending document bindings for operator selections and claim packets."""

from copy import deepcopy


def documents_for_packet(packet, *, templates=None):
    """Canonical draft bindings shared with the candidate preparation path."""
    identity = packet["identity"]
    roles = {}

    def role(source_id, name):
        if source_id:
            roles.setdefault(source_id, set()).add(name)

    role(packet["claim"]["source_id"], "claim")
    role(packet["sustainability"]["source_id"], "sustainability_fact")
    role(packet["financial"]["source_id"], "financial_fact")
    role(packet["explanation"]["source_id"], "explanation")
    for key, name in (
        ("commitment_source_id", "c3_commitment"),
        ("funding_plan_source_id", "c3_funding"),
    ):
        role((packet.get("c3_context") or {}).get(key), name)
    for key, name in (
        ("definition_source_ids", "c4_definition"),
        ("calculation_source_ids", "c4_calculation"),
    ):
        for source_id in (packet.get("c4_context") or {}).get(key, []):
            role(source_id, name)
    decision = {
        key: deepcopy(packet[key])
        for key in ("item", "comparability", "claim", "c3_context", "c4_context")
    }
    decision["claim_id"] = identity["claim_id"]
    documents = {}
    for document_id in sorted({ref["document_id"] for ref in packet["sources"]}):
        financial = document_id == identity["financial_document_version"]
        refs = [ref for ref in packet["sources"] if ref["document_id"] == document_id]
        base = deepcopy((templates or {}).get(document_id, {}))
        base.update(
            tenant_id=identity["tenant_id"],
            company_id=identity["company_id"],
            package_id=identity["package_id"],
            document_version_id=document_id,
            document_role="financial" if financial else "sustainability",
            artifact_sha256=refs[0]["artifact_sha256"],
            corp_code=identity["dart_corp_code"],
            fiscal_year=identity["financial_fiscal_year"],
            rcept_no=identity["rcept_no"] if financial else None,
            consolidation=identity["consolidation"],
            as_of_date=identity["as_of_date"],
            published_at=identity["financial_published_at" if financial else "sr_published_at"],
            available_on=identity["financial_published_at" if financial else "sr_published_at"],
            period_start=identity["financial_period_start" if financial else "period_start"],
            period_end=identity["financial_period_end" if financial else "period_end"],
            relevant_items=[packet["item"]],
            synthetic=packet["synthetic"],
            decision_binding=deepcopy(decision),
            binding_state="draft",
        )
        bindings, facts = {}, {}
        for ref in refs:
            sid = ref["source_id"]
            bindings[sid] = dict(
                locator=ref["locator"], quote=ref["quote"], roles=sorted(roles.get(sid, set()))
            )
            for fact in (packet["sustainability"], packet["financial"]):
                if fact["source_id"] == sid:
                    facts[sid] = {key: fact[key] for key in ("raw", "normalized", "kind", "unit")}
        base.update(source_bindings=bindings, fact_bindings=facts)
        documents[document_id] = base
    return documents
