# 升级与回滚验证（最终介质 1.1.22，全新 Snapshot-0 容器）

## 升级（Test E，mm-cr-e6）
1. 以旧正式介质 1.1.15 安装旧系统（端口随机 14515，属旧版行为）；
2. 以原厂 smoke 工具向旧系统灌入真实业务：上传 2 组数据、建目录、建草稿、启动匹配、生成结果（17/17）；
3. DB 指纹 before：inode=3342162657 size=299008；
4. 新介质向导升级：自动识别“升级安装”、沿用端口 14515、保留 admin 密码、storage.env 指向不变；
5. after：current→releases/1.1.22，previous→releases/1.1.15；DB inode/size 完全不变；
   users=['admin']、tasks=1、sessions=1、files=3、results 目录 1 项——全部保留；
   /api/health version=1.1.22。
结论：升级保数据 ✅（session 设计符合产品预期：同库升级 session 存活）。

## 升级失败自动回滚（Test F/R，mm-cr-r6）
- 构造“通过完整性校验但启动即崩”的合成坏构建 1.1.99（容器内注入，模拟构建期缺陷；正式介质从未发布过坏包）；
- 向导升级：介质校验→复制→doctor 通过→切换→start→readiness 120s 失败；
- 结果 rc=48；current 自动回滚至 releases/1.1.22，模型 current 同步回滚；
  服务 active、health=1.1.22、数据（users）不变；失败信息为业务语言 + 处理建议。
结论：失败自动回滚 ✅。

## 数据保护红线复验
- storage.env 单一来源、两份 DB 阻断逻辑在安装器中生效（D 轮与单测覆盖）；
- 升级/重装不清空 uploads/results/indexes，不重置 admin，不覆盖既有密码文件（E/R 实测）。
