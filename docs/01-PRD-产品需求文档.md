# EvoCode Agent — 产品需求文档（PRD）

| 项目 | 内容 |
| --- | --- |
| 产品名称 | EvoCode Agent（智能研发 Agent 平台） |
| 文档版本 | v0.1（设计阶段草案） |
| 文档状态 | 待确认 |
| 撰写日期 | 2026-11-04 |
| 关联文档 | 02-信息架构与路由 · 03-设计系统 · 04-前端目录结构 · 05-页面布局与组件 · 06-API 设计 · 07-开发计划 |

> **当前状态声明（重要）**：本文档描述的是产品设计目标，**截至目前项目尚未编写任何功能代码**。文档中标注「Mock」的能力表示前端阶段将使用明确标注的模拟数据渲染，标注「真实」的能力依赖后端实现。任何未在开发计划（doc 07）中排期的能力均属规划，不代表已实现。

---

## 1. 产品概述

### 1.1 愿景与定位

EvoCode Agent 是一个基于大语言模型（GLM-5.3 / GLM-5.3-Flash）的**自主软件研发 Agent 系统**。它不是聊天机器人，也不是普通管理后台，而是一个「能看懂研发任务、自主规划、调用工具、修改代码、执行测试，并从历史任务中持续积累经验」的工程化 Agent 平台。

一句话定位：

> **一个可观测、可审核、可进化的 AI 研发工作台** —— Agent 在前台执行任务，Skill 经验库在后台持续进化，人始终掌握关键节点的确认权。

### 1.2 与「AI 对话产品」的本质区别

| 维度 | 普通 AI 对话产品 | EvoCode Agent |
| --- | --- | --- |
| 交互单元 | 一轮对话 | 一个任务（Task）→ 一次执行（Run）→ 计划/工具/代码/测试 |
| 自主性 | 用户逐步追问 | Agent 自主拆解任务、多步执行、失败重试 |
| 记忆 | 会话内上下文 | 分层长期记忆 + 历史任务恢复 + 上下文压缩 |
| 经验积累 | 无 | Skill 自进化：从执行反馈中提取经验，版本化管理 |
| 人机关系 | 一问一答 | 人在关键节点审批（危险操作、方案分歧） |
| 可观测性 | 对话记录 | 多 Agent 协作可视化、Token 成本、评测体系 |

### 1.3 目标用户与核心场景

| 用户 | 场景 |
| --- | --- |
| 个人开发者 | 把「给这个函数补单测并修复失败用例」这类任务交给 Agent，自己只审核结果 |
| 小型研发团队 | 团队共享 Skill 库，项目规范沉淀为可复用、可进化的经验资产 |
| Agent/LLM 工程师 | 观测 Context、评测 Multi-Agent 与 Skill 进化效果，调优 Agent 行为 |

三个核心用户故事：

1. **提交任务 → 观察执行 → 关键点审批**：用户在 Workspace 输入需求，Agent 生成计划并逐步执行；遇到 `git push`、删除文件等危险工具调用时暂停请求审批，用户批准后继续。
2. **从失败中沉淀经验**：某类任务失败后，系统提取教训生成候选 Skill（或修订现有 Skill），经评测集验证提升后进入候选审核队列，用户确认后合入新版本。
3. **回顾与评测**：用户在 Evaluation Center 查看成功率、模型对比、Token 成本与 Skill 进化前后的效果变化，在 Workflow Center 回放某次执行的多 Agent 协作过程。

### 1.4 核心技术理念 → 产品化映射

每个技术方向都必须在产品中有明确呈现，避免「黑盒」：

