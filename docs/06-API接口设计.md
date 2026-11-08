# 06 — 前后端 API 接口设计

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v0.1（设计阶段草案） |
| 后端技术 | Python · FastAPI · LangGraph · PostgreSQL · Redis · Chroma · MCP |
| 通信方式 | REST（数据/操作） + SSE（执行事件实时流） |
| 前端 Mock | MSW handlers 与本文接口一一对应，`VITE_API_MODE` 切换 |

---

## 1. 总体约定

| 项 | 约定 |
| --- | --- |
| Base URL | `/api/v1`（版本前缀强制，未来破坏性变更走 `/v2`） |
| 鉴权 | 当前阶段单机无鉴权；预留 `Authorization: Bearer <token>` 头，后端以中间件位接入 |
| Content-Type | `application/json; charset=utf-8`（SSE 除外） |
| 时间 | ISO 8601 UTC（`2026-11-04T12:30:00Z`），前端本地化显示 |
| ID | 字符串 ULID：`task_01J...` / `run_01J...` / `skill_01J...` / `evt_...`（事件序号用整数 seq） |
| 分页 | `?page=1&size=20` → `{items, total, page, size}`；游标分页（`?cursor=`）用于事件类接口 |
| 错误体 | 统一 `{"error": {"code", "message", "details?"}}`，HTTP 状态码语义化 |
| 幂等 | `POST /tasks`、`POST /eval/runs` 支持 `Idempotency-Key` 头（前端对可重复操作自动生成） |
| CORS | 开发环境 `http://localhost:5173` 白名单 |

错误码（首批）：`invalid_request`(400) / `not_found`(404) / `conflict`(409) / `approval_required`(409, 特定语义) / `rate_limited`(429) / `model_unavailable`(503) / `internal`(500)。

## 2. 核心数据模型（TypeScript 契约，`src/types/api.ts`）

> 后端以 Pydantic schema 对齐同一结构；枚举值两侧共享。

