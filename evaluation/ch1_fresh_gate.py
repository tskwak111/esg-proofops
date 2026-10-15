"""Fresh Linux ARM64 raster-PDF -> generated OCR sim -> CH1 -> strict replay.

No saved response or production key is read. Tesseract reads each newly rendered
PNG and a simulation transport wraps that output in the Upstage schema. Simulated
confidence is deliberately marked as such: this proves wiring, not accuracy of
Upstage or a real model. Test collections live only in the output's private ledger.
"""

import argparse
import csv
import io
import json
import platform
import subprocess
import uuid
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from proofops.adapters.local.ch1_charts import extract, policy, replay
from proofops.adapters.local.upstage import UpstageProbe
from proofops.adapters.local.upstage_ocr_page import PageOCRStore
from proofops.domain.provenance import canonical_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Linux", "aarch64"):
        raise ValueError("CH1_LINUX_ARM64_REQUIRED")
    args.output.mkdir(parents=True, exist_ok=False)
    nonce = uuid.uuid4().hex
    values = [320 + int(nonce[:3], 16) % 100, 530 + int(nonce[3:6], 16) % 100]
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    pages = []
    layouts = []
    for number, kind in enumerate(("bar", "line", "pie", "image_table"), 1):
        image = Image.new("RGB", (600, 400), "white")
        draw = ImageDraw.Draw(image)
        draw.text((30, 20), "Carbon", font=font, fill="black")
        draw.text((450, 20), "GWh", font=font, fill="black")
        if kind == "pie":
            draw.pieslice((220, 90, 360, 230), 0, 288, fill="#dddddd", outline="black")
            draw.text((235, 255), "80%", font=font.font_variant(size=40), fill="black")
            draw.text((240, 340), "2024", font=font, fill="black")
        else:
            for index, (x, value) in enumerate(zip((150, 350), values, strict=True)):
                draw.text((x, 125), str(value), font=font, fill="black")
                draw.text((x, 340), str(2023 + index), font=font, fill="black")
                if kind == "bar":
                    draw.rectangle((x, 175, x + 55, 310), fill="#dddddd")
                elif kind == "line":
                    draw.ellipse((x + 15, 180, x + 25, 190), fill="black")
            if kind == "line":
                draw.line((170, 185, 370, 185), fill="black", width=2)
            if kind == "image_table":
                draw.rectangle((100, 80, 450, 315), outline="black", width=2)
                draw.line((285, 80, 285, 315), fill="black", width=2)
        pages.append(image)
        layouts.append(
            dict(
                id=kind,
                page=number,
                kind=kind,
                bbox=[0, 0, 600, 400],
                alignment="single" if kind == "pie" else "columns",
                year=dict(quote="2024") if kind == "pie" else None,
                series=[
                    dict(
                        format="percent" if kind == "pie" else "number",
                        label=dict(quote="Carbon"),
                        unit=dict(quote="GWh"),
                    )
                ],
            )
        )
    pdf = io.BytesIO()
    pages[0].save(
        pdf, format="PDF", save_all=True, append_images=pages[1:], resolution=72, quality=100
    )
    source = pdf.getvalue()
    (args.output / "fresh-original.pdf").write_bytes(source)
    transport_calls = []

    def generated_ocr(png):
        transport_calls.append(sha256(png).hexdigest())
        # Each invocation consumes this new request image. No fixture lookup.
        raw = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "tsv"],
            input=png,
            capture_output=True,
            check=True,
        ).stdout.decode()
        words = []
        for row in csv.DictReader(io.StringIO(raw), delimiter="\t"):
            if not row["text"].strip():
                continue
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            words.append(
                dict(
                    id=len(words),
                    text=row["text"],
                    confidence=0.99 if float(row["conf"]) >= 80 else 0.5,
                    boundingBox=dict(
                        vertices=[
                            dict(x=x, y=y),
                            dict(x=x + w, y=y),
                            dict(x=x + w, y=y + h),
                            dict(x=x, y=y + h),
                        ]
                    ),
                )
            )
        with Image.open(io.BytesIO(png)) as img:
            width, height = img.size
        return json.dumps(
            dict(
                apiVersion="1.1",
                modelVersion="ocr-260930",
                numBilledPages=1,
                pages=[dict(id=0, width=width, height=height, words=words)],
                stored=False,
                ch1_simulated_confidence=True,
            )
        ).encode(), "ch1-fresh-sim"

    ledger, spend = args.output / "sim.sqlite3", args.output / "sim-spend.json"
    UpstageProbe("offline-simulation", ledger)
    spend.write_text(json.dumps(dict(limit_usd="10", cumulative_usd="0")))
    store = PageOCRStore(ledger, spend, transport=generated_ocr)
    scope = dict(
        tenant_id="ch1-fresh-simulation",
        run_id="ch1-" + nonce,
        document_version_id=str(uuid.uuid4()),
        parse_manifest_id=str(uuid.uuid4()),
        source_sha256=sha256(source).hexdigest(),
        selected_pages=[1, 2, 3, 4],
    )
    request = dict(scope=scope, layouts=layouts)
    (args.output / "request.json").write_text(json.dumps(request, indent=2))
    receipt = extract(source, scope, layouts, store=store, policy_sha256=canonical_hash(policy()))
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2))
    assert len(transport_calls) == 4
    points = [p for r in receipt["regions"] for p in r["observations"]]
    assert len(points) == 7, [(r["id"], r["observations"]) for r in receipt["regions"]]
    assert all(p["status"] == "verified" and not p["eligible_for_scoring"] for p in points)
    assert {p["fields"]["value"]["literal"] for p in points} == {*map(str, values), "80%"}
    assert replay(receipt, source, receipt["request"], store=store) == receipt
    assert len(transport_calls) == 4
    report = dict(
        status="passed",
        schema="ch1-fresh-linux-gate-v1",
        platform=platform.platform(),
        nonce=nonce,
        source_sha256=sha256(source).hexdigest(),
        policy_sha256=canonical_hash(policy()),
        fresh_transport_calls=4,
        saved_responses=0,
        real_provider_calls=0,
        network="none",
        generated_labels=values,
        observations=len(points),
        scoring_eligible=0,
        kinds=[r["kind"] for r in receipt["regions"]],
        strict_replay_equal=True,
        limitation="fresh deterministic simulation; no real-model accuracy claim",
    )
    (args.output / "gate.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
