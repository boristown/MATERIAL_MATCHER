# MATERIAL_MATCHER 浏览器与客户端兼容规范

> 文档版本：1.0  
> 日期：2026-09-16  
> 状态：Normative  
> 适用范围：MATERIAL_MATCHER Web 前端、发布构建、页面开发、现场验收。  
> 目标环境包括客户现场 Windows 7 终端以及可能存在的早期 Chrome / Firefox 浏览器。

## 1. 当前结论

**当前主线前端不能宣称兼容 Firefox 47.x，也不能宣称兼容同年代的早期 Chrome。**

当前 `web/package.json` 使用：

- Vue `3.5.13`；
- Element Plus `2.8.8`；
- Vite `6.0.1`；
- Vue Router `4.5.0`；
- Axios `1.7.9`。

当前 `vite.config.ts` 没有 legacy 构建、没有显式旧浏览器 target，也没有统一 polyfill 入口。

因此：

1. Vite 6 默认生产构建面向现代浏览器，默认基线约为 Chrome 87+ / Firefox 78+；
2. Element Plus 2.5+ 官方兼容基线为 Chrome 85+ / Firefox 79+；
3. Vue 3 要求浏览器原生支持 ES2016，IE11 不在支持范围；
4. 当前项目 CSS 已使用 `display: grid`、`backdrop-filter` 等现代能力，Firefox 47 对其中部分能力不支持；
5. 即使只把 JavaScript 降级为 ES5/ES2015，也不能自动解决组件库、CSS 布局和浏览器 API 的兼容问题。

所以“Windows 7”本身不是主要阻碍，**真正的兼容边界是浏览器版本和浏览器能力**。

---

## 2. 兼容等级

### 2.1 A 级：正式保证环境

正式版本必须保证：

```text
Chrome >= 87
Firefox >= 79
```

只要浏览器达到上述版本，Windows 7 可以作为客户端操作系统使用；服务端仍按项目既定部署规范运行于银河麒麟 Linux V10。

A 级要求：

- 页面功能完整；
- 页面布局和视觉效果完整；
- 所有正式业务流程通过；
- 不允许出现白屏、按钮不可点击、表格不可操作、上传失败等兼容问题。

### 2.2 L 级：客户现场旧浏览器兼容目标

以下环境定义为 **Legacy / L 级兼容目标**：

```text
Firefox 47.x ～ 78.x
Chrome 49.x ～ 86.x
Windows 7
```

L 级是明确的工程目标，但在完成本文第 5～8 章的 legacy 改造和真实浏览器验收之前，**不得对外宣称已兼容**。

L 级允许视觉降级，但核心业务能力必须保持：

- 登录 / 退出；
- 方案列表、方案编辑、方案版本；
- 数据上传与字段识别；
- 字段映射、权重、阈值配置；
- 启动匹配任务；
- STEP 2 任务进度和中间结果；
- STEP 3 人工复核；
- STEP 4 结果查看与 Excel 下载；
- 基础数据；
- 系统设置中与当前用户权限有关的正式功能。

允许降级的视觉能力包括：

- 毛玻璃 / `backdrop-filter`；
- 非必要动画；
- 阴影层次；
- 部分渐变和高级滤镜；
- 非核心装饰效果。

不允许把“页面能打开”作为 L 级兼容验收标准。

### 2.3 不支持环境

```text
Internet Explorer 11 及更早版本
```

Vue 3 本身不支持 IE11，本项目不得为了 IE 单独回退到 Vue 2。

---

## 3. Firefox 47 的特殊约束

Firefox 47 属于远早于当前 Vue / Element Plus 官方支持范围的浏览器。

因此支持 Firefox 47 必须同时处理四个层次，而不能只增加一个 Babel 配置：

```text
JavaScript 语法降级
+ ES / Web API Polyfill
+ CSS 布局降级
+ Element Plus 组件真实验证/必要替代
```

特别注意：Element Plus 2.8.8 官方并不保证 Firefox 47。若实际验证发现某个 Element Plus 组件无法通过 polyfill 修复，则必须：

1. 对关键业务组件提供项目内 legacy 替代实现；或
2. 为旧浏览器提供独立的 legacy presentation layer；
3. 两套前端必须共用同一后端 API、权限模型和业务语义，禁止形成两套业务逻辑。

不得通过“Firefox 47 太旧”直接忽略已承诺的现场兼容目标。

---

## 4. 页面开发强制规则

为避免后续 Agent 再次引入只在现代浏览器可运行的页面，所有新页面和页面重构必须遵守以下规则。

### 4.1 JavaScript / TypeScript

- 不直接依赖只存在于新浏览器的全局 API；
- 使用新 API 前必须经过统一兼容层或 feature detection；
- 不在业务页面各自散落 polyfill；
- 禁止依赖 `crypto.randomUUID()`、`structuredClone()` 等新 API 作为核心流程前提；
- 新增依赖时必须检查其最低浏览器版本；
- legacy 模式不得依赖 native ESM、dynamic import 或 `import.meta` 直接在旧浏览器执行；
- 所有生产兼容测试必须针对 `vite build` 产物，不能用 Vite dev server 代替。

### 4.2 CSS

核心页面不得只有现代布局而无 fallback。

要求：

- `display: grid`：核心业务布局必须同时具备 flex / block fallback，不能让不支持 Grid 的浏览器页面结构崩溃；
- flex `gap`：不得作为关键间距的唯一实现，应有 margin fallback；
- `backdrop-filter`：只能作为渐进增强，缺失时必须仍可读、可操作；
- `position: sticky`：不得成为功能正确性的必要条件；
- CSS 动画和 filter 均不得影响按钮、表格、弹窗等核心交互；
- SVG Logo / 图标可以使用，但不得依赖新 CSS 才能显示关键文字和操作入口；
- 不允许为了视觉效果使用会导致旧浏览器整块内容不可见的 CSS。

