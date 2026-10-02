# XP 兼容项目（前端 Vue 3 → Vue 2.7 降级）

> 状态：M0 已启动（2026-10-02）  
> 关联 issue：#213  
> 开发基线：**v1.3.22**（ops/incremental/NEXT-BASELINE.md）  
> 计划交付：M2 完成后切 1.3.23，随现场增量单独入包；**不阻塞 #207（1.3.22 增量包制作）**

## 1. 背景与硬约束

13 所现场存在 Windows XP 客户端。XP 上浏览器上限为：

```text
Chrome 49（最后一个 XP 版本）
Firefox 52 ESR（最后一个 XP 版本）
```

两者仅支持 ES5，不支持 ES module、Proxy、async/await、可选链等。当前前端栈为
Vue 3.5 + Element Plus 2.8 + Vite 6 + vue-router 4，**Vue 3 的 Proxy 响应式在 ES5 环境不可 polyfill**，
因此必须把前端降级到 Vue 2.7（Composition API 兼容层）才能运行。

现有门禁同样会拦截 XP 浏览器：`web/public/browser-check.js`（Chrome<87 / Firefox<79 / 无 noModule 即跳转不支持页）。

## 2. 技术决策（定稿口径）

- Vue 3.5 → **Vue 2.7**（官方支持 `<script setup>` 与 Composition API，脚本层迁移成本低）
- vue-router 4 → **vue-router 3.6**（`createRouter/createWebHistory` → `new VueRouter({ mode: 'history' })`）
- Element Plus 2.8 → **Element UI 2.15**（M0 组件盘点见 §5，所用组件 2.15 全覆盖；`ElMessage/ElMessageBox` 改回 `this.$message/$confirm` 或 import 调用；locale 改 `element-ui/lib/locale/lang/zh-CN`）
- axios 1.7 保留（经 build 转译即可）
- 构建：继续 Vite 6（Node 20 工具链/CI 不动），加 **@vitejs/plugin-legacy**（targets: chrome>=49, firefox>=52；core-js polyfill；产出 ESM+SystemJS 双轨）；`nomodule` 轨在 XP 浏览器实际执行
- `browser-check.js`：按 UA+能力探测放行 Chrome49/FF52（XP 白名单口径），其余维持原门禁
- docs/BROWSER_COMPATIBILITY.md 出 2.0 版：常规基线（Chrome≥87/FF≥79）+ XP 特例基线双口径
- 交付介质：win7/ 目录旁增 **winxp/**（Chrome 49 便携 + Firefox 52 ESR 离线安装包 + 使用说明）
- 服务器端零改动；API/契约不变

## 3. M0 盘点结果（2026-10-02 实测）

- 规模：web/src 15 个 `.vue` 共 ~7,473 行；15/15 全部使用 `<script setup>`（Vue 2.7 SFC 编译器支持）
- 宏使用：`defineModel` 仅 1 处（DualExcelUploadPanel.vue，2.7 不支持，改 props/emit 透传）；`withDefaults/defineExpose` 待 M1 全量扫描
- 组件清单（次数）：el-table×22/column×129、button×121、option×43、tag×41、descriptions-item×37、select×32、input×16、alert×16、upload×6、input-number×6、switch×5、radio-button×5、progress×5、empty×5、collapse×5、tab-pane×4、dialog×4、checkbox×4、tooltip×3、slider×3、steps×2、form×2、popover×1、pagination×1、drawer×1 —— **Element UI 2.15 全部有对应组件**
- 入口：main.ts 一次性 `use(ElementPlus,{locale})`，无图标库依赖、无 pinia
- 疑点（M1 处理）：src 下同模块存在 `.js` 与 `.ts` 双份（router/api/auth/…，见 FRONTEND_PARALLEL_DEVELOPMENT.md 背景），需确认 `.ts` 为唯一事实源后再迁移
- `web/package.json build` 前置 20 个 node 契约测试 + vue-tsc：降级时 vue-tsc 切 Volar 2.7 target（`vueCompilerOptions.target:"2.7"`），契约测试保持

## 4. 里程碑与完成定义

| 里程碑 | 内容 | DoD |
|---|---|---|
| M0 审计 | 语法/组件/双文件扫描，锁定迁移面 | 本文档 §3 补全 + audit.md |
| M1 构建管线 | Vue3 基线上接通 plugin-legacy，验证 SystemJS/ES5 产物与体积 | `npm run build` 出 legacy chunk，Chrome49 仿真环境（VM/便携浏览器）可加载骨架页 |
| M2 迁移 | Vue2.7 + Element UI + router3 全量迁移，五步工作流功能回归 | 契约测试+CI 绿；XP 仿真浏览器完成登录→上传→方案→匹配→导出全流程 |
| M3 交付 | 介质 winxp/、门禁与兼容规范 2.0、现场 XP 真机验收 | 现场 XP 机器实测通过；切 v1.3.23，产 1.3.22→1.3.23 增量包 |

## 5. 风险登记

1. Element Plus → Element UI：table 列插槽/作用域语法、dialog `v-model:visible`→`:visible.sync`、select 多选行为差异——M2 按组件清单逐个回归
2. ES5 包体与性能：XP 老机器 + polyfill 体积，需控制首屏（M1 出实测体积/加载时间）
3. 双栈维护窗口：迁移在长分支 `feat/xp-vue2` 进行，main 保持 Vue3；期间现场缺陷热修双份同步
4. 若后续 XP 机器需要访问 https（当前现场 http://:18080）：Chrome49/FF52 的 TLS 套件与服务器侧核对（M3）
5. vue-tsc/契约测试脚本对 Vue2.7 SFC 的兼容性（M1 先跑通）

## 6. 与现场补丁线的关系（2026-10-02 标记）

- 现场当前态：13 所 = 1.3.20（9/24 升级）+ 9/28 手发热修（= 1.3.22 代码语义，tag v1.3.22 待补）；**#207 增量包未制作**
- 下次现场增量入包内容以 `ops/incremental/NEXT-BASELINE.md` 的"待入内容标记"一节为准
- 本项目产出走 1.3.23 独立增量，不与 #207 混包（XP 客户端在 #207 包交付后仍无法使用 Web，属预期内，现场优先保障麒麟侧任务）

## 7. 工作纪律（本轮同步 GitHub 的事实记录）

- 仓库：github.com/boristown/MATERIAL_MATCHER；**当前 main 无分支保护、无 ruleset**（API 实测）；CI 仅 PR 触发，main 无 push 流水线
- 2026-09-25 以来所有 PR backend 恒红：根因是 `scripts/check_repo_files.py` 缺 `docs/deploy-evidence/**` 与 `ops/incremental/**`（vendor wheel）白名单，PR 均带红照合——本 PR 已修复
- 红线：**9/15–9/21 未整理完的未提交内容（本地旧分支如 pr28 系列、.scratch 区）不得提交/推送**；本轮只提交：CI 门禁修复、本目录文档、NEXT-BASELINE 与 PATCH-TIMELINE 标记
- 客户现场手改 5 处（MANUAL-手敲diff.md）与 r1/r2 均已同步回外网（tie_break 开关 / _tie_amb() / NOT EXISTS），核对记录见 git log 7305b0f、6f325ad 及 src 相应文件
