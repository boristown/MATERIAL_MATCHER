# MATERIAL_MATCHER 浏览器与客户端兼容规范

> 文档版本：1.1  
> 日期：2026-09-16  
> 状态：Normative  
> 适用范围：MATERIAL_MATCHER Web 前端、发布构建、页面开发、现场验收。

## 1. 正式支持基线

当前正式支持的最低浏览器版本为：

```text
Chrome >= 87
Firefox >= 79
```

Windows 7 可以作为客户端操作系统使用，但浏览器仍必须达到上述最低版本。

当前前端技术栈为 Vue 3.5.13 + Element Plus 2.8.8 + Vite 6.0.1。Windows 7 本身不是主要兼容边界，浏览器的 JavaScript、CSS、Web API 与组件库能力才是实际边界。

## 2. 明确不支持的旧浏览器

下列环境不得进入正式业务应用：

```text
Firefox < 79
Chrome < 87
Internet Explorer 及其他缺少 ES module 基础能力的浏览器
```

尤其包括客户现场可能存在的：

```text
Firefox 47.x
Chrome 49.x 等早期版本
```

这些版本可能无法正确执行当前 Vite 生产 bundle、Vue 3、Element Plus 组件以及项目中的现代 CSS。禁止通过“页面偶尔能打开”来宣称兼容。

## 3. 启动前浏览器门禁

浏览器版本检查必须发生在 Vue / Vite 主应用启动之前。

实现位置：

```text
web/public/browser-check.js
web/public/unsupported-browser.html
web/index.html
```

强制要求：

1. `browser-check.js` 必须使用旧浏览器可解析的 ES5 级语法；
2. 检测脚本必须在 `<script type="module">` 主应用入口之前执行；
3. 不允许把最低版本判断写在 Vue 页面内部，因为不支持的浏览器可能根本无法解析主 bundle；
4. 发现低版本浏览器后必须立即进入独立静态提示页；
5. 提示页本身不得依赖 Vue、Element Plus、ES module、CSS Grid、CSS 变量或其他现代运行时；
6. 该页面不得调用业务 API，也不得修改业务数据。

## 4. 浏览器识别与提示文案

### 4.1 Firefox

检测到 Firefox 且主版本小于 79 时，必须阻止进入主应用并显示：

```text
浏览器版本过低
请使用 Firefox ≥79
```

页面可以额外显示检测到的版本，例如：

```text
检测到当前 Firefox 版本：47
```

### 4.2 Chrome

检测到 Chrome 且主版本小于 87 时，必须阻止进入主应用并显示：

```text
浏览器版本过低
请使用 Chrome ≥87
```

页面可以额外显示检测到的版本，例如：

```text
检测到当前 Chrome 版本：49
```

### 4.3 其他过旧浏览器

如果无法可靠识别为 Firefox/Chrome，但浏览器连 ES module 基础能力都不具备，则显示通用提示：

```text
浏览器版本过低
请使用 Chrome ≥87 或 Firefox ≥79
```

不得在未知浏览器上伪造 Firefox/Chrome 版本信息。

## 5. 识别规则

Firefox 使用 User-Agent 中的：

```text
Firefox/<major>
```

Chrome / Chromium 使用：

```text
Chrome/<major>
Chromium/<major>
```

识别 Chrome 时必须排除明显的 Edge / Opera 标识，避免把其他 Chromium 浏览器错误标成 Chrome。

版本判断只使用主版本号。例如：

```text
Firefox/78.15 -> 78 -> 不支持
Firefox/79.0  -> 79 -> 支持
Chrome/86...  -> 86 -> 不支持
Chrome/87...  -> 87 -> 支持
```

## 6. 页面开发兼容红线

即使浏览器达到正式最低版本，页面开发仍需遵守以下规则：

- 不把 `backdrop-filter` 等高级视觉能力作为可操作性的前提；
- 新增浏览器 API 时必须检查 Chrome 87 / Firefox 79 是否支持；
- 新增第三方依赖时必须检查其最低浏览器版本；
- 不得在单个页面私自提升最低浏览器版本；
- `App.vue`、`main.ts`、`vite.config.ts`、`package.json` 和浏览器门禁属于 shared infrastructure；
- 页面 Agent 不得删除或绕过浏览器门禁；
- 所有业务核心操作在最低支持版本上必须可用，包括登录、上传、表格、下拉、弹窗、STEP 1～STEP 4、人工复核与结果下载。

## 7. Windows 7 现场规则

Windows 7 不是自动拒绝条件。

现场验收时必须同时记录：

```text
Windows 版本
浏览器名称
浏览器完整版本号
```

如果现场机器为 Windows 7，但 Firefox >=79 或 Chrome >=87，允许进入应用并继续功能验收。

如果现场浏览器低于最低版本，则只允许显示浏览器升级提示页，不允许进入业务流程。

## 8. 验收用例

浏览器门禁至少覆盖以下测试：

| User-Agent 场景 | 预期结果 |
|---|---|
| Firefox 47 | 跳转提示页，显示“请使用 Firefox ≥79” |
| Firefox 78 | 跳转提示页，显示“请使用 Firefox ≥79” |
| Firefox 79 | 正常进入主应用 |
| Chrome 49 | 跳转提示页，显示“请使用 Chrome ≥87” |
| Chrome 86 | 跳转提示页，显示“请使用 Chrome ≥87” |
| Chrome 87 | 正常进入主应用 |
| 无 ES module 能力的未知旧浏览器 | 跳转通用提示页 |

还必须验证：

- 提示页在 Firefox 47 中自身可正常显示；
- 提示页不发生白屏；
- 提示页不加载 Vue/Element Plus；
- 升级浏览器后重新访问可正常进入系统；
- 现代浏览器不出现误拦截。

## 9. 关于未来 Legacy 兼容

如果未来客户明确要求“Firefox 47 也必须运行完整业务应用”，那将是独立的 Legacy 兼容工程，至少需要评估：

```text
legacy bundle
polyfill
CSS fallback
Element Plus 关键组件替代/验证
真实 Windows 7 + Firefox 47 全流程测试
```

在该专项完成前，本项目当前产品策略是：**低于最低版本时友好阻止并引导升级，而不是在未验证的旧浏览器上继续运行。**

## 10. 当前状态

截至 2026-09-16：

```text
Chrome >=87：正式支持基线
Firefox >=79：正式支持基线
Windows 7：允许，但浏览器必须达到最低版本
Firefox <79：启动前阻止并显示升级页面
Chrome <87：启动前阻止并显示升级页面
未知且无 ES module 基础能力的旧浏览器：启动前阻止并显示通用升级页面
Firefox 47 完整业务兼容：未实现，也不应宣称已实现
```
