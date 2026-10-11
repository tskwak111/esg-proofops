"""Exact sentence-set and aligned consensus-state comparison, never accuracy."""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.pa3_replay import checkpoint


def inputs(directory):
    extract = checkpoint(directory, "extract")
    tag = checkpoint(directory, "tag")
    claims = extract["discovery"]["claims"]
    by_id = {c["claim_id"]: c for c in tag["claims"]}
    aligned = defaultdict(list)
    for claim in claims:
        key = (tuple(sorted({r["page_num"] for r in claim["source_refs"]})), claim["quote"])
        aligned[key].append((claim, by_id[claim["claim_id"]]))
    return extract, tag, aligned


def grade(claim):
    value = claim.get("decision") or claim.get("provisional_grade") or {}
    return value.get("evidence_grade") or "hold"


def states(claim):
    value = claim.get("decision") or claim.get("provisional_grade") or {}
    return {e["element_id"]: e["state"] for e in value.get("elements", [])}


def compare(first, second):
    a, ta, ca = inputs(first)
    b, tb, cb = inputs(second)
    sa = {c["quote"] for c in a["discovery"]["claims"]}
    sb = {c["quote"] for c in b["discovery"]["claims"]}
    common = sorted(ca.keys() & cb.keys())
    unambiguous = [k for k in common if len(ca[k]) == len(cb[k]) == 1]
    matches, total, changed = 0, 0, []
    grade_matches, absent_from_one = 0, 0
    for key in unambiguous:
        ac, bc = ca[key][0][1], cb[key][0][1]
        x, y = states(ac), states(bc)
        differences = []
        for element in sorted(x.keys() | y.keys()):
            total += 1
            if element not in x or element not in y:
                absent_from_one += 1
            if element in x and element in y and x[element] == y[element]:
                matches += 1
            else:
                differences.append(
                    dict(element=element, first=x.get(element), second=y.get(element))
                )
        grade_matches += grade(ac) == grade(bc)
        if differences or grade(ac) != grade(bc):
            changed.append(
                dict(
                    pages=key[0],
                    quote=key[1],
                    element_changes=differences,
                    first_grade=grade(ac),
                    second_grade=grade(bc),
                )
            )
    da = Counter(grade(c) for c in ta["claims"])
    db = Counter(grade(c) for c in tb["claims"])
    return dict(
        first=str(first),
        second=str(second),
        source_pdf_identical=a["source_sha256"] == b["source_sha256"],
        rulepack_identical=ta["rule_pack_sha256"] == tb["rule_pack_sha256"],
        first_claims=len(ta["claims"]),
        second_claims=len(tb["claims"]),
        sentences=dict(
            first=len(sa),
            second=len(sb),
            intersection=len(sa & sb),
            union=len(sa | sb),
            jaccard=len(sa & sb) / len(sa | sb),
            first_only=sorted(sa - sb),
            second_only=sorted(sb - sa),
        ),
        aligned_claims=len(unambiguous),
        ambiguous=len(common) - len(unambiguous),
        element_states=dict(
            matches=matches,
            compared=total,
            agreement=matches / total if total else None,
            missing_from_one=absent_from_one,
        ),
        aligned_grade_matches=grade_matches,
        first_grades=dict(da),
        second_grades=dict(db),
        grade_delta={k: db[k] - da[k] for k in sorted(da.keys() | db.keys())},
        grade_distribution_total_variation=0.5
        * sum(
            abs(da[k] / len(ta["claims"]) - db[k] / len(tb["claims"]))
            for k in da.keys() | db.keys()
        ),
        changed=changed,
        accuracy_claim=False,
        actual_confirmed_grades=[
            sum(c.get("decision") is not None for c in t["claims"]) for t in (ta, tb)
        ],
    )


def raw_model_compare(first, second, role="extract"):
    from proofops.domain.provenance import canonical_hash

    def load(directory):
        with sqlite3.connect(
            (directory / "live-luna.sqlite3").as_uri() + "?mode=ro", uri=True
        ) as db:
            receipts = {
                k: (s, json.loads(v))
                for k, s, v in db.execute("SELECT request_id,signature,receipt FROM probe_calls")
                if json.loads(v)["response_request"]["role"] == role
            }
        result = {}
        for key, (signature, r) in receipts.items():
            raw = json.loads(
                (
                    directory
                    / "live-luna.sqlite3.responses"
                    / (canonical_hash(f"{key}:{len(r['attempts'])-1}") + ".json")
                ).read_text()
            )["provider_response"]
            scope = r["response_request"]
            result[(signature, scope["replica"], scope["schema_sha256"])] = (
                signature,
                raw["choices"][0]["message"]["content"],
                raw.get("system_fingerprint"),
            )
        return result

    a, b = load(first), load(second)
    common = sorted(a.keys() & b.keys())
    return dict(
        first_requests=len(a),
        second_requests=len(b),
        matched_requests=len(common),
        same_wire=sum(a[k][0] == b[k][0] for k in common),
        identical_raw_content=sum(a[k][1] == b[k][1] for k in common),
        first_fingerprints=dict(Counter(str(v[2]) for v in a.values())),
        second_fingerprints=dict(Counter(str(v[2]) for v in b.values())),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    before = compare(
        root / "PA2/server/28fd07a4-5a26-42b9-926a-1963b76a4293",
        root / "PA2/server/a091ed1e-653c-4e29-9494-cd32cd912358",
    )
    after = compare(root / "PA4/fresh-a-final", root / "PA4/fresh-b-final")
    result = dict(
        before=before,
        after=after,
        raw_model={
            role: raw_model_compare(root / "PA4/fresh-a-final", root / "PA4/fresh-b-final", role)
            for role in ("extract", "preliminary", "relation", "elements")
        },
        scope="LG retained-parser inputs; fresh extraction and 3-replica tagging; exact quotes",
        controlled_before_pair=False,
        new_parameter="top_p=1 explicit; temperature=0 and reasoning_effort=none unchanged",
    )
    (root / "PA4/comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                k: {
                    x: v[x]
                    for x in [
                        "first_claims",
                        "second_claims",
                        "aligned_claims",
                        "element_states",
                        "first_grades",
                        "second_grades",
                        "grade_delta",
                    ]
                }
                for k, v in [("before", before), ("after", after)]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
