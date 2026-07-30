# SPEC_PROCESS.md — ForgeLoop 设计协作过程记录

## 1. 关键追问与修正

### 1.1 动作协议：为什么不用 function-calling？

**追问**：设计初期考虑过使用 OpenAI function-calling，但追问后发现 function-calling 把动作解析与 schema 校验外包给供应商，而这层工程必须在代码里可独立单测。

**决策**：采用自定义 JSON-in-text 协议。LLM 输出包含 `thought`、`tool`、`args` 的 JSON 对象，自研解析器从自由文本中提取 JSON。解析失败时结构化错误回灌 + 连续 N 次熔断。

**影响**：增加了 `parser/` 模块的工作量，但确保了协议层的可测试性和供应商无关性。

### 1.2 熔断阈值 N

**追问**：连续解析失败几次后熔断？

**决策**：N=3。理由：1 次太激进（偶发格式错误），5 次太宽松（浪费 token），3 次是工程惯例。

### 1.3 停机条件设计

**追问**：什么条件下 agent 应该停止？

**决策**：四类停机条件：
1. 完成信号（`done` 工具 + `success=true`）
2. 最大轮数（默认 50，可配置）
3. 连续失败熔断（3 次连续失败 → STOPPED_FAILURE_BREAKER）
4. 连续相同动作熔断（3 次相同 args_hash → STOPPED_LOOP）

### 1.4 HITL 审批的阻塞方式

**追问**：Plan 1 中 `_await_approval` 是 no-op stub，Plan 2 需要实现真正的阻塞。用 DB 轮询还是 WebSocket？

**决策**：DB 轮询（每 2 秒）。理由：跨重启可恢复、无需额外组件、≤2 秒延迟可接受。WebSocket 留到 Plan 3b。

### 1.5 SQLite WAL 模式

**追问**：agent loop 和 WebUI 如何并发访问 SQLite？

**决策**：`PRAGMA journal_mode=WAL`。允许并发读 + 单写。每个线程打开自己的连接。

### 1.6 错误响应格式

**追问**：FastAPI 的 `HTTPException(detail={...})` 会序列化为 `{"detail": {...}}`，但 spec 要求 `{"error": "msg"}`。

**决策**：自定义异常处理器。auth 用 `UnauthorizedError` + `register_auth_handler`；404/400 用 `HTTPException` handler 统一扁平化。

## 2. 关键迭代

### 迭代 1：Plan 1 → Plan 2 的 _await_approval 重写

Plan 1 中 `_await_approval` 是 `pass`（no-op），RequireApproval 动作自动执行。Plan 2 重写为 DB 轮询循环，返回 `"approved"/"denied"/"timeout"`。这改变了 RequireApproval 分支的控制流，需要更新所有依赖 stub 行为的测试。

**教训**：stub 方法应在注释中标注 "intentional stub, Plan X will implement"，避免被误认为完成。

### 迭代 2：check_same_thread 问题

Plan 2 的测试需要在线程间共享 SQLite 连接。SQLite 默认禁止跨线程使用连接。添加 `check_same_thread=False` 参数到 `connect()`，但 reviewer 指出这违反了 "per-thread connections" 约束。

**修正**：将 `check_same_thread=False` 限定为测试专用参数（默认 `True`），生产代码使用每线程独立连接。

### 迭代 3：GuardrailsConfig 直接构造 vs load_config

E2E 测试中直接构造 `GuardrailsConfig(workspace_root=...)` 会导致 `rules=[]`（空规则列表），使 `done` 工具触发 `RequireApproval`（默认决策），创建无人处理的审批请求，导致测试挂起。

**修正**：使用 `load_config([])` 加载默认规则集（包含 `allow_done` 规则）。

## 3. 采纳与推翻的建议

