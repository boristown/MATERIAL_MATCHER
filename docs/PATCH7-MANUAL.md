# PATCH7 手敲现场版：复核工作台按值映射显示源值（"10"→"国产"）
外网代码：main `v1.3.19`。本手册让客户机（1.3.14/15/16 基线）在不重启前端的情况下获得同样效果。
原理：workbench 接口出口把源值按方案 value_mapping 替换后返回；**数据库、人工匹配 Excel、结果导出仍是原始值**（审计保真）。

## 步骤（容器内逐行，每行看回显）
```
cd /opt/material_matcher/current/app/material_matcher/services
```
```
cp review_workbench_service.py review_workbench_service.py.bak-p7
```
```
grep -c '_value_mapping' review_workbench_service.py
```
→ 回显 `0` 才继续（`2` 说明已打过，直接跳"重启"）。
```
sed -i 's/item\["source_payload"\] = self._decode(item.get("source_payload"))/item["source_payload"] = self._apply_value_mapping(self._decode(item.get("source_payload")), self._value_mapping(task_id))/' review_workbench_service.py
```
```
grep -c '_apply_value_mapping' review_workbench_service.py
```
→ 回显应为 `2`（列表 + 单条两个出口）。
追加辅助函数（整段是一个 heredoc，一次敲入，回显是提示符回到 # 或 $）：
```
cat >> review_workbench_service.py <<'E'
def _p7_vmap(self, task_id):
    import json as _j
    m = {}
    try:
        with self.repo.connect() as cn:
            r = cn.execute("SELECT config_snapshot FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        cfg = _j.loads(str(r[0])) if r and r[0] else {}
        for rule in cfg.get("rules", []) or []:
            vm = rule.get("value_mapping") or {}
            if vm:
                for f in ((rule.get("source") or {}).get("fields") or []):
                    d = m.setdefault(str(f), {})
                    for k, v in vm.items():
                        d[str(k).strip()] = str(v)
    except Exception:
        return {}
    return m
def _p7_apply(payload, m):
    if not isinstance(payload, dict) or not m:
        return payload
    out = dict(payload)
    for f, mm in m.items():
        v = out.get(f)
        if v is not None and str(v).strip() in mm:
            out[f] = mm[str(v).strip()]
    return out
ReviewWorkbenchService._value_mapping = _p7_vmap
ReviewWorkbenchService._apply_value_mapping = staticmethod(_p7_apply)
E
```
```
/opt/material_matcher/current/runtime/bin/python3 -m py_compile review_workbench_service.py
```
→ 无输出 = OK。
## 重启（宿主机）
```
exit
```
```
docker restart material_matcher-app
```
## 验证
页面 Ctrl+F5 → 任一带映射（10→国产）的记录：源列显示 `国产`，字段对比"一致"。
## 回滚（容器内一行）
```
mv /opt/material_matcher/current/app/material_matcher/services/review_workbench_service.py.bak-p7 /opt/material_matcher/current/app/material_matcher/services/review_workbench_service.py
```
然后宿主机 `docker restart material_matcher-app`。