| 技术方向 | 是什么 | 产品化呈现（前端可见物） |
| --- | --- | --- |
| **Skill 自进化** | 从历史任务与执行反馈中提取经验，生成/修订/评测 Skill，支持版本与回滚 | Skill Center：Skill 库、版本时间线、进化历史、候选审核队列、评测对比 |
| **Context Engineering** | 上下文构建、智能压缩、路由与分层长期记忆 | Context Center：窗口用量仪表、Token 分布、压缩事件时间线、记忆层级、检索测试 |
| **Multi-Agent 协作** | Planner / Executor / Reviewer / Replanner 分工 | Workflow Center：执行图（React Flow）+ 节点状态回放；Workspace 内消息按角色着色 |
| **MCP 工具接入** | 文件系统、Git、代码搜索、测试等工具经 MCP 标准化接入 | Settings-MCP 配置；Workspace 中每次工具调用的结构化卡片 |
| **Harness Engineering** | 工具权限、沙箱执行、任务验证、失败重试、人工确认 | Workspace 审批卡片；Settings 工具权限矩阵；系统参数（重试/沙箱） |
| **Model Router** | 按任务复杂度路由 GLM-5.3 / GLM-5.3-Flash | Settings 路由策略；Dashboard/评测中的模型维度统计 |
| **Evaluation** | 成功率、Skill 效果、压缩效果、Token 成本评估 | Evaluation Center 全部图表；Skill 详情页内嵌评测结果 |

---

## 2. 核心流程

### 2.1 任务主流程（Run 生命周期）

```
用户提交需求
   │
   ▼
┌─────────┐   计划    ┌──────────┐  执行   ┌──────────┐
│ Planner │─────────▶│ Executor │───────▶│ Reviewer │
└─────────┘          └────┬─────┘        └────┬─────┘
                          │ 工具调用            │ 审查
                          │ (MCP/沙箱)         ▼
                          │              ┌──────────┐  通过
                          │              │ 通过判定？ │─────────▶ 任务完成
                          │              └────┬─────┘
                          │                   │ 不通过 / 失败
                          ▼                   ▼
                    ┌──────────────────────────────┐
                    │ Replanner（修订计划 / 重试）    │──▶ 回到 Executor
                    └──────────────────────────────┘
   任意危险工具调用 ──▶ waiting_approval ──▶ 人工批准 / 拒绝
```

状态机（Task/Run 共用）：`queued → planning → executing → reviewing → waiting_approval(可插) → completed / failed / cancelled`。

### 2.2 Skill 进化闭环

```
历史任务(成功/失败) → 反馈信号(重试次数/审查意见/测试结果)
        │
        ▼
   经验提取器 → 候选 Skill(新增/修订 vN+1)
        │
        ▼
   回归评测集验证(进化前 vs 进化后) → 达标？
        │否──▶ 归档并记录原因
        │是
        ▼
   候选审核队列 ──用户批准──▶ 合入新版本(可回滚) / ──拒绝──▶ 淘汰
```

### 2.3 数据流（前后端）

```
React 前端 ──REST──▶ FastAPI ──▶ LangGraph(Multi-Agent) ──▶ MCP 工具/沙箱
   ▲                    │
   └──────SSE 事件流──────┘  （计划更新、消息、工具调用、审批请求、进度）
                │
                ├── PostgreSQL（任务/Skill/评测等持久化）
                ├── Redis（运行态、队列、SSE 广播）
                └── Chroma（记忆向量检索）
```

---

## 3. 功能需求（按页面）

优先级定义：**P0** = 首个可演示闭环必须；**P1** = 完整产品体验；**P2** = 后续扩展。数据来源列标注该功能的真实数据依赖（后端未就绪前一律 Mock 渲染）。

### 3.1 Dashboard 工作台

目标：30 秒内掌握「Agent 在干什么、花了多少、进化了多少」。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-D1 | KPI 指标卡：任务总数(今日/累计)、运行中任务、Token 消耗(今日/累计)、Skill 数量与累计进化次数 | P0 | `GET /dashboard/summary` |
| F-D2 | 任务趋势图（近 14 天，创建/成功/失败堆叠面积图），支持时间范围切换 | P0 | Mock → `GET /dashboard/trends` |
| F-D3 | Token 消耗图（按模型 GLM-5.3 / GLM-5.3-Flash 分组堆叠柱状图） | P0 | Mock → 同上接口 |
| F-D4 | 最近任务列表（状态、模型、耗时、Token、点击进入 Workspace 对应任务） | P0 | `GET /tasks?limit=8` |
| F-D5 | Agent 运行状态环形图（idle/running/waiting_approval 等分布） | P1 | Mock → `GET /agents/status` |
| F-D6 | Skill 进化动态 Feed（最近 N 条候选生成/合入/回滚事件） | P1 | `GET /skills/events` |
| F-D7 | 系统健康面板：API/PostgreSQL/Redis/Chroma/MCP Server 连接状态点 | P1 | `GET /system/health` |
| F-D8 | 快捷入口：新建任务按钮（全局） | P0 | — |

