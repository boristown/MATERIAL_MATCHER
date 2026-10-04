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

| 里程碑 | 内容 | DoD | 状态 |
|---|---|---|---|
| M0 审计 | 语法/组件/双文件扫描，锁定迁移面 | 本文档 §3 补全 + audit.md | 基本完成（§3 已录） |
| M1 构建管线 | Vue3 基线上接通 plugin-legacy，验证 SystemJS/ES5 产物与体积 | `npm run build` 出 legacy chunk，Chrome49 仿真环境（VM/便携浏览器）可加载骨架页 | **构建侧完成（2026-10-02），真浏览器加载=待 M3** |
| M2 迁移 | Vue2.7 + Element UI + router3 全量迁移，五步工作流功能回归 | 契约测试+CI 绿；XP 仿真浏览器完成登录→上传→方案→匹配→导出全流程 | **进行中（2026-10-03 首轮跑通）** |
| M3 交付 | 介质 winxp/、门禁与兼容规范 2.0、现场 XP 真机验收 | 现场 XP 机器实测通过；切 v1.3.23，产 1.3.22→1.3.23 增量包 | 未开始 |

### M2 首轮进展记录（2026-10-03，分支 `feat/xp-vue2`，未合入 main）

- 依赖切换完成：vue@2.7.16 + vue-router@3.6.5 + element-ui@2.15.14；构建用 @vitejs/plugin-vue2 + plugin-legacy。
- **适配层**（不改业务源码语义）：`src/vue-router-compat.ts`（createRouter/createWebHistory/useRouter/useRoute → VueRouter3 + Proxy 实时 $route + push/replace Promise 化）与 `src/element-plus-compat.ts`（ElMessage/ElMessageBox → element-ui Message/MessageBox），经 vite alias 按 `^vue-router$`/`^element-plus$` 精确注入；`src/compat-shims.d.ts`+`vue-router-shim.d.ts` 补类型。
- 模板机械转换：`el-dialog/el-drawer v-model→:visible.sync`；`:model-value→:value`、`@update:model-value→@input`（注意 sed 误产 `@update:value` 已修正为 `@input`）；`el-radio-button value→label`；模板内 TS 注解与非空断言 `!`/`as` 全部移除（Vue2 模板编译器不认 TS）；`defineEmits` 元组式→调用签名式×4；多根模板（FieldMappingCanvas/TaskWorkspace）补单根 wrapper。
- 浏览器门禁改造：`browser-check.js` 基线 Firefox≥52/Chrome≥49；能力门从 noModule 改为 Promise+Proxy+Symbol 探测（FF52/Chrome49 原生具备，IE 被拦）；unsupported-browser.html 文案与 test-browser-check 契约同步更新。
- **低内核真机验收（首轮）**：Linux Firefox 52.9.0esr（XP 同源引擎）+ Xvfb，直连生产 `dist/index.html`（含守卫与 nomodule 双轨），legacy SystemJS 轨成功渲染应用壳+四步导航+标题文案；FF52 注意其 UA 伪装为 `rv:60.0/Firefox/60.0`（官方行为），门禁解析兼容。geckodriver 0.15/0.19 与 52.9 Marionette 握手均失败，改用"采集页 + XHR 自报"无驱动方案（脚本：`/tmp/opencode/ff52_test.sh`，本轮环境工具，不进仓库）。
- 全量 `npm run build`（20 项契约测试 + vue-tsc + 双轨构建）在分支上全绿；es-check es6 过。
- **低内核验证（重要事实修正）**：
  1. Mozilla 归档 `52.9.0esr/linux-x86_64` 路径现被轮换返回 **Firefox 140**（`browser/application.ini Version=140.17.0`、UA `rv:140.0`、实测支持 ES module）。外网当前拿不到真 52 二进制，早期"FF52 渲染成功"记录实为 FF140 module 轨，**作废重记**。
  2. 改用真同代引擎验证：**Node 6.17.1 / V8 5.1.281**（Chrome 45–53 时代，无 async/await、对象展开、`??`；XP Chrome49=V8 4.9，为其子集）+ jsdom@11 加载 dist 的 **legacy SystemJS 轨**（剥除 module 轨页面 `xp-legacy.html`，资源经本地 http.server 供给）：`window.System` 就位、Vue2 挂载完成（`#app` 被替换为渲染根，符合 Vue2 行为）、UI 文本 545 字符（登录壳+四步导航完整）、**jsErrors=0 / consoleErrs=0**。
  3. 辅助门禁：`es-check es6` 对 `*-legacy*.js` 通过（语法面）；FF140（现代引擎）在 module 轨跑通后端全链（登录→STEP1/2/3/4 页面+API 全部 200，登录经 UI 表单事件填充）。
  4. Node6+jsdom11 验证环境脚本存于 `/tmp/opencode/es5run/es5_boot.js`（环境工具，不进仓库）；XP 真机（Chrome49/FF52 + 现场数据）验收仍为 M3 必做项。
