"""CSV shape/reference checks only; never certifies semantic gold correctness."""

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).parent


def load(folder):
    tables = {}
    for template in sorted((ROOT / "templates").glob("*.csv")):
        with template.open(encoding="utf-8-sig", newline="") as handle:
            expected = next(csv.reader(handle))
        with (folder / template.name).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected:
                raise ValueError(f"{template.name}: header mismatch")
            rows = list(reader)
            if any(None in row or any(v is None for v in row.values()) for row in rows):
                raise ValueError(f"{template.name}: invalid column count")
            tables[template.stem] = rows
    return tables


def validate(tables, final=False):
    docs = {row["document_id"]: row for row in tables["corpus"]}
    claims = {row["claim_id"] for row in tables["claims"]}
    if len(docs) != len(tables["corpus"]) or len(claims) != len(tables["claims"]):
        raise ValueError("duplicate document_id/claim_id")
    splits = {}
    for row in tables["corpus"]:
        if not row["document_id"] or not row["company_id"]:
            raise ValueError("missing document/company identity")
        company = row["company_id"]
        if company in splits and splits[company] != row["split"]:
            raise ValueError("company split leakage")
        splits[company] = row["split"]
        if final and row["rights_status"] != "approved":
            raise ValueError("final corpus rights not approved")
    for row in tables["claims"]:
        if row["document_id"] not in docs or not row["claim_id"] or not row["quote"]:
            raise ValueError("invalid claim reference/quote")
    for name in ("elements", "numeric", "assurance", "reconciliation"):
        for row in tables[name]:
            if row["claim_id"] not in claims:
                raise ValueError(f"{name}: dangling claim_id")
    for row in tables["elements"]:
        if row["state"] not in {"present", "absent", "unknown", "conflict", "not_applicable"}:
            raise ValueError("invalid element state")
        if row["state"] == "present" and not (
            row["quote"]
            and row["physical_page"]
            and row["binding_reason"]
            and row["evidence_document_id"] in docs
        ):
            raise ValueError("present lacks source or binding")
        if row["state"] == "absent" and not row["searched_scope"]:
            raise ValueError("absent lacks search scope")
    for row in tables["reconciliation"]:
        if row["financial_document_id"] not in docs:
            raise ValueError("missing financial document")
        if row["expected_execution_state"] == "completed":
            if row["expected_status"] not in {"matched", "needs_explanation", "not_applicable"}:
                raise ValueError("invalid reconciliation status")
        elif (
            row["expected_execution_state"] not in {"blocked", "not_run"} or row["expected_status"]
        ):
            raise ValueError("blocked/not_run must not have status")
    return {name: len(rows) for name, rows in tables.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "examples")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    tables = load(args.folder)
    counts = validate(tables, args.final)
    if args.self_test:
        import copy

        for mutation in ("source", "split", "status", "claim"):
            broken = copy.deepcopy(tables)
            if mutation == "source":
                broken["elements"][0]["quote"] = ""
            elif mutation == "split":
                broken["corpus"][1]["split"] = "test"
            elif mutation == "status":
                broken["reconciliation"][0]["expected_status"] = "matched"
            else:
                broken["numeric"][0]["claim_id"] = "missing"
            try:
                validate(broken)
            except ValueError:
                pass
            else:
                raise AssertionError(f"failed to reject {mutation}")
    print(f"PASS: shape and references only; rows={counts}; semantic review still required")


if __name__ == "__main__":
    main()
