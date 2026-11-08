/**
 * 后端契约类型（唯一来源：docs/06 §2）。
 * Mock fixture 与真实响应共用这些类型，保证 Mock/真实同构。
 */

// ── 通用 ─────────────────────────────────────────────

export type TaskStatus =
  | 'queued'
  | 'planning'
  | 'executing'
  | 'reviewing'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AgentRole = 'planner' | 'executor' | 'reviewer' | 'replanner' | 'user' | 'system'

export type RiskLevel = 'safe' | 'gated' | 'dangerous'

export type ToolPolicy = 'auto' | 'require_approval' | 'disabled'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

/** 统一错误体（docs/06 §1） */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: unknown
  }
}

// ── 任务与运行 ────────────────────────────────────────

export interface TaskStats {
  durationMs: number
  tokensIn: number
  tokensOut: number
  toolCalls: number
  testPassRate?: number
}

export interface Task {
  id: string
  title: string
  description: string
  repo?: string
  status: TaskStatus
  model: 'glm-5.3' | 'glm-5.3-flash' | 'auto'
  skillIds: string[]
  createdAt: string
  updatedAt: string
  stats: TaskStats
  latestRunId?: string
}

export interface Run {
  id: string
  taskId: string
  status: TaskStatus
  startedAt?: string
  finishedAt?: string
  model: string
  stats: TaskStats & { replanCount: number }
}

export interface PlanStep {
  id: string
  index: number
  title: string
  detail?: string
  agent: AgentRole
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'replanned'
  attempt: number
  toolCallIds: string[]
}

export interface Plan {
  id: string
  runId: string
  revision: number
  steps: PlanStep[]
}

export interface Message {
  id: string
  runId: string
  role: AgentRole
  content: string
  createdAt: string
  tokens?: number
}

export interface ToolCall {
  id: string
  runId: string
  stepId?: string
  server: string
  tool: string
  args: Record<string, unknown>
  resultSummary?: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  risk: RiskLevel
  durationMs?: number
  createdAt: string
}

export interface Approval {
  id: string
  runId: string
  toolCallId: string
  tool: string
  summary: string
  risk: RiskLevel
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  createdAt: string
  resolvedAt?: string
  resolvedBy?: 'user' | 'auto'
}

export interface DiffFile {
  path: string
  additions: number
  deletions: number
  patch: string
}

export interface CodeDiff {
  id: string
  runId: string
  files: DiffFile[]
  createdAt: string
}

export interface TestResult {
  id: string
  runId: string
  passed: number
  failed: number
  skipped: number
  failures: { name: string; message: string; snippet?: string }[]
  logTail?: string
  createdAt: string
}

// ── Skill ────────────────────────────────────────────

export type SkillStatus = 'active' | 'draft' | 'deprecated'

export type SkillCategory = 'testing' | 'refactor' | 'debugging' | 'docs' | 'workflow' | 'other'

export interface Skill {
  id: string
  name: string
  slug: string
  description: string
  category: SkillCategory
  status: SkillStatus
  currentVersion: string
  metrics: {
    usageCount: number
    successRate: number
    evolutions: number
    avgTokenDelta: number
  }
  createdAt: string
  updatedAt: string
}

export interface SkillVersion {
  id: string
  skillId: string
  version: string
  changelog: string
  content: string
  source: { type: 'task' | 'evolution' | 'manual'; refId?: string }
  evalScore?: number
  createdAt: string
}

export type CandidateStatus = 'pending' | 'approved' | 'rejected'

export interface SkillCandidate {
  id: string
  skillId?: string
  kind: 'create' | 'revise'
  proposedVersion: string
  summary: string
  proposedContent: string
  evidenceTaskIds: string[]
  evaluation: {
    suite: string
    before: number
    after: number
    sampleSize: number
  } | null
  status: CandidateStatus
  createdAt: string
}

export interface SkillEvent {
  id: string
  skillId?: string
  type: 'proposed' | 'approved' | 'rejected' | 'rolled_back' | 'created'
  message: string
  createdAt: string
}

// ── Context / Memory ─────────────────────────────────

