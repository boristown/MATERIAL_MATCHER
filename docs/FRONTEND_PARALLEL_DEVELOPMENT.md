# MATERIAL_MATCHER 前端并行开发与页面隔离规范

> 文档版本：1.0  
> 日期：2026-09-16  
> 状态：Normative  
> 目标：允许 ChatGPT、OpenCode Agent 或其他开发 Agent 同时修改不同页面，避免相互覆盖和高频 merge conflict。

## 1. 核心原则

前端按“页面所有权”拆分。

一个页面任务默认只能修改：

```text
该页面自己的 .vue
该页面自己的 styles/pages/<page>.css（如果存在）
该页面专属组件目录（如果存在）
该页面专属测试
```

不同页面的 Agent 不得为了局部 UI 调整去修改全局壳层、全局 CSS、路由或 API 基础设施。

---

## 2. 当前页面边界

| 页面 | 路由 | 主文件 | 默认所有权 |
|---|---|---|---|
| 登录 | `/login` | `web/src/views/LoginView.vue` | 独立页面 |
| STEP 1 方案列表 | `/profiles` | `web/src/views/ProfilesView.vue` | 独立页面 |
| STEP 1 任务配置/方案编辑 | `/tasks/new`, `/tasks/workspace` | `web/src/views/TaskWorkspace.vue` | 独立页面 |
| STEP 2 匹配计算 | `/tasks` | `web/src/views/TasksView.vue` | 独立页面 |
| STEP 3 人工调整 | `/review` | `web/src/views/ReviewView.vue` | 独立页面 |
| STEP 4 输出结果 | `/results` | `web/src/views/ResultsView.vue` | 独立页面 |
| 准确率验收 | `/tasks/:taskId/evaluation` | `web/src/views/TaskEvaluationView.vue` | 独立页面 |
| 基础数据 | `/data` | `web/src/views/DataView.vue` | 独立页面 |
| 系统设置 | `/system` | `web/src/views/SystemView.vue` | 独立页面 |

其中 STEP 2 / STEP 3 / STEP 4 已从原先共用的 `TasksView.vue + mode` 模式拆开，后续可以分别交给不同 Agent，不再要求三个页面修改同一 Vue 文件。

---

## 3. Shared Infrastructure：禁止页面 Agent 直接修改

以下文件属于共享基础设施：

```text
web/src/App.vue
web/src/router.ts
web/src/api.ts
web/src/main.ts
web/src/styles.css
web/vite.config.ts
web/package.json
```

规则：

1. 页面任务默认不得修改这些文件；
2. 如果页面确实需要公共能力，先在页面 PR 中说明需求，公共层由指定 Agent 单独修改；
3. 不允许两个并行页面 PR 同时修改同一个 shared infrastructure 文件；
4. 路由已经存在时，页面 Agent 不得因为重构页面再次编辑 `router.ts`；
5. 页面 Agent 不得为了自己的样式直接往 `styles.css` 追加 CSS。

---

## 4. 页面样式所有权

新增或调整页面样式时优先使用：

```text
<style scoped>
```

或页面专属文件：

```text
web/src/styles/pages/<page>.css
```

目前已建立：

```text
web/src/styles/pages/review.css
web/src/styles/pages/results.css
```

后续需要时按相同规则增加：

```text
profiles.css
tasks.css
workspace.css
evaluation.css
data.css
system.css
login.css
```

页面样式选择器必须以页面根类为前缀，例如：

```css
.review-page .candidate-card { ... }
.results-page .result-summary { ... }
```

禁止不同页面创建无前缀的通用类名并依赖加载顺序覆盖彼此。

---

## 5. 推荐的双 Agent 分工

可以安全并行的示例：

```text
Agent A
  web/src/views/ProfilesView.vue
  web/src/views/TaskWorkspace.vue
  profiles/workspace 专属样式

Agent B
  web/src/views/TasksView.vue
  tasks 专属样式
```

也可以：

```text
Agent A -> ReviewView.vue + review.css
Agent B -> ResultsView.vue + results.css
```

这两种情况下正常开发不需要修改同一文件。

如果两个任务都需要改 `App.vue`、`router.ts`、`api.ts` 或 `styles.css`，则不属于“页面级并行”，必须把公共改动拆成第三个 shared-infra PR。

---

## 6. Git 分支规则

每个 Agent 从最新 `main` 开独立分支：

```text
main
├── ui/chatgpt-<page>-<date>
└── ui/opencode-<page>-<date>
```

禁止：

- Agent B 从 Agent A 的开发分支开分支；
- 两个 Agent 共用一个工作分支；
- 一个 Agent force-push 覆盖另一个 Agent 的分支；
- 未同步最新 `main` 就长期继续开发。

一个 PR 合并后，另一个 Agent 只需同步最新 `main`。如果双方遵守页面所有权，通常不会发生文本级冲突。

---

## 7. 页面与业务逻辑边界

页面隔离不意味着复制后端业务逻辑。

允许：

- 各页面拥有自己的展示状态；
- 各页面独立调用已有 `/api`；
- 各页面拥有自己的样式和交互。

禁止：

- 在多个页面复制匹配评分、权限判断、任务状态迁移等后端业务规则；
- 为了页面隔离制造两套 API 语义；
- 把客户专用逻辑写进页面。

真正的业务规则仍由后端和配置契约负责。

---

## 8. 浏览器兼容性同时适用

所有并行页面开发必须遵守：

```text
docs/BROWSER_COMPATIBILITY.md
```

尤其是旧浏览器目标：

- Firefox 47.x；
- 客户现场旧 Chrome；
- Windows 7。

页面 Agent 使用 `display:grid`、flex `gap`、`backdrop-filter` 或新 Web API 时，必须提供 legacy fallback 或明确由 shared compatibility layer 提供。

不得由某一个页面 Agent 私自修改 Vite target / polyfill 来解决自己的页面问题。

---

## 9. PR 检查清单

页面级 PR 提交前确认：

- [ ] 只修改自己负责的页面和页面专属文件；
- [ ] 未修改其他 Agent 正在负责的页面；
- [ ] 未修改 `styles.css` 做页面局部样式；
- [ ] 未修改 shared infrastructure，或已明确说明并拆分；
- [ ] 没有引入客户专用硬编码；
- [ ] 新 CSS / Web API 符合浏览器兼容规范；
- [ ] 路由、权限和 API 语义未被页面重构改变；
- [ ] 构建通过；
- [ ] 页面核心流程完成回归。

---

## 10. 本次拆分后的目标状态

本次重构完成后，下面三个页面可真正独立开发：

```text
STEP 2 -> TasksView.vue
STEP 3 -> ReviewView.vue
STEP 4 -> ResultsView.vue
```

它们不再通过 `mode` 共享同一个页面文件。

以后如果需要进一步降低冲突，优先继续把页面专属 CSS 和页面专属组件迁入各自目录，而不是继续扩大 `styles.css` 或建立新的大型共享页面组件。
