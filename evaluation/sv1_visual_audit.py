"""Re-render every recovered source crop and build inspectable comparison sheets."""

import io
import json
import math
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw, ImageOps
from proofops.domain.provenance import canonical_hash

from evaluation.sv1_source_audit import OUT


def main():
    summary = json.loads((OUT / "replay-summary.json").read_text())
    assert len(summary["states"]) == 12
    directory = OUT / "crops"
    directory.mkdir(exist_ok=True)
    grouped = defaultdict(list)
    for row in summary["recovered"]:
        grouped[row["source_path"]].append(row)
    comparisons = []
    unique = {}
    for path, rows in grouped.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == rows[0]["source_sha256"]
        with pdfplumber.open(path) as document:
            pages = {}
            for row in rows:
                for record in row["records"]:
                    ref = record["ref"]
                    proof = record["normalization"]
                    quote = record["canonical_quote"]
                    rendered = next(
                        r
                        for r in proof["rendered_attempts"]
                        if canonical_hash(r) == proof["rendered_read_sha256"]
                    )
                    native = " ".join(proof["native_text"].split())
                    visible = " ".join(rendered["text"].split())
                    assert native.count(quote) == visible.count(quote) == 1
                    assert "".join(proof["parser_quote"].split()) == "".join(quote.split())
                    assert "".join(g["char"] for g in proof["glyphs"]) == "".join(quote.split())
                    page = ref["page_num"]
                    box = ref["bbox"]
                    if page not in pages:
                        pages[page] = document.pages[page - 1].to_image(resolution=216).original
                    crop = pages[page].crop(
                        [
                            math.floor(box[0] * 3),
                            math.floor(box[1] * 3),
                            math.ceil(box[2] * 3),
                            math.ceil(box[3] * 3),
                        ]
                    )
                    padded = ImageOps.expand(crop, border=rendered["padding_px"], fill="white")
                    buffer = io.BytesIO()
                    padded.save(buffer, format="PNG")
                    data = buffer.getvalue()
                    assert sha256(data).hexdigest() == rendered["image_sha256"]
                    key = (row["source_sha256"], page, tuple(box), quote)
                    if key not in unique:
                        index = len(unique) + 1
                        name = f'{index:02}-{row["state"].split("-")[1]}-p{page}.png'
                        (directory / name).write_bytes(data)
                        unique[key] = dict(
                            index=index,
                            crop=name,
                            source_sha256=row["source_sha256"],
                            page=page,
                            bbox=box,
                            canonical_quote=quote,
                            parser_quote=proof["parser_quote"],
                            rendered_text=rendered["text"],
                            crop_sha256=sha256(data).hexdigest(),
                            visual_status="pending",
                        )
                    comparisons.append(
                        dict(
                            state=row["state"],
                            claim_id=row["claim_id"],
                            sample=unique[key]["index"],
                            canonical_quote=quote,
                            raw_quote=ref["quote"],
                            native_unique=True,
                            rendered_unique=True,
                            pixel_hash_matches=True,
                        )
                    )
            for image in pages.values():
                image.close()
    samples = list(unique.values())
    for offset in range(0, len(samples), 4):
        selected = samples[offset : offset + 4]
        tiles = []
        for sample in selected:
            im = Image.open(directory / sample["crop"]).convert("RGB")
            tile = Image.new("RGB", (max(im.width, 1200), im.height + 45), "#f2f2f2")
            tile.paste(im, (0, 45))
            draw = ImageDraw.Draw(tile)
            draw.text(
                (10, 12),
                f"Sample {sample['index']:02} | p{sample['page']} | {sample['crop']}",
                fill="black",
            )
            tiles.append(tile)
        sheet = Image.new(
            "RGB", (max(t.width for t in tiles), sum(t.height + 15 for t in tiles)), "white"
        )
        y = 0
        for tile in tiles:
            sheet.paste(tile, (0, y))
            y += tile.height + 15
        sheet.save(directory / f"sheet-{offset//4+1:02}.png")
    result = dict(
        total_recovered_claims=len(summary["recovered"]),
        comparison_count=len(comparisons),
        unique_samples=len(samples),
        samples=samples,
        comparisons=comparisons,
        incorrect_verified="pending_visual_review",
    )
    (OUT / "visual-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 복구 인용 문자열·렌더 대조",
        "",
        "| 번호 | 상태/claim | 원문 쪽 | 파서 원문 | 네이티브 정본 | crop |",
        "|---:|---|---:|---|---|---|",
    ]
    for row in comparisons:
        sample = samples[row["sample"] - 1]

        def escape(x):
            return x.replace("|", "\\|").replace("\n", " ")

        lines.append(
            f"| {row['sample']} | {row['state']}/{row['claim_id']} | {sample['page']} | "
            f"{escape(row['raw_quote'])} | {escape(row['canonical_quote'])} | "
            f"[crop](crops/{sample['crop']}) |"
        )
    (OUT / "recovery-comparison.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ["samples", "comparisons"]}))


if __name__ == "__main__":
    main()
