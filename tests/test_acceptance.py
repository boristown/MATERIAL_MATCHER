from __future__ import annotations

import json
from pathlib import Path

from material_matcher.security.users import UserService
from material_matcher.services.acceptance_service import AcceptanceService
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


def _settings(tmp_path: Path, *, with_policy: bool = False) -> Settings:
    policy = {
        'acceptance_min_truth_rows': 100,
        'acceptance_min_truth_coverage': 0.95,
        'acceptance_min_top1_accuracy': 0.85,
        'acceptance_min_final_accuracy': 0.95,
        'acceptance_max_review_rate': 0.20,
        'acceptance_max_scale_hours': 2.0,
    } if with_policy else {}
    settings = Settings(
        data_dir=tmp_path / 'data',
        config_dir=tmp_path / 'etc',
        log_dir=tmp_path / 'log',
        admin_password='Ab3dEf7Gh9',
        web_dist_dir=tmp_path / 'release' / 'web' / 'dist',
        embedding_model_root=tmp_path / 'models',
        worker_enabled=False,
        **policy,
    )
    settings.ensure_dirs()
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    return settings


def _bootstrap(meta: MetadataRepository, settings: Settings) -> None:
    users = UserService(meta)
    users.ensure_bootstrap_admin(settings.admin_password)
    users.set_password('admin', 'ChangedAdmin123')


def _insert_evaluation_evidence(meta: MetadataRepository, run_id: str, metrics: dict[str, object]) -> None:
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO files(file_id,role,original_name,stored_path,size_bytes,sha256,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ('truth1', 'supplement', 'truth.csv', '/tmp/truth.csv', 1, 'truth-sha', 'READY', '2026-09-15T11:59:00+00:00'),
        )
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('task1', '业务验收任务', 'source', 'catalog', None, None, '{}', 'sha', 'RESULT', 'COMPLETED', 100.0, 100, 100, '2026-09-15T10:00:00+00:00', '2026-09-15T10:00:00+00:00', '2026-09-15T11:00:00+00:00', None, None, None),
        )
        connection.execute(
            "INSERT INTO evaluation_runs(run_id,task_id,truth_file_id,key_mode,key_column,expected_column,metrics,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, 'task1', 'truth1', 'source_id', '物料号', '集团码', json.dumps(metrics), '2026-09-15T12:00:00+00:00'),
        )


def test_acceptance_distinguishes_code_ready_from_external_production_evidence(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    _bootstrap(meta, settings)

    report = AcceptanceService(meta, settings).report()
    assert report['schema_version'] == 2
    assert report['code_ready'] is True
    assert report['production_ready'] is False
    status = {gate['name']: gate['status'] for gate in report['gates']}
    assert status['runtime_directories'] == 'PASS'
    assert status['security_governance'] == 'PASS'
    assert status['acceptance_policy'] == 'BLOCKED'
    assert status['production_embedding'] == 'BLOCKED'
    assert status['business_gold_evaluation'] == 'BLOCKED'
    assert status['million_scale_end_to_end'] == 'BLOCKED'
    assert status['kylin_v10_host'] in {'PASS', 'BLOCKED'}


def test_acceptance_detects_real_scale_only_from_completed_task_and_real_index_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_policy=True)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    _bootstrap(meta, settings)
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
    assert gate['evidence']['duration_hours'] == 1.0


def test_acceptance_fails_when_real_gold_metrics_are_below_explicit_policy(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_policy=True)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    _bootstrap(meta, settings)
    metrics = {
        'truth_rows': 200,
        'truth_coverage': 1.0,
        'top1_accuracy': 0.80,
        'final_accuracy': 0.96,
        'review_rate': 0.10,
    }
    _insert_evaluation_evidence(meta, 'eval-low', metrics)

    report = AcceptanceService(meta, settings).report()
    gate = next(item for item in report['gates'] if item['name'] == 'business_gold_evaluation')
    assert gate['status'] == 'FAIL'
    assert gate['evidence']['checks']['top1_accuracy'] is False
    assert report['code_ready'] is False


def test_acceptance_passes_business_gate_only_when_all_explicit_metrics_pass(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_policy=True)
    meta = MetadataRepository(settings.data_dir / 'meta' / 'material_matcher.db')
    _bootstrap(meta, settings)
    metrics = {
        'truth_rows': 500,
        'truth_coverage': 0.99,
        'top1_accuracy': 0.90,
        'final_accuracy': 0.98,
        'review_rate': 0.12,
    }
    _insert_evaluation_evidence(meta, 'eval-pass', metrics)

    report = AcceptanceService(meta, settings).report()
    gate = next(item for item in report['gates'] if item['name'] == 'business_gold_evaluation')
    assert gate['status'] == 'PASS'
    assert all(gate['evidence']['checks'].values())
