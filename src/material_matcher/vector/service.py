from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import time
from typing import Callable

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.base import EmbeddingProvider
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import create_embedding_provider
from material_matcher.embedding.text import retrieval_text_signature
from material_matcher.ingestion.reader import detect_layout, iter_tabular_rows
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.index import EmbeddedBBQFlatIndex


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class VectorIndexService:
    def __init__(
        self,
        metadata: MetadataRepository,
        files: FileRepository,
        settings: Settings,
        provider_factory: Callable[[Settings, MatchingConfig], EmbeddingProvider] | None = None,
    ) -> None:
        self.meta = metadata
        self.files = files
        self.settings = settings
        self.provider_factory = provider_factory or self._default_provider_factory

    @staticmethod
    def _default_provider_factory(settings: Settings, config: MatchingConfig) -> EmbeddingProvider:
        retrieval = config.retrieval
        return create_embedding_provider(
            settings,
            provider_name=retrieval.provider,
            model_id=retrieval.model_id,
            dimensions=retrieval.dimensions,
            max_length=retrieval.max_length,
            precision=retrieval.precision,
        )

    def provider(self, config: MatchingConfig) -> EmbeddingProvider:
        return self.provider_factory(self.settings, config)

    def _fingerprint(
        self,
        *,
        catalog_version_id: str,
        target_file: dict[str, object],
        group_code_column: str,
        config: MatchingConfig,
        provider: EmbeddingProvider,
    ) -> str:
        payload = {
            "catalog_version_id": catalog_version_id,
            "target_file_sha256": target_file["sha256"],
            "group_code_column": group_code_column,
            "provider": asdict(provider.spec),
            "target_text_signature": retrieval_text_signature(config, "target"),
            "scope_target_field": config.scope.target_field if config.scope_mode != "GLOBAL" else None,
            "algorithm": "embedded_bbq_flat_v2",
            "coarse_kernel": EmbeddedBBQFlatIndex.COARSE_KERNEL,
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    def _find_ready(self, fingerprint: str) -> dict[str, object] | None:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT * FROM index_versions WHERE status='READY' ORDER BY created_at DESC").fetchall()
        for row in rows:
            item = dict(row)
            try:
                metadata = json.loads(str(item["metadata"]))
            except json.JSONDecodeError:
                continue
            if metadata.get("fingerprint") == fingerprint:
                item["metadata"] = metadata
                return item
        return None

    def ensure_index(
        self,
        *,
        catalog_version_id: str,
        target_file: dict[str, object],
        group_code_column: str,
        config: MatchingConfig,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[EmbeddedBBQFlatIndex, EmbeddingProvider, dict[str, object]]:
        provider = self.provider(config)
        fingerprint = self._fingerprint(
            catalog_version_id=catalog_version_id,
            target_file=target_file,
            group_code_column=group_code_column,
            config=config,
            provider=provider,
        )
        final_root = self.settings.index_dir / fingerprint
        ready = self._find_ready(fingerprint)
        if ready and final_root.exists():
            return EmbeddedBBQFlatIndex(final_root), provider, {**ready, "reused": True}

        lock_path = self.settings.index_dir / f".{fingerprint}.lock"
        if lock_path.exists() and time.time() - lock_path.stat().st_mtime > self.settings.index_lock_stale_seconds:
            lock_path.unlink(missing_ok=True)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(lock_fd)
        except FileExistsError as exc:
            raise DomainError(
                "INDEX_BUILD_IN_PROGRESS",
                "相同集团目录的向量索引正在构建，请稍后重试",
                status_code=409,
                details={"fingerprint": fingerprint},
            ) from exc

        ready = self._find_ready(fingerprint)
        if ready and final_root.exists():
            lock_path.unlink(missing_ok=True)
            return EmbeddedBBQFlatIndex(final_root), provider, {**ready, "reused": True}

        index_id = fingerprint
        created_at = datetime.now().astimezone().isoformat()
        base_metadata = {
            "fingerprint": fingerprint,
            "provider": asdict(provider.spec),
            "path": str(final_root),
            "catalog_version_id": catalog_version_id,
            "target_file_sha256": target_file["sha256"],
            "group_code_column": group_code_column,
            "algorithm_version": "embedded_bbq_flat_v2",
            "coarse_kernel": EmbeddedBBQFlatIndex.COARSE_KERNEL,
        }
        with self.meta.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO index_versions(index_id,catalog_version_id,metadata,status,created_at) VALUES(?,?,?,?,?)",
                (index_id, catalog_version_id, _canonical(base_metadata), "BUILDING", created_at),
            )
        target_path = Path(str(target_file["stored_path"]))
        total_estimate = max(1, detect_layout(target_path).row_count_estimate)
        cache = EmbeddingCache(self.settings.embedding_cache_dir, provider)
        try:
            def progress(done: int) -> None:
                if on_progress:
                    on_progress(done, total_estimate)

            index, stats = EmbeddedBBQFlatIndex.build(
                final_root,
                provider=provider,
                cache=cache,
                target_rows=iter_tabular_rows(target_path),
                config=config,
                group_code_column=group_code_column,
                metadata=base_metadata,
                embedding_batch_size=self.settings.embedding_batch_size,
                scan_block_rows=self.settings.index_scan_block_rows,
                on_progress=progress,
            )
            completed_metadata = {**base_metadata, "stats": asdict(stats), "index_metadata": index.metadata}
            with self.meta.connect() as connection:
                connection.execute("UPDATE index_versions SET metadata=?, status='READY' WHERE index_id=?", (_canonical(completed_metadata), index_id))
            return index, provider, {"index_id": index_id, "catalog_version_id": catalog_version_id, "metadata": completed_metadata, "status": "READY", "created_at": created_at, "reused": False}
        except Exception as exc:
            failed_metadata = {**base_metadata, "error": str(exc)}
            with self.meta.connect() as connection:
                connection.execute("UPDATE index_versions SET metadata=?, status='FAILED' WHERE index_id=?", (_canonical(failed_metadata), index_id))
            raise
        finally:
            lock_path.unlink(missing_ok=True)

    def list_versions(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT * FROM index_versions ORDER BY created_at DESC").fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(str(item["metadata"]))
            except json.JSONDecodeError:
                pass
            result.append(item)
        return result