### 采纳
- **六维度分层实现**：数据模型 → LLM 抽象 → 工具 → 治理 → 主循环 → 反馈 → 记忆 → 配置 → 凭据 → WebUI。每层可独立测试。
- **TDD 严格执行**：每个机制先写失败测试，再写最少实现。147 个测试全部通过。
- **Subagent-driven development**：每个 task 派新鲜 subagent，task 间 review。有效防止了上下文污染。
- **WAL 模式 + 每线程连接**：解决了并发访问问题。

### 推翻
- **使用 WebSocket 实时更新**：推迟到 Plan 3b。轮询足够，WebSocket 增加复杂度。
- **多会话并发执行**：推迟到 Plan 3b。当前单会话满足课程要求。
- **PyPI 打包**：课程允许任选 Docker 或 PyPI，选择 Docker。

## 4. 冷启动验证记录

### 4.1 验证环境

- **验证 agent**：非 OpenCode 的另一 agent 类型，全新 session
- **提供文档**：SPEC.md + PLAN.md（项目根目录）
- **验证时间**：2026-07-30

### 4.2 阻断性问题

**问题 A：PLAN.md 是索引而非自包含文档**

冷启动 agent 发现 PLAN.md 只是指向 `docs/superpowers/plans/` 下两份详细计划文件的索引，不包含 task 定义。agent 无法仅凭 PLAN.md 获得足够的实现信息。

**分析**：spec 缺陷。PLAN.md 应自包含 task 定义（目标 / 文件路径 / 实现要点 / 验证步骤），或至少在文档中明确指向详细计划文件。

**修正**：在 PLAN.md 中明确标注详细计划文件路径，并在冷启动提示词中说明"PLAN.md 引用的详细计划文件也在仓库内，可读取"。

**问题 B：所有 task 已标记 complete**

冷启动 agent 发现 PLAN.md 中 34 个 task 全部标记 ✅ complete，无法"选前 2 个无依赖 task"实现。

**分析**：流程错误。冷启动验证（Stage 3）应在实现（Stage 4）之前进行，但实际执行顺序是先实现后验证。不过 agent 在 C 表发现的不一致仍然有价值的发现。

**修正**：记录此次验证为"回顾性冷启动"——验证 spec 的清晰度而非实现新 task。agent 的发现（C 表）已逐条修复。

### 4.3 文档-代码不一致（C 表）

| # | 位置 | 问题 | 判定 | 修正 |
|---|------|------|------|------|
| 1 | SPEC.md:740 vs sweeper.py:43 | ApprovalRequest 状态 spec 写 EXPIRED，代码用 TIMEOUT | spec 缺陷 | SPEC.md 改为 TIMEOUT |
| 2 | SPEC.md:345 vs server/app.py:66 | POST /sessions 写 status="QUEUED"，不在状态机枚举内，无消费者 | spec 缺陷 | SPEC.md 标注 PAUSED 为预留状态；POST /sessions 的 QUEUED 限制记录在 README 已知限制中 |
| 3 | SPEC.md:797 (T8.1) | 要求 CI grep 扫 sk- 模式，CI 配置中无此 job | spec 缺陷 | 在 .gitlab-ci.yml 和 .github/workflows/ci.yml 中添加 credential-scan job |
| 4 | SPEC.md:841 (R4) | 缓解措施列了"限速"，代码中无 rate limiting | spec 过度承诺 | SPEC.md 改为"文档推荐反代+TLS+限速；v1 未实现限速，列为已知限制" |
| 5 | SPEC.md:344 | PAUSED 是合法非终态，但无暂停/恢复端点 | spec 缺陷 | SPEC.md 标注 PAUSED 为预留状态，当前实现无暂停/恢复端点 |

### 4.4 教训

1. **冷启动验证必须在实现前做**——否则无法验证 spec 的可实现性
2. **PLAN.md 必须自包含**——不能依赖外部文件的索引
3. **spec 中的状态枚举必须与代码一致**——EXPIRED vs TIMEOUT 是典型的设计→实现漂移
4. **spec 不应过度承诺**——"限速"写在 spec 里但未实现，冷启动 agent 正确地发现了这个不一致

## 5. 反思

（待用户填写 — REFLECTION.md 素材）