```ts
// ── 通用 ─────────────────────────────────────────────
type TaskStatus = 'queued' | 'planning' | 'executing' | 'reviewing'
  | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';
type AgentRole = 'planner' | 'executor' | 'reviewer' | 'replanner' | 'user' | 'system';
type RiskLevel = 'safe' | 'gated' | 'dangerous';
type ToolPolicy = 'auto' | 'require_approval' | 'disabled';

interface Page<T> { items: T[]; total: number; page: number; size: number }

// ── 任务与运行 ────────────────────────────────────────
interface Task {
  id: string; title: string; description: string;
  repo?: string;                       // 规划项
  status: TaskStatus;
  model: 'glm-5.3' | 'glm-5.3-flash' | 'auto';
  skillIds: string[];
  createdAt: string; updatedAt: string;
  stats: { durationMs: number; tokensIn: number; tokensOut: number;
           toolCalls: number; testPassRate?: number };
  latestRunId?: string;
}

interface Run {
  id: string; taskId: string; status: TaskStatus;
  startedAt?: string; finishedAt?: string;
  model: string;
  stats: Task['stats'] & { replanCount: number };
}

interface PlanStep {
  id: string; index: number; title: string; detail?: string;
  agent: AgentRole;                    // 执行主体
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'replanned';
  attempt: number;                     // 重试次数
  toolCallIds: string[];
}
interface Plan { id: string; runId: string; revision: number; steps: PlanStep[] }

interface Message {
  id: string; runId: string; role: AgentRole;
  content: string;                     // Markdown
  createdAt: string; tokens?: number;
}

interface ToolCall {
  id: string; runId: string; stepId?: string;
  server: string;                      // MCP server 名: filesystem/git/search/tests
  tool: string;                        // 工具名
  args: Record<string, unknown>;
  resultSummary?: string;              // 截断摘要；原始结果分页拉取
  status: 'running' | 'succeeded' | 'failed' | 'cancelled';
  risk: RiskLevel;
  durationMs?: number; createdAt: string;
}

interface Approval {
  id: string; runId: string; toolCallId: string;
  tool: string; summary: string;       // 人可读的影响说明
  risk: RiskLevel;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  createdAt: string; resolvedAt?: string; resolvedBy?: 'user' | 'auto';
}

interface DiffFile { path: string; additions: number; deletions: number;
                     patch: string /* unified diff */ }
interface CodeDiff { id: string; runId: string; files: DiffFile[]; createdAt: string }

interface TestResult {
  id: string; runId: string;
  passed: number; failed: number; skipped: number;
  failures: { name: string; message: string; snippet?: string }[];
  logTail?: string; createdAt: string;
}

// ── Skill ────────────────────────────────────────────
type SkillStatus = 'active' | 'draft' | 'deprecated';
interface Skill {
  id: string; name: string; slug: string; description: string;
  category: 'testing' | 'refactor' | 'debugging' | 'docs' | 'workflow' | 'other';
  status: SkillStatus;
  currentVersion: string;              // semver
  metrics: { usageCount: number; successRate: number; evolutions: number;
             avgTokenDelta: number };
  createdAt: string; updatedAt: string;
}
interface SkillVersion {
  id: string; skillId: string; version: string;
  changelog: string; content: string;  // Skill 正文(Markdown)
  source: { type: 'task' | 'evolution' | 'manual'; refId?: string };
  evalScore?: number;                  // 该版本评测得分
  createdAt: string;
}
type CandidateStatus = 'pending' | 'approved' | 'rejected';
interface SkillCandidate {
  id: string; skillId?: string;        // 为空 = 新增 Skill
  kind: 'create' | 'revise';
  proposedVersion: string;
  summary: string; proposedContent: string;
  evidenceTaskIds: string[];
  evaluation: { suite: string; before: number; after: number; sampleSize: number } | null;
  status: CandidateStatus; createdAt: string;
}
interface SkillEvent { id: string; skillId?: string; type: 'proposed' | 'approved'
  | 'rejected' | 'rolled_back' | 'created'; message: string; createdAt: string }

// ── Context / Memory ─────────────────────────────────
interface ContextSegment { key: 'system' | 'skill' | 'memory' | 'history'
  | 'working' | 'compressed'; tokens: number }
interface ContextSession {
  id: string; runId: string; windowTokens: number; usedTokens: number;
  segments: ContextSegment[];
  compressionEvents: CompressionEvent[];
  updatedAt: string;
}
interface CompressionEvent { id: string; reason: string; trigger: 'threshold'
  | 'manual' | 'routing'; beforeTokens: number; afterTokens: number;
  summaryId?: string; createdAt: string }
type MemoryLayer = 'core' | 'episodic' | 'semantic' | 'procedural';
interface MemoryItem {
  id: string; layer: MemoryLayer; content: string;
  sourceTaskId?: string; score: number; lastUsedAt?: string;
  usageCount: number; createdAt: string;
}
interface HistorySummary { id: string; title: string; content: string;
  sourceTaskId: string; refCount: number; createdAt: string }

// ── Workflow / Evaluation / System ───────────────────
interface WorkflowNode { id: string; agent: AgentRole; label: string;
  status: TaskStatus | 'pending'; metrics: { durationMs: number; tokens: number;
  messages: number; toolCalls: number }; position: { x: number; y: number } }
interface WorkflowEdge { id: string; source: string; target: string;
  condition?: string }   // 'review.passed' | 'review.failed' | 'retry<3' | ...
interface WorkflowGraph { runId: string; nodes: WorkflowNode[]; edges: WorkflowEdge[] }

interface EvalOverview { range: string; successRate: number; avgDurationMs: number;
  avgCostPerTask: number; compressionRate: number;
  trend: { date: string; overall: number; byType: Record<string, number> }[] }
interface EvalModelCompare { model: string; successRate: number; avgDurationMs: number;
  avgCost: number; sampleSize: number }
interface EvalSkillDelta { skillId: string; name: string; before: number;
  after: number; delta: number; sampleSize: number }
interface EvalRun { id: string; suite: string; taskCount: number; successRate: number;
  avgTokens: number; createdAt: string; cases: { taskId: string; title: string;
  passed: boolean; tokens: number }[] }

interface ModelSettings { keyMasked: string; baseUrl: string;
  models: { id: 'glm-5.3' | 'glm-5.3-flash'; temperature: number;
            maxTokens: number; enabled: boolean }[] }
interface RoutingRule { id: string; condition: { metric: 'complexity' | 'file_count'
  | 'task_type'; op: '<' | '>' | 'in'; value: number | string[] };
  target: 'glm-5.3' | 'glm-5.3-flash'; enabled: boolean }
interface McpServer { id: string; name: string; transport: 'stdio' | 'sse';
  commandOrUrl: string; enabled: boolean; status: 'connected' | 'error'
  | 'disabled'; tools: { name: string; description: string; risk: RiskLevel }[] }
interface ToolPermission { tool: string; server: string; risk: RiskLevel;
  policy: ToolPolicy }
interface SystemParams { contextWindowTokens: number; compressionThreshold: number;
  maxRetries: number; sandboxEnabled: boolean; maxConcurrency: number }
```

## 3. REST 接口清单

