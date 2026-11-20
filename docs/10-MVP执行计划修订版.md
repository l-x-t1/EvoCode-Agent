# EvoCode Agent MVP 执行计划（修订版 v2）

- 日期：2026-11-15
- 依据：用户《MVP 开发总任务书》（附件截断，验收标准按 §一 推断执行，后续以用户补充为准）+《执行计划修订要求》
- 里程碑编号 M1→M2…（docs/09）在本计划中细化为批次 B1→B9；**每批结束后停止，输出验收报告，经用户确认后进入下一批**

## 〇、已有成果核对（保护清单，2026-11-15 实测）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| D1 时区字段 | ✅ 保持 | information_schema 计 timestamptz 列 = 44 |
| D2 文档与模型同步 | ⚠️ 部分 | docs/08 已定模型枚举 `glm-5.3/glm-5.3-flash/auto`（agent_tasks.model）；config 缺模型名常量 → B3 补 `GLM_MODEL`/`GLM_FLASH_MODEL` 配置 |
| D3 PG/Redis 容器 | ✅ healthy | `docker ps` Up 6 hours (healthy) ×2 |
| D4 Alembic 核验 | ✅ 保持 | alembic_version=598f054066fc，21 表（20 应用 + alembic_version），D4 全量校验 diff=0 仍有效 |
| D5 开发用户初始化 | ❌ 未完成 | users 表 0 行、无 seed/init、无 current_user 依赖 → **B1 补齐**（幂等 seed + 单用户身份解析） |

红线（全程有效）：不输出/读取密钥值；不 DROP、不 alembic downgrade；不动 oracle-free；不改既有 API 契约与 DB schema（B1–B9 零迁移）；不重复建表/重置数据。

## 一、推断的 MVP 验收标准（12 项，附件缺失部分由本节承担）

1. 前端 live 模式：自然语言创建任务 → 真实库 → Dashboard/Workspace 真实展示，无 MockBadge
2. 真实 GLM 驱动 Planner 生成计划并落库，非模拟返回值
3. Executor 经 Tool Registry 调用 ≥3 类内部工具（工作区文件读写、测试运行、代码检索），严格限制在授权工作区
4. SSE 实时可见，事件落库 agent_execution_logs，Last-Event-ID 断线续传
5. 高危操作真实触发人工审批，批准/拒绝影响执行流
6. Reviewer 检查结果；失败时 Replanner 调整计划重试（多轮、步数/重试上限受控）
7. 任务终态产出执行报告；tool_calls/approvals/execution_logs 全程留痕
8. Context：多轮对话、token 统计、超限压缩 + snapshot 版本保存与恢复重建（含任务目标/约束/步骤/工具结果/代码位置/对话历史）
9. Skill：注册/版本/候选/审核/回滚可用，未经审核的候选不得覆盖正式版
10. RAG MVP：导入→解析→chunk→向量+BM25→RRF→引用回答，评测可跑；Embedding Provider 独立抽象
11. 文档解析 MVP：PDF/Word/Excel/HTML/MD/TXT 统一接口；OCR/图片理解/图表问答分立验收
12. 全模块 pytest 覆盖；B9 ≥10 场景端到端真实测试并留存记录

## 二、批次明细

### B1 真实数据链路（本批，立即执行）

- **目标**：Dashboard/Workspace 全部已接线接口真实化（15 个），打通「创建任务→列表/详情→审批决策落库→Dashboard 数字变化」。
- **依赖**：D1–D4 成果（已核对）；无 LLM 依赖。
- **修改范围**：
  - 后端新增 `app/schemas/{common,tasks,runs,dashboard,approvals}.py`、`app/repositories/{base,users,tasks,runs,approvals,dashboard}.py`、`app/services/{tasks,approvals,dashboard}.py`、`app/core/metrics.py`、`app/api/v1/{tasks,runs,dashboard,approvals,system}.py`、`scripts/seed.py`、tests 4 个新文件
  - 后端修改：`api/v1/router.py`（按域注册）、`api/deps.py`（get_current_user 单用户解析）、`main.py`（prod 关 docs、CORS headers 收窄、请求延迟度量中间件）、`services/health.py`（api_latency 真实度量）、`core/response.py`（补 approval_required 错误码）
  - 前端：`vite.config.ts`（dev proxy→8000）、`.env.development`（live）、`connectionStore`（apiMode 默认值与 MSW 启动条件统一）、`TopBar`（30s 轮询健康→setApiHealthy）、`DashboardPage`（delta 去硬编码）、vitest 基建 + eventPlayer/runStore/client 测试
