# EvoCode Agent — 后端服务

FastAPI + SQLAlchemy 2 (async) + PostgreSQL + Redis 的模块化分层后端。设计文档：[docs/08-后端架构与数据库设计.md](../docs/08-后端架构与数据库设计.md)。

> **当前阶段（Phase 1）**：基础工程——配置/日志/异常、PG/Redis 连接管理、20 张表模型、Alembic、健康检查三接口、统一错误体、基础测试。
> **尚未实现（不虚构）**：Agent 业务逻辑（LangGraph）、Skill 自进化、MCP 工具、SSE 事件流、记忆检索（Chroma）——分别属于 docs/07 的 P2/P3。

## 环境要求

- Python ≥ 3.12（本机验证 3.13.5）
- Docker Desktop（运行 PostgreSQL 16 与 Redis 7）

## 快速启动

```bash
# 1. 基础设施（postgres/redis）
cd backend
docker compose up -d postgres redis
docker compose ps            # 等待两个容器 healthy

# 2. Python 环境
python -m venv .venv
.venv\Scripts\activate       # Windows；bash: source .venv/Scripts/activate
pip install -e ".[dev]"

# 3. 环境变量
cp .env.example .env         # 按需修改；GLM_API_KEY P3 前留空

# 4. 数据库迁移
alembic upgrade head

# 5. 启动
uvicorn app.main:app --reload --port 8000
```

## 验证（Phase 1 完成标准）

| 标准 | 验证方式 |
| --- | --- |
| 1. 启动 | `uvicorn app.main:app` 控制台出现「启动（env=dev）」 |
| 2. Swagger | 浏览器打开 <http://localhost:8000/docs> |
| 3. 健康检查 | `curl http://localhost:8000/api/v1/health` |
| 4. PG/Redis 连接 | health 返回中 `postgres.status=ok`、`redis.status=ok` |
| 5. 基础测试 | `pytest`（依赖未启动时集成用例自动跳过并如实标注） |

三个探针接口的语义：

| 接口 | 语义 |
| --- | --- |
| `GET /healthz` | 进程存活，恒 200 |
| `GET /readyz` | 就绪探针：PG/Redis 任一不可用 → **503** + 错误体 |
| `GET /api/v1/health` | 各依赖 `status + latencyMs`，恒 200；`chroma=disabled`（P3 启用）、`mcp=[]`（P3 接入） |

## 目录结构

```
app/
├── api/          # 路由（v1）与依赖注入；路由不直接触碰 DB
├── core/         # 配置(.env)/日志(敏感值过滤)/异常/响应约定/枚举
├── db/           # engine+session、redis 连接管理（lifespan 建立与释放）
├── models/       # 20 张表（SQLAlchemy 2 声明式，ULID 主键，级联策略见 docs/08 §8）
├── schemas/      # Pydantic v2（对齐前端 types/api.ts）
├── repositories/ # 数据访问层
├── services/     # 业务编排层
└── agents/ tools/ skills/ context/ memory/ evaluation/   # 骨架（P2/P3 实装）
```

## 接口契约（与前端）

- 成功：**裸实体 JSON**（无 `{code,data}` 包装）
- 失败：`{"error": {"code", "message", "details"?}}`
- 分页：`{"items","total","page","size"}`
- 前端切真实数据：`frontend/.env.development` 改 `VITE_API_MODE=live` + 代理 `/api` 到 8000 端口（P2 联调时配置）

## 测试

```bash
pytest            # 全量
pytest tests/test_health.py -v
```

- 不依赖 PG/Redis 的用例始终可跑；
- 集成用例在依赖不可用时 **skip**（不会假装通过）；
- `alembic revision --autogenerate -m "..."` 需在 PG 可用时执行。

## 常见问题

- **readyz 返回 503**：PG/Redis 未启动或连接串不对，`docker compose ps` 看健康状态、核对 `.env` 的 `DATABASE_URL`/`REDIS_URL`。
- **ulid 导入错误**：`python-ulid>=4`，生成方式为 `ulid.default_generator.generate()`（API 与 v2 不同）。
