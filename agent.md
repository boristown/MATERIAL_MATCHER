# MATERIAL_MATCHER 运维 Agent 上线执行手册

> 适用对象：负责将 MATERIAL_MATCHER 部署到客户银河麒麟 Linux V10 环境的运维智能体。  
> 目标：把已经完成的代码交付转换为**有证据、可回滚、可验收**的正式上线。  
> 原则：本文件是执行契约，不是建议清单。不得为了“完成任务”跳过任何失败门禁，也不得把 synthetic benchmark 当成生产验收。

## 0. 成功定义

只有同时满足以下条件，才允许报告“正式上线完成”：

1. 部署的是经过 CI 全绿且版本与 `src/material_matcher/VERSION` 一致的精确提交/发布产物；
2. 离线包三层完整性校验通过；
3. 目标机明确识别为银河麒麟 Linux V10，CPU 架构与介质一致；
4. `material-matcher doctor --require-frontend --require-embedding --require-release-manifest` 成功；
5. systemd 服务 active，`/api/health` 和 `/api/health/ready` 均成功；
6. bootstrap `admin` 已完成首次密码轮换；
7. RBAC 至少验证 admin/operator/reviewer/viewer 的服务端权限边界；
8. 项目方已**事先批准**业务准确率与性能阈值，并写入验收环境变量；
9. 正式 `BAAI/bge-base-zh-v1.5` ONNX/tokenizer 已安装并完成真实 Embedding benchmark；
10. BBQ synthetic Recall benchmark 已执行，仅作为检索回归保护；
11. 使用真实历史正确集团码/人工金标完成业务准确率验收，且达到事先批准阈值；
12. 至少完成一次 **>=100,000 Source × >=1,000,000 Target** 的真实端到端任务，且耗时达到事先批准阈值；
13. 最终执行 `material-matcher acceptance --require-production-ready`，退出码必须为 **0** 且 JSON 中 `production_ready=true`；
14. 保存完整上线证据包和回滚点。

如果最后仍有 `BLOCKED`，说明代码路径已经具备但外部证据尚不完整；**不得**把 `code_ready=true` 描述为生产已上线。

---

## 1. 不可违反的护栏

- 正式环境**禁止 Docker**；使用仓库提供的自包含 Runtime + systemd。
- 正式安装**禁止联网补依赖**。Runtime 准备阶段必须使用 `pip --no-index`；缺 wheel 就停止。
- 正式环境禁止设置 `MATERIAL_MATCHER_ALLOW_UNSUPPORTED_OS=1`。该变量只允许非生产测试。
- 禁止跳过 `verify_offline_bundle.py`、`doctor`、readiness 或最终 `acceptance`。
- 禁止手工修改发布目录中的 Python/JS/模型文件；任何修改都会破坏 manifest 证据链。
- 禁止直接覆盖 `/opt/material_matcher/current` 或 `/var/lib/material_matcher/models/current` 的内容；它们必须是版本化目录的链接。
- 禁止删除 `/var/lib/material_matcher`、历史索引、历史结果或历史数据库来“解决升级问题”。
- 禁止在看到验收结果后反向降低阈值。阈值必须由业务/项目负责人在正式金标与百万级测试**之前**确认。
- 禁止用 `benchmark vector` 的 synthetic Recall 替代真实业务准确率。
- 禁止用小样本任务、估算值或投影时间替代 100K×1M 正式任务。
- 不要在目标机改源码。如果发现代码缺陷，停止上线并回到 GitHub 走修复 PR + CI。

---

## 2. 上线前必须获得的输入

开始前逐项确认；任何必需项不存在时，记录为 `BLOCKED` 并停止对应阶段。

### 2.1 代码与版本

- Git 仓库：`boristown/MATERIAL_MATCHER`
- 正式版本：以 `src/material_matcher/VERSION` 为唯一人工维护源；升级版本时只修改这一处
- 精确 Git commit SHA：由最终合并/发布时记录，不能只写 `main`。
- PR #4 已合并或明确批准用于交付，最终提交 CI backend/frontend 均为绿色。

