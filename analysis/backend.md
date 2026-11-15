# EvoCode Agent 后端全面扫描报告（只读调查）

- 调查范围：`backend/`（排除 `.venv`、`__pycache__`、`*.egg-info`），2026-11-15
- 方法：目录枚举 → 逐文件精读 → 全库 grep（TODO/FIXME/pass/SSE/langgraph/websocket/路由装饰器）
- 硬约束遵守：未改任何代码，未读取 `.env` 内容（仅读 `.env.example`），未执行任何迁移/破坏性命令
- 整体判定：**backend 处于 Phase 1「基础工程」完成态**——数据层与横切层齐备且质量高，业务层（Agent/Skill/MCP/SSE/记忆）为空骨架。README.md:5-6 与各空包 `__init__.py` 的自述与代码事实一致，无「文档吹牛、代码造假」的情况。

---

## ① 目录树与模块清单

```
backend/
├── alembic/
│   ├── env.py
│   └── versions/598f054066fc_initial_20_tables.py   # 初始迁移（已应用）
├── app/
│   ├── main.py                 # 应用工厂 + lifespan + 根级探针
│   ├── agents/    → 仅 __init__.py（空骨架，P3 实装）
│   ├── api/
│   │   ├── deps.py             # get_db 依赖注入（预留）
│   │   └── v1/{router.py, health.py}
│   ├── context/   → 仅 __init__.py（空骨架，P3）
│   ├── core/                  # config.py, enums.py, exceptions.py, logging.py, response.py — 全部实实现
│   ├── db/                    # session.py, redis.py — 真实现
│   ├── evaluation/→ 仅 __init__.py（空骨架，P3）
│   ├── memory/    → 仅 __init__.py（空骨架，P3）
│   ├── models/                # base + 9 个模型文件，20 张表 — 真实现
│   ├── repositories/→ 仅 __init__.py（空骨架）
│   ├── schemas/               # 仅 health.py（4 个模型）
│   ├── services/              # 仅 health.py
│   ├── skills/    → 仅 __init__.py（空骨架，P3）
│   └── tools/     → 仅 __init__.py（空骨架，P3）
├── scripts/                    # 空目录（无任何脚本）
├── tests/                      # conftest + 4 个测试文件（17 个用例）
├── alembic.ini / pyproject.toml / docker-compose.yml / README.md / .env.example
```

模块清单（实际存在的包及状态）：

| 包 | 状态 | 证据 |
|---|---|---|
| app/api | 真实现（仅 health 域） | api/v1/health.py:12-16 |
| app/core | 真实现（5 个文件全实装） | config.py 全文 / exceptions.py:31-79 / logging.py / enums.py:14-115 / response.py |
| app/db | 真实现（PG+Redis 连接管理） | db/session.py:29-80 / db/redis.py:21-66 |
| app/models | 真实现（20 表聚合注册） | models/__init__.py（聚合 import）+ 9 个模型文件 |
| app/schemas | 真实现但极小（仅 health 域） | schemas/health.py:7-30 |
| app/services | 真实现但仅 1 个服务 | services/health.py:26-52 |
| app/api/deps.py | 真实现但当前无人消费 | deps.py:16-17 |
| app/agents / context / evaluation / memory / skills / tools | **空骨架**（仅 docstring，声明 P3 实装） | 各包 __init__.py |
| app/repositories | **空骨架**（分层约定已写明，无实现） | repositories/__init__.py |

## ② 全部 API 路由表

grep `@router` / `@app.get` 装饰器，全库共 **3 条路由**（均挂载生效），另有 2 个 router 装配点：

| # | 文件:行 | HTTP 方法 | 路径 | 所属 router | 挂载点 |
|---|---|---|---|---|---|
| 1 | app/main.py:65-67 | GET | /healthz | 无（内联挂 app 根） | create_app() 直接注册 |
| 2 | app/main.py:70-90 | GET | /readyz | 无（内联挂 app 根） | create_app() 直接注册 |
| 3 | app/api/v1/health.py:12-16 | GET | /api/v1/health | health.router | api/v1/router.py:8 → main.py:63（prefix=/api/v1） |

router 装配链：`api/v1/router.py:7-8` 只 include 了 `health.router`，文件头注释明说「P2 起按域注册 tasks/runs/skills/...」。