export type ContextSegmentKey = 'system' | 'skill' | 'memory' | 'history' | 'working' | 'compressed'

export interface ContextSegment {
  key: ContextSegmentKey
  tokens: number
}

export interface CompressionEvent {
  id: string
  reason: string
  trigger: 'threshold' | 'manual' | 'routing'
  beforeTokens: number
  afterTokens: number
  summaryId?: string
  createdAt: string
}

export interface ContextSession {
  id: string
  runId: string
  windowTokens: number
  usedTokens: number
  segments: ContextSegment[]
  compressionEvents: CompressionEvent[]
  updatedAt: string
}

export type MemoryLayer = 'core' | 'episodic' | 'semantic' | 'procedural'

export interface MemoryItem {
  id: string
  layer: MemoryLayer
  content: string
  sourceTaskId?: string
  score: number
  lastUsedAt?: string
  usageCount: number
  createdAt: string
}

export interface HistorySummary {
  id: string
  title: string
  content: string
  sourceTaskId: string
  refCount: number
  createdAt: string
}

// ── Workflow / Evaluation ────────────────────────────

export interface WorkflowNode {
  id: string
  agent: AgentRole
  label: string
  status: TaskStatus | 'pending'
  metrics: {
    durationMs: number
    tokens: number
    messages: number
    toolCalls: number
  }
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  condition?: string
}

export interface WorkflowGraph {
  runId: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface EvalOverview {
  range: string
  successRate: number
  avgDurationMs: number
  avgCostPerTask: number
  compressionRate: number
  trend: { date: string; overall: number; byType: Record<string, number> }[]
}

export interface EvalModelCompare {
  model: string
  successRate: number
  avgDurationMs: number
  avgCost: number
  sampleSize: number
}

export interface EvalSkillDelta {
  skillId: string
  name: string
  before: number
  after: number
  delta: number
  sampleSize: number
}

export interface EvalRun {
  id: string
  suite: string
  taskCount: number
  successRate: number
  avgTokens: number
  createdAt: string
  cases: { taskId: string; title: string; passed: boolean; tokens: number }[]
}

// ── Settings / System ────────────────────────────────

export interface ModelSettings {
  keyMasked: string
  baseUrl: string
  models: {
    id: 'glm-5.3' | 'glm-5.3-flash'
    temperature: number
    maxTokens: number
    enabled: boolean
  }[]
}

export interface RoutingRule {
  id: string
  condition: { metric: 'complexity' | 'file_count' | 'task_type'; op: '<' | '>' | 'in'; value: number | string[] }
  target: 'glm-5.3' | 'glm-5.3-flash'
  enabled: boolean
}

export interface McpServer {
  id: string
  name: string
  transport: 'stdio' | 'sse'
  commandOrUrl: string
  enabled: boolean
  status: 'connected' | 'error' | 'disabled'
  tools: { name: string; description: string; risk: RiskLevel }[]
}

export interface ToolPermission {
  tool: string
  server: string
  risk: RiskLevel
  policy: ToolPolicy
}

export interface SystemParams {
  contextWindowTokens: number
  compressionThreshold: number
  maxRetries: number
  sandboxEnabled: boolean
  maxConcurrency: number
}

export interface SystemHealth {
  api: { status: 'ok' | 'error'; latencyMs: number }
  postgres: { status: 'ok' | 'error'; latencyMs: number }
  redis: { status: 'ok' | 'error'; latencyMs: number }
  chroma: { status: 'ok' | 'error'; latencyMs: number }
  mcp: { name: string; status: 'ok' | 'error' | 'disabled'; latencyMs: number }[]
}

// ── Dashboard ────────────────────────────────────────

export interface DashboardSummary {
  tasksTotal: number
  tasksToday: number
  tasksRunning: number
  tokensTotal: number
  tokensToday: number
  skillCount: number
  skillEvolutions: number
  successRate: number
}

export interface DashboardTrends {
  range: '7d' | '14d' | '30d'
  taskTrend: { date: string; created: number; succeeded: number; failed: number }[]
  tokenTrend: { date: string; glm53: number; flash: number }[]
}