### 3.2 Agent Workspace（核心页面）

目标：一个页面完成「提交任务 → 观察执行 → 处理审批 → 查看产物」的完整工作流。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-W1 | 任务信息区：标题、状态、模型、所用 Skill、开始/耗时统计 | P0 | `GET /tasks/:id` |
| F-W2 | 对话消息流：用户与各角色 Agent 消息，按角色着色区分 | P0 | `GET /tasks/:id/messages` + SSE |
| F-W3 | 任务输入框：多行输入、附加仓库路径（规划项），提交创建任务 | P0 | `POST /tasks` |
| F-W4 | 执行时间线（EventStream）：消息内联展示工具调用卡、代码 Diff 卡、测试结果卡，按时间倒序/正序排列 | P0 | `GET /runs/:id/events` + SSE |
| F-W5 | 工具调用卡片（ToolCallCard）：MCP server、工具名、参数、结果摘要、耗时、风险级别，可展开原始参数/结果 | P0 | SSE `tool.call.*` |
| F-W6 | 代码变更卡（DiffViewer）：按文件分组的 unified diff，行级着色，折叠长文件 | P1 | SSE `code.diff.created` |
| F-W7 | 测试结果卡：通过/失败/跳过统计 + 失败用例摘要（终端样式） | P1 | SSE `test.finished` |
| F-W8 | 人工审批卡（ApprovalCard）：危险操作描述 + 批准/拒绝按钮，状态流转 | P0 | SSE `approval.requested` + `POST /approvals/:id` |
| F-W9 | 计划面板（PlanTree）：步骤树、每步状态与执行 Agent、重规划标记 | P0 | SSE `plan.updated` |
| F-W10 | 上下文用量迷你仪表：当前 Run 的窗口占用与压缩提示，点击跳转 Context Center | P1 | `GET /context/sessions/:runId` |
| F-W11 | 产物面板：变更文件列表、生成测试报告入口 | P1 | Mock → `GET /runs/:id/artifacts` |
| F-W12 | 任务列表抽屉（移动端/快捷切换历史任务） | P1 | `GET /tasks` |
| F-W13 | 停止/取消运行中的任务（二次确认） | P1 | `POST /tasks/:id/cancel` |

### 3.3 Skill Center

目标：把 Agent 的「经验」当作一等公民管理：可浏览、可审核、可回滚、可评测。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-S1 | Skill 库列表：搜索、分类/状态筛选（active/draft/deprecated），卡片含成功率/使用次数 | P0 | `GET /skills` |
| F-S2 | Skill 详情（主从布局）：描述、适用场景、参数、当前版本、关联指标 | P0 | `GET /skills/:id` |
| F-S3 | 版本管理：版本时间线、任意两版本 diff 查看、回滚到指定版本（需确认） | P1 | `GET /skills/:id/versions` + `POST .../rollback` |
| F-S4 | 进化历史：该 Skill 的每次进化事件（来源任务、触发原因、变化摘要） | P1 | `GET /skills/:id/evolutions` |
| F-S5 | 候选审核队列：待审 Skill（新增/修订），展示证据（来源任务）+ 评测前后对比 + 批准/拒绝 | P0 | `GET /skills/candidates` + `POST .../review` |
| F-S6 | Skill 评测结果：回归评测集上的成功率/Token 变化（进化前 vs 后柱状对比） | P1 | `GET /skills/:id/evaluations` |
| F-S7 | 手动新建/编辑 Skill（表单 + Markdown 编辑器） | P2 | `POST /skills` |
| F-S8 | Skill 使用追踪：哪些任务引用了该 Skill | P2 | `GET /skills/:id/usages` |

### 3.4 Context Center