### 2.2 目标机

- 银河麒麟 Linux V10；
- systemd 可用；
- root/sudo 权限；
- CPU 架构为 `x86_64` 或 `aarch64`；
- 足够的本地持久化磁盘；
- 内存容量满足客户验收计划；
- 客户网络/防火墙允许访问最终选定的 12000–29999 高位端口。

### 2.3 离线构建输入（不得进入 Git）

- 与目标架构一致、可整体迁移的基础 Python Runtime；
- 完整 wheelhouse，包括正式依赖及传递依赖；
- `onnxruntime`；
- `tokenizers`；
- 正式模型目录 `BAAI/bge-base-zh-v1.5`，至少包含：
  - `tokenizer.json`
  - `model_int8.onnx` 或 `model.onnx`
- Node 构建环境仅需要存在于发布机，客户机无需 Node。

### 2.4 业务验收输入

上线前向项目负责人获取并记录以下**批准值**，不要自行决定：

```text
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_ROWS=<正整数>
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_COVERAGE=<0..1>
MATERIAL_MATCHER_ACCEPTANCE_MIN_TOP1_ACCURACY=<0..1>
MATERIAL_MATCHER_ACCEPTANCE_MIN_FINAL_ACCURACY=<0..1>
MATERIAL_MATCHER_ACCEPTANCE_MAX_REVIEW_RATE=<0..1>
MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS=<正数，小时>
```

还必须准备：

- 客户真实 >=1,000,000 行 Target 集团码目录；
- 客户真实 >=100,000 行 Source；
- 独立真实金标/历史正确集团码文件；
- 明确金标对齐字段（`source_id` 或 `source_row_id`）与正确集团码列。

---

## 3. 发布机：锁定代码并跑源码门禁

不要直接从浮动分支构建。切到批准的精确提交：

```bash
git clone https://github.com/boristown/MATERIAL_MATCHER.git
cd MATERIAL_MATCHER
git fetch --all --tags
git checkout <APPROVED_COMMIT_SHA>
git status --porcelain
```

`git status --porcelain` 必须为空。

确认 canonical 版本。发布人员升级版本时**只修改** `src/material_matcher/VERSION`：

```bash
RELEASE_VERSION="$(cat src/material_matcher/VERSION)"
printf 'MATERIAL_MATCHER version: %s\n' "$RELEASE_VERSION"
```

`pyproject.toml` 使用 PEP 621 dynamic version，不再维护第二份产品版本号。

如果发布机允许安装开发依赖，执行：

```bash
python3 -m pip install -e '.[dev]'
python3 - <<'PY'
from importlib.metadata import version
import material_matcher
from pathlib import Path
canonical = Path('src/material_matcher/VERSION').read_text(encoding='utf-8').strip()
assert material_matcher.__version__ == canonical
assert version('material-matcher') == canonical
print(canonical)
PY
pytest -q
python3 -m compileall -q src
bash -n installer/install.sh
python3 scripts/check_repo_files.py
```

前端：

```bash
cd web
npm install --no-audit --no-fund
npm run build
cd ..
```

任一步失败立即停止，不构建正式介质。

---

## 4. 发布机：生成自包含 Runtime

假设：

```text
/release-input/python-base
/release-input/wheelhouse
/release-input/models/BAAI/bge-base-zh-v1.5
/release-work
/release-output
```

先确定目标架构：

```bash
TARGET_ARCH=x86_64   # 或 aarch64；必须与客户机 uname -m 对应
```

生成 Runtime：

```bash
python3 scripts/prepare_runtime.py \
  --base-runtime-dir /release-input/python-base \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-work/runtime \
  --target-arch "$TARGET_ARCH"
```

该步骤必须成功完成离线依赖安装、`pip check`、关键模块 import、CPU 架构校验和 Runtime 文件树摘要。

