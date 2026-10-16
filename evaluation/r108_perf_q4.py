"""Q4 literal candidate coverage and opt-in extraction-only R108 experiment.

AI provisional gold is read only for scoring, never for candidate selection or
prompts. Existing E2E3 receipts stay immutable. New proposals supplement saved
extraction; fresh selections are separately scored, with the unchanged matcher.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from proofops.adapters.parsing.parser_artifacts import (
    iter_parser_artifacts,
    parser_artifact_path,
    read_parser_json,
)
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_worker.extract_runner import select_stable_paragraph_sources

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
E2E = LAB / "sprint5/E2E3"
OUT = LAB / "perf"
COMPANIES = ("sk", "hyundai", "posco", "samsung", "naver", "kia")
INPUT_HASHES = {}


def read(path):
    path = parser_artifact_path(path)
    raw = path.read_bytes()
    INPUT_HASHES[str(path)] = hashlib.sha256(raw).hexdigest()
    return read_parser_json(path)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def matcher():
    p = LAB / "sprint4/SC/score_r108.py"
    INPUT_HASHES[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("q4_matcher", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineProbe:
    model = "openai/gpt-6-luna"
    wire_policy_version = 2

    def complete(self, *args, **kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")


def setup(company, directory):
    state = E2E / "states" / (company + "-attempt3")
    settings = read(state / "settings.json")
    manifest = read(state / "pilot.json")
    graph_path = next(iter_parser_artifacts(state, "graph.json"))
    gm = read(graph_path.parent / "manifest.json")
    candidates = candidates_from_snapshot(read(graph_path.parent / "candidates.json"))
    graph = fuse_candidates(
        candidates, tenant_id=manifest["tenant_id"], fusion_version=gm.get("fusion_version", 1)
    )
    assert graph.to_dict() == read(graph_path)
    source = Path(manifest["source_path"])
    INPUT_HASHES[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    assert INPUT_HASHES[str(source)] == graph.source_sha256
    opts = {
        name: settings.get(name, False)
        for name in (
            "extraction_year_notation",
            "extraction_context",
            "extraction_table_context",
            "extraction_source_ids",
            "extraction_assertion_prompt",
            "extraction_complete_selection",
            "extraction_content_bounds",
            "extraction_atomic",
        )
    }
    opts["position_order"] = "position_context_order" in settings
    # Candidate coverage is over raw source offsets. Display glyph repairs are
    # intentionally not transplanted into row quotes or unrelated parent spans.
    extractor = UpstageClaimExtractor(
        OfflineProbe(),
        directory / company,
        **opts,
        extraction_table_rows=True,
        extraction_recall_prompt=True,
    )
    base_opts = opts | (
        {"display_text_profile": "glyph-joined-display-v1"}
        if "display_text_policy" in settings
        else {}
    )
    original_extractor = UpstageClaimExtractor(
        OfflineProbe(), directory / (company + "-baseline"), **base_opts
    )
    assert asdict(original_extractor.profile) == settings["extraction_profile"]
    baseline = []
    for p in sorted(state.glob("extraction-receipts/*/result.json")):
        r, packet, raw = (
            read(p),
            read(p.with_name("packet.json")),
            read(p.with_name("raw_response.json")),
        )
        assert r["packet_sha256"] == canonical_hash(packet)
        assert r["content_sha256"] == canonical_hash(raw["content"])
        assert r["profile"] == settings["extraction_profile"]
        data = packet["untrusted_document_data"]
        restored, _ = original_extractor._resolve_payload(
            json.loads(raw["content"]), data["text"], data["source_id"], packet=packet
        )
        assert [asdict(span) | {"topic_ids": list(span.topic_ids)} for span in restored] == r[
            "spans"
        ]
        baseline.extend(
            dict(
                company_id=company,
                page_num=data["page_num"],
                source_id=data["source_id"],
                quote=s["quote"],
                char_start=s["char_start"],
                char_end=s["char_end"],
                claim_id=f"{company}:{data['source_id']}:{s['char_start']}:{s['char_end']}",
            )
            for s in r["spans"]
            if s["kind"] == "claim"
        )
    scope = SimpleNamespace(
        mode="declared_subset",
        selected_pages=manifest.get("claim_pages") or manifest["selected_pages"],
    )
    base_ids = select_stable_paragraph_sources(graph, scope, 256)
    row_ids = select_stable_paragraph_sources(graph, scope, 256, extraction_table_rows=True)
    entries, before = [], []
    for block in graph.blocks:
        if block.source_id not in row_ids | base_ids:
            continue
        packet = dict(
            tenant_id=graph.tenant_id,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            source_sha256=graph.source_sha256,
            extraction_profile=asdict(extractor.profile),
            untrusted_document_data=dict(
                source_id=block.source_id,
                page_num=block.page_num,
                kind=block.kind,
                text=block.normalized_text,
            ),
        )
        contexts, omissions = (
            extractor._context_for(packet, graph) if extractor._context else ([], [])
        )
        try:
            if block.source_id in base_ids:
                before.extend(
                    dict(
                        company_id=company,
                        page_num=block.page_num,
                        quote=block.normalized_text[a:b],
                        claim_id=sid,
                    )
                    for sid, (a, b) in extractor._sentence_index(
                        block.normalized_text, block.source_id, extractor._content_bounds
                    )
                )
            planned = extractor._row_entries(packet, block.normalized_text, contexts)
        except ValueError:
            continue
        for entry in planned:
            # Parent axes/nearby context belong to this source only. They have
            # no IDs and never enter the source span or matcher quote.
            if "parent_context" not in entry:
                entry = entry | {"parent_context": contexts}
            entries.append(
                dict(
                    company_id=company,
                    page_num=block.page_num,
                    source_id=block.source_id,
                    kind=block.kind,
                    entry=entry,
                    packet=packet,
                    omitted_source_ids=omissions,
                )
            )
    after = [
        dict(
            company_id=company,
            page_num=e["page_num"],
            quote=e["entry"]["text"],
            claim_id=e["entry"]["sentence_id"],
        )
        for e in entries
    ]
    return dict(
        graph=graph,
        extractor=extractor,
        baseline=baseline,
        before=before,
        after=after,
        entries=entries,
        new_sources=sorted(row_ids - base_ids),
        scope=list(scope.selected_pages),
    )


def coverage(quote, texts, m):
    from difflib import SequenceMatcher

    quote = m.norm(quote)
    chars = set()
    for text in texts:
        text = m.norm(text)
        if quote and quote in text:
            return 1.0
        for a, _, size in SequenceMatcher(None, quote, text, autojunk=False).get_matching_blocks():
            if size >= 8:
                chars.update(range(a, a + size))
    return len(chars) / len(quote) if quote else 0.0


def score(gold, rows, m):
    normalized = [m.normalize_claim(r) for r in rows]
    gm, _ = m.align(gold, normalized, threshold=0.82)
    return dict(
        TP=len(gm),
        FP=len(rows) - len(gm),
        FN=len(gold) - len(gm),
        claims=len(rows),
        precision=len(gm) / len(rows) if rows else None,
        recall=len(gm) / len(gold) if gold else None,
        matched_ids=sorted(gold[i]["claim_id"] for i in gm),
    )


def preflight(all_data, gold, m):
    result = {}
    for c, data in all_data.items():
        g = [r for r in gold if r["_company"] == c]
        row = dict(
            scope=data["scope"],
            baseline_claims=len(data["baseline"]),
            before_candidates=len(data["before"]),
            after_candidates=len(data["after"]),
            added_sources=len(data["new_sources"]),
            after_kinds=dict(Counter(e["kind"] for e in data["entries"])),
        )
        from proofops.application.ingest.table_row_candidates import row_candidates

        row["quality_excluded_structural_sources"] = [
            {
                "source_id": b.source_id,
                "page_num": b.page_num,
                "quality": b.quality,
                "row_candidates": len(row_candidates(b.normalized_text, kind=b.kind)),
            }
            for b in data["graph"].blocks
            if b.page_num in data["scope"]
            and b.quality not in ("verified", "unverified")
            and row_candidates(b.normalized_text, kind=b.kind)
        ]
        row["added_candidate_examples"] = [
            {
                "source_id": e["source_id"],
                "page_num": e["page_num"],
                "kind": e["kind"],
                "quote": e["entry"]["text"],
            }
            for e in data["entries"]
            if e["source_id"] in data["new_sources"]
        ][:3]
        if g:
            row["baseline"] = score(g, data["baseline"], m)
            row["candidate_before"] = score(g, data["before"], m)
            row["candidate_after"] = score(g, data["after"], m)
            for label in ("before", "after"):
                row["literal_coverage_" + label] = [
                    r["claim_id"]
                    for r in g
                    if coverage(
                        r["_quote"],
                        [e["quote"] for e in data[label] if e["page_num"] == r["_page"]],
                        m,
                    )
                    >= 0.9
                ]
            row["newly_covered"] = sorted(
                set(row["literal_coverage_after"]) - set(row["literal_coverage_before"])
            )
        else:
            row["noise_note"] = (
                "No gold used for NAVER/Kia; counts are candidate noise proxies, not precision."
            )
        result[c] = row
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--invoke", action="store_true")
    ap.add_argument(
        "--replay",
        action="store_true",
        help="Replay saved paid selections under final profiles; no calls",
    )
    args = ap.parse_args()
    m = matcher()
    gold, synthetic = m.normalize_gold(read(LAB / "gold-v1/draft.json"))
    assert synthetic
    with tempfile.TemporaryDirectory() as tmp:
        data = {c: setup(c, Path(tmp)) for c in COMPANIES}
        offline = preflight(data, gold, m)
        save(
            OUT / "Q4-candidates.json",
            dict(
                gold_label="SYNTHETIC provisional AI draft; not human accuracy",
                matcher_threshold=0.82,
                matching="unchanged official greedy 1:1",
                companies=offline,
            ),
        )
        print(
            json.dumps(
                {
                    c: {
                        k: v
                        for k, v in r.items()
                        if k
                        in (
                            "before_candidates",
                            "after_candidates",
                            "added_sources",
                            "newly_covered",
                        )
                    }
                    for c, r in offline.items()
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.replay:
            replay_final(data)
        if args.invoke:
            if not any(offline[c]["newly_covered"] for c in COMPANIES[:3]):
                raise ValueError("NO_FREE_CANDIDATE_IMPROVEMENT")
            paid(data, gold, m, offline)
        unchanged = all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in INPUT_HASHES.items()
        )
        assert unchanged
        save(OUT / "Q4-input-hashes.json", dict(unchanged=unchanged, files=INPUT_HASHES))


def provider_rows(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return {
            rid: (Decimal(v), receipt)
            for rid, v, receipt in db.execute(
                "select request_id,committed,receipt from probe_calls"
            )
        }


def batch_wire(items):
    return json.dumps(
        {
            "untrusted_document_data": {
                "source_sentences": [
                    e["entry"]
                    | {"source_id": e["source_id"], "page_num": e["page_num"], "kind": e["kind"]}
                    for e in items
                ]
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def plan_batches(entries):
    batches, current = [], []
    # Stable document/page/source ordering, independent of gold or matching.
    for e in sorted(
        entries, key=lambda e: (e["page_num"], e["source_id"], e["entry"]["char_start"])
    ):
        if len(current) >= 12 or len(batch_wire(current + [e]).encode()) > 8500:
            if current:
                batches.append(current)
            current = []
        if len(batch_wire([e]).encode()) > 8500:
            raise ValueError("Q4_SINGLE_CANDIDATE_TOO_LARGE")
        current.append(e)
    if current:
        batches.append(current)
    return batches


def merge_proposals(baseline, fresh):
    # A new immutable comparison artifact retains the baseline exactly. New
    # row/cell aliases are deduplicated by exact page/quote, never fuzzy match.
    result = list(baseline)
    seen = {(r["page_num"], r["quote"]) for r in baseline}
    for r in fresh:
        key = r["page_num"], r["quote"]
        if key not in seen:
            result.append(r)
            seen.add(key)
    return result


def paid(data, gold, m, offline):
    from proofops.adapters.local.openrouter import POLICY as TRANSPORT_POLICY
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops_agent.upstage_extraction import _system_prompt

    cap = Decimal(".40")
    reserve = Decimal(TRANSPORT_POLICY["reservation_usd"])
    ledger = ROOT / ".local/openrouter/budget.sqlite3"
    r108 = LAB / "sprint3/E2E/r108-spend.json"
    calls_before = provider_rows(ledger)
    historic = sum(
        (
            Decimal(v["unsettled_usd"])
            for v in json.loads(r108.read_text())["initial_ledgers"].values()
        ),
        Decimal(0),
    )
    paid_root = OUT / "Q4-paid"
    paid_root.mkdir(mode=0o700, exist_ok=False)
    execution_id = str(uuid4())
    execution = dict(
        task="perf-Q4",
        execution_id=execution_id,
        limit_usd=str(cap),
        delta_usd="0",
        actual_settled_delta_usd="0",
        new_unsettled_usd="0",
        status="reserved",
        company="sk/hyundai/posco/samsung",
        reservation_usd=str(cap),
        scope="extraction only; no parse/tag/decision",
        calls=[],
        baseline_provider_call_count=len(calls_before),
    )
    lock_path = r108.with_suffix(".decisions.lock")

    def update_execution(initial=False):
        # Re-read the shared record every time; preserve other task entries.
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = json.loads(r108.read_text())
            prior = next(
                (x for x in d["executions"] if x.get("execution_id") == execution_id), None
            )
            old = (
                Decimal(prior.get("r108_committed_usd", prior["delta_usd"]))
                if prior
                else Decimal(0)
            )
            outstanding = sum(
                (
                    Decimal(x.get("reservation_usd", "0"))
                    for x in d["executions"]
                    if x.get("status") in ("reserved", "running")
                    and x.get("execution_id") != execution_id
                ),
                Decimal(0),
            )
            if initial:
                assert not any(x.get("task") == "perf-Q4" for x in d["executions"])
                assert Decimal(d["cumulative_usd"]) + historic + outstanding + cap <= Decimal(
                    d["limit_usd"]
                )
            now = provider_rows(ledger)
            our = {rid: now[rid] for rid in execution["calls"] if rid in now}
            charged = sum((v for v, _ in our.values()), Decimal(0))
            unsettled = sum((v for v, receipt in our.values() if receipt is None), Decimal(0))
            assert charged <= cap
            booked = cap if execution["status"] in ("reserved", "running") else charged
            if Decimal(d["cumulative_usd"]) - old + booked + historic > Decimal(d["limit_usd"]):
                raise ValueError("R108_BUDGET_EXHAUSTED")
            execution.update(
                r108_committed_usd=str(booked),
                delta_usd=str(charged),
                actual_settled_delta_usd=str(charged - unsettled),
                new_unsettled_usd=str(unsettled),
                reservation_usd=str(cap - charged)
                if execution["status"] in ("reserved", "running")
                else "0",
            )
            if prior:
                prior.clear()
                prior.update(execution)
            else:
                d["executions"].append(dict(execution))
            d["cumulative_usd"] = str(Decimal(d["cumulative_usd"]) - old + booked)
            save(r108, d)
            save(paid_root / "execution.json", execution)
            return charged

    update_execution(initial=True)
    # Credential read stays local to the existing authorized connector input.
    key = next(
        line.split("=", 1)[1].strip().strip('"').strip("'")
        for line in (ROOT / ".env.openrouter.local").read_text().splitlines()
        if line.startswith("OPENROUTER_API_KEY=")
    )
    probe = OpenRouterProbe(key, ledger, wire_policy_version=2)
    execution["status"] = "running"
    all_fresh, all_combined, all_baseline, results = [], [], [], {}
    try:
        for c in COMPANIES[:4]:
            d = data[c]
            extractor = d["extractor"]
            system = _system_prompt(
                extraction_context=extractor._context,
                extraction_table_context=extractor._table_context,
                source_ids=True,
                assertion_prompt=extractor._assertion_prompt,
                complete_selection=extractor._complete_selection,
                extraction_table_rows=True,
                extraction_recall_prompt=True,
            )
            # Same profile prompt bytes as production. The batch puts each
            # source's parent context on its own entry; contexts have no IDs.
            assert canonical_hash(system) == extractor.profile.prompt_sha256
            fresh, attempts = [], []
            for number, items in enumerate(plan_batches(d["entries"])):
                spent = update_execution()
                if spent + reserve > cap:
                    raise ValueError("Q4_BUDGET_EXHAUSTED")
                rid = str(uuid4())
                execution["calls"].append(rid)
                update_execution()  # durable R108 request registration before dispatch
                folder = paid_root / c / str(number)
                folder.mkdir(parents=True)
                request = dict(
                    request_id=rid,
                    profile=asdict(extractor.profile),
                    system_prompt=system,
                    user_json=batch_wire(items),
                    max_tokens=1024,
                    wire_policy="q4-batched-source-ids-v1",
                    packets=[e["packet"] for e in items],
                )
                save(folder / "request.json", request)
                event = dict(request_id=rid, candidate_count=len(items), status="failed")
                try:
                    response = probe.complete(
                        system,
                        request["user_json"],
                        request_id=rid,
                        max_tokens=1024,
                        json_mode=True,
                    )
                    save(folder / "response.json", response)
                    payload = json.loads(response["content"])
                    allowed = {e["entry"]["sentence_id"]: e for e in items}
                    if (
                        not isinstance(payload, dict)
                        or set(payload) != {"sentence_ids"}
                        or not isinstance(payload["sentence_ids"], list)
                        or any(
                            not isinstance(s, str) or s not in allowed
                            for s in payload["sentence_ids"]
                        )
                        or len(set(payload["sentence_ids"])) != len(payload["sentence_ids"])
                    ):
                        raise ValueError("Q4_INVALID_SELECTION")
                    selected = []
                    # Resolve per source with production's exact-span validator,
                    # not a relaxed evaluator quote/offset implementation.
                    by_source = {}
                    for sid in payload["sentence_ids"]:
                        e = allowed[sid]
                        by_source.setdefault(e["source_id"], []).append(sid)
                    for source_id, ids in by_source.items():
                        e = next(e for e in items if e["source_id"] == source_id)
                        packet = e["packet"]
                        spans, rejected = extractor._resolve_payload(
                            {"sentence_ids": ids},
                            packet["untrusted_document_data"]["text"],
                            source_id,
                            packet=packet,
                            context_graph=d["graph"],
                        )
                        for s in spans:
                            if s.kind == "claim":
                                block = next(
                                    b for b in d["graph"].blocks if b.source_id == source_id
                                )
                                ref = asdict(
                                    block.source_ref(
                                        normalized_char_start=s.char_start,
                                        normalized_char_end=s.char_end,
                                    )
                                )
                                selected.append(
                                    dict(
                                        company_id=c,
                                        page_num=e["page_num"],
                                        source_id=source_id,
                                        quote=s.quote,
                                        char_start=s.char_start,
                                        char_end=s.char_end,
                                        source_ref=ref,
                                        source_quality=block.quality,
                                        binding_status="undetermined",
                                        eligible_for_scoring=False,
                                        source_attestation="not_run",
                                        claim_id=f"{c}:{source_id}:{s.char_start}:{s.char_end}",
                                    )
                                )
                    fresh.extend(selected)
                    event.update(status="passed", selected=len(selected))
                    save(folder / "validation.json", dict(claims=selected, event=event))
                except ValueError as error:
                    code = str(error)
                    # Only finite public failure codes, never provider/key payloads.
                    event["error"] = (
                        code
                        if code
                        in (
                            "Q4_INVALID_SELECTION",
                            "PROBE_REQUEST_TOO_LARGE",
                            "OPENROUTER_REQUEST_FAILED",
                            "UPSTAGE_RECEIPT_INVALID_RESERVATION_RETAINED",
                        )
                        else "MODEL_SPAN_OR_SCHEMA_INVALID"
                    )
                    save(folder / "failure.json", event)
                    if code in (
                        "BUDGET_EXHAUSTED",
                        "OPENROUTER_REQUEST_FAILED",
                        "OPENROUTER_HTTP_401",
                        "OPENROUTER_HTTP_403",
                    ):
                        raise ValueError("Q4_TRANSPORT_STOP") from None
                finally:
                    attempts.append(event)
                    update_execution()
                print(
                    c,
                    number,
                    event["status"],
                    "selected",
                    event.get("selected", 0),
                    "cost",
                    execution["delta_usd"],
                    flush=True,
                )
            combined = merge_proposals(d["baseline"], fresh)
            g = [r for r in gold if r["_company"] == c]
            before = score(g, d["baseline"], m)
            after = score(g, combined, m)
            lost = sorted(set(before["matched_ids"]) - set(after["matched_ids"]))
            assert not lost
            results[c] = dict(
                before=before,
                fresh=score(g, merge_proposals([], fresh), m),
                after=after,
                existing_match_losses=lost,
                attempts=attempts,
            )
            save(
                paid_root / c / "claims.json",
                dict(baseline=d["baseline"], fresh=fresh, combined=combined),
            )
            all_fresh.extend(merge_proposals([], fresh))
            all_combined.extend(combined)
            all_baseline.extend(d["baseline"])
            print(c, "TP", before["TP"], "->", after["TP"], flush=True)
        execution["status"] = "complete"
    except BaseException:
        execution["status"] = "stopped"
        raise
    finally:
        update_execution()
        groups = {}
        for label, companies in (("unexposed", COMPANIES[:3]), ("samsung", ("samsung",))):
            g = [r for r in gold if r["_company"] in companies]

            def rows(values):
                return [r for r in values if r["company_id"] in companies]

            groups[label] = dict(
                before=score(g, rows(all_baseline), m),
                fresh=score(g, rows(all_fresh), m),
                after=score(g, rows(all_combined), m),
            )
        save(
            OUT / "Q4-analysis.json",
            dict(
                companies=results,
                groups=groups,
                execution=execution,
                interpretation=(
                    "Extraction-only additive experiment; saved E2E3 claims retained, "
                    "no receipt or revision overwritten. Fresh batch results scored separately. "
                    "No tag/attestation/decision improvement claimed."
                ),
                candidate_measurement=offline,
                input_hashes=INPUT_HASHES,
            ),
        )


def replay_final(data):
    """New replay record; paid requests and responses retain their original hashes."""
    results = {}
    for c in COMPANIES[:4]:
        d = data[c]
        by_id = {e["entry"]["sentence_id"]: e for e in d["entries"]}
        requested = set()
        selected_spans = 0
        for p in sorted((OUT / "Q4-paid" / c).glob("*/request.json")):
            request = read(p)
            old_entries = json.loads(request["user_json"])["untrusted_document_data"][
                "source_sentences"
            ]
            for old in old_entries:
                sid = old["sentence_id"]
                new = by_id[sid]
                expected = new["entry"] | {
                    "source_id": new["source_id"],
                    "page_num": new["page_num"],
                    "kind": new["kind"],
                }
                assert old == json.loads(json.dumps(expected))
                requested.add(sid)
            assert request["profile"]["prompt_sha256"] == d["extractor"].profile.prompt_sha256
            response = read(p.with_name("response.json"))
            validation = read(p.with_name("validation.json"))
            payload = json.loads(response["content"])
            actual = []
            for source_id in sorted({by_id[s]["source_id"] for s in payload["sentence_ids"]}):
                ids = [s for s in payload["sentence_ids"] if by_id[s]["source_id"] == source_id]
                packet = by_id[ids[0]]["packet"]
                spans, rejected = d["extractor"]._resolve_payload(
                    {"sentence_ids": ids},
                    packet["untrusted_document_data"]["text"],
                    source_id,
                    packet=packet,
                    context_graph=d["graph"],
                )
                actual.extend(
                    (source_id, s.char_start, s.char_end, s.quote)
                    for s in spans
                    if s.kind == "claim"
                )
            expected = [
                (r["source_id"], r["char_start"], r["char_end"], r["quote"])
                for r in validation["claims"]
            ]
            assert sorted(actual) == sorted(expected)
            selected_spans += len(actual)
        assert requested == set(by_id)
        results[c] = dict(
            candidates_unchanged=len(requested),
            spans_unchanged=selected_spans,
            final_profile=asdict(d["extractor"].profile),
        )
    save(
        OUT / "Q4-final-replay.json",
        dict(
            companies=results,
            paid_calls=0,
            note=(
                "Final header safeguard narrows ambiguous first data rows. "
                "Saved evaluation candidates and resolved results are identical; "
                "earlier receipts are not rewritten."
            ),
        ),
    )


if __name__ == "__main__":
    main()
