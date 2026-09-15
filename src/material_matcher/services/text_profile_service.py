from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.profiling import profile_retrieval_texts
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.service import VectorIndexService


class TextProfileService:
    """Read-only preflight profiler for actual Source/Target retrieval text."""

    def __init__(
        self,
        metadata: MetadataRepository,
        files: FileRepository,
        settings: Settings,
        indexes: VectorIndexService,
    ) -> None:
        self.meta = metadata
        self.files = files
        self.settings = settings
        self.indexes = indexes

    def _draft(self, draft_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM task_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
        return dict(row)

    def _catalog(self, version_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT c.name, v.* FROM catalog_versions v JOIN catalogs c ON c.catalog_id=v.catalog_id WHERE v.version_id=?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise DomainError("CATALOG_NOT_FOUND", "集团码目录版本不存在", status_code=404)
        return dict(row)

    def profile_draft(self, draft_id: str, *, sample_rows: int = 4096, scan_limit: int = 100_000) -> dict[str, object]:
        draft = self._draft(draft_id)
        if not draft.get("source_file_id") or not draft.get("catalog_version_id"):
            raise DomainError("TASK_DRAFT_INCOMPLETE", "请先完成 Source / Target 数据选择", status_code=422)
        try:
            config = MatchingConfig.model_validate(json.loads(str(draft.get("config_document") or "{}")))
        except Exception as exc:
            raise DomainError("INVALID_PROFILE", "匹配规则格式不正确，请先保存有效规则", status_code=422) from exc
        if not config.rules:
            raise DomainError("TASK_DRAFT_INCOMPLETE", "请先配置至少一条匹配规则", status_code=422)

        source = self.files.get(str(draft["source_file_id"]))
        catalog = self._catalog(str(draft["catalog_version_id"]))
        target = self.files.get(str(catalog["source_file_id"]))
        provider = self.indexes.provider(config)

        common = {
            "config": config,
            "token_counter": provider,
            "sample_rows": sample_rows,
            "scan_limit": scan_limit,
            "max_batch_size": self.settings.embedding_batch_size,
            "token_budget": self.settings.embedding_token_budget,
        }
        source_profile = profile_retrieval_texts(Path(str(source["stored_path"])), side="source", **common)
        target_profile = profile_retrieval_texts(Path(str(target["stored_path"])), side="target", **common)
        recommended = max(
            int(source_profile["token_profile"]["recommended_max_length"]),
            int(target_profile["token_profile"]["recommended_max_length"]),
        )
        return {
            "draft_id": draft_id,
            "provider": asdict(provider.spec),
            "sample_rows": int(sample_rows),
            "scan_limit": int(scan_limit),
            "current_max_length": int(config.retrieval.max_length),
            "recommended_max_length": recommended,
            "recommendation_is_advisory": True,
            "source": source_profile,
            "target": target_profile,
        }