- 后端全链回归（同分支 dist + 本地 1.3.22 实例，独立数据目录）：上传→目录→草稿→规则→启动→COMPLETED→`/result` 直出合法 xlsx（5 sheet 齐全，未定稿可导 r1 语义生效）。
- 未完（M2 剩余）：带后端 API 的五步全流程回归（登录/上传/方案/匹配/导出，本地起 material_matcher 服务）；Element UI 尺寸/图标观感走查（size="large" 语义、empty/descriptions 渲染）；样式 `gap` 在 XP Chrome49 的降级核对（FF52 无碍）；`.js` 编译残留与 `.ts` 定源最终清理（当前靠 resolve.extensions .ts 优先规避）。

### M1 结果记录（2026-10-02）

- `@vitejs/plugin-legacy@6` + `terser@5` 接入，targets=chrome>=49/firefox>=52；产物双轨：
  `index.js 1.39MB(gzip 445KB) + index-legacy.js 1.91MB + polyfills-legacy.js 155KB`，`nomodule` 接线正确（polyfill→entry→老浏览器兜底）。
- **语法验证**：legacy chunk 以 `es-check es6`（ECMAScript 2015 解析）通过——即 async/await、对象展开、`?.`/`??` 等 FF52/Chrome49 不支持的语法已全部被 Babel 转译；箭头函数/class/模板字符串保留属**正确行为**（XP 的 Chrome 49/FF 52 原生支持，严格 ES5 是过度目标）。
- 全量 `npm run build`（20 项契约测试 + vue-tsc + 双轨构建）通过。
- 关键发现（影响 M3 浏览器策略）：
  1. Chrome 49 / Firefox 52 ESR **均原生支持 Proxy**（Vue 3 的核心依赖）。理论上当前 Vue3 经 legacy 轨即可在 XP 启动；真正卡点是 **CSS**：自研样式含 44 处 `gap/grid`，flex `gap` 需 Chrome 84+（FF 52 已支持）。
  2. 结论：降级方向不变（Vue2.7+Element UI 对老浏览器更稳、且覆盖未来更老客户端），但 **XP 现场首选 Firefox 52 ESR**（随介质 winxp/ 目录分发），Chrome 49 作为备用并预期布局降级。
  3. M3 真机验收以 XP+FF52 为主通道。
- 遗留到 M2：`src` 下 `.js/.ts` 双份文件定源；`defineModel` 1 处（DualExcelUploadPanel.vue，Vue2.7 不支持，改 props/emit）；Element Plus→Element UI 组件映射清单（§3 组件盘点可直接复用）。

## 5. 风险登记