### 4.3 DOM / 浏览器 API

下列能力如被依赖，必须统一检测并按需 polyfill：

- `URL` / `URLSearchParams`；
- `Object.assign`；
- `Array.from`；
- `Symbol`；
- `CustomEvent`；
- `ResizeObserver`；
- `IntersectionObserver`；
- `AbortController`；
- 其他由 Vue / Element Plus / 新增依赖实际触发的 Web API。

Polyfill 清单必须以构建产物和真实旧浏览器测试为依据，不允许无边界地全量注入。

---

## 5. Legacy 构建要求

后续实现旧浏览器兼容时，必须提供现代包和 legacy 包，而不是把所有用户都强制降级。

推荐方向：

```text
Vite modern build
+ @vitejs/plugin-legacy
+ 明确 browsers target
+ 必要 ES polyfills
+ 必要 Web API polyfills
```

最低目标应覆盖：

```text
firefox >= 47
chrome >= 49
```

但 `@vitejs/plugin-legacy` 只解决构建产物的一部分问题；它不能证明 Element Plus 和页面 CSS 已兼容。

构建必须满足：

1. 现代浏览器优先加载 modern bundle；
2. 旧浏览器加载 legacy bundle；
3. 旧浏览器不解析会直接导致语法错误的现代入口；
4. legacy polyfill 在业务代码之前加载；
5. 两种 bundle 调用同一 `/api`；
6. CI 同时执行 modern build 和 legacy build；
7. 发布包同时携带两种产物及版本信息。

---

## 6. 组件库兼容边界

当前 Element Plus `2.8.8` 的官方最低兼容范围高于 Firefox 47 / Chrome 49。

因此：

- A 级浏览器可直接依赖 Element Plus 官方兼容范围；
- L 级浏览器必须逐组件验收；
- 一个组件在现代浏览器正常，不代表它在 L 级浏览器合格；
- L 级关键组件出现不可修复问题时，应在项目内提供轻量替代组件，不应为了单个组件整体回退 Vue 主版本；
- 替代组件的 API / 业务行为应与现代页面保持一致。

优先验收的 Element Plus 组件：

```text
Button
Input
Select
Upload
Table
Dialog / MessageBox
Progress
Tag
Steps
Pagination（如启用）
```

---

## 7. 真实浏览器验收矩阵

旧浏览器兼容不能只依靠 TypeScript、ESLint 或现代 Playwright 浏览器推断。

发布 L 级兼容版本前，至少要在真实或虚拟 Windows 7 环境验证：

| 环境 | 级别 | 要求 |
|---|---|---|
| Chrome 87+ | A | 全量正式验收 |
| Firefox 79+ | A | 全量正式验收 |
| Firefox 47.x | L | 核心流程全量验收 |
| 一台客户现场实际旧 Chrome | L | 核心流程全量验收 |

若客户现场旧 Chrome 版本未知，交付前必须先获取实际版本号，不得猜测。

Firefox 47 / 旧 Chrome 的测试证据至少保存：

- 浏览器完整版本号；
- Windows 版本；
- 登录页截图；
- STEP 1～STEP 4 各至少一张截图；
- 文件上传成功证据；
- 弹窗 / 下拉 / 表格操作证据；
- 控制台错误；
- 下载结果证据；
- 失败项与已接受的视觉降级项。

---

## 8. L 级核心验收门禁

以下任一情况存在时，不得标记“Firefox 47 / 旧 Chrome 已兼容”：

1. 首屏白屏；
2. JS bundle 语法错误；
3. 登录无法完成；
4. 路由无法切换；
5. 上传组件无法选文件或提交；
6. Select / Dialog / Table 等关键组件不可操作；
7. STEP 1～STEP 4 任一核心流程中断；
8. CSS 导致按钮、表格、弹窗不可见或遮挡；
9. 下载结果失败；
10. 仅在现代浏览器测试、未在目标旧浏览器实测。

---

## 9. Agent 并行开发约束

本项目允许多个 Agent 同时修改不同页面。兼容规则属于所有页面共同遵守的基础契约：

- Agent 修改自己的页面时，不得通过修改全局构建 target 来临时解决局部问题；
- 页面专属样式应放在页面自身样式文件或 scoped style，避免多人同时修改一个全局 CSS；
- 公共兼容层、polyfill、Vite legacy 配置属于 shared infrastructure，必须由单独 PR 或明确指定的 Agent 修改；
- 任一页面新增现代浏览器 API 或现代 CSS 能力时，PR 描述必须说明其 L 级 fallback；
- 页面级开发不得删除已有 legacy fallback。

这样两个 Agent 可以并行改不同页面，同时不因为某个页面的兼容修复覆盖另一页面。

---

## 10. 当前状态标记

截至 2026-09-16：

```text
A 级现代浏览器：当前技术栈可支持，但仍需按正式版本执行回归测试。
Windows 7 + A 级浏览器：原则上可支持。
Firefox 47.x：当前未达标。
Chrome 49.x ～ 86.x：当前未达标。
legacy 双构建：尚未实现。
legacy polyfill 层：尚未实现。
旧浏览器 CSS fallback：尚未系统完成。
真实 Windows 7 + Firefox 47 验收：尚未执行。
```

后续只有在 legacy 构建、CSS fallback、关键组件验证和真实浏览器验收全部完成后，才能把对应状态改为“已支持”。
