"""Read-only E2E8 source inventory; never imports a runtime/model client."""

import json
import sqlite3
from collections import Counter
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from proofops.adapters.parsing.parser_artifacts import parser_artifact_path

ROOT = Path("/path/to/ESG_ProofOps")
BASE = ROOT / "outputs/agent-results/R108-redesign/lab/sprint6/E2E8"
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/source/SV1"


def load_state(path):
    funnel = json.loads((path / "funnel.json").read_text())
    with sqlite3.connect((path / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT value FROM job_records WHERE kind='artifact' AND run_id=? "
            "AND record_id LIKE '%/checkpoint'",
            (funnel["run_id"],),
        ).fetchall()
    extract = [
        json.loads(v)
        for (v,) in rows
        if sha256(v).hexdigest() == funnel["checkpoint_pins"]["extract"]["sha256"]
    ]
    assert len(extract) == 1
    extract = extract[0]
    parse = [
        json.loads(v)
        for (v,) in rows
        if sha256(v).hexdigest() == extract["parse_checkpoint_sha256"]
    ]
    assert len(parse) == 1
    parse = parse[0]
    folder = (
        path
        / "parser-prepared"
        / extract["tenant_id"]
        / extract["document_version_id"]
        / extract["parse_manifest_id"]
    )
    candidates = parser_artifact_path(folder / "candidates.json")
    candidates_bytes = candidates.read_bytes()
    assert sha256(candidates_bytes).hexdigest() == parse["artifacts"][candidates.name]
    pdfs = [
        p
        for p in (path / "objects/original").glob("**/*.pdf")
        if not p.name.endswith(".display-v2.pdf")
        and sha256(p.read_bytes()).hexdigest() == extract["source_sha256"]
    ]
    assert len(pdfs) == 1
    return funnel, extract, parse, folder, pdfs[0]


def main():
    import pdfplumber
    import pypdfium2 as pdfium

    OUT.mkdir(parents=True, exist_ok=True)
    summary, rows = [], []
    for name, path in json.loads((BASE / "state-map.json").read_text()).items():
        funnel, extract, parse, folder, source = load_state(Path(path))
        reasons = Counter()
        with pdfplumber.open(source) as doc, pdfium.PdfDocument(source) as native:
            for claim in funnel["claims"]:
                if claim["source_verification"]["status"] == "verified":
                    continue
                reasons[claim["stop_reason"]] += 1
                for att in claim["source_verification"]["attestations"]:
                    ref = att["ref"]
                    box = ref["bbox"]
                    page = doc.pages[ref["page_num"] - 1]
                    with (
                        closing(native[ref["page_num"] - 1]) as np,
                        closing(np.get_textpage()) as tp,
                    ):
                        text = (
                            ""
                            if box is None
                            else tp.get_text_bounded(
                                box[0], page.height - box[3], box[2], page.height - box[1]
                            )
                        )
                    q = "".join(ref["quote"].split())
                    t = "".join(text.split())
                    rows.append(
                        dict(
                            state=name,
                            claim_id=claim["claim_id"],
                            old_reason=att["reason"],
                            ref=ref,
                            native_text=text,
                            whitespace_only_candidate=bool(q and t.count(q) == 1),
                            annotations=len(page.annots or []),
                            has_acroform="AcroForm" in doc.doc.catalog,
                            has_ocg="OCProperties" in doc.doc.catalog,
                            source_path=str(source),
                            source_sha256=extract["source_sha256"],
                        )
                    )
        summary.append(
            dict(
                state=name,
                total=funnel["summary"]["total"],
                verified=funnel["summary"]["source_verified"],
                losses=sum(reasons.values()),
                reasons=dict(reasons),
            )
        )
        print(name, dict(reasons), flush=True)
    (OUT / "before.json").write_text(
        json.dumps(dict(summary=summary, losses=rows), ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "| state | total | verified | lost | render | interactive | glyph | invalid |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        r = s["reasons"]
        lines.append(
            "| "
            + " | ".join(
                map(
                    str,
                    [
                        s["state"],
                        s["total"],
                        s["verified"],
                        s["losses"],
                        *[
                            r.get("SOURCE:" + k, 0)
                            for k in [
                                "rendered_quote_unresolved",
                                "interactive_visibility_requires_review",
                                "glyph_geometry_unresolved",
                                "source_invalid",
                            ]
                        ],
                    ],
                )
            )
            + " |"
        )
    (OUT / "loss-classification.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