---

## 5. 发布机：构建 Release

确认 `web/dist/index.html` 已存在，然后：

```bash
python3 scripts/build_release.py \
  --runtime-dir /release-work/runtime \
  --web-dist-dir web/dist \
  --output-dir /release-work/release \
  --target-arch "$TARGET_ARCH"
```

必须得到：

```text
/release-work/release/
  app/material_matcher/
  runtime/
  web/dist/
  release-manifest.json
```

Release builder 会拒绝版本不一致、Runtime 摘要错误、架构不一致、启动器不可执行或前端缺失。

---

## 6. 发布机：组装并验证正式离线包

```bash
RELEASE_VERSION="$(cat src/material_matcher/VERSION)"
BUNDLE="/release-output/material-matcher-${RELEASE_VERSION}-${TARGET_ARCH}"
python3 scripts/build_offline_bundle.py \
  --release-dir /release-work/release \
  --model-dir /release-input/models/BAAI/bge-base-zh-v1.5 \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir "$BUNDLE" \
  --target-arch "$TARGET_ARCH" \
  --model-id BAAI/bge-base-zh-v1.5
```

发布机可先做结构预检：

```bash
python3 "$BUNDLE/verify_offline_bundle.py" "$BUNDLE" --skip-arch
sha256sum "$BUNDLE/offline-manifest.json"
```

保存：

- approved commit SHA；
- `offline-manifest.json` SHA-256；
- `release-manifest.json`；
- `runtime-manifest.json`；
- Target arch。

`--skip-arch` 仅允许发布机预检；目标机禁止使用。

---

## 7. 目标机：安装前取证与备份

先记录目标机：

```bash
cat /etc/os-release
uname -m
systemctl --version | head -1
free -h
df -hT
```

确认是银河麒麟 Linux V10，且架构与 bundle 一致。

如果是升级，**安装前必须备份元数据和配置**：

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
sudo mkdir -p "/var/backups/material_matcher/$STAMP"
if [ -d /etc/material_matcher ]; then
  sudo cp -a /etc/material_matcher "/var/backups/material_matcher/$STAMP/etc-material_matcher"
fi
if [ -d /var/lib/material_matcher/meta ]; then
  sudo cp -a /var/lib/material_matcher/meta "/var/backups/material_matcher/$STAMP/meta"
fi
sudo readlink -f /opt/material_matcher/current 2>/dev/null || true
sudo readlink -f /var/lib/material_matcher/models/current 2>/dev/null || true
```

不要备份时删除或移动在线目录。

---

## 8. 目标机：先验证离线介质，再安装

复制完整 bundle 到目标机后：

```bash
cd /path/to/material-matcher-<version>-<arch>
python3 verify_offline_bundle.py .
```

这里**禁止** `--skip-arch`。

通过后：

```bash
sudo ./install.sh
```

安装器会自己执行：

- manifest/架构校验；
- Kylin 检查；
- 持久化磁盘选择；
- release/model 版本化复制；
- 在旧服务仍在线时执行新版本 doctor；
- 短停机原子切换；
- systemd 启动；
- readiness；
- 启动失败自动回退 previous release/model。

如果 `install.sh` 返回非 0，停止，不要手工把失败版本强行设为 current。

---

## 9. 目标机：安装后基础验证

读取实际端口：

```bash
sudo cat /etc/material_matcher/server.env
source /etc/material_matcher/server.env
```

检查：

```bash
sudo systemctl status material_matcher.service --no-pager
sudo journalctl -u material_matcher.service -n 200 --no-pager
curl -fsS "http://127.0.0.1:${MATERIAL_MATCHER_PORT}/api/health"
curl -fsS "http://127.0.0.1:${MATERIAL_MATCHER_PORT}/api/health/ready"
```

严格 doctor：

```bash
sudo -u material_matcher env \
  MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher \
  MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher \
  MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher \
  MATERIAL_MATCHER_MODEL_ROOT=/var/lib/material_matcher/models/current \
  MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist \
  /opt/material_matcher/current/runtime/bin/material-matcher doctor \
  --require-frontend --require-embedding --require-release-manifest
