from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class DictionaryService:
    """Immutable, versioned business dictionaries used by explicit pipeline steps.

    A dictionary document has the stable shape::

        {"mapping": {"SUS304": "304不锈钢"}, "case_sensitive": true}

    Matching configs reference a dictionary with a ``dictionary_map`` processing
    step. ``bind_references`` validates the reference and freezes both the
    referenced SHA and mapping into the config document. This intentionally
    makes task/profile snapshots self-contained: later dictionary versions can
    never change a historical task. Candidate traces omit the mapping payload so
    the frozen config does not multiply into every candidate explanation.
    """

    def __init__(self, metadata: MetadataRepository) -> None:
        self.meta = metadata

    @staticmethod
    def validate_document(document: dict[str, Any]) -> dict[str, object]:
        mapping = document.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            raise DomainError("INVALID_DICTIONARY", "同义词规则至少需要一条", status_code=422)
        normalized: dict[str, str] = {}
        for raw_key, raw_value in mapping.items():
            key = str(raw_key)
            value = str(raw_value)
            if not key:
                raise DomainError("INVALID_DICTIONARY", "同义词的原始写法不能为空", status_code=422)
            normalized[key] = value
        return {
            "mapping": normalized,
            "case_sensitive": bool(document.get("case_sensitive", True)),
        }

    def _dictionary(self, dictionary_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM dictionaries WHERE dictionary_id=?", (dictionary_id,)).fetchone()
        if row is None:
            raise DomainError("DICTIONARY_NOT_FOUND", "同义词表不存在", status_code=404)
        return dict(row)

    def create(self, name: str, document: dict[str, Any], operator: str = "") -> dict[str, object]:
        name = name.strip()
        if not name:
            raise DomainError("INVALID_DICTIONARY_NAME", "同义词表名称不能为空", status_code=422)
        normalized = self.validate_document(document)
        dictionary_id = uuid.uuid4().hex
        created_at = _now()
        digest = _sha(normalized)
        with self.meta.connect() as connection:
            connection.execute("INSERT INTO dictionaries VALUES(?,?,?)", (dictionary_id, name, created_at))
            connection.execute(
                "INSERT INTO dictionary_versions(dictionary_id,version_no,document,sha256,created_at,created_by) VALUES(?,?,?,?,?,?)",
                (dictionary_id, 1, _canonical(normalized), digest, created_at, operator or "system"),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, "dictionary", dictionary_id, "DICTIONARY_CREATED", _canonical({"version_no": 1, "sha256": digest}), created_at),
            )
        return self.get(dictionary_id)

    def list(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*,
                       (SELECT MAX(version_no) FROM dictionary_versions v WHERE v.dictionary_id=d.dictionary_id) AS latest_version,
                       (SELECT sha256 FROM dictionary_versions v2 WHERE v2.dictionary_id=d.dictionary_id ORDER BY version_no DESC LIMIT 1) AS latest_sha256,
                       (SELECT document FROM dictionary_versions v3 WHERE v3.dictionary_id=d.dictionary_id ORDER BY version_no DESC LIMIT 1) AS latest_document,
                       (SELECT created_at FROM dictionary_versions v4 WHERE v4.dictionary_id=d.dictionary_id ORDER BY version_no DESC LIMIT 1) AS updated_at
                FROM dictionaries d ORDER BY COALESCE(updated_at,d.created_at) DESC
                """
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            document = json.loads(str(item.pop("latest_document"))) if item.get("latest_document") else {"mapping": {}}
            item["entry_count"] = len(document.get("mapping", {})) if isinstance(document, dict) else 0
            result.append(item)
        return result

    def get(self, dictionary_id: str) -> dict[str, object]:
        item = self._dictionary(dictionary_id)
        versions = self.versions(dictionary_id)
        item["latest"] = versions[0] if versions else None
        return item

    def versions(self, dictionary_id: str) -> list[dict[str, object]]:
        self._dictionary(dictionary_id)
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dictionary_versions WHERE dictionary_id=? ORDER BY version_no DESC",
                (dictionary_id,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["document"] = json.loads(str(item["document"]))
            result.append(item)
        return result

    def version(self, dictionary_id: str, version_no: int) -> dict[str, object]:
        self._dictionary(dictionary_id)
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT * FROM dictionary_versions WHERE dictionary_id=? AND version_no=?",
                (dictionary_id, int(version_no)),
            ).fetchone()
        if row is None:
            raise DomainError("DICTIONARY_VERSION_NOT_FOUND", "同义词版本不存在", status_code=404)
        item = dict(row)
        item["document"] = json.loads(str(item["document"]))
        return item

    def add_version(
        self,
        dictionary_id: str,
        document: dict[str, Any],
        operator: str = "",
        base_version_no: int | None = None,
    ) -> dict[str, object]:
        self._dictionary(dictionary_id)
        normalized = self.validate_document(document)
        created_at = _now()
        digest = _sha(normalized)
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version_no),0) AS version_no FROM dictionary_versions WHERE dictionary_id=?",
                (dictionary_id,),
            ).fetchone()
            current_version_no = int(row["version_no"])
            if base_version_no is not None and int(base_version_no) != current_version_no:
                raise DomainError(
                    "DICTIONARY_VERSION_CONFLICT",
                    "同义词已被其他人更新，请刷新页面并基于最新版本重新编辑后再保存",
                    status_code=409,
                    details={"current_version_no": current_version_no, "base_version_no": int(base_version_no)},
                )
            version_no = current_version_no + 1
            connection.execute(
                "INSERT INTO dictionary_versions(dictionary_id,version_no,document,sha256,created_at,created_by) VALUES(?,?,?,?,?,?)",
                (dictionary_id, version_no, _canonical(normalized), digest, created_at, operator or "system"),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, "dictionary", dictionary_id, "DICTIONARY_VERSION_CREATED", _canonical({"version_no": version_no, "sha256": digest}), created_at),
            )
        return self.version(dictionary_id, version_no)

    def _visit_pipelines(self, document: dict[str, Any], *, materialize: bool) -> dict[str, Any]:
        resolved = deepcopy(document)
        pipelines: list[list[dict[str, Any]]] = []
        for rule in resolved.get("rules", []) if isinstance(resolved.get("rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            for side_name in ("source", "target"):
                side = rule.get(side_name)
                if isinstance(side, dict) and isinstance(side.get("pipeline"), list):
                    pipelines.append(side["pipeline"])
        retrieval = resolved.get("retrieval")
        if isinstance(retrieval, dict):
            for side_name in ("source", "target"):
                side = retrieval.get(side_name)
                if isinstance(side, dict) and isinstance(side.get("pipeline"), list):
                    pipelines.append(side["pipeline"])

        for pipeline in pipelines:
            for step in pipeline:
                if not isinstance(step, dict) or str(step.get("op")) != "dictionary_map":
                    continue
                options = step.setdefault("options", {})
                if not isinstance(options, dict):
                    raise DomainError("INVALID_DICTIONARY_REFERENCE", "dictionary_map 的 options 格式不正确", status_code=422)
                dictionary_id = options.get("dictionary_id")
                version_no = options.get("version_no")
                if not dictionary_id and isinstance(options.get("mapping"), dict):
                    continue
                if not dictionary_id or version_no is None:
                    raise DomainError("INVALID_DICTIONARY_REFERENCE", "dictionary_map 必须同时指定 dictionary_id 和 version_no", status_code=422)
                version = self.version(str(dictionary_id), int(version_no))
                expected_sha = str(version["sha256"])
                frozen_sha = options.get("dictionary_sha256")
                if frozen_sha and str(frozen_sha) != expected_sha:
                    raise DomainError("DICTIONARY_VERSION_CHANGED", "同义词版本摘要与任务冻结值不一致，请检查数据完整性", status_code=409)
                options["dictionary_id"] = str(dictionary_id)
                options["version_no"] = int(version_no)
                options["dictionary_sha256"] = expected_sha
                options.pop("mapping", None)
                options.pop("case_sensitive", None)
                if materialize:
                    payload = version["document"]
                    if not isinstance(payload, dict):
                        raise DomainError("INVALID_DICTIONARY", "同义词版本内容损坏", status_code=409)
                    options["mapping"] = dict(payload.get("mapping") or {})
                    options["case_sensitive"] = bool(payload.get("case_sensitive", True))
        return resolved

    def bind_references(self, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and make referenced dictionary versions part of the immutable snapshot."""
        return self._visit_pipelines(document, materialize=True)

    def materialize(self, document: dict[str, Any]) -> dict[str, Any]:
        """Refresh runtime mappings while rejecting any SHA mismatch."""
        return self._visit_pipelines(document, materialize=True)
