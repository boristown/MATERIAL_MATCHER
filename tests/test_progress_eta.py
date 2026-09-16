from __future__ import annotations

from pathlib import Path

from material_matcher.services.match_service import MatchService
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.storage.files import FileRepository


def _service(tmp_path: Path) -> MatchService:
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "etc", log_dir=tmp_path / "log", admin_password="x")
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    return MatchService(metadata, FileRepository(settings.data_dir, metadata), settings)


def test_query_phase_estimate_extrapolates_whole_task_eta(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task = "task-1"
    t0 = 1000.0
    # 90 秒内完成 450 行 → 300 行/分钟;总 10000 行
    for step in range(10):
        service.observe_progress(task, "query", 50 + step * 45, 10000, now=t0 + step * 10)
    estimate = service.progress_estimate(task, "RERANK", now=t0 + 90)
    assert estimate is not None
    assert estimate["kind"] == "query"
    assert 270 <= estimate["rows_per_minute"] <= 330
    remaining = (10000 - 500) / 300.0 * 60
    assert abs(estimate["phase_remaining_seconds"] - remaining) < remaining * 0.12
    # 整任务 ETA 至少覆盖打分阶段剩余
    assert estimate["eta_seconds"] > remaining
    assert estimate["eta_at"]


def test_index_phase_estimate_uses_index_samples(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task = "task-2"
    t0 = 500.0
    for step in range(8):
        service.observe_progress(task, "index", step * 1280, 1_000_000, now=t0 + step * 30)
    service.observe_progress(task, "query", 10, 100, now=t0 + 240)
    estimate = service.progress_estimate(task, "INDEX", now=t0 + 240)
    assert estimate is not None and estimate["kind"] == "index"
    assert estimate["phase_done"] == 8960 and estimate["phase_total"] == 1_000_000
    assert estimate["eta_seconds"] > estimate["phase_remaining_seconds"]


def test_estimate_requires_two_fresh_samples(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.observe_progress("t3", "query", 10, 100, now=10.0)
    assert service.progress_estimate("t3", "RERANK", now=11.0) is None
    service.observe_progress("t3", "query", 20, 100, now=41.0)
    assert service.progress_estimate("t3", "RERANK", now=41.0) is not None
    # 超过 15 分钟窗口的样本被丢弃
    assert service.progress_estimate("t3", "RERANK", now=2000.0) is None
