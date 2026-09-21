#!/usr/bin/env python3
"""撤回种子中写死列名的 value_mapping 预置规则（seed-enum-gnjk）。
用法（native 或容器内均可）：python3 unseed_value_preset.py
幂等：已无该规则的方案自动跳过；有变化的方案以“移除预置规则”发布新版本。"""
import sys, json
sys.path.insert(0, "/opt/material_matcher/current/app")
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.services.profile_service import ProfileService

s = Settings.load()
meta = MetadataRepository(s.data_dir / "meta" / "material_matcher.db")
svc = ProfileService(meta)
done = []
with meta.connect() as cc:
    rows = cc.execute("SELECT profile_id, name FROM profiles").fetchall()
for pid, name in [(str(r[0]), str(r[1])) for r in rows]:
    try:
        info = svc.get(pid)
        cur = (info.get("latest_published") or {}).get("document")
        if not isinstance(cur, dict):
            continue
        rules = cur.get("rules") or []
        kept = [r for r in rules if r.get("id") != "seed-enum-gnjk"]
        if len(kept) == len(rules):
            continue
        newdoc = dict(cur); newdoc["rules"] = kept
        svc.save_draft(pid, newdoc)
        svc.publish(pid)
        done.append(name)
    except Exception as e:
        print("skip", name, type(e).__name__, str(e)[:80])
print("unseeded:", done or "nothing (all clean)")