1. Element Plus → Element UI：table 列插槽/作用域语法、dialog `v-model:visible`→`:visible.sync`、select 多选行为差异——M2 按组件清单逐个回归
2. ES5 包体与性能：XP 老机器 + polyfill 体积，需控制首屏（M1 出实测体积/加载时间）
3. 双栈维护窗口：迁移在长分支 `feat/xp-vue2` 进行，main 保持 Vue3；期间现场缺陷热修双份同步
4. 若后续 XP 机器需要访问 https（当前现场 http://:18080）：Chrome49/FF52 的 TLS 套件与服务器侧核对（M3）
5. vue-tsc/契约测试脚本对 Vue2.7 SFC 的兼容性（M1 先跑通）

## 6. 与现场补丁线的关系（2026-10-02 标记）

- 现场当前态：13 所 = 1.3.20（9/24 升级）+ 9/28 手发热修（= 1.3.22 代码语义；tag `v1.3.22` 已于 2026-10-02 补打并推送）；**#207 增量包未制作**
- 下次现场增量入包内容以 `ops/incremental/NEXT-BASELINE.md` 的"待入内容标记"一节为准
- 本项目产出走 1.3.23 独立增量，不与 #207 混包（XP 客户端在 #207 包交付后仍无法使用 Web，属预期内，现场优先保障麒麟侧任务）

## 7. 工作纪律（本轮同步 GitHub 的事实记录）

- 仓库：github.com/boristown/MATERIAL_MATCHER；**当前 main 无分支保护、无 ruleset**（API 实测）；CI 仅 PR 触发，main 无 push 流水线
- 2026-09-25 以来所有 PR backend 恒红：根因是 `scripts/check_repo_files.py` 缺 `docs/deploy-evidence/**` 与 `ops/incremental/**`（vendor wheel）白名单，PR 均带红照合——本 PR 已修复
- 红线：**9/15–9/21 未整理完的未提交内容（本地旧分支如 pr28 系列、.scratch 区）不得提交/推送**；本轮只提交：CI 门禁修复、本目录文档、NEXT-BASELINE 与 PATCH-TIMELINE 标记
- 客户现场手改 5 处（MANUAL-手敲diff.md）与 r1/r2 均已同步回外网（tie_break 开关 / _tie_amb() / NOT EXISTS），核对记录见 git log 7305b0f、6f325ad 及 src 相应文件

### M2 视觉回归与修复（2026-10-05，Playwright 真截图驱动）

用户要求"调 Vue 版本后视觉核对"→ 真机截图暴露三组缺陷，已全部修复（commit 731f0d4）：

1. **致命·双 Vue 实例**：element-ui 是 CJS，其 `require('vue')` 被 rollup 解析成第二份
   `vue.runtime.common.js`，导致**所有 el-table 的 body 跨实例渲染崩溃**（表头在、行全空，
   控制台 `getTagNamespace`/`toLowerCase`/`setAttribute` 报错）。此前"渲染成功"的截图只看了
   无表格页面（登录/外壳），表格页从未真正通过。修复：vite alias `^vue$` → `vue/dist/vue.runtime.esm.js`
   单副本 + `resolve.dedupe:['vue']`。**教训：npm ls vue 显示 deduped 不代表 bundle 单副本，必须查产物。**
2. **el-button link 是 Element Plus 独有 prop**：UI2 下 27 处 link 按钮渲染成大块 primary 按钮。
   映射 `link type="primary"→type="text"`；danger/success/info 配 `.mm-text-*` 颜色类。
3. **Vue2 scoped slot 必须单根**：5 处多根列模板（ResultsView/TasksView×2/TaskWorkspaceBase×2）
   补 span/div 包裹（此前因表格未渲染而未暴露）。
4. 顺带修复 STEP4"生成中"盲区并双分支同步（main PR#217 / XP da2c4e0+731f0d4）：
   重新生成（有旧文件）时同样显示"生成中"+行内"新版生成中，此为上一版"提示。

**终验截图（全部正常，pageerror=0）**：STEP4 历史清单（生成中/已完成两行+横幅）、STEP3 人工调整
（历史计算记录 5 行+汇总卡+调参区）、STEP2 任务列表、Profiles、登录页；后端 pytest 307 全绿。
