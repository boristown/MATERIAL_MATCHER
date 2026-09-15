from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


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
    embedding_model_root: Path = Path("/opt/material_matcher/models")
    embedding_batch_size: int = 128
    embedding_intra_threads: int = 0
    index_scan_block_rows: int = 8192
    query_batch_size: int = 64
    index_lock_stale_seconds: int = 21_600

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"

    @property
    def embedding_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "embeddings"

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
            embedding_model_root=Path(os.getenv("MATERIAL_MATCHER_MODEL_ROOT", "/opt/material_matcher/models")),
            embedding_batch_size=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_BATCH_SIZE", "128")),
            embedding_intra_threads=int(os.getenv("MATERIAL_MATCHER_EMBEDDING_INTRA_THREADS", "0")),
            index_scan_block_rows=int(os.getenv("MATERIAL_MATCHER_INDEX_SCAN_BLOCK_ROWS", "8192")),
            query_batch_size=int(os.getenv("MATERIAL_MATCHER_QUERY_BATCH_SIZE", "64")),
            index_lock_stale_seconds=int(os.getenv("MATERIAL_MATCHER_INDEX_LOCK_STALE_SECONDS", "21600")),
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
