from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook

from material_matcher.domain.models import MatchingConfig
from material_matcher.services.catalog_service import CatalogService
from material_matcher.services.match_service import MatchService
from material_matcher.services.profile_service import ProfileService
from material_matcher.services.review_workbench_service import ReviewWorkbenchService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="test-password",
        embedding_model_root=tmp_path / "models",
        web_dist_dir=tmp_path / "web-dist",
        baseline_max_target_rows=1000,
        worker_enabled=False,
    )
    settings.ensure_dirs()
    return settings


def _workbook(headers: list[str], rows: list[list[object]], sheet_name: str) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(["模板说明"])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _save(
    files: FileRepository,
    settings: Settings,
    *,
    name: str,
    role: str,
    headers: list[str],
    rows: list[list[object]],
) -> dict[str, object]:
    return files.save_stream(
        name,
        role,
        _workbook(headers, rows, "数据"),
        settings.max_upload_bytes,
    )


def _child_document(source_field: str, target_field: str, child_type: str) -> dict[str, object]:
    return {
        "source_id_column": "SAP_CODE",
        "scope_mode": "GLOBAL",
        "source_filter": {
            "field": "TYPE",
            "values": [child_type],
            "mode": "include",
            "match": "exact",
        },
        "rules": [
            {
                "id": f"{source_field}-to-{target_field}",
                "source": {"fields": [source_field]},
                "target": {"fields": [target_field]},
                "matcher": "fuzzy",
                "weight": 100,
                "critical": False,
            }
        ],
        # Deliberately permissive child thresholds. Tests below prove that the
        # parent, not these child decisions, controls the final state.
        "decision": {
            "success_threshold": 50,
            "review_enabled": True,
            "review_threshold": 10,
            "top_n": 5,
        },
        "retrieval": {"mode": "scan"},
        "advanced": {},
    }


def _publish(
    profiles: ProfileService,
    *,
    name: str,
    source_field: str,
    target_field: str,
    child_type: str,
) -> dict[str, object]:
    profile = profiles.create(
        name,
        _child_document(source_field, target_field, child_type),
    )
    return profiles.publish(str(profile["profile_id"]))


def _parent_config(
    children: list[dict[str, object]],
    catalogs: list[dict[str, object]],
    *,
    success_threshold: int = 95,
    minimum_score_gap: float = 0.0,
) -> MatchingConfig:
    child_refs = [
        {
            "profile_id": str(child["profile_id"]),
            "version_no": int(child["version_no"]),
        }
        for child in children
    ]
    run_refs = [
        {
            "profile_id": str(child["profile_id"]),
            "version_no": int(child["version_no"]),
            "catalog_version_id": str(catalog["version_id"]),
        }
        for child, catalog in zip(children, catalogs, strict=True)
    ]
    return MatchingConfig.model_validate(
        {
            "source_id_column": "SAP_CODE",
            "scope_mode": "GLOBAL",
            "source_filter": {
                "field": "TYPE",
                "values": ["A007"],
                "mode": "include",
                "match": "exact",
            },
            "rules": [],
            "decision": {
                "success_threshold": success_threshold,
                "review_enabled": True,
                "review_threshold": 50,
                "top_n": 5,
            },
            "retrieval": {"mode": "scan"},
            "advanced": {
                "profile_kind": "composite",
                "composite_children": child_refs,
                "composite_run": run_refs,
                "matching_safety": {"minimum_score_gap": minimum_score_gap},
            },
        }
    )


def _insert_task(
    metadata: MetadataRepository,
    *,
    task_id: str,
    source_file_id: str,
    catalog_version_id: str,
    config: MatchingConfig,
) -> None:
    encoded = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    created_at = "2026-09-20T11:00:00+08:00"
    with metadata.connect() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                f"run-{task_id}",
                source_file_id,
                catalog_version_id,
                None,
                None,
                encoded,
                digest,
                "CALCULATE",
                "PENDING",
                0.0,
                0,
                0,
                created_at,
                created_at,
                None,
                None,
                None,
                None,
            ),
        )