### 3.1 Dashboard

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/dashboard/summary` | KPI：任务总数(今日/累计)、运行中、Token(今日/累计)、Skill 数、进化次数 |
| GET | `/dashboard/trends?range=7d\|14d\|30d` | 任务趋势(创建/成功/失败) + 按模型 Token 序列 |
| GET | `/agents/status` | Agent 状态分布（Mock） |
| GET | `/skills/events?limit=10` | Skill 进化动态 |
| GET | `/system/health` | `{api, postgres, redis, chroma, mcp: [{name,status,latencyMs}]}` |

### 3.2 Tasks / Runs（Workspace）

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/tasks?status=&q=&page=&size=` | 任务分页列表 |
| POST | `/tasks` | 创建任务 `{title, description, repo?, model?}` → 201 Task（立即触发一次 Run） |
| GET | `/tasks/:taskId` | 任务详情（含 stats、skillIds） |
| POST | `/tasks/:taskId/cancel` | 取消任务（运行中才有效） |
| GET | `/tasks/:taskId/messages?cursor=` | 对话消息（游标分页） |
| POST | `/tasks/:taskId/messages` | 追加用户输入（对运行中任务插话，P1） |
| GET | `/tasks/:taskId/runs` | 该任务的运行历史 |
| GET | `/runs/:runId` | Run 详情（stats/状态） |
| GET | `/runs/:runId/plan` | 当前计划（含 revision） |
| GET | `/runs/:runId/tool-calls?cursor=` | 工具调用列表 |
| GET | `/runs/:runId/diffs` | 代码变更列表（CodeDiff[]） |
| GET | `/runs/:runId/tests` | 测试结果列表 |
| GET | `/runs/:runId/events?after=seq` | **历史事件补拉**（SSE 断线恢复用，按 seq 升序） |
| GET | `/runs/:runId/artifacts` | 产物清单（Mock → P1） |

### 3.3 Approvals（Harness）

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/approvals?status=pending` | 待审批列表 |
| POST | `/approvals/:approvalId` | `{decision: 'approved' \| 'rejected', comment?}` → 200（Run 经 SSE 继续推进） |

### 3.4 Skills

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/skills?q=&category=&status=&page=` | Skill 列表 |
| GET | `/skills/:skillId` | 详情（含 metrics） |
| POST | `/skills` | 手动新建（P2） |
| GET | `/skills/:skillId/versions` | 版本列表（倒序） |
| GET | `/skills/:skillId/versions/:a/diff/:b` | 两版本内容 diff |
| POST | `/skills/:skillId/rollback` | `{version}` → 回滚（生成新版本记录，不删历史） |
| GET | `/skills/:skillId/evolutions` | 进化事件列表 |
| GET | `/skills/:skillId/evaluations` | 该 Skill 的评测记录（前后对比） |
| GET | `/skills/:skillId/usages?cursor=` | 引用任务（P2） |
| GET | `/skills/candidates?status=pending` | 候选审核队列 |
| POST | `/skills/candidates/:candidateId/review` | `{decision: 'approved' \| 'rejected', comment?}` → 批准即合入新版本 |

### 3.5 Context / Memory

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/context/sessions?limit=` | 会话列表（选择器） |
| GET | `/context/sessions/:sessionId` | 窗口用量 + segments + 压缩事件（轮询/SSE `context.updated`） |
| GET | `/context/summaries?cursor=` | 历史摘要列表（Mock） |
| GET | `/memory?layer=&page=` | 记忆条目（分层） |
| POST | `/memory/search` | `{query, topK=8, layers?}` → `{items: MemoryItem & {similarity}[]}`（检索测试器，Mock） |

### 3.6 Workflow

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/runs?status=&q=&page=` | 运行列表（RunListPanel） |
| GET | `/workflow/runs/:runId/graph` | 图快照：nodes（含实时状态/指标）+ edges（条件标签）+ 回放事件序列引用 |
| GET | `/workflow/template` | 默认编排模板（静态拓扑，P2/Mock） |

