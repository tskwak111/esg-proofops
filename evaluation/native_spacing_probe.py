"""Reproduce split-Tj spacing disagreement without changing verification policy.

Run: uv run python evaluation/native_spacing_probe.py
This is a reader diagnostic, not source approval or a production correction.
"""

import json
from contextlib import closing
from ctypes import c_double
from importlib.metadata import version
from io import BytesIO

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def probe(split: bool) -> dict:
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    text = b"(A) Tj (B) Tj" if split else b"(AB) Tj"
    stream.set_data(b"BT /F1 12 Tf -0.17 Tc 30 100 Td " + text + b" ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    source = output.getvalue()
    with pdfplumber.open(BytesIO(source)) as document, pdfium.PdfDocument(source) as native:
        chars = document.pages[0].chars
        assert [c["text"] for c in chars] == ["A", "B"]
        with closing(native[0]) as native_page, closing(native_page.get_textpage()) as textpage:
            origins = []
            for index in range(textpage.count_chars()):
                if raw.FPDFText_GetUnicode(textpage, index) == ord("B"):
                    x, y = c_double(), c_double()
                    assert raw.FPDFText_GetCharOrigin(textpage, index, x, y)
                    origins.append(x.value)
            assert len(origins) == 1
    miner_x = chars[1]["matrix"][4]
    return {
        "split_tj": split,
        "pdfminer_b_x": miner_x,
        "pdfium_b_x": origins[0],
        "difference_pt": miner_x - origins[0],
    }


if __name__ == "__main__":
    single, split = probe(False), probe(True)
    assert abs(single["difference_pt"]) < 0.001
    assert abs(single["pdfium_b_x"] - split["pdfium_b_x"]) < 0.001
    print(
        json.dumps(
            {
                "schema": "native_spacing_probe_v1",
                "versions": {
                    name: version(name) for name in ("pdfminer.six", "pdfplumber", "pypdfium2")
                },
                "samples": [single, split],
                "split_spacing_disagrees": abs(split["difference_pt"]) > 0.001,
                "source_quality_changed": False,
                "additional_model_calls": 0,
            },
            indent=2,
        )
    )
