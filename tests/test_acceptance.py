from __future__ import annotations

from pathlib import Path

from material_matcher.security.users import UserService
from material_matcher.services.acceptance_service import AcceptanceService
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        data_dir=tmp_path / 'data',
        config_dir=tmp_path / 'etc',
        log_dir=tmp_path / 'log',
        admin_password='Ab3dEf7Gh9',
        web_dist_dir=tmp_path / 'release' / 'web' / 'dist',
        embedding_model_root=tmp_path / 'models',
        worker_enabled=False,
    )
    settings.ensure_dirs()
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    return settings


def test_acceptance_distinguishes_code_ready_from_external_production_evidence(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    UserService(meta).ensure_bootstrap_admin(settings.admin_password)

    report = AcceptanceService(meta, settings).report()
    assert report['code_ready'] is True
    assert report['production_ready'] is False
    status = {gate['name']: gate['status'] for gate in report['gates']}
    assert status['runtime_directories'] == 'PASS'
    assert status['security_governance'] == 'PASS'
    assert status['production_embedding'] == 'BLOCKED'
    assert status['business_gold_evaluation'] == 'BLOCKED'
    assert status['million_scale_end_to_end'] == 'BLOCKED'
    assert status['kylin_v10_host'] in {'PASS', 'BLOCKED'}


def test_acceptance_detects_real_scale_only_from_completed_task_and_real_index_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    UserService(meta).ensure_bootstrap_admin(settings.admin_password)
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('task-scale', '百万级验收', 'source', 'catalog', None, None, '{}', 'sha', 'RESULT', 'COMPLETED', 100.0, 100000, 100000, '2026-09-15T10:00:00+00:00', '2026-09-15T10:00:00+00:00', '2026-09-15T11:00:00+00:00', None, None, None),
        )
        connection.execute(
            "INSERT INTO index_versions VALUES(?,?,?,?,?)",
            ('idx-scale', 'catalog', '{"stats":{"row_count":1000000}}', 'READY', '2026-09-15T10:00:00+00:00'),
        )
        connection.execute(
            "INSERT INTO task_runtime VALUES(?,?,?,?,?)",
            ('task-scale', 'vector', 'DONE', 'idx-scale', '2026-09-15T11:00:00+00:00'),
        )

    report = AcceptanceService(meta, settings).report()
    gate = next(item for item in report['gates'] if item['name'] == 'million_scale_end_to_end')
    assert gate['status'] == 'PASS'
    assert gate['evidence']['task']['source_rows'] == 100000
    assert gate['evidence']['task']['target_rows'] == 1000000
    assert gate['evidence']['task']['duration_seconds'] == 3600.0
