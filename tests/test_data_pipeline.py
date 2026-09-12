from material_matcher.data_pipeline import Dataset, apply_transforms, join_datasets, route_record


def test_join_transform_and_route_without_customer_code() -> None:
    left = Dataset(
        name="ztmm_mara",
        columns=["MATNR", "ZWLYX", "ZXH"],
        rows=[{"MATNR": "0001", "ZWLYX": "A006", "ZXH": "3240"}],
    )
    right = Dataset(
        name="mara",
        columns=["MATNR", "MEINS"],
        rows=[{"MATNR": "0001", "MEINS": "KG"}],
    )
    joined = join_datasets(
        left,
        right,
        {
            "id": "source_view",
            "type": "left",
            "keys": [{"left": "MATNR", "right": "MATNR"}],
            "select": ["MEINS"],
        },
    )
    assert joined.rows[0]["MEINS"] == "KG"

    transformed = apply_transforms(
        joined,
        {
            "identity": {"op": "concat", "fields": ["ZXH", "MEINS"], "separator": " ", "skip_empty": True},
            "type_name": {"op": "value_map", "field": "ZWLYX", "mapping": {"A006": "复合材料"}},
        },
    )
    assert transformed.rows[0]["identity"] == "3240 kg"
    assert transformed.rows[0]["type_name"] == "复合材料"

    route = route_record(
        transformed.rows[0],
        {
            "by_source_field": "ZWLYX",
            "routes": [
                {"values": ["A001"], "target_catalog": "electronics"},
                {"values": ["A006"], "target_catalog": "composites"},
            ],
        },
    )
    assert route is not None
    assert route["target_catalog"] == "composites"