```

必须退出 0。

---

## 10. 首次登录与安全治理

首次安装生成的 bootstrap 密码在：

```text
/etc/material_matcher/secret/admin_password.env
```

文件必须保持：

```bash
sudo stat -c '%U %G %a %n' /etc/material_matcher/secret/admin_password.env
```

预期 owner 为 root、权限 `600`。

浏览器以 `admin` + bootstrap 密码登录后，系统会**强制修改密码**。新密码不能与 bootstrap 密码相同。完成轮换并重新登录后，再创建正式账号。

建议至少准备：

- 2 个 admin（避免单一管理员锁死）；
- operator：创建任务、目录、方案和执行匹配；
- reviewer：仅执行人工复核/准确率验收等允许操作；
- viewer：只读。

用不同角色实际登录验证：

- viewer 可以读任务但不能创建任务；
- reviewer 不能修改配置，但可执行被授权的人工复核动作；
- operator 可以创建任务但不能管理用户；
- admin 可以管理用户；
- 禁用/改角色/重置密码后旧 session 立即失效；
- 系统拒绝停用最后一个启用 admin。

安全验证未完成时最终 acceptance 的 `security_governance` 不应被视为上线签字证据。

---

## 11. 固化项目验收阈值

在**运行正式金标和百万级性能测试之前**，取得项目负责人批准值并创建：

```bash
sudo tee /etc/material_matcher/acceptance.env >/dev/null <<'EOF'
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_ROWS=<APPROVED_INTEGER>
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_COVERAGE=<APPROVED_0_TO_1>
MATERIAL_MATCHER_ACCEPTANCE_MIN_TOP1_ACCURACY=<APPROVED_0_TO_1>
MATERIAL_MATCHER_ACCEPTANCE_MIN_FINAL_ACCURACY=<APPROVED_0_TO_1>
MATERIAL_MATCHER_ACCEPTANCE_MAX_REVIEW_RATE=<APPROVED_0_TO_1>
MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS=<APPROVED_POSITIVE_HOURS>
EOF
sudo chown root:material_matcher /etc/material_matcher/acceptance.env
sudo chmod 0640 /etc/material_matcher/acceptance.env
```

把 `<APPROVED_...>` 替换为批准值。不要把示例占位符原样执行。

保存阈值批准记录。**不得在看到测试结果后降低门槛。**

后续运行 acceptance 前加载：

```bash
set -a
source /etc/material_matcher/acceptance.env
set +a
```

---

## 12. 功能烟测

使用不影响正式统计的小样本先完成一次全链路烟测。

至少验证：

1. 登录；
2. 基础数据 → 上传/创建集团码目录；
3. 集团码目录不可变版本、active 切换；
4. 新建任务第 1 步可选：
   - 已有 READY 目录版本；
   - 上传新 Target；
5. Source 上传、字段识别；
6. 第 2 步默认生成至少一条字段规则；
7. GLOBAL / STRICT / MAPPED 至少按项目实际配置验证一种；
8. Dry Run；
9. 正式任务执行；
10. 人工确认/标记未匹配；
11. 生成并下载 Excel；
12. 可选匹配方案发布/复用，旧任务快照不随方案升级漂移；
13. 如项目使用业务字典：创建不可变字典版本并在方案规则中引用，确认历史任务不随新字典版本改变。

任何业务错误必须是中文可理解错误；如果出现 500，记录 `X-Request-ID` 并立即检查 journal，不要绕过。

---

## 13. 正式 Embedding 基准

必须使用目标机已安装的正式 ONNX 模型，不使用 deterministic provider。

```bash
sudo -u material_matcher env \
  MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher \
  MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher \
  MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher \
  MATERIAL_MATCHER_MODEL_ROOT=/var/lib/material_matcher/models/current \
  MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist \
  /opt/material_matcher/current/runtime/bin/material-matcher benchmark embedding \
  --samples 10000
