from pathlib import Path

from material_matcher.ingestion.inspector import inspect_tabular_file
from material_matcher.ingestion.reader import detect_layout, iter_tabular_rows


def _write_csv(path: Path, rows: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write("物料编码,物料描述\n")
        for index in range(rows):
            stream.write(f"{index},六角螺栓 M{index}x30\n")


def test_csv_row_count_estimate_is_not_capped_by_sample_window(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    _write_csv(path, 5200)
    inspected = inspect_tabular_file(path)
    sheet = inspected["sheets"][0]
    assert sheet["row_count_estimate"] == 5200
    assert detect_layout(path).row_count_estimate == 5200


def test_csv_row_count_estimate_handles_small_and_nonterminated_files(tmp_path: Path) -> None:
    full = tmp_path / "full.csv"
    _write_csv(full, 10)
    assert inspect_tabular_file(full)["sheets"][0]["row_count_estimate"] == 10

    unterminated = tmp_path / "tail.csv"
    unterminated.write_bytes("物料编码,物料描述\n1,A\n2,B".encode("utf-8"))
    assert inspect_tabular_file(unterminated)["sheets"][0]["row_count_estimate"] == 2
    assert len(list(iter_tabular_rows(unterminated))) == 2
