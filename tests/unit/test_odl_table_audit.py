from evaluation.odl_table_audit import audit, bottom_left


def test_coordinate_origin_is_explicit_and_unknown_or_nan_is_rejected():
    assert bottom_left({"l": 10, "t": 20, "r": 30, "b": 40, "coord_origin": "TOPLEFT"}, 100) == [
        10,
        60,
        30,
        80,
    ]
    assert bottom_left({"l": 10, "t": 80, "r": 30, "b": 60, "coord_origin": "BOTTOMLEFT"}, 100) == [
        10,
        60,
        30,
        80,
    ]
    assert bottom_left({"l": 10, "t": 20, "r": 30, "b": 40}, 100) is None
    assert (
        bottom_left({"l": float("nan"), "t": 20, "r": 30, "b": 40, "coord_origin": "TOPLEFT"}, 100)
        is None
    )


def test_overlapping_year_headers_and_uniform_replacement_boxes_stay_unapproved():
    cells = [
        {
            "row number": 1,
            "column number": 1,
            "column span": 2,
            "bounding box": [0, 50, 100, 100],
            "kids": [{"content": "2025년"}],
        },
        {
            "row number": 1,
            "column number": 2,
            "bounding box": [50, 50, 100, 100],
            "kids": [{"content": "2030년"}],
        },
    ]
    raw = {
        "kids": [
            {
                "type": "table",
                "id": 1,
                "page number": 105,
                "bounding box": [0, 0, 100, 100],
                "rows": [{"cells": cells}],
            }
        ]
    }
    backend = {
        "pages": {"105": {"size": {"height": 100}}},
        "tables": [
            {
                "prov": [
                    {
                        "page_no": 105,
                        "bbox": {"l": 0, "t": 100, "r": 100, "b": 0, "coord_origin": "BOTTOMLEFT"},
                    }
                ],
                "data": {
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                            "text": "2025년",
                            "bbox": {"l": 10, "t": 5, "r": 20, "b": 15, "coord_origin": "TOPLEFT"},
                        },
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 1,
                            "text": "2030년",
                            "bbox": {"l": 60, "t": 5, "r": 70, "b": 15, "coord_origin": "TOPLEFT"},
                        },
                    ]
                },
            }
        ],
    }
    result = audit(raw, backend)["tables"][0]
    assert result["overlapping_slots"][0]["column"] == 2
    assert result["cells_without_preserved_backend_geometry"] == 2
    assert result["semantic_binding"] == "not_approved"
    cells[0]["bounding box"] = None
    assert not audit(raw, backend)["tables"][0]["cells"][0]["backend_geometry_preserved"]
