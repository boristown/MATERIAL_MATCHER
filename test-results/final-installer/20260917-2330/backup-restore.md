# 备份 / 验证 / 恢复（Test G，mm-cr-g6，1.1.22 正式介质）

路径：安装后通过中文维护菜单（维护工具.sh 终端模式）执行：
1. 菜单 8) 备份数据 → 生成 /var/backups/material_matcher/mm-backup-<ts>.tar.gz
   （sqlite3 backup API 一致性备份 + /etc/material_matcher 配置，包权限 0600）；
2. 菜单 9) 验证最近备份 → “备份验证通过：integrity=ok，表数量=25”；
3. 制造漂移：运行库中插入 zombie 用户；
4. mmctl restore <备份> → 恢复前自动留存当前库 material_matcher.db.pre-restore-<ts>；
5. 恢复后：users=['admin']（zombie 消失）、服务 active、/api/health/ready=ready。

诊断包安全检查（导出 mm-diagnostics-*.tar.gz）：不含 admin 密码/会话/客户文件正文/全量 DB（grep 验证 0 命中）。
结论：备份恢复 ✅。