- **API 影响**：新增 16 个端点（dashboard 5、tasks 6、runs 4、approvals 2、system/health 别名 1）；响应形状与 `types/api.ts` 逐字段对齐（Page<T>/裸实体/错误体/ISO8601 UTC/前缀 ULID）。
- **数据库影响**：**零迁移、零 DDL**。幂等键存 Redis（SETNX+TTL，非新表）；开发用户由 seed 幂等创建；diffs/tests 从 agent_execution_logs 事件溯源读取（`code.diff.created`/`test.finished` payload），符合既有事件溯源设计。
- **测试方案**：pytest 新增 tasks/dashboard/approvals/runs API 测试（含幂等重放、409 终态守卫、错误体断言），保留原 17 个；前端 vitest ≥10 用例；`npm run build`。
- **完成条件**：seed 后 live 模式两页真实数据可浏览、创建任务真实落库；pytest 全绿（真实退出码 0）；build/test 全绿。
- **风险与未完成项**：审批决策仅落库（执行流恢复在 B3）；SSE 流式端点在 B3（本批提供 history JSON）；`.env.production` 保持 mock 由部署决策（记录在案）。

### B2 Tool Registry + Harness（隔离诚实分级）

- **目标**：统一工具入口、参数校验、权限矩阵、超时/重试/最大步数、审批闸门、执行日志。
- **修改范围**：`app/tools/`（registry + 内部工具：workspace 文件读写/列表、pytest 运行、代码检索、git diff）、`app/core/security.py`（路径规范化 + 符号链接/路径逃逸检查 + 工作区白名单 + 命令白名单 + 输出上限 + 进程终止）、`app/services/harness.py`。
- **隔离声明（按修订要求如实标注）**：Windows MVP 采用「路径规范化 + symlink 逃逸检查 + 工作区白名单 + 命令白名单 + 超时终止」的**应用层访问控制**，**不是操作系统级沙箱**；容器隔离执行接口（provider 抽象，Windows 容器/local 子进程双实现）在本批定义接口、local 实现落地，容器实现列为风险项。系统提示与 UI 将如实标注当前隔离级别。
- **API/DB 影响**：零迁移；tool_calls/approvals/execution_logs 开始被真实写入。
- **测试**：路径逃逸（`../`、绝对路径、symlink）拒绝用例；命令白名单拒绝用例；超时终止真实用例；权限矩阵用例。
- **完成条件**：越权访问全被拒且有测试证明；工具执行全链路落库。

### B3 LLM + Agent 闭环（Workspace 真实 SSE）

- **目标**：真实 GLM 驱动 Planner→Executor→Reviewer→Replanner；run 编排 + SSE；任务恢复。
- **依赖**：B1、B2、**GLM_API_KEY 已配置**（未配置则此批阻塞，如实报告）。
- **修改范围**：`app/llm/`（GLM 客户端，open.bigmodel.cn OpenAI 兼容协议；config 补 GLM_MODEL/GLM_FLASH_MODEL + 温度/maxTokens 从 settings 域读取）、`app/agents/`（LangGraph 状态机：planner/executor/reviewer/replanner 节点 + 条件边）、`app/services/runs.py`（编排 + 断点恢复 + 审批恢复原执行位置/拒绝→replanner）、SSE 端点（`text/event-stream`，`{v,seq,ts,runId,payload}` 信封 + Last-Event-ID）、服务重启后 running 任务恢复扫描。
- **状态机（按修订要求）**：task/run 共用 8 状态；waiting_approval 恢复时回到挂起前的执行位置（由 agent_execution_logs seq + plan_step 状态重建）；审批拒绝 → plan_step 标 failed → replanner 追加 revision；步数/重试上限来自 settings.system 域；工具幂等键防重复调用。
- **API/DB 影响**：零迁移；agent_runs/messages/model_usage/execution_logs 真实写入；前端 Workspace 切真实 SSE（B1 的 useRunStream 已具备续传）。
- **测试**：mock LLM 的状态机单元测试 + 真实 GLM 冒烟（key 就绪后）；SSE 续传测试（断开重连补齐）；审批通过/拒绝两条路径测试。
- **风险**：GLM key 未配置则 B3 阻塞；LangGraph 版本兼容性。

