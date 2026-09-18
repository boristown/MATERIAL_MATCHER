testG-backup-restore.log：菜单/命令行备份（sqlite3 backup API 经容器写入宿主 bind 目录）→ verify（integrity ok，27 表）→ 插入 zombie → restore（自动留存 pre-restore）→ zombie 消失、服务 ready → export 诊断包（DIAG-NO-PASSWORD）。