```

记录：吞吐、P50/P95 batch latency、token P50/P95/P99/P99.9、截断率、padding efficiency。

如果真实任务语料画像建议不同 max_length，只能由业务/技术负责人显式确认后修改；系统不会自动改正式配置。

---

## 14. BBQ Recall 回归保护

执行：

```bash
sudo -u material_matcher env \
  MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher \
  MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher \
  MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher \
  MATERIAL_MATCHER_MODEL_ROOT=/var/lib/material_matcher/models/current \
  MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist \
  /opt/material_matcher/current/runtime/bin/material-matcher benchmark vector \
  --target-rows 10000 --queries 100 --dimensions 128 --top-k 100
```

该结果用于验证 BBQ 相对 float32 exact cosine 的检索质量没有异常退化。它**不是业务准确率签字项**。

---

## 15. 真实金标准确率验收

先完成一份与正式规则相同的真实任务，然后在 UI 的“准确率验收”入口：

1. 上传 `supplement` 金标；
2. 选择 `source_id` 或 `source_row_id`；
3. 指定金标 key 列；
4. 指定正确集团码列；
5. 运行验收；
6. 检查覆盖率、Top1、最终准确率、Review率、未匹配率、候选 Recall 及错例。

不要用训练/调参时人工挑选的容易样本代替独立验收集。

验收结果会写入 `evaluation_runs/evaluation_items`，最终 acceptance 会读取**最新真实验收记录**并与第 11 节的批准阈值比较：

- 指标达到全部阈值 → PASS；
- 已有实测但任一指标低于阈值 → FAIL；
- 未配置阈值或没有真实金标 → BLOCKED。

FAIL 时不要降低阈值；回到开发/规则优化流程。

---

## 16. 100K Source × 1M Target 正式端到端验收

这是生产规模门禁，必须用真实数据。

1. 在“基础数据”创建/选择 >=1,000,000 有效 Target 的正式目录版本；
2. 上传 >=100,000 Source；
3. 使用批准的正式匹配方案/规则；
4. 确认向量执行路径和正式 Embedding ready；
5. 启动任务并等待完成；
6. 不得人为修改数据库的行数、任务时间或 index metadata；
7. 记录首次建索引耗时和整个任务耗时；
8. 使用相同 Target 再运行一次代表性任务，确认索引被复用；
9. 记录资源证据：

```bash
sudo systemctl show material_matcher.service -p MemoryCurrent -p MemoryPeak -p CPUUsageNSec
du -sh /var/lib/material_matcher/indexes /var/lib/material_matcher/cache 2>/dev/null || true
df -hT /var/lib/material_matcher
sudo journalctl -u material_matcher.service --since '<TEST_START_TIME>' --no-pager > material-matcher-scale.log
```

最终 acceptance 只把满足：

```text
Source >= 100000
Target index rows >= 1000000
任务状态 COMPLETED
实际任务起止时间完整
实际耗时 <= MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS
```

的正式任务判为 PASS。

如果性能不达标，先保留证据再回开发优化；不要直接认定必须上 native SIMD/HNSW，是否进一步优化由实测瓶颈决定。

---

## 17. 最终生产门禁

准备统一 CLI 环境：

```bash
set -a
source /etc/material_matcher/acceptance.env
set +a

export MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher
export MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher
export MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher
export MATERIAL_MATCHER_MODEL_ROOT=/var/lib/material_matcher/models/current
export MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist
```

先查看报告：

```bash
sudo -u material_matcher -E \
  /opt/material_matcher/current/runtime/bin/material-matcher acceptance \
  | tee /tmp/material-matcher-acceptance.json