### B4 Context MVP

- **目标**：上下文组装与压缩，保证任务关键信息不因压缩丢失。
- **修改范围**：`app/context/`（窗口组装：system/skill/memory/history/working 六段；token 统计用 GLM usage 回传 + 本地近似；阈值触发压缩；压缩前后 snapshot 写 context_snapshots 并关联版本；任务恢复时重建）。
- **API/DB 影响**：零迁移；context_snapshots 真实写入；`GET /context/sessions*` 接口对齐前端类型。
- **测试**：压缩触发阈值、恢复完整性（目标/约束/已完成与未完成步骤/工具结果/代码位置均在重建结果中）。
- **完成条件**：超阈值自动压缩可复现，恢复测试通过。

### B5 Skill MVP

- **目标**：Skill 生命周期 + 候选审核闸门。
- **修改范围**：`app/skills/`（registry/versions/candidates/review/rollback 服务）+ 对应 10 个 API；候选基于任务执行反馈生成（B3 事件驱动）；**候选必须经审核才发布，正式版不可被未审核候选覆盖**（DB 约束 + service 守卫 + 测试证明）。
- **测试**：审核拒绝不生效、发布版本号 +1、回滚生成事件、审核中并发修改 conflict。

### B6 RAG MVP

- **目标**：导入→解析→chunk→混合检索→RRF→引用回答→评测回归。
- **Embedding Provider 抽象（按修订要求）**：`app/rag/embedding.py` 独立 Provider 接口 + 配置（模型名/维度）；**先实测 open.bigmodel.cn 实际可用的 embedding 接口与模型**，不可用则接入备选 provider（如本地 sentence-transformers 或其他兼容 API），不假定主对话 Key 可调用一切能力；支持文档重新向量化。
- **修改范围**：`app/rag/`（parser/chunker/retrievers/bm25+vector/rrf/citation/eval）、Chroma 依赖启用；检索接口 `POST /memory/search` + 引用来源追踪。
- **测试**：各格式解析真实文件用例、RRF 融合正确性、检索评测集（可定位质量问题：分向量/BM25 单路得分对比）。

### B7 OCR / 图片理解 / 图表问答（分立验收）

- **目标**：三个分立能力，各设验收标准，不用一次调用冒充全部。
  - OCR：图片 → 文本（含坐标/页码来源），验收：≥3 种真实截图文本提取准确可用；
  - 图片理解：图片 → 结构化描述，验收：对象/场景/文字分类描述；
  - 图表问答：图表图片 + 问题 → 数据级回答，验收：能从柱状/折线图读出具体数值。
- **修改范围**：`app/multimodal/`（GLM vision API 封装 + 统一输入接口）+ API + 前端上传入口（与文档关联）。
- **风险**：GLM vision 接口能力需实测；无法满足的能力如实标记「未完成」。

### B8 前端资产页接真 + 清场

- **目标**：Skills/Context/Workflow/Evaluation/Settings 真实功能（对应后端 API 随 B5/B4/B6 落地）；**清除交付模式中所有 Mock 与占位**：MSW 仅 dev+mock 模式加载、移除 `.env.production` 的 mock、Dashboard 硬编码清理、占位页替换。
- **修改范围**：五页实现 + React Flow 引入 + 后端对应接口（settings 5 域、workflow graph、eval 聚合）。
- **测试**：build + vitest + 手工联调记录。

### B9 端到端验收

- **目标**：**≥10 个真实 E2E 场景**，全部留存真实执行记录（命令、时间、结果）：
  ① 正常任务端到端 ② 多轮对话任务 ③ 失败→重规划成功 ④ 工具超时→重试 ⑤ 权限拒绝 ⑥ 审批通过恢复 ⑦ 审批拒绝→replanner ⑧ SSE 断线 Last-Event-ID 续传 ⑨ 服务重启任务恢复 + Snapshot 重建 ⑩ Skill 回滚 ⑪ RAG 检索引用 ⑫ 压缩触发与恢复（≥10，取实际通过数如实报告）
- **完成条件**：场景通过率如实报告；未通过项列为未解决问题；docs/07 复选框与 docs/06 契约差异同步修订。

## 三、验收报告格式（每批固定输出）

修改文件清单 / 实现说明 / 测试命令与真实退出码 / 通过-失败-跳过数 / 未解决问题 / 下一批建议。**每批结束后停止，等待用户确认。**