def _build_fixture(tmp_path: Path):
    settings = _settings(tmp_path)
    metadata = MetadataRepository(settings.metadata_db_path)
    files = FileRepository(settings.data_dir, metadata)
    catalogs = CatalogService(metadata, files)
    profiles = ProfileService(metadata)
    matcher = MatchService(metadata, files, settings)

    source = _save(
        files,
        settings,
        name="sap-a007.xlsx",
        role="source",
        headers=["SAP_CODE", "TYPE", "NAME", "MODEL", "BRAND"],
        rows=[["S-001", "A007", "电机", "M100", "ACME"]],
    )

    target_a = _save(
        files,
        settings,
        name="target-a.xlsx",
        role="target",
        headers=["集团码A", "名称A"],
        rows=[["G-DUP", "电机"], ["G-A", "电动机"]],
    )
    target_b = _save(
        files,
        settings,
        name="target-b.xlsx",
        role="target",
        headers=["code_b", "spec_b"],
        rows=[["G-DUP", "M100X"], ["G-B", "M10"]],
    )
    target_c = _save(
        files,
        settings,
        name="target-c.xlsx",
        role="target",
        headers=["gc_c", "BRAND_C"],
        rows=[["G-C", "ACM"], ["G-D", "ACME LTD"]],
    )

    catalog_a = catalogs.create("目录A", str(target_a["file_id"]), "集团码A")
    catalog_b = catalogs.create("目录B", str(target_b["file_id"]), "code_b")
    catalog_c = catalogs.create("目录C", str(target_c["file_id"]), "gc_c")

    child_a = _publish(
        profiles,
        name="普通方案A",
        source_field="NAME",
        target_field="名称A",
        child_type="Z001",
    )
    child_b = _publish(
        profiles,
        name="普通方案B",
        source_field="MODEL",
        target_field="spec_b",
        child_type="Z002",
    )
    child_c = _publish(
        profiles,
        name="普通方案C",
        source_field="BRAND",
        target_field="BRAND_C",
        child_type="Z003",
    )

    return {
        "settings": settings,
        "metadata": metadata,
        "files": files,
        "matcher": matcher,
        "profiles": profiles,
        "source": source,
        "targets": [target_a, target_b, target_c],
        "catalogs": [catalog_a, catalog_b, catalog_c],
        "children": [child_a, child_b, child_c],
    }