目标：让「上下文」从黑盒变成可观测、可验证的资产。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-C1 | 上下文窗口仪表（选中 Run）：总窗口、已用、剩余，分段环形图（system/skill/memory/history/working/compressed） | P0 | Mock → `GET /context/sessions/:runId` |
| F-C2 | Token 分布：各上下文段随时间变化的堆叠面积图（含压缩前后跳变） | P1 | 同上 |
| F-C3 | 压缩事件时间线：每次压缩的触发原因（阈值）、压缩率、被摘要的区间 | P0 | 同上 |
| F-C4 | 记忆层级视图：core / episodic / semantic / procedural 四层卡片，条目数与最近使用 | P0 | `GET /memory` |
| F-C5 | 记忆检索测试器：输入 query，返回 top-k 命中记忆条目与相似度分数（调参用） | P1 | Mock → `POST /memory/search` |
| F-C6 | 历史摘要列表：跨会话恢复的任务摘要（来源任务、生成时间、被引用次数） | P1 | Mock → `GET /context/summaries` |
| F-C7 | 压缩策略参数展示（只读，入口跳转 Settings） | P2 | Settings API |

### 3.5 Workflow Center

目标：可视化 Multi-Agent 执行关系与状态，支持单次运行回放。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-F1 | 执行图（React Flow）：Planner/Executor/Reviewer/Replanner 节点 + 条件边（通过/失败→重规划等） | P0 | Mock → `GET /workflow/runs/:id/graph` |
| F-F2 | 运行选择器：左侧 Run 列表（按任务/时间筛选） | P0 | `GET /runs` |
| F-F3 | 节点状态实时着色（running 脉冲 / done / failed）+ 进度回放（滑块或播放） | P1 | SSE + 图快照 |
| F-F4 | 节点详情侧板：选中节点的输入摘要、输出摘要、耗时、Token、消息/工具调用数 | P0 | 同 graph 接口 |
| F-F5 | 边条件标签：如 `review.passed` / `review.failed` / `retry<3` | P1 | 同上 |
| F-F6 | 图模板视图（无运行时的静态拓扑，展示默认编排） | P2 | Mock |

### 3.6 Evaluation Center

目标：用数据回答「这套 Agent 到底行不行、进化有没有用」。

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-E1 | KPI 行：任务成功率、平均耗时、平均 Token 成本、上下文压缩率 | P0 | Mock → `GET /eval/overview` |
| F-E2 | 成功率趋势（近 30 天折线，分整体/按任务类型） | P0 | 同上 |
| F-E3 | 模型对比（GLM-5.3 vs GLM-5.3-Flash：成功率/耗时/成本分组柱状图） | P0 | `GET /eval/models` |
| F-E4 | Skill 进化前后对比：配对柱状图（进化前/后成功率与 Token），列出参与评测的 Skill | P0 | `GET /eval/skills` |
| F-E5 | 上下文压缩效果：压缩率 vs 任务成功率的关系（双轴折线或散点） | P1 | `GET /eval/compression` |
| F-E6 | 评测任务明细表：评测批次、任务、结果、Token、可跳转详情 | P1 | `GET /eval/runs` |
| F-E7 | 触发一次评测批次的按钮（规划项，需后端评测器） | P2 | `POST /eval/runs` |

### 3.7 Settings

| 编号 | 功能 | 优先级 | 数据来源 |
| --- | --- | --- | --- |
| F-ST1 | 模型配置：GLM API Key（脱敏显示）、base URL、温度/max_tokens、连通性测试 | P0 | `GET/PUT /settings/models` |
| F-ST2 | 模型路由策略：复杂度阈值规则表（简单任务→Flash，复杂任务→5.3），规则启停 | P1 | `GET/PUT /settings/routing` |
| F-ST3 | MCP Server 配置：列表、传输方式（stdio/SSE）、启用状态、工具发现状态与工具数 | P0 | `GET/PUT /settings/mcp` |
| F-ST4 | 工具权限矩阵：工具 × 策略（auto / require_approval / disabled），风险级别标注 | P0 | `GET/PUT /settings/permissions` |
| F-ST5 | 系统参数：上下文窗口大小、压缩阈值、失败重试次数、沙箱开关、并发上限 | P1 | `GET/PUT /settings/system` |
| F-ST6 | 外观设置：紧凑/舒适密度切换（深色为默认唯一主题，预留浅色扩展） | P2 | 本地存储 |

---