### 3.7 Evaluation

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/eval/overview?range=7d\|30d\|90d` | KPI + 成功率趋势（含按类型） |
| GET | `/eval/models?range=` | 模型对比数组 |
| GET | `/eval/skills?range=` | Skill 进化前后对比数组 |
| GET | `/eval/compression?range=` | 压缩率 vs 成功率序列 |
| GET | `/eval/runs?page=` | 评测批次列表（含逐任务 cases） |
| POST | `/eval/runs` | 触发评测批次（P2） |

### 3.8 Settings

| Method | Path | 说明 |
| --- | --- | --- |
| GET / PUT | `/settings/models` | 模型配置（Key 只回传掩码；PUT `{apiKey?}` 可更新） |
| POST | `/settings/models/test` | `{modelId}` → `{ok, latencyMs, modelList[]}` 连通性测试 |
| GET / PUT | `/settings/routing` | 路由规则数组 + 默认模型 |
| GET | `/settings/mcp` | Server 列表（含工具发现结果） |
| POST | `/settings/mcp` | 添加 Server `{name, transport, commandOrUrl, env?}` |
| PUT | `/settings/mcp/:serverId` | 启用/禁用/编辑 |
| POST | `/settings/mcp/:serverId/discover` | 重新发现工具 |
| GET / PUT | `/settings/permissions` | 工具权限数组（PUT 全量或 `PATCH` 单条） |
| GET / PUT | `/settings/system` | 系统参数 |

## 4. SSE 事件协议（实时执行流）

### 4.1 连接

```
GET /api/v1/runs/:runId/events        响应 Content-Type: text/event-stream
心跳: : ping（注释行），每 15s
恢复: 请求头/查询参数 Last-Event-ID=<seq>，服务端从该序号续传
```

事件帧格式（`event` + `id` + `data`），`data` 统一 JSON：

```json
{ "v": 1, "seq": 42, "ts": "2026-11-04T12:30:00Z", "runId": "run_01J...", "payload": { ... } }
```

### 4.2 事件类型表

| event | payload 要点 | 前端消费 |
| --- | --- | --- |
| `run.status` | `{status, finishedAt?, error?}` | TaskHeader 状态、取消/重试按钮 |
| `plan.updated` | `{plan: Plan}`（全量替换，带 revision） | PlanTree |
| `message.created` | `{message: Message}` | 会话流 |
| `message.delta` | `{messageId, delta}`（可选流式，P1） | 打字机渲染 |
| `tool.call.started` | `{toolCall: ToolCall}` | 插入 ToolCallCard(loading) |
| `tool.call.completed` | `{toolCall}` | 卡片落定（结果/耗时/风险） |
| `code.diff.created` | `{diff: CodeDiff}` | DiffViewer 卡片 |
| `test.finished` | `{result: TestResult}` | TestResultCard |
| `approval.requested` | `{approval: Approval}` | ApprovalCard + 全局提醒 |
| `approval.resolved` | `{approvalId, status}` | 卡片落定、解除等待态 |
| `context.updated` | `{session: ContextSession}` | ContextGauge 迷你仪表 |
| `workflow.node` | `{nodeId, status, metrics}` | Workflow 图实时着色 |
| `run.completed` / `run.failed` | `{stats, summary?}` | 终态 UI + 通知 |

> 设计要点：`tool.call.*`、`approval.*`、`plan.updated` 同时被 Workspace 与 Workflow 两个 feature 消费，事件处理函数收敛在 `stores`/归一化层，避免两处重复解析。事件 schema 带 `v` 字段，后续扩展向下兼容。

## 5. Mock 方案（与真实接口同构）

| 项 | 方案 |
| --- | --- |
| 拦截层 | MSW `http.handler` 按 §3 路径注册；`VITE_API_MODE=live` 时整体不加载 |
| 数据 | `mocks/fixtures/*` 类型化种子（含运行中/待审/失败等故事线） |
| SSE | `eventPlayer.ts` 按剧本 `setTimeout` 推送 §4 事件；审批事件后**真实暂停**等待前端调用 `POST /approvals/:id` 再继续剧本（保证审批流可交互演示） |
| 延迟 | 统一 120~400ms 随机延迟，检索测试 300ms，还原真实手感 |
| 标注 | Mock 驱动区块挂 `MockBadge`（doc 05 §8） |

## 6. 后端架构草图（约定，供 P4 起实施）

```
backend/
├── app/
│   ├── main.py                 # FastAPI 实例、CORS、路由注册
│   ├── api/v1/                 # routers: dashboard/ tasks/ runs/ approvals/ skills/
│   │                           #          context/ workflow/ eval/ settings/
│   ├── schemas/                # Pydantic 模型（与 §2 对齐）
│   ├── agents/                 # LangGraph: graph.py(编排) planner.py executor.py
│   │                           #           reviewer.py replanner.py
│   ├── skills/                 # 提取器/评测器/版本库(git-backed)
│   ├── context/                # 组装/压缩/记忆(chroma 客户端)
│   ├── harness/                # 权限矩阵、沙箱(docker/subprocess)、重试、审批闸门
│   ├── router/                 # 模型路由策略引擎
│   ├── mcp/                    # MCP client 连接池与工具注册表
│   ├── events/                 # 事件总线 → Redis pub/sub → SSE endpoint
│   └── db/                     # SQLModel/alembic 迁移
├── tests/
└── docker-compose.yml          # postgres/redis/chroma/backend
```

数据流：LangGraph 节点执行 → 发事件到 Redis Stream → SSE endpoint 转发（按 runId 订阅）→ 事件同步落库（`run_events` 表，供 `?after=seq` 补拉）。