def test_composite_pipeline_runs_three_heterogeneous_children_without_merging_excel(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    matcher: MatchService = fixture["matcher"]
    source = fixture["source"]
    parent = _parent_config(fixture["children"], fixture["catalogs"])

    target_count_before = len([item for item in fixture["files"].list() if item["role"] == "target"])
    rows = matcher.composite_matcher.execute(source=source, parent_config=parent)
    target_count_after = len([item for item in fixture["files"].list() if item["role"] == "target"])

    # No physical union file is created: the three original Target files remain
    # independent and each child sees only its own schema.
    assert target_count_before == target_count_after == 3
    assert len(rows) == 1
    row = rows[0]

    # All children had Z001/Z002/Z003 filters, while the source row is A007.
    # Getting candidates from every child proves the parent filter replaced them.
    assert row.source_id == "S-001"
    assert {candidate.child_profile_id for candidate in row.candidates} == {
        str(child["profile_id"]) for child in fixture["children"]
    }

    # 2 + 2 + 2 candidates with G-DUP appearing twice => exactly five unique
    # group codes after global deduplication and parent Top5.
    assert len(row.candidates) == 5
    assert len({candidate.group_code for candidate in row.candidates}) == 5
    assert [candidate.rank for candidate in row.candidates] == [1, 2, 3, 4, 5]

    duplicate = next(candidate for candidate in row.candidates if candidate.group_code == "G-DUP")
    assert duplicate.score == 100.0
    assert duplicate.child_profile_id == str(fixture["children"][0]["profile_id"])
    assert duplicate.child_profile_version == int(fixture["children"][0]["version_no"])
    assert duplicate.child_profile_name == "普通方案A"
    assert duplicate.target_file_id == str(fixture["targets"][0]["file_id"])
    assert duplicate.target_file_name == "target-a.xlsx"
    assert duplicate.target_row_number is not None

    from_a = next(candidate for candidate in row.candidates if candidate.child_profile_name == "普通方案A")
    from_b = next(candidate for candidate in row.candidates if candidate.child_profile_name == "普通方案B")
    from_c = next(candidate for candidate in row.candidates if candidate.child_profile_name == "普通方案C")
    assert "名称A" in from_a.target_payload and "spec_b" not in from_a.target_payload
    assert "spec_b" in from_b.target_payload and "BRAND_C" not in from_b.target_payload
    assert "BRAND_C" in from_c.target_payload and "名称A" not in from_c.target_payload

    # Parent threshold controls the final decision. Child thresholds are 50, but
    # setting the parent threshold to 100 makes a score of exactly 100 REVIEW
    # under the existing strict threshold semantics.
    strict_parent = _parent_config(
        fixture["children"],
        fixture["catalogs"],
        success_threshold=100,
    )
    strict_rows = matcher.composite_matcher.execute(source=source, parent_config=strict_parent)
    assert strict_rows[0].status == "REVIEW"

    # Parent minimum score gap is also a final-decision rule, not a child rule.
    gap_parent = _parent_config(
        fixture["children"],
        fixture["catalogs"],
        success_threshold=95,
        minimum_score_gap=100.0,
    )
    gap_rows = matcher.composite_matcher.execute(source=source, parent_config=gap_parent)
    assert gap_rows[0].status == "REVIEW"

    # Frozen child order plus deterministic global sort makes repeat runs stable.
    repeated = matcher.composite_matcher.execute(source=source, parent_config=parent)
    assert [
        (candidate.rank, candidate.group_code, candidate.score, candidate.child_profile_id)
        for candidate in repeated[0].candidates
    ] == [
        (candidate.rank, candidate.group_code, candidate.score, candidate.child_profile_id)
        for candidate in row.candidates
    ]


def test_match_service_routes_composite_and_persists_step3_provenance(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    matcher: MatchService = fixture["matcher"]
    metadata: MetadataRepository = fixture["metadata"]
    parent = _parent_config(fixture["children"], fixture["catalogs"])

    _insert_task(
        metadata,
        task_id="composite-task",
        source_file_id=str(fixture["source"]["file_id"]),
        catalog_version_id=str(fixture["catalogs"][0]["version_id"]),
        config=parent,
    )
    matcher.execute_task("composite-task")

    with metadata.connect() as connection:
        task = connection.execute(
            "SELECT status,total_rows FROM tasks WHERE task_id='composite-task'"
        ).fetchone()
        persisted = connection.execute(
            """SELECT child_profile_id,child_profile_version,child_profile_name,
                      target_file_id,target_file_name,target_row_number
               FROM match_candidates
               WHERE task_id='composite-task'
               ORDER BY rank"""
        ).fetchall()
    assert task["status"] == "COMPLETED"
    assert int(task["total_rows"]) == 1
    assert len(persisted) == 5
    assert all(row["child_profile_id"] for row in persisted)
    assert all(row["child_profile_version"] for row in persisted)
    assert all(row["child_profile_name"] for row in persisted)
    assert all(row["target_file_id"] for row in persisted)
    assert all(row["target_file_name"] for row in persisted)
    assert all(row["target_row_number"] is not None for row in persisted)
    assert matcher.runtime_status("composite-task")["execution_mode"] == "composite"

    # STEP3 workbench gets provenance as first-class candidate fields, not hidden
    # inside or mixed into the heterogeneous target payload.
    workbench = ReviewWorkbenchService(metadata)
    items = workbench.list_items(
        "composite-task",
        status="ALL",
        page=1,
        page_size=50,
        include_candidates=5,
    )
    candidates = items["items"][0]["candidates"]
    assert candidates[0]["child_profile_id"]
    assert candidates[0]["child_profile_version"]
    assert candidates[0]["child_profile_name"]
    assert candidates[0]["target_file_id"]
    assert candidates[0]["target_file_name"]
    assert candidates[0]["target_row_number"] is not None


def test_single_pipeline_route_remains_unchanged(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    matcher: MatchService = fixture["matcher"]
    metadata: MetadataRepository = fixture["metadata"]
    profiles: ProfileService = fixture["profiles"]

    child = fixture["children"][0]
    published = profiles.version(str(child["profile_id"]), int(child["version_no"]))
    single = MatchingConfig.model_validate(published["document"]).model_copy(
        update={
            "source_filter": _parent_config(
                fixture["children"],
                fixture["catalogs"],
            ).source_filter,
        },
        deep=True,
    )
    assert matcher.composite_matcher.is_composite(single) is False

    _insert_task(
        metadata,
        task_id="single-task",
        source_file_id=str(fixture["source"]["file_id"]),
        catalog_version_id=str(fixture["catalogs"][0]["version_id"]),
        config=single,
    )
    matcher.execute_task("single-task")

    with metadata.connect() as connection:
        task = connection.execute(
            "SELECT status,total_rows FROM tasks WHERE task_id='single-task'"
        ).fetchone()
        candidate = connection.execute(
            """SELECT child_profile_id,child_profile_version,child_profile_name,
                      target_file_id,target_file_name
               FROM match_candidates
               WHERE task_id='single-task'
               ORDER BY rank LIMIT 1"""
        ).fetchone()
    assert task["status"] == "COMPLETED"
    assert int(task["total_rows"]) == 1
    assert matcher.runtime_status("single-task")["execution_mode"] == "scan"
    assert candidate["child_profile_id"] is None
    assert candidate["child_profile_version"] is None
    assert candidate["child_profile_name"] is None
    assert candidate["target_file_id"] is None
    assert candidate["target_file_name"] is None
