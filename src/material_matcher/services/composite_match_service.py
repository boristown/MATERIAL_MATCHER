from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Callable

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.matching.engine import CandidateResult, RowResult
from material_matcher.matching.scorer import decide_status, minimum_score_gap
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


ChildRunner = Callable[..., list[RowResult]]
ProgressCallback = Callable[[int, int, int, int], None]


@dataclass(frozen=True)
class CompositeRunEntry:
    profile_id: str
    version_no: int
    catalog_version_id: str


@dataclass
class _RowBucket:
    source_id: str
    source_payload: dict[str, object]
    source_row_number: int | None
    candidates: dict[str, CandidateResult]


class CompositeMatchService:
    """Fan one source dataset out through frozen child schemes, then merge candidates.

    Child Target files are never physically combined. Every child execution keeps
    its own field mapping, normalization pipeline, dictionary bindings, retrieval
    configuration, scope, weights, Target schema and group-code column.

    The parent owns source filtering/source id and the final decision policy. This
    prevents child category filters such as Z001 from filtering out cross-category
    parent rows.
    """

    def __init__(
        self,
        metadata: MetadataRepository,
        files: FileRepository,
        child_runner: ChildRunner,
    ) -> None:
        self.meta = metadata
        self.files = files
        self.child_runner = child_runner

    @staticmethod
    def is_composite(config: MatchingConfig) -> bool:
        advanced = config.advanced if isinstance(config.advanced, dict) else {}
        return str(advanced.get("profile_kind") or "single") == "composite"

    @staticmethod
    def _advanced(config: MatchingConfig) -> dict[str, object]:
        return config.advanced if isinstance(config.advanced, dict) else {}

    def execution_entries(self, parent_config: MatchingConfig) -> list[CompositeRunEntry]:
        """Translate the Composite Profile Model into the executor contract.

        The model freezes child definitions in advanced.composite_children and the
        workspace binds each child to one immutable catalog version in
        advanced.composite_run. Keeping this translation here prevents MatchService
        from depending on UI/Profile implementation details.
        """

        advanced = self._advanced(parent_config)
        raw_run = advanced.get("composite_run")
        if not isinstance(raw_run, list) or len(raw_run) < 2:
            raise DomainError(
                "COMPOSITE_RUN_INCOMPLETE",
                "组合匹配至少需要两个已绑定目标文件的子方案",
                status_code=422,
            )

        run_by_key: dict[tuple[str, int], CompositeRunEntry] = {}
        run_order: list[tuple[str, int]] = []
        for raw in raw_run:
            if not isinstance(raw, dict):
                raise DomainError("COMPOSITE_RUN_INCOMPLETE", "组合匹配运行配置格式不正确", status_code=422)
            profile_id = str(raw.get("profile_id") or "").strip()
            catalog_version_id = str(raw.get("catalog_version_id") or "").strip()
            try:
                version_no = int(raw.get("version_no") or 0)
            except (TypeError, ValueError):
                version_no = 0
            if not profile_id or version_no <= 0 or not catalog_version_id:
                raise DomainError(
                    "COMPOSITE_RUN_INCOMPLETE",
                    "组合匹配的子方案版本与目标文件绑定不完整",
                    status_code=422,
                )
            key = (profile_id, version_no)
            if key in run_by_key:
                raise DomainError("COMPOSITE_RUN_DUPLICATE", "组合匹配不能重复执行同一个子方案版本", status_code=422)
            run_by_key[key] = CompositeRunEntry(profile_id, version_no, catalog_version_id)
            run_order.append(key)

        raw_children = advanced.get("composite_children")
        if isinstance(raw_children, list) and raw_children:
            child_order: list[tuple[str, int]] = []
            for raw in raw_children:
                if not isinstance(raw, dict):
                    raise DomainError("COMPOSITE_PROFILE_INVALID", "组合方案冻结的子方案格式不正确", status_code=422)
                profile_id = str(raw.get("profile_id") or "").strip()
                try:
                    version_no = int(raw.get("version_no") or 0)
                except (TypeError, ValueError):
                    version_no = 0
                key = (profile_id, version_no)
                if not profile_id or version_no <= 0 or key in child_order:
                    raise DomainError("COMPOSITE_PROFILE_INVALID", "组合方案冻结的子方案版本无效", status_code=422)
                child_order.append(key)
            if set(child_order) != set(run_order):
                raise DomainError(
                    "COMPOSITE_RUN_PROFILE_MISMATCH",
                    "本次运行绑定的子方案与父方案冻结版本不一致",
                    status_code=422,
                )
            return [run_by_key[key] for key in child_order]

        # Compatibility adapter while the dedicated model PR is still landing.
        # The run mapping itself remains version-pinned.
        return [run_by_key[key] for key in run_order]

    def _published_child(self, entry: CompositeRunEntry) -> tuple[str, MatchingConfig]:
        with self.meta.connect() as connection:
            row = connection.execute(
                """SELECT p.name,v.document
                   FROM profile_versions v
                   JOIN profiles p ON p.profile_id=v.profile_id
                   WHERE v.profile_id=? AND v.version_no=? AND v.status='PUBLISHED'""",
                (entry.profile_id, entry.version_no),
            ).fetchone()
        if row is None:
            raise DomainError(
                "PROFILE_VERSION_NOT_FOUND",
                "组合方案引用的已发布子方案版本不存在",
                status_code=422,
                details={"profile_id": entry.profile_id, "version_no": entry.version_no},
            )
        try:
            child = MatchingConfig.model_validate(json.loads(str(row["document"])))
        except Exception as exc:
            raise DomainError(
                "COMPOSITE_CHILD_INVALID",
                "组合方案引用的子方案配置无法加载",
                status_code=422,
                details={"profile_id": entry.profile_id, "version_no": entry.version_no},
            ) from exc
        if self.is_composite(child):
            raise DomainError("COMPOSITE_NESTING_NOT_SUPPORTED", "组合方案暂不支持嵌套组合方案", status_code=422)
        if not child.rules:
            raise DomainError("COMPOSITE_CHILD_INVALID", "组合方案的普通子方案缺少字段匹配规则", status_code=422)
        return str(row["name"]), child

    def _catalog(self, version_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute(
                """SELECT c.name,v.*
                   FROM catalog_versions v
                   JOIN catalogs c ON c.catalog_id=v.catalog_id
                   WHERE v.version_id=?""",
                (version_id,),
            ).fetchone()
        if row is None:
            raise DomainError("CATALOG_VERSION_NOT_FOUND", "组合方案引用的集团码目录版本不存在", status_code=422)
        catalog = dict(row)
        if str(catalog.get("status") or "") != "READY":
            raise DomainError("CATALOG_NOT_READY", "组合方案引用的集团码目录版本尚不可用", status_code=409)
        return catalog

    @staticmethod
    def _child_config(child: MatchingConfig, parent: MatchingConfig) -> MatchingConfig:
        if not parent.source_id_column:
            raise DomainError("COMPOSITE_SOURCE_ID_REQUIRED", "组合方案必须配置源物料编码字段", status_code=422)
        # Child keeps rules/pipelines/dictionaries/retrieval/scope/weights and
        # scoring safety. Parent replaces only source selection and final decision.
        return child.model_copy(
            update={
                "source_id_column": parent.source_id_column,
                "source_filter": parent.source_filter,
                "decision": parent.decision,
            },
            deep=True,
        )

    @staticmethod
    def _decorate_candidate(
        candidate: CandidateResult,
        *,
        entry: CompositeRunEntry,
        profile_name: str,
        target_file: dict[str, object],
    ) -> CandidateResult:
        return replace(
            candidate,
            child_profile_id=entry.profile_id,
            child_profile_version=entry.version_no,
            child_profile_name=profile_name,
            target_file_id=str(target_file.get("file_id") or ""),
            target_file_name=str(target_file.get("original_name") or ""),
        )

    @staticmethod
    def _candidate_sort_key(candidate: CandidateResult) -> tuple[float, str]:
        # Duplicate group codes are collapsed before ordering.
        return (-float(candidate.score), str(candidate.group_code))

    @classmethod
    def _trim_bucket(cls, bucket: _RowBucket, top_n: int) -> None:
        ordered = sorted(bucket.candidates.values(), key=cls._candidate_sort_key)[:top_n]
        bucket.candidates = {candidate.group_code: candidate for candidate in ordered}

    @classmethod
    def _merge_child_rows(
        cls,
        buckets: dict[str, _RowBucket],
        rows: list[RowResult],
        *,
        top_n: int,
    ) -> None:
        for row in rows:
            bucket = buckets.get(row.source_row_id)
            if bucket is None:
                bucket = _RowBucket(
                    source_id=row.source_id,
                    source_payload=dict(row.source_payload),
                    source_row_number=row.source_row_number,
                    candidates={},
                )
                buckets[row.source_row_id] = bucket
            for candidate in row.candidates:
                existing = bucket.candidates.get(candidate.group_code)
                # Equal-score duplicates keep the first child in frozen order, so
                # sequential and future parallel execution remain deterministic.
                if existing is None or float(candidate.score) > float(existing.score):
                    bucket.candidates[candidate.group_code] = candidate
            cls._trim_bucket(bucket, top_n)

    @staticmethod
    def _unsafe_status(config: MatchingConfig) -> str:
        return "REVIEW" if config.decision.review_enabled else "UNMATCHED"

    @classmethod
    def _finalize_bucket(
        cls,
        source_row_id: str,
        bucket: _RowBucket,
        parent_config: MatchingConfig,
    ) -> RowResult:
        ordered = sorted(bucket.candidates.values(), key=cls._candidate_sort_key)[: parent_config.decision.top_n]
        candidates = [replace(candidate, rank=rank) for rank, candidate in enumerate(ordered, start=1)]
        first = float(candidates[0].score) if candidates else 0.0
        second = float(candidates[1].score) if len(candidates) > 1 else 0.0
        status = decide_status(first, parent_config) if candidates else "UNMATCHED"

        if status == "MATCHED" and candidates and not candidates[0].auto_match_safe:
            status = cls._unsafe_status(parent_config)

        if status == "MATCHED" and candidates:
            competitor = next(
                (candidate for candidate in candidates[1:] if candidate.group_code != candidates[0].group_code),
                None,
            )
            if competitor is not None and first - float(competitor.score) < minimum_score_gap(parent_config):
                status = cls._unsafe_status(parent_config)

        if (
            status == "MATCHED"
            and parent_config.decision.review_enabled
            and len(candidates) > 1
            and float(candidates[1].score) == first
            and candidates[1].group_code != candidates[0].group_code
        ):
            status = "REVIEW"

        return RowResult(
            source_row_id=str(source_row_id),
            source_id=bucket.source_id,
            source_payload=dict(bucket.source_payload),
            status=status,
            final_group_code=candidates[0].group_code if status == "MATCHED" and candidates else None,
            first_score=first,
            second_score=second,
            score_gap=round(first - second, 4),
            critical_conflict=candidates[0].critical_conflict if candidates else False,
            candidates=candidates,
            source_row_number=bucket.source_row_number,
        )

    @staticmethod
    def _source_sort_key(row: RowResult) -> tuple[int, int | str]:
        value = str(row.source_row_id)
        return (0, int(value)) if value.isdigit() else (1, value)

    def execute(
        self,
        *,
        source: dict[str, object],
        parent_config: MatchingConfig,
        max_source_rows: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[RowResult]:
        if not self.is_composite(parent_config):
            raise DomainError("NOT_COMPOSITE_PROFILE", "当前方案不是组合匹配方案", status_code=422)

        entries = self.execution_entries(parent_config)
        buckets: dict[str, _RowBucket] = {}
        child_count = len(entries)

        # V1 intentionally executes children in frozen order. The child boundary is
        # independent, so it can later be scheduled in parallel; merging still happens
        # in frozen order to preserve deterministic equal-score tie handling.
        for child_index, entry in enumerate(entries):
            profile_name, frozen_child = self._published_child(entry)
            child_config = self._child_config(frozen_child, parent_config)
            catalog = self._catalog(entry.catalog_version_id)
            target = self.files.get(str(catalog["source_file_id"]))
            if str(target.get("role") or "") != "target":
                raise DomainError("INVALID_FILE_ROLE", "组合方案子方案必须绑定集团码目标文件", status_code=422)

            def child_progress(done: int, total: int, *, index: int = child_index) -> None:
                if on_progress is not None:
                    on_progress(index, child_count, done, total)

            child_rows = self.child_runner(
                source=source,
                target=target,
                catalog=catalog,
                config=child_config,
                max_source_rows=max_source_rows,
                on_progress=child_progress,
            )
            decorated_rows: list[RowResult] = []
            for row in child_rows:
                decorated_rows.append(
                    replace(
                        row,
                        candidates=[
                            self._decorate_candidate(
                                candidate,
                                entry=entry,
                                profile_name=profile_name,
                                target_file=target,
                            )
                            for candidate in row.candidates
                        ],
                    )
                )
            self._merge_child_rows(
                buckets,
                decorated_rows,
                top_n=parent_config.decision.top_n,
            )

        rows = [
            self._finalize_bucket(source_row_id, bucket, parent_config)
            for source_row_id, bucket in buckets.items()
        ]
        rows.sort(key=self._source_sort_key)
        return rows