## ③ 每条路由的实现完整度

| 路由 | 判定 | 证据 |
|---|---|---|
| GET /healthz | **真实现**（恒 200 存活探针） | main.py:65-67，直接返回 `{"status":"ok"}`；tests/test_health.py:15-16 断言通过 |
| GET /readyz | **真实现**（有完整业务逻辑：探测 PG/Redis，任一失败→503+统一错误体 not_ready） | main.py:70-90 调 services/health.py:44-52 `get_readiness()`；tests/test_health.py:33-43 断言 503 分支错误码与 details 键 |
| GET /api/v1/health | **真实现**（聚合 4 依赖探针 + 延迟；chroma 如实报 disabled、mcp 报空数组，不虚构） | api/v1/health.py:12-16 → services/health.py:26-41；tests/test_health.py:19-30 断言五键契约 |

统计：**路由总数 3；真实现 3 / 桩 0 / 仅文档未实现 0**（就存在的路由而言全部真实现）。
但若按规划业务面对账：**tasks、runs、plans、tool_calls、approvals、conversations、messages、skills（4 表）、context_snapshots、memory_items、eval_runs/cases、model_usage、settings 等 17 张业务表无一有对应 API**——属于「缺位」而非桩。

## ④ services 层 / LangGraph 执行链 / 工具 / Redis / SSE

| 能力 | 是否存在 | 完整度与证据 |
|---|---|---|
| services 层 | 仅 1 个文件 | services/health.py（52 行）为真业务逻辑：并行探针聚合、延迟测量。services/__init__.py 自述「事务边界在此」但无其他服务 |
| LangGraph / agent 执行链 | **不存在** | app/agents/__init__.py 仅 docstring「P3 实装…不含任何实现——不虚构功能」；pyproject.toml:19 注释「P3 引入：langgraph / chromadb / langchain（本期不安装）」，依赖清单确实无 langgraph |
| 工具调用 / MCP | **不存在**（仅数据结构就绪） | app/tools/__init__.py 空骨架；但 models/execution.py 的 ToolCall、Approval 表已建，enums.py:31-45 的 ToolCallStatus/ApprovalStatus/RiskLevel 已定义 |
| Redis 使用 | **连接管理真实现，业务使用为零** | db/redis.py:21-66：init/close/get/probe(PING+延迟) 齐备；全库 grep 无任何业务代码调用 get_redis()（无缓存、无 pub/sub、无队列） |
| SSE | **端到端不存在，但数据层已预埋** | 全库无 text/event-stream / EventSource / sse-starlette 依赖；models/execution.py:106 注释「事件溯源表：每条 SSE 事件一行；(run_id, seq) 数据库级唯一，支撑断点续传（Last-Event-ID）」——schema 设计先于实现 |
| GLM/LLM 调用 | 不存在 | config.py:53-54 已预留 GLM_API_KEY(GLM_BASE_URL 指向 open.bigmodel.cn)，无任何调用代码 |

## ⑤ main.py 装配清单

- **应用工厂**：`create_app()`（main.py:46-91），模块级 `app = create_app()`（main.py:94）
- **lifespan**（main.py:31-42）：setup_logging → init_engine → init_redis → yield → close_redis + dispose_engine（资源对称释放，异常时 probe 路径如实报告）
- **中间件**：仅 1 个——CORSMiddleware（main.py:54-60），白名单来自 `ALLOWED_ORIGINS`（逗号分隔，config.py:66-67），allow_credentials=True，方法白名单 GET/POST/PUT/PATCH/DELETE/OPTIONS。**无**鉴权、限流、GZip、请求日志中间件
- **异常处理**（main.py:62 → exceptions.py:31-79）：4 个 handler 全实装——BizException（业务语义化状态码）、StarletteHTTPException（404/405/429 映射错误码）、RequestValidationError（422+validation_error）、兜底 Exception（500+internal，记 traceback 不泄细节）。统一出口 `{"error":{"code","message","details"?}}`
- **router**：仅 `api_router`（prefix=/api/v1，内含 1 条 /health）；另内联 /healthz、/readyz
- **docs**：/docs 与 /openapi.json 开启（未按 ENV 关闭生产 docs，见问题 #8）

