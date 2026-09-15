from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    config_dir: Path
    log_dir: Path
    admin_password: str
    session_ttl_seconds: int = 28_800
    max_upload_bytes: int = 120 * 1024 * 1024
    max_total_upload_bytes: int = 2 * 1024 * 1024 * 1024
    chunk_size_bytes: int = 8 * 1024 * 1024
    baseline_max_target_rows: int = 20_000
    worker_poll_seconds: float = 0.1
    worker_enabled: bool = True
    embedding_provider: str = "onnx_local"
    embedding_model_id: str = "BAAI/bge-base-zh-v1.5"
    embedding_dimensions: int = 768
    embedding_max_length: int = 256
    embedding_precision: str = "int8"
    embedding_model_root: Path = Path("/var/lib/material_matcher/models/current")
    embedding_batch_size: int = 128
    embedding_token_budget: int = 16_384
    embedding_intra_threads: int = 0
    index_scan_block_rows: int = 8192
    index_scan_workers: int = 0
    query_batch_size: int = 64
    index_lock_stale_seconds: int = 21_600
    web_dist_dir: Path = Path("/opt/material_matcher/current/web/dist")
    acceptance_min_truth_rows: int | None = None
    acceptance_min_truth_coverage: float | None = None
    acceptance_min_top1_accuracy: float | None = None
    acceptance_min_final_accuracy: float | None = None
    acceptance_max_review_rate: float | None = None
    acceptance_max_scale_hours: float | None = None

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"

    @property
    def embedding_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "embeddings"

    @property
    def acceptance_thresholds(self) -> dict[str, int | float | None]:
        return {
            "min_truth_rows": self.acceptance_min_truth_rows,
            "min_truth_coverage": self.acceptance_min_truth_coverage,
            "min_top1_accuracy": self.acceptance_min_top1_accuracy,
            "min_final_accuracy": self.acceptance_min_final_accuracy,
            "max_review_rate": self.acceptance_max_review_rate,
            "max_scale_hours": self.acceptance_max_scale_hours,
        }

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("MATERIAL_MATCHER_DATA_DIR", "/var/lib/material_matcher")),
            config_dir=Path(os.getenv("MATERIAL_MATCHER_CONFIG_DIR", "/etc/material_matcher")),
            log_dir=Path(os.getenv("MATERIAL_MATCHER_LOG_DIR", "/var/log/material_matcher")),
            admin_password=os.getenv("MATERIAL_MATCHER_ADMIN_PASSWORD", ""),
            baseline_max_target_rows=int(os.getenv("MATERIAL_MATCHER_BASELINE_MAX_TARGET_ROWS", "20000")),
            embedding_provider=os.getenv("MATERIAL_MATCHER_EMBEDDING_PROVIDER", "onnx_local"),
            embedding_model_id=os.getenv("MATERIAL_MATCHER_EMBEDDING_MODEL_ID", "BAAI/bge-base-zh-v1.5"),
            embedding_dimensions=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_DIMENSIONS", "768")),
            embedding_max_length=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_MAX_LENGTH", "256")),
            embedding_precision=os.getenv("MATERIAL_MATCHER_EMBEDDING_PRECISION", "int8"),
            embedding_model_root=Path(os.getenv("MATERIAL_MATCHER_MODEL_ROOT", "/var/lib/material_matcher/models/current")),
            embedding_batch_size=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_BATCH_SIZE", "128")),
            embedding_token_budget=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_TOKEN_BUDGET", "16384")),
            embedding_intra_threads=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_INTRA_THREADS", "0")),
            index_scan_block_rows=int(os.getenv("MATERIAL_MATCHER_INDEX_SCAN_BLOCK_ROWS", "8192")),
            index_scan_workers=int(os.getenv("MATERIAL_MATCHER_INDEX_SCAN_WORKERS", "0")),
            query_batch_size=int(os.getenv("MATERIAL_MATCHER_QUERY_BATCH_SIZE", "64")),
            index_lock_stale_seconds=int(os.getenv("MATERIAL_MATCHER_INDEX_LOCK_STALE_SECONDS", "21600")),
            web_dist_dir=Path(os.getenv("MATERIAL_MATCHER_WEB_DIST_DIR", "/opt/material_matcher/current/web/dist")),
            acceptance_min_truth_rows=_optional_int("MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_ROWS"),
            acceptance_min_truth_coverage=_optional_float("MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_COVERAGE"),
            acceptance_min_top1_accuracy=_optional_float("MATERIAL_MATCHER_ACCEPTANCE_MIN_TOP1_ACCURACY"),
            acceptance_min_final_accuracy=_optional_float("MATERIAL_MATCHER_ACCEPTANCE_MIN_FINAL_ACCURACY"),
            acceptance_max_review_rate=_optional_float("MATERIAL_MATCHER_ACCEPTANCE_MAX_REVIEW_RATE"),
            acceptance_max_scale_hours=_optional_float("MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS"),
        )

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir / "meta",
            self.data_dir / "uploads",
            self.data_dir / "tmp",
            self.data_dir / "results",
            self.index_dir,
            self.embedding_cache_dir,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