```

解释：

- `PASS`：当前环境有证据且达到显式门槛；
- `BLOCKED`：实现存在，但仍缺外部证据/目标环境/阈值；
- `FAIL`：真实配置/环境/实测指标有问题。

最终硬门禁：

```bash
sudo -u material_matcher -E \
  /opt/material_matcher/current/runtime/bin/material-matcher acceptance \
  --require-production-ready
```

退出码约定：

- `0`：全部门禁 PASS，可进入上线确认；
- `2`：存在 FAIL，禁止上线；
- `3`：没有 FAIL 但仍有 BLOCKED，禁止宣称生产完成。

同时验证 JSON：

```text
code_ready = true
production_ready = true
summary.blocked = 0
summary.fail = 0
```

这四项缺一不可。

---

## 18. 上线后观察

正式切流后至少持续观察：

```bash
sudo systemctl is-active material_matcher.service
sudo journalctl -u material_matcher.service -f
```

重点关注：

- 500 / traceback；
- worker FAILED / RECOVERING；
- index BUILDING 长期不结束；
- 磁盘增长异常；
- 内存峰值；
- 浏览器在超大列表场景的实际行为；
- 业务 Review/未匹配比例与验收基线是否明显偏移。

如果发现重大问题，停止新增任务并进入回滚评估。

---

## 19. 回滚原则

安装器在**激活/启动/readiness 阶段失败**时会自动恢复安装前的 release/model 链接；先信任自动回滚，不要再手工覆盖。

如果是上线后才发现业务缺陷：

1. 停止新增任务；
2. 保存当前日志和验收证据；
3. 记录：

```bash
readlink -f /opt/material_matcher/current
readlink -f /opt/material_matcher/previous
readlink -f /var/lib/material_matcher/models/current
readlink -f /var/lib/material_matcher/models/previous
```

4. **先确认数据库兼容性和安装前备份可用**；不要只切旧代码却继续使用不兼容的新数据库；
5. 优先由批准的旧版离线介质/既定回滚变更执行，不要现场编辑 current；
6. 回滚后重新执行 doctor、health/readiness 和关键烟测。

不要删除失败版本，保留其 manifest、日志和数据库备份用于追责与复盘。

---

## 20. 最终证据包

运维 Agent 在报告“上线完成”时必须同时交付以下证据索引（可以是文件路径/工单附件，不要把密码放进去）：

- Git commit SHA；
- 版本（来自 `src/material_matcher/VERSION`）；
- CI run URL / backend+frontend success；
- offline manifest SHA-256；
- release/runtime manifests；
- `/etc/os-release`；
- `uname -m`；
- `doctor` JSON/输出；
- `/api/health`；
- `/api/health/ready`；
- systemd active/status 摘要；
- bootstrap 密码已轮换的确认（**不要记录密码**）；
- RBAC 验证结果；
- 已批准的 acceptance 阈值版本/签字来源；
- 正式 Embedding benchmark run；
- vector Recall guard run；
- 业务 gold evaluation run_id 与指标；
- 百万级 task_id、index_id、Source/Target 行数、端到端耗时；
- MemoryPeak / 索引磁盘 / 文件系统剩余空间；
- 最终 `acceptance --require-production-ready` JSON；
- 回滚点与回滚演练/验证结果。

### 运维 Agent 最终报告模板

只有最终门禁退出 0 时使用：

```text
MATERIAL_MATCHER <version> 已完成正式上线。
Commit: <sha>
Host: 银河麒麟 Linux V10 / <arch>
Service: active
Health/Ready: PASS
Doctor: PASS
Security/RBAC: PASS
Embedding: PASS
Business Gold Evaluation: PASS (run_id=<id>)
100K×1M E2E: PASS (task_id=<id>, index_id=<id>, duration=<hours>)
Acceptance: production_ready=true, blocked=0, fail=0
Rollback point: <previous release/model/db backup>
Evidence bundle: <path/ticket>
```

若门禁不是全部 PASS，应改为报告“上线被阻塞”，列出 BLOCKED/FAIL 项及证据，不得改写为“基本完成”。
