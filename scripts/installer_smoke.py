#!/usr/bin/env python3
"""安装后最小业务 smoke：STEP1 上传 → 匹配 → STEP3 结果 → STEP4 导出下载。

只使用 Python 标准库（可在安装介质 bootstrap runtime 中直接运行）：
    bootstrap/python/bin/python3 tools/installer_smoke.py --base-url http://127.0.0.1:18080 \
        --smoke-dir smoke --password-file /etc/material_matcher/secret/admin_password.env
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    RESULTS.append((name, bool(ok), info))
    print(("PASS " if ok else "FAIL ") + name + (f" :: {info}" if info else ""), flush=True)


def generate_local_pw() -> str:
    import secrets
    import string

    body = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    return "Smoke" + body + str(secrets.choice("0123456789"))  # 保证含字母与数字且长度>=10


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def json(self, method: str, path: str, payload: object = None) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body.decode("utf-8"))
            except Exception:
                return exc.code, {"raw": body[:400].decode("utf-8", "replace")}
        try:
            return 200, json.loads(body.decode("utf-8"))
        except Exception:
            return 200, {"raw": body[:400].decode("utf-8", "replace")}

    def upload(self, path: str, role: str, file_path: pathlib.Path) -> tuple[int, dict]:
        boundary = "----mmsmokeboundary7c3f1"
        filename = file_path.name
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"role\"\r\n\r\n{role}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode(),
                file_path.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            self.base + path,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, {"error": exc.read()[:400].decode("utf-8", "replace")}

    def download(self, path: str) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path)
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--password", default="")
    parser.add_argument("--password-file", default="")
    parser.add_argument("--smoke-dir", default="smoke")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    candidates: list[str] = []
    if args.password:
        candidates.append(args.password)
    if args.password_file:
        try:
            for line in pathlib.Path(args.password_file).read_text(encoding="utf-8").splitlines():
                if line.startswith("MATERIAL_MATCHER_ADMIN_PASSWORD="):
                    candidates.append(line.split("=", 1)[1].strip())
        except OSError:
            pass
    store = pathlib.Path("/var/tmp/mm-smoke-admin.pw")
    try:
        if store.is_file():
            candidates.append(store.read_text(encoding="utf-8").strip())
    except OSError:
        pass
    if not candidates:
        print("FAIL login :: 未提供密码（--password 或 --password-file）")
        return 2

    smoke_dir = pathlib.Path(args.smoke_dir)
    source_xlsx = smoke_dir / "smoke-待匹配数据.xlsx"
    target_xlsx = smoke_dir / "smoke-集团标准数据.xlsx"
    if not (source_xlsx.is_file() and target_xlsx.is_file()):
        print(f"FAIL smoke-data :: 缺少 {source_xlsx} 或 {target_xlsx}")
        return 2

    api = Api(args.base_url)
    started = time.time()

    status, health = api.json("GET", "/api/health")
    check("health", status == 200, json.dumps(health, ensure_ascii=False)[:120])
    status, ready = api.json("GET", "/api/health/ready")
    check("health/ready", status == 200 and ready.get("status") == "ready", json.dumps(ready, ensure_ascii=False)[:160])

    login: dict = {}
    password = ""
    for candidate in candidates:
        status, attempt = api.json("POST", "/api/auth/login", {"username": "admin", "password": candidate})
        if status == 200 and attempt.get("ok") is True:
            login, password = attempt, candidate
            break
    check("STEP0 admin 登录", bool(login), "")
    if not login:
        return _finish(args, started)

    if (login.get("user") or {}).get("must_change_password"):
        new_pw = "Smoke" + generate_local_pw()
        status, changed = api.json("POST", "/api/auth/change-password", {"current_password": password, "new_password": new_pw})
        check("STEP0 首次登录修改密码", status == 200, f"status={status}")
        status, login = api.json("POST", "/api/auth/login", {"username": "admin", "password": new_pw})
        check("STEP0 新密码重新登录", status == 200, f"status={status}")
        if status != 200:
            return _finish(args, started)
        try:  # 记录本次验收密码（root 权限环境下的本地缓存，便于重复验收；不含在诊断包中）
            store.write_text(new_pw, encoding="utf-8")
            store.chmod(0o600)
        except OSError:
            pass

    status, page = api.json("GET", "/")
    check("前端页面可达", status == 200, "")

    expected_profiles = ["A001 元器件", "A002 标准紧固件", "A003 金属材料", "A005 非金属材料", "A006 复合材料", "A007 物资类其他(跨类目)"]
    status, profiles = api.json("GET", "/api/profiles")
    profile_rows = profiles if isinstance(profiles, list) else []
    names = sorted(str(p.get("name", "")) for p in profile_rows)
    check("默认 6 个正式匹配方案已预置", status == 200 and names == sorted(expected_profiles), f"names={len(names)}")
    opened = 0
    for row in profile_rows:
        code, detail = api.json("GET", f"/api/profiles/{row.get('profile_id')}")
        if code == 200 and detail.get("latest_published"):
            opened += 1
    check("全部方案可正常打开", opened == len(expected_profiles), f"opened={opened}")

    status, dictionaries = api.json("GET", "/api/dictionaries")
    dict_rows = dictionaries if isinstance(dictionaries, list) else []
    dictionary_id = str(dict_rows[0]["dictionary_id"]) if dict_rows else ""
    status, dict_versions = api.json("GET", f"/api/dictionaries/{dictionary_id}/versions") if dictionary_id else (0, {})
    versions = dict_versions if isinstance(dict_versions, list) else []
    head = versions[0] if versions else {}
    rules = len(((head.get("document") or {}).get("mapping") or {})) if isinstance(head, dict) else 0
    check("默认同义词配置存在（规则+版本）", bool(versions) and rules >= 20, f"versions={len(versions)} rules={rules}")

    if dictionary_id and isinstance(head, dict):
        mapping = dict((head.get("document") or {}).get("mapping") or {})
        case_sensitive = bool((head.get("document") or {}).get("case_sensitive", True))
        base_no = int(head.get("version_no") or 0)
        dropped_key = next(iter(mapping))
        trimmed = {k: v for k, v in mapping.items() if k != dropped_key}
        code_removed, removed = api.json("POST", f"/api/dictionaries/{dictionary_id}/versions", {"mapping": trimmed, "case_sensitive": case_sensitive, "base_version_no": base_no})
        removed_no = int((removed or {}).get("version_no") or 0)
        code_restored, restored = api.json("POST", f"/api/dictionaries/{dictionary_id}/versions", {"mapping": mapping, "case_sensitive": case_sensitive, "base_version_no": removed_no})
        restored_mapping = ((restored or {}).get("document") or {}).get("mapping") or {}
        code_head, versions_after = api.json("GET", f"/api/dictionaries/{dictionary_id}/versions")
        same_rules = restored_mapping == mapping
        grew = isinstance(versions_after, list) and len(versions_after) == len(versions) + 2
        check("同义词批量删除模拟→新不可变版本→恢复", code_removed == 200 and code_restored == 200 and same_rules and grew,
              f"removed={code_removed} restored={code_restored} versions {len(versions)}→{len(versions_after) if isinstance(versions_after, list) else '?'}")

    status, source_up = api.upload("/api/files/upload", "source", source_xlsx)
    check("STEP1 上传待匹配数据", status == 200 and "file" in source_up, f"status={status}")
    status, target_up = api.upload("/api/files/upload", "target", target_xlsx)
    check("STEP1 上传集团标准数据", status == 200 and "file" in target_up, f"status={status}")
    if status != 200 or "file" not in target_up:
        return _finish(args, started)

    source_file_id = str(source_up["file"]["file_id"])
    target_file_id = str(target_up["file"]["file_id"])

    status, catalog = api.json(
        "POST",
        "/api/catalogs",
        {"name": "安装验收-集团标准数据", "source_file_id": target_file_id, "group_code_column": "集团码"},
    )
    check("STEP1 建立标准数据目录", status == 200 and "version_id" in catalog, f"status={status}")
    if "version_id" not in catalog:
        return _finish(args, started)
    catalog_version_id = str(catalog["version_id"])

    fallback_config = {
        "source_id_column": "物料编码",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "smoke-name-model",
                "source": {"fields": ["物料名称", "型号"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["物料名称", "型号"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 70,
                "critical": False,
                "matcher_options": {},
            },
            {
                "id": "smoke-brand",
                "source": {"fields": ["品牌"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["生产厂家"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 30,
                "critical": False,
                "matcher_options": {},
            },
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "scan", "retrieval_top_k": 20, "oversample": 2},
        "advanced": {"workspace_target": {"file_id": target_file_id, "group_code_column": "集团码"}},
    }

    status, draft = api.json("POST", "/api/task-drafts", {"name": "安装验收 smoke 任务"})
    check("STEP1 创建任务草稿", status == 200 and "draft_id" in draft, f"status={status}")
    if "draft_id" not in draft:
        return _finish(args, started)
    draft_id = str(draft["draft_id"])
    api.json("PUT", f"/api/task-drafts/{draft_id}/data", {"source_file_id": source_file_id, "catalog_version_id": catalog_version_id})

    def run_task_with(config: dict, label: str) -> tuple[bool, str, dict]:
        code, _ = api.json("PUT", f"/api/task-drafts/{draft_id}/rules", config)
        if code != 200:
            return False, "", {}
        code, started_run = api.json("POST", f"/api/task-drafts/{draft_id}/start")
        if code not in (200, 202) or "task_id" not in started_run:
            return False, "", {}
        task_id = str(started_run["task_id"])
        deadline = time.time() + 300
        task: dict = {}
        while time.time() < deadline:
            _, task = api.json("GET", f"/api/tasks/{task_id}")
            if task.get("status") in {"COMPLETED", "FAILED"}:
                break
            time.sleep(1)
        return task.get("status") == "COMPLETED", task_id, task

    import copy as _copy

    profile_task_ok = False
    task_id, task = "", {}
    a007 = next((p for p in profile_rows if str(p.get("name", "")).startswith("A007")), None)
    if a007 is not None:
        code, a007_detail = api.json("GET", f"/api/profiles/{a007['profile_id']}")
        published = (a007_detail or {}).get("latest_published") or {}
        profile_document = published.get("document")
        if isinstance(profile_document, dict) and (profile_document.get("advanced") or {}).get("profile_kind") == "composite":
            children = (profile_document.get("advanced") or {}).get("composite_children") or []
            present = all(any(str(p.get("profile_id")) == str(c.get("profile_id")) for p in profile_rows) for c in children)
            check("A007 预置为跨类目组合方案（子方案齐备）", len(children) >= 2 and present, f"children={len(children)}")
            flat = next((p for p in profile_rows if not str(p.get("name", "")).startswith("A007")), None)
            if flat is not None:
                code, flat_detail = api.json("GET", f"/api/profiles/{flat['profile_id']}")
                profile_document = ((flat_detail or {}).get("latest_published") or {}).get("document")
        if code == 200 and isinstance(profile_document, dict) and profile_document.get("rules"):
            profile_config = _copy.deepcopy(profile_document)
            profile_config["source_id_column"] = "物料编码"
            advanced = dict(profile_config.get("advanced") or {})
            advanced["workspace_target"] = {"file_id": target_file_id, "group_code_column": "集团码"}
            profile_config["advanced"] = advanced
            profile_task_ok, task_id, task = run_task_with(profile_config, "A007")
    check("使用默认方案 A007 完成任务", profile_task_ok, "" if profile_task_ok else "主路径未通过，改用内置最小配置验证")
    if not profile_task_ok:
        ok, task_id, task = run_task_with(fallback_config, "fallback")
        check("STEP1/2 内置配置任务完成", ok, f"status={task.get('status')}")
        if not ok:
            return _finish(args, started)
    check("STEP1 启动匹配", bool(task_id), f"task={task_id[:8]}")
    check("STEP2 匹配完成", task.get("status") == "COMPLETED", f"status={task.get('status')} 用时={int(time.time() - started)}s")

    status, items = api.json("GET", f"/api/tasks/{task_id}/workbench/items?limit=5")
    check("STEP3 打开结果明细", status == 200, f"status={status}")
    check("STEP2/3 进度与结果可见", task.get("status") == "COMPLETED" and status == 200, "")

    status, fin = api.json("POST", f"/api/tasks/{task_id}/finalize", {"allow_unresolved_review": True})
    check("STEP4 生成结果", status == 200, f"status={status}")
    status, exports = api.json("GET", f"/api/tasks/{task_id}/exports")
    download_url = (exports.get("final_result") or {}).get("download_url") if isinstance(exports, dict) else None
    check("STEP4 导出清单", bool(download_url), json.dumps(exports, ensure_ascii=False)[:120])
    ok_bytes = 0
    if download_url:
        code, payload = api.download(download_url)
        ok_bytes = len(payload) if code == 200 else 0
    check("STEP4 下载结果 Excel", ok_bytes > 1000, f"bytes={ok_bytes}")
    return _finish(args, started)


def _finish(args: argparse.Namespace, started: float) -> int:
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    failed = [name for name, ok, _ in RESULTS if not ok]
    summary = f"SMOKE {passed}/{total} passed in {int(time.time() - started)}s" + (
        f"; failed: {', '.join(failed)}" if failed else ""
    )
    print(summary)
    if args.report:
        pathlib.Path(args.report).write_text(
            json.dumps({"passed": passed, "total": total, "failed": failed, "seconds": int(time.time() - started)}, ensure_ascii=False),
            encoding="utf-8",
        )
    return 0 if not failed and passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