## 4. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 性能 | 首屏 LCP < 2.5s（本地/内网）；SSE 事件到达 UI 延迟 < 300ms；列表页万级数据分页/虚拟滚动 |
| 可靠性 | SSE 断线自动重连（指数退避）+ `Last-Event-ID` 续传；请求失败有统一重试与错误提示 |
| 安全 | API Key 仅脱敏展示；危险工具默认 require_approval；预留登录鉴权（当前阶段单机单用户） |
| 可扩展性 | 前端按 feature 模块化（见 doc 04），新增页面不侵入既有代码；API 全部带 `/v1` 版本前缀；SSE 事件 schema 带 `v` 字段；图表/模型路由规则均为数据驱动可配置 |
| 一致性 | 所有页面使用同一设计系统（doc 03）；Mock 数据与真实 API 同构（同一 TS 类型，见 doc 06），切换 `VITE_API_MODE` 即可切换数据源 |
| 可访问性 | 焦点可见、键盘可达（侧边导航/审批卡）、色彩对比 ≥ 4.5:1（正文），动画尊重 `prefers-reduced-motion` |

---

## 5. 核心数据实体总览

详细字段见 doc 06《API 设计》，此处仅列关系：

```
Task 1 ─── n Run 1 ─── n RunEvent(SSE 持久化) 
 │            ├── n Message        （对话消息）
 │            ├── n ToolCall       （工具调用）
 │            ├── n Approval       （审批记录）
 │            └── 1 Plan ─── n PlanStep
 │            └── 1 ContextSession ─── n CompressionEvent
 ├── n Skill(使用)      Skill 1 ─── n SkillVersion ─── n SkillEvaluation
 └── n MemoryItem(产出)  CandidateSkill（审核队列，关联 Skill+证据任务）
EvalRun（评测批次）── n EvalCase（逐任务结果）
Settings（models / routing / mcp / permissions / system）
```

---

## 6. 边界与不做的事（当前阶段）

1. **不虚构已实现功能**：所有页面在 P0~P3 阶段使用 MSW Mock 数据渲染，界面上以统一的 `MockBadge`（「模拟数据」角标）明确标注；未接入后端前不宣称任何功能可用。
2. **不做**：多用户/组织/权限体系、在线 IDE、实时多人协作、插件市场、移动原生 App（仅响应式 Web）、语音输入。
3. **暂缓**：浅色主题（仅做 token 分层预留）、手动 Skill 编辑器（P2）、自动评测触发（P2）。
4. 代码执行一律经沙箱 Harness，前端只展示结果，不直接暴露 Shell。

---

## 7. 术语表

| 术语 | 定义 |
| --- | --- |
| Task | 用户提交的一个研发需求，产品的一等交互单元 |
| Run | Task 的一次具体执行（可多次重跑），SSE 事件挂在 Run 上 |
| Plan / PlanStep | Planner 产出的步骤计划及其中一步 |
| Skill | 结构化的经验知识（触发条件 + 指导内容），可被 Agent 加载 |
| Candidate Skill | 由进化流程提出、等待人工审核的 Skill 新增/修订 |
| Context Session | 一次 Run 的上下文构建与消费记录 |
| Memory Item | 长期记忆条目（core/episodic/semantic/procedural 四层） |
| Approval | 人工确认记录（对应危险工具调用或方案分歧） |
| Harness | 工具执行管控层：权限、沙箱、验证、重试、审批 |
| Model Router | 按任务复杂度在 GLM-5.3 / GLM-5.3-Flash 间路由的策略 |
| MSW | Mock Service Worker，前端 Mock 方案 |
| MockBadge | 界面上标注「当前展示为模拟数据」的统一组件 |

---

## 8. 成功指标（上线后衡量，非当前功能）

| 指标 | 定义 | 目标方向 |
| --- | --- | --- |
| 任务成功率 | Run 最终 completed 的比例（按任务类型分层） | 随 Skill 进化持续上升 |
| 人工干预率 | 每 Run 平均审批/纠正次数 | 下降 |
| Token 成本 / 任务 | 成功任务的平均 Token 花费 | 下降（路由+压缩） |
| Skill 采纳率 | 候选 Skill 批准合入比例 | 健康区间（过高说明评审太松） |
| 进化收益 | Skill 进化前后评测成功率差值 | 显著为正 |
| 上下文压缩保真 | 压缩后 vs 压缩前任务成功率差值 | 接近 0 |