## ⑥ tests 下 4 个测试文件

| 文件 | 用例数 | 测什么 |
|---|---|---|
| test_config.py | 4 | Settings 默认值、ALLOWED_ORIGINS 逗号解析、SensitiveStr repr 遮蔽（密钥不泄进日志/repr）、遮蔽不影响实际取值 |
| test_error_handlers.py | 3 | 统一错误体契约：404→not_found 信封、405→invalid_request 信封、成功响应为裸实体（无 code/data 包装） |
| test_health.py | 4 | /healthz 恒 200、/api/v1/health 五键契约（camelCase latencyMs、chroma=disabled、mcp=[]）、/readyz 语义（依赖可用 200 / 不可用 503+not_ready+details 两键）、依赖在线时集成断言（否则显式 skip，不造假） |
| test_models.py | 6 | 20 表全部注册、前缀 ULID 生成与长度、agent_execution_logs 唯一约束、context_snapshots 版本化唯一+部分唯一索引、approvals 待审部分唯一索引、6 条外键级联策略抽查 |

conftest.py：app_client 夹具经 LifespanManager 拉起完整 lifespan；deps_available 夹具如实探测 PG/Redis 决定集成用例执行或跳过。合计 17 用例，与既有事实「17 个测试全过」一致。

## ⑦ 发现的问题

**架构/结构**
1. **数据层远超消费层**：20 张表 + 精心设计的约束/索引/级联已建好，但仅 1 条业务无关的 health 路由消费它们。agent_execution_logs 的 SSE 断点续传设计（execution.py:4,106）、审批状态机枚举（enums.py:45-52）均为「先行基建」，无任何代码路径触达——风险是长期无人验证这些设计。
2. **repositories 层空转**：分层约定写着「路由与 service 不直接触碰 Session」（repositories/__init__.py），但该层零文件、deps.py:16 的 get_db 也无任何路由消费——分层是声明而非实践，P2 首个业务域落地时才见真章。
3. **API 覆盖与核心卖点零交集**：八大能力（Agent 工作流、Harness、Skill 进化、Context、MCP、RAG、文档解析、多模态）在 API 层无一入口；SSE、LangGraph、Chroma、MCP 全部缺位且依赖未装（pyproject.toml:11-20）。

**实现瑕疵（小）**
4. services/health.py:29-31：`api_latency` 在 `start = time.perf_counter()` 后下一行立刻计算，恒≈0ms——"API 延迟"字段无实际度量意义（对外语义失真，前端徽标展示的 api.latencyMs 无信息量）。
5. db/session.py:62-70 `db_session()` 请求结束自动 commit——无写路径时无害，但 P2 引入只读路由也会走 commit，且「session 内多段逻辑共享事务边界」的语义未定义。
6. 生产可见性：main.py:49-50 未按 `ENV=prod` 关闭 /docs 与 /openapi.json；CORS `allow_headers=["*"]` 与 `allow_credentials=True` 组合偏宽。
7. scripts/ 目录存在但为空；pyproject 描述写「FastAPI + LangGraph + …」而 langgraph 未安装（宣传与依赖清单不一致，属文案问题）。

**卫生**
8. 全库 **0 个 TODO/FIXME/XXX/HACK**；唯一一处 `pass` 在 core/logging.py:33，是日志过滤器内「吞异常保业务」的有意设计（带 noqa 注释），非烂尾。
9. 无鉴权（P1 有记录的决策，deps.py:5 注明 P2 接入 current_user）——非缺陷，属阶段内取舍。

## 待证项 / 建议下一步

1. **P2 首个业务域（建议 tasks/runs + SSE）**：把 agent_execution_logs(run_id,seq) → SSE Last-Event-ID 重放链路打通，是验证全部预埋基建的最短路径。
2. 落地时先补 repositories 层与 schemas/tasks 域模型，兑现自述分层；get_db 依赖随之启用。
3. 修 health.py api_latency 度量（如改为进程启动时间或请求处理计时中间件）。
4. docs/07、docs/08 中的 P2/P3 计划清单可作对账基准——本轮未读 docs/（超出 backend 范围），建议下一轮核对计划与代码的映射。
