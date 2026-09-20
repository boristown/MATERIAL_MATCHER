from __future__ import annotations

from datetime import datetime
import hashlib
import json
import uuid

from pydantic import ValidationError

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _canonical(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(document: dict[str, object]) -> str:
    return hashlib.sha256(_canonical(document).encode("utf-8")).hexdigest()


class ProfileService:
    """Versioned, optional matching templates.

    Published versions are immutable. A profile can have one editable DRAFT
    (version_no=0). Rollback never mutates history; it creates a new published
    version copied from the selected historical version.
    """

    def __init__(self, metadata: MetadataRepository) -> None:
        self.meta = metadata
        self.dictionaries = DictionaryService(metadata)

    def _profile(self, profile_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if row is None:
            raise DomainError("PROFILE_NOT_FOUND", "匹配方案不存在", status_code=404)
        return dict(row)

    def _validate(self, document: dict[str, object], *, profile_id: str | None = None) -> MatchingConfig:
        try:
            bound = self.dictionaries.bind_references(document)
            config = MatchingConfig.model_validate(bound)
        except DomainError:
            raise
        except ValidationError as exc:
            message = exc.errors()[0].get("msg", "匹配方案格式不正确") if exc.errors() else "匹配方案格式不正确"
            raise DomainError("INVALID_PROFILE", str(message).replace("Value error, ", ""), status_code=422) from exc
        if not config.source_id_column:
            raise DomainError("INVALID_PROFILE", "匹配方案必须配置客户物料编码字段", status_code=422)

        advanced = config.advanced if isinstance(config.advanced, dict) else {}
        profile_kind = str(advanced.get("profile_kind") or "single")
        if profile_kind == "composite":
            children = advanced.get("composite_children")
            if not isinstance(children, list) or len(children) < 2:
                raise DomainError("INVALID_PROFILE", "跨类目组合方案至少需要选择两个已发布子方案", status_code=422)
            seen: set[tuple[str, int]] = set()
            for child in children:
                if not isinstance(child, dict):
                    raise DomainError("INVALID_PROFILE", "组合方案的子方案配置格式不正确", status_code=422)
                child_id = str(child.get("profile_id") or "")
                try:
                    version_no = int(child.get("version_no"))
                except (TypeError, ValueError):
                    version_no = 0
                if not child_id or version_no <= 0:
                    raise DomainError("INVALID_PROFILE", "组合方案必须固定到已发布的子方案版本", status_code=422)
                if profile_id and child_id == profile_id:
                    raise DomainError("INVALID_PROFILE", "组合方案不能引用自身", status_code=422)
                key = (child_id, version_no)
                if key in seen:
                    raise DomainError("INVALID_PROFILE", "组合方案不能重复选择同一个子方案版本", status_code=422)
                seen.add(key)
                child_version = self.version(child_id, version_no)
                child_document = child_version.get("document") if isinstance(child_version, dict) else None
                child_advanced = child_document.get("advanced") if isinstance(child_document, dict) else {}
                if isinstance(child_advanced, dict) and str(child_advanced.get("profile_kind") or "single") == "composite":
                    raise DomainError("INVALID_PROFILE", "组合方案暂不支持嵌套组合方案，请选择普通子方案", status_code=422)
            return config

        if profile_kind not in {"", "single"}:
            raise DomainError("INVALID_PROFILE", f"不支持的方案类型：{profile_kind}", status_code=422)
        if not config.rules:
            raise DomainError("INVALID_PROFILE", "普通匹配方案至少需要一条字段匹配规则", status_code=422)
        return config

    def create(self, name: str, document: dict[str, object] | None = None) -> dict[str, object]:
        name = name.strip()
        if not name:
            raise DomainError("INVALID_PROFILE_NAME", "匹配方案名称不能为空", status_code=422)
        profile_id = uuid.uuid4().hex
        created_at = _now()
        draft = document or {}
        with self.meta.connect() as connection:
            connection.execute("INSERT INTO profiles VALUES(?,?,?)", (profile_id, name, created_at))
            connection.execute(
                "INSERT INTO profile_versions(profile_id,version_no,document,sha256,status,created_at) VALUES(?,?,?,?,?,?)",
                (profile_id, 0, _canonical(draft), _sha(draft), "DRAFT", created_at),
            )
        return self.get(profile_id)

    def list(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*,
                       (SELECT MAX(version_no) FROM profile_versions v WHERE v.profile_id=p.profile_id AND v.status='PUBLISHED') AS latest_published_version,
                       EXISTS(SELECT 1 FROM profile_versions d WHERE d.profile_id=p.profile_id AND d.status='DRAFT') AS has_draft,
                       (SELECT created_at FROM profile_versions v2 WHERE v2.profile_id=p.profile_id ORDER BY CASE WHEN status='DRAFT' THEN 1 ELSE 0 END DESC, version_no DESC LIMIT 1) AS updated_at
                FROM profiles p ORDER BY p.name ASC, COALESCE(updated_at,p.created_at) DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        with self.meta.connect() as connection:
            draft = connection.execute("SELECT * FROM profile_versions WHERE profile_id=? AND status='DRAFT'", (profile_id,)).fetchone()
            published = connection.execute("SELECT * FROM profile_versions WHERE profile_id=? AND status='PUBLISHED' ORDER BY version_no DESC LIMIT 1", (profile_id,)).fetchone()
        profile["draft"] = self._decode_version(draft)
        profile["latest_published"] = self._decode_version(published)
        return profile

    @staticmethod
    def _decode_version(row) -> dict[str, object] | None:
        if row is None:
            return None
        item = dict(row)
        item["document"] = json.loads(str(item["document"]))
        return item

    def save_draft(self, profile_id: str, document: dict[str, object]) -> dict[str, object]:
        self._profile(profile_id)
        now = _now()
        with self.meta.connect() as connection:
            existing = connection.execute("SELECT 1 FROM profile_versions WHERE profile_id=? AND status='DRAFT'", (profile_id,)).fetchone()
            if existing:
                connection.execute(
                    "UPDATE profile_versions SET document=?,sha256=?,created_at=? WHERE profile_id=? AND status='DRAFT'",
                    (_canonical(document), _sha(document), now, profile_id),
                )
            else:
                connection.execute(
                    "INSERT INTO profile_versions(profile_id,version_no,document,sha256,status,created_at) VALUES(?,?,?,?,?,?)",
                    (profile_id, 0, _canonical(document), _sha(document), "DRAFT", now),
                )
        return self.get(profile_id)

    def rename(self, profile_id: str, name: str) -> dict[str, object]:
        name = str(name or "").strip()
        if not name or len(name) > 120:
            raise DomainError("INVALID_PROFILE_NAME", "方案名称不能为空且不能超过120个字符", status_code=422)
        self._profile(profile_id)
        with self.meta.connect() as connection:
            connection.execute("UPDATE profiles SET name=? WHERE profile_id=?", (name, profile_id))
        return {"profile_id": profile_id, "name": name}

    def delete(self, profile_id: str) -> dict[str, object]:
        self._profile(profile_id)
        with self.meta.connect() as connection:
            draft_refs = int(connection.execute("SELECT COUNT(*) FROM task_drafts WHERE template_profile_id=?", (profile_id,)).fetchone()[0])
            task_refs = int(connection.execute("SELECT COUNT(*) FROM tasks WHERE profile_id=?", (profile_id,)).fetchone()[0])
            if draft_refs or task_refs:
                raise DomainError(
                    "PROFILE_IN_USE",
                    f"方案已被 {task_refs} 个任务 / {draft_refs} 个草稿引用,不能删除;可改名或停用引用后再删",
                    status_code=409,
                    details={"task_refs": task_refs, "draft_refs": draft_refs},
                )
            connection.execute("DELETE FROM profile_versions WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
        return {"deleted": profile_id}

    def validate(self, profile_id: str) -> dict[str, object]:
        profile = self.get(profile_id)
        draft = profile.get("draft")
        if not isinstance(draft, dict):
            raise DomainError("PROFILE_DRAFT_NOT_FOUND", "当前方案没有可校验的草稿", status_code=409)
        config = self._validate(dict(draft["document"]), profile_id=profile_id)
        return {"ok": True, "profile_id": profile_id, "normalized": config.model_dump(mode="json")}

    def publish(self, profile_id: str) -> dict[str, object]:
        profile = self.get(profile_id)
        draft = profile.get("draft")
        if not isinstance(draft, dict):
            raise DomainError("PROFILE_DRAFT_NOT_FOUND", "当前方案没有可发布的草稿", status_code=409)
        config = self._validate(dict(draft["document"]), profile_id=profile_id)
        normalized = config.model_dump(mode="json")
        now = _now()
        with self.meta.connect() as connection:
            row = connection.execute("SELECT COALESCE(MAX(version_no),0) AS version_no FROM profile_versions WHERE profile_id=? AND status='PUBLISHED'", (profile_id,)).fetchone()
            version_no = int(row["version_no"]) + 1
            connection.execute(
                "INSERT INTO profile_versions(profile_id,version_no,document,sha256,status,created_at) VALUES(?,?,?,?,?,?)",
                (profile_id, version_no, _canonical(normalized), _sha(normalized), "PUBLISHED", now),
            )
            connection.execute("DELETE FROM profile_versions WHERE profile_id=? AND status='DRAFT'", (profile_id,))
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, "profile", profile_id, "PROFILE_PUBLISHED", _canonical({"version_no": version_no, "sha256": _sha(normalized)}), now),
            )
        return self.version(profile_id, version_no)

    def versions(self, profile_id: str) -> list[dict[str, object]]:
        self._profile(profile_id)
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT * FROM profile_versions WHERE profile_id=? ORDER BY CASE WHEN status='DRAFT' THEN 0 ELSE 1 END, version_no DESC", (profile_id,)).fetchall()
        return [self._decode_version(row) for row in rows]

    def version(self, profile_id: str, version_no: int) -> dict[str, object]:
        self._profile(profile_id)
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM profile_versions WHERE profile_id=? AND version_no=? AND status='PUBLISHED'", (profile_id, version_no)).fetchone()
        item = self._decode_version(row)
        if item is None:
            raise DomainError("PROFILE_VERSION_NOT_FOUND", "匹配方案版本不存在", status_code=404)
        return item

    def rollback(self, profile_id: str, version_no: int) -> dict[str, object]:
        source = self.version(profile_id, version_no)
        document = dict(source["document"])
        now = _now()
        with self.meta.connect() as connection:
            latest = connection.execute("SELECT COALESCE(MAX(version_no),0) AS version_no FROM profile_versions WHERE profile_id=? AND status='PUBLISHED'", (profile_id,)).fetchone()
            new_version = int(latest["version_no"]) + 1
            connection.execute(
                "INSERT INTO profile_versions(profile_id,version_no,document,sha256,status,created_at) VALUES(?,?,?,?,?,?)",
                (profile_id, new_version, _canonical(document), _sha(document), "PUBLISHED", now),
            )
            connection.execute("DELETE FROM profile_versions WHERE profile_id=? AND status='DRAFT'", (profile_id,))
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, "profile", profile_id, "PROFILE_ROLLBACK_PUBLISHED", _canonical({"source_version": version_no, "new_version": new_version}), now),
            )
        return self.version(profile_id, new_version)
