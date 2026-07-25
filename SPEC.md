# ForgeLoop — Coding Agent Harness 设计规格

- **日期**：2026-07-19
- **状态**：设计定稿，待实现计划
- **作者**：ForgeLoop 设计会话（brainstorming skill 产出）
- **核心等式**：Agent = LLM + Harness。本项目交付 Harness 这一层。

---

## 0. 项目定位

ForgeLoop 是一个自研的 Coding Agent Harness：把"只会决定下一步做什么"的 LLM 封装成能稳定读写代码、执行命令、运行测试并自我修正的系统。六个维度（决策封装 / 动作工具 / 上下文与记忆 / 治理护栏 / 反馈闭环 / 声明式配置）都有可运行的最低实现，其中**治理护栏**是 main contribution。

## 1. 硬性约束（全部不可协商）

1. **自实现 agent 主循环**：组织上下文 → 调用 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断。禁止建立在 LangChain AgentExecutor、AutoGen、CrewAI、LlamaIndex agent 或任何编码智能体 SDK 的 agent runner 之上；只允许用底层零件（单次 chat completion API、HTTP 库、解析库）。
2. **可注入的 LLM 抽象层**：同一接口既可接真实供应商，也可替换为 mock/stub LLM 跑完全离线的确定性单元测试。
3. **六维度最低实现 + 治理做深**：护栏规则引擎（`guardrail(action) -> Allow | Deny | RequireApproval`，规则来自声明式配置）；HITL 审批状态机（危险动作进 PENDING，可持久化与恢复）；路径范围围栏（写操作限制在工作区内，越界即拦截）。
4. **反馈闭环是代码机制**：确定性校验器（运行 pytest/lint，解析输出为结构化结果），失败分类后回灌进下一轮上下文，驱动 agent 自我修正；不允许"让 LLM 自查"式的提示词方案。
5. **判定标准**：移除真实 LLM 后，工具分发、治理拦截、反馈回灌、记忆读写、停机判断每个机制都能用确定性单元测试验证。每个机制在设计时指出对应的可测试断言。
6. **凭据安全**：API key 绝不硬编码 / 不进 Git / 不进日志与 shell history；用 OS 钥匙串（Python keyring）做安全存储，.env 作为可选来源并说明明文风险；首次运行引导隐藏输入录入 key，支持查看状态（不回显明文）/ 更新 / 清除。
7. **分发**：Docker 镜像（单条 build + 单条 run 可启动）+ PyPI 包，README 说明目标机上 key 的安全配置方式与已知限制。
8. **可公网访问的 WebUI**（FastAPI + 简单前端）：展示 agent 运行轨迹、待审批动作队列（HITL 审批在此点按钮）、记忆内容。课程交付硬要求。
9. **技术栈**：Python 3.12 + pytest + FastAPI。
10. **记忆跨会话持久化**：项目约定、历史决策，按需检索注入上下文而非全量载入；存储与检索自己实现（JSONL/SQLite + 关键词/标签检索），不接现成 memory 框架。

## 2. 跨切面决策（brainstorming 阶段敲定）

| 决策 | 取值 | 理由 |
|---|---|---|
| WebUI 用户模型 | **单用户 + 共享密钥鉴权** | 课程项目够用；公网暴露但所有端点需 bearer token；避免任何访客审批动作；API key 全局单个（owner 的） |
| LLM 供应商范围 | **仅 OpenAI 兼容 API** | 一个适配器覆盖 OpenAI/DeepSeek/Moonshot/本地 vLLM/Ollama；与"自定义 JSON schema 从文本解析"天然契合；只管一个 key |

## 3. 系统架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / WebUI                          │
└──────────────┬──────────────────────────────┬───────────────┘
               │ start session                │ approve/deny
               ▼                              │
┌─────────────────────────────────────────────────────────────┐
│                     Agent Main Loop                         │
│  组织 context → 调 LLM → parse → guardrail → execute →       │
│  feedback → 停机判断 → 回灌                                  │
└──┬──────────┬──────────┬──────────┬──────────┬─────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌────────┐ ┌─────────┐ ┌────────┐ ┌─────────┐
│ LLM  │ │ Parser │ │Govern-  │ │ Tools  │ │Feedback │
│Abstr│ │(Block1)│ │ance(B5) │ │(B2)    │ │Classfr │
│      │ │        │ │+HITL    │ │        │ │(B4)     │
└──┬───┘ └────────┘ └────┬────┘ └───┬────┘ └────┬────┘
   │                       │          │           │
   │  keyring (B8)         │          │           │
   ▼                       ▼          ▼           ▼
┌─────────────────────────────────────────────────────────────┐
│              SQLite (forgeloop.db) — Block 6                 │
│   Session / Turn / Action / ApprovalRequest / MemoryEntry    │
└─────────────────────────────────────────────────────────────┘
```

主循环伪码：
```
while session.status == RUNNING:
    context = build_context(session)              # task + history + memory + feedback
    raw = llm.complete(context)                   # LLM 抽象层（可注入 mock）
    action_or_err = parse(raw)                    # Block 1
    if parse_error:
        retry within turn; on PARSE_FAIL_LIMIT → FAILED_PARSE
        continue
    decision = guardrail(action, session)         # Block 5（路径围栏 + 规则引擎）
    if decision.verdict == Deny:
        record BLOCKED; feed back; continue
    if decision.verdict == RequireApproval:
        create ApprovalRequest; session → PENDING_APPROVAL; block
        on approve → execute; on deny → feed back; on timeout → stop
    result = tool_registry.dispatch(action)       # Block 2
    feedback = FeedbackClassifier.classify(result) # Block 4
    persist Turn/Action/FeedbackSignal             # Block 6
    inject feedback into next context
    check_shutdown(session)                        # Block 3
```

### 3.1 LLM 抽象层（硬约束 #2）

同一接口既接真实 OpenAI 兼容供应商，也可替换为 mock/stub 跑确定性测试：

```python
class LLMProvider(Protocol):
    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse: ...

@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str

@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.0
    base_url: str | None = None     # None = 默认供应商
    # 注意：不含 api_key。key 由 RealLLMProvider 内部从 keyring/env 取（Block 8）

@dataclass
class LLMResponse:
    content: str                     # LLM 原始文本输出
    meta: LLMCallMeta                 # 不含 key、不含 headers
@dataclass
class LLMCallMeta:
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
```

- **RealLLMProvider**：用 `httpx` 调 OpenAI Chat Completions 兼容端点。key 从 `keyring.get_key()` 取，无则从 env `OPENAI_API_KEY` 取，都无则引导录入。key 绝不出现在 LLMConfig、日志、meta 中。
- **MockLLMProvider**：测试用。接受一个响应序列（list[str]）或一个 callable `(messages, config) -> str`，按序/按逻辑返回固定字符串。完全离线、确定性，满足硬约束 #5。

### 3.2 上下文结构（build_context）

每轮 LLM 调用前，harness 组装 context（按顺序拼成 messages 列表）：

1. **system**：系统提示——工具 schema 清单（六个工具的 args）、输出格式约束（"只输出一个 JSON 对象，字段 thought/tool/args"）、安全边界声明（"你只能在工作区内操作"）。
2. **user**：任务描述（session.task）。
3. **user**：`[MEMORY]` 段——top-K 检索命中的记忆条目（Block 6）。
4. **历史轮次**（按序）：每轮一对消息：
   - **assistant**：上一轮 LLM 的 raw 输出（thought + tool + args 的 JSON）。
   - **user**：上一轮工具结果信封 + `[FEEDBACK]` 段（若有 FeedbackSignal）。
5. **user**：若上一轮 parse 失败 → parse 纠错消息（Block 1）。

历史轮次按 `MAX_HISTORY_TURNS`（默认 20）截断，超出只保留最近 N 轮 + 第一轮（task），中间折叠为摘要。防 context 爆炸。

---

## 4. 主题块 1 — 动作协议（Action Protocol）

### 4.1 格式

**单轮单动作 + 自定义 JSON 对象（嵌入文本，宽松提取）**。每轮 LLM 输出一个 JSON 对象：

```json
{
  "thought": "我需要先读取 src/main.py 了解结构，再决定如何修改。",
  "tool": "read_file",
  "args": {"path": "src/main.py"}
}
```

- `thought`（string，必填）：LLM 推理过程。用于 WebUI 轨迹展示与调试，不参与工具执行。
- `tool`（string，必填）：工具名，必须在 `{read_file, write_file, run_shell, run_tests, list_dir, done}` 内。
- `args`（object，必填）：工具参数，schema 由各工具定义（见 Block 2）。

Harness 端赋值（LLM 不控制）：`turn_id`、`action_id`、`status`、`started_at`、`finished_at`、`result`。

**单轮单动作**：Harness 强制每轮只执行一个动作。若 LLM 输出多个，取第一个、记 warning。理由：治理审批、反馈归因、确定性测试都按"一轮一动作"建模最简单。

### 4.2 解析策略（三级降级）

LLM 被系统提示要求"只输出 JSON 对象，不要散文"，但实际会夹带 prose。解析器按序尝试：

1. **严格模式**：整段输出直接 `json.loads`。成功 → 用。
2. **围栏提取**：找第一个 ` ```json ... ``` ` 围栏块，`json.loads` 其内容。
3. **大括号匹配**：找第一个 `{` 到匹配的 `}`（栈式计数），`json.loads`。
4. **全部失败** → 记 `ParseError`，进入失败处理流程。

JSON 解析成功后做 **schema 校验**：`tool` 在允许集合内？`args` 含该工具必填字段？`thought` 非空？任一不过 → 视为 ParseError。

### 4.3 解析失败处理（重试 + 熔断）

- 单次 ParseError → 不消耗一个"动作轮"，而是**在同一轮内回灌一条 system 消息**：`"上一条输出无法解析为合法动作。请只输出一个 JSON 对象，字段：thought(必填, string), tool(必填, 取自 {…}), args(必填, object)。上次错误：{具体错误}。"`，重新调用 LLM。
- 连续 `PARSE_FAIL_LIMIT`（默认 3）次 ParseError → **解析熔断**，Session 状态置 `FAILED_PARSE`，停机。
- `PARSE_FAIL_LIMIT` 来自声明式配置，可调。

### 4.4 备选与取舍

| 方案 | 优点 | 缺点 | 取舍 |
|---|---|---|---|
| **A. 单 JSON 对象/轮（采用）** | 简单、治理/反馈/测试都按单动作建模；与 OpenAI 兼容口天然契合 | 探索阶段不能批量读多个文件 | v1 优先简洁与可测性 |
| B. 多动作/轮（`{"actions":[...]}`） | 批量读高效 | 每个动作独立审批/反馈归因复杂 | 拒绝；YAGNI |
| C. XML 标签 | 对 prose 夹带更鲁棒 | 解析代码更多、非标准 | 拒绝 |

### 4.5 可测试断言

- `T1.1` `parse('{"thought":"x","tool":"read_file","args":{"path":"a.py"}}')` → `Action(tool="read_file", args={"path":"a.py"}, thought="x")`。
- `T1.2` 含 prose + 围栏的输出 → 仍正确提取。
- `T1.3` `{"tool":"bogus_tool",...}` → `ParseError(tool_not_found)`。
- `T1.4` `{"tool":"read_file","args":{}}`（缺 path）→ `ParseError(missing_arg)`。
- `T1.5` 完全非 JSON 文本 → `ParseError(unparseable)`。
- `T1.6` mock LLM 连续 3 次返回垃圾 → Session 状态 `FAILED_PARSE`，未执行任何工具。
- `T1.7` mock LLM 第 1 次返回垃圾、第 2 次返回合法 JSON → 第 2 次被解析执行，Session 继续。

---

## 5. 主题块 2 — 工具清单（Tool Inventory）

### 5.1 统一结果信封

所有工具返回同一结构：

```json
{
  "ok": true,
  "result": { ... } | null,
  "error": { "code": "path_outside_workspace", "message": "..." } | null,
  "truncated": false
}
```

**关键语义**：`ok` 只表示"工具执行无内部异常"。`run_shell` 命令 exit_code=1 仍算 `ok=true`（命令失败是结果，不是工具错误），exit_code 进 `result`，LLM 据此自我修正。`ok=false` 仅用于：工具内部异常、超时、治理拦截、参数校验失败。

**输出截断**：每个字符串字段上限 `MAX_OUTPUT_BYTES`（默认 10KB，可配），超长截断并置 `truncated=true`。

### 5.2 六个工具

#### 5.2.1 `read_file`
```json
// args
{"path": "src/main.py", "offset": 0, "limit": 2000}
// offset/limit 可选，默认从头读 2000 行
// result
{"path": "src/main.py", "content": "...", "lines": 42, "truncated": false}
// errors: file_not_found | path_outside_workspace | binary_file | file_too_large
```
- 治理：默认 Allow，受路径围栏约束。读操作默认也围在工作区内，可配置 `read_allowlist` 放行系统路径。
- 边界：二进制文件（含 NUL 字节）拒绝；单文件上限 `MAX_READ_BYTES`（默认 256KB）。

#### 5.2.2 `write_file`（双模式）
```json
// mode A: overwrite（新建/全量覆盖）
{"path": "src/new.py", "mode": "overwrite", "content": "full file content..."}
// mode B: edit（精确串替换，old_string 必须唯一匹配一次）
{"path": "src/main.py", "mode": "edit", "old_string": "def foo():\n    return 1",
 "new_string": "def foo():\n    return 2"}
// result
{"path": "src/main.py", "bytes_written": 128, "mode": "edit"}
// errors: path_outside_workspace | parent_missing | old_string_not_found | old_string_ambiguous | permission_denied
```
- 治理：默认 RequireApproval；受路径围栏（越界 Deny）。可配规则放宽（如 `*.py` 在工作区内 Allow）。
- edit 模式：old_string 必须在文件中**唯一匹配**，否则报 `old_string_ambiguous`，要求 LLM 提供更多上下文行。

#### 5.2.3 `run_shell`
```json
// args
{"command": "git status --short", "cwd": ".", "timeout": 60}
// cwd 相对工作区；timeout 默认 60s，上限 MAX_TIMEOUT（默认 300s）
// result
{"command": "git status", "exit_code": 0, "stdout": "...", "stderr": "...",
 "duration_ms": 120, "timed_out": false}
// errors: timeout | command_not_found | cwd_outside_workspace
```
- 治理：**高风险**。默认 RequireApproval；危险模式（`rm -rf`、`curl|sh`、`sudo` 等）→ Deny；网络出口可配。规则来自 Block 5。
- 边界：不继承 harness 的敏感环境变量（过滤 `*KEY*`/`*TOKEN*`/`*SECRET*`，对应硬约束 #6）；stdout/stderr 各截断 10KB。

#### 5.2.4 `run_tests`
```json
// args
{"target": "tests/", "args": ["-x", "--tb=short"]}
// 默认跑 pytest；target 默认 "tests/"
// result（原始输出，由 Block 4 FeedbackClassifier 解析为结构化 FeedbackSignal）
{"command": "pytest tests/ -x --tb=short -ra -q", "exit_code": 1,
 "stdout": "...(原始 pytest stdout, 截断 10KB)...", "duration_ms": 3200}
// errors: pytest_not_installed | target_not_found | collection_error
```
- 治理：默认 Allow；但执行测试代码，可配 RequireApproval。
- 关键：工具只返回原始 stdout + exit_code（与 run_shell 同构）；**结构化解析由 Block 4 的 FeedbackClassifier/TestParser 负责**（硬约束 #4 要求解析在确定性校验器内，不在工具内）。pytest 调用固定加 `--tb=short -ra -q` 以稳定解析格式。

#### 5.2.5 `list_dir`
```json
// args
{"path": "src", "recursive": false}
// result
{"path": "src", "entries": [{"name": "main.py", "type": "file", "size": 1024},
                             {"name": "utils", "type": "dir", "size": 0}]}
// errors: not_found | not_a_dir | path_outside_workspace
```
- 治理：Allow，受路径围栏。`recursive=true` 时条目数上限 `MAX_DIR_ENTRIES`（默认 500）。

#### 5.2.6 `done`
```json
// args
{"summary": "已实现 foo 功能，12 项测试全通过。", "success": true}
// result: 无（终端动作，Session 结束）
// errors: 无（纯信号）
```
- 治理：Allow。但 harness 记录"最后一次 run_tests 的状态"到 Session；可选配置 `require_green_tests_to_done`：若 `success=true` 但上次测试有失败 → 拒绝并回灌提示（Block 5 定）。
- 语义：`success` 是 LLM 自评，harness 不盲信，但尊重其作为停机信号；最终成败由 Session 记录的测试状态客观判定。

### 5.3 可测试断言

- `T2.1` read_file 读不存在路径 → `ok=false, error.code="file_not_found"`。
- `T2.2` read_file 读工作区外路径 → `ok=false, error.code="path_outside_workspace"`。
- `T2.3` write_file edit 模式，old_string 在文件中出现两次 → `ok=false, error.code="old_string_ambiguous"`。
- `T2.4` write_file 写工作区外路径 → 治理 Deny，`ok=false, error.code="denied_by_guardrail"`，文件未被创建。
- `T2.5` run_shell 跑 `rm -rf /` → 治理 Deny，命令未执行。
- `T2.6` run_shell 跑 `echo hi` → `ok=true, result.exit_code=0, result.stdout="hi\n"`。
- `T2.7` run_shell 跑 `sleep 10` 设 timeout=1 → `ok=false, error.code="timeout"`，进程被 kill。
- `T2.8` run_tests 喂固定 pytest 输出 fixture → `result.exit_code=1, result.stdout` 含原始 pytest 文本（结构化解析由 FeedbackClassifier 负责，见 T4.1）。
- `T2.9` done → Session 状态变 `COMPLETED`，停机。
- `T2.10` run_shell 环境变量过滤：harness env 含 `OPENAI_API_KEY=sk-xxx` → 子进程 env 不含该变量。

---

## 6. 主题块 3 — 停机条件（Shutdown Conditions）

### 6.1 概念对齐：Round vs Turn

- **Turn**：一次 LLM 调用（含同轮内的 parse 重试）。Turn 内若 parse 失败，不前进 round。
- **Round**：一个完整循环 `{LLM 调用 → parse → governance → 执行 → 结果 → 回灌}`，**只在成功执行（或被治理拦截）一个动作后**才算一轮。Round 计数器只在此刻 +1。

### 6.2 五个停机条件

1. **完成信号 `done`**：LLM 调 `done` → `COMPLETED`。若 `require_green_tests_to_done=true` 且 `done(success=true)` 但上次 run_tests 有失败 → 拒绝 done，回灌提示，不停机。`done(success=false)` 永远被接受 → `COMPLETED_WITH_FAILURE`。
2. **最大轮数 `MAX_ROUNDS`**：默认 50（可配）。Round 计数 ≥ MAX_ROUNDS → `STOPPED_MAX_ROUNDS`。
3. **解析熔断 `PARSE_FAIL_LIMIT`**：连续 3 次 parse 失败（同 turn 内）→ `FAILED_PARSE`。
4. **硬熔断 `MAX_CONSECUTIVE_FAILURES`**：连续 round 中动作结果为 `ok=false`（工具内部错误 / 治理 Deny）≥ 3 → `STOPPED_FAILURE_BREAKER`。不计数：命令 exit_code≠0、HITL 拒绝、parse 失败。任一 `ok=true` 的 round → 计数器清零。
5. **循环熔断 `MAX_IDENTICAL_ACTIONS`**：连续 round 的动作 `(tool, args_hash)` 完全相同 ≥ 3 → `STOPPED_LOOP`。即使 `ok=true` 也算。任一不同动作 → 计数器清零。

**附：审批超时 `APPROVAL_TIMEOUT`**：Session 处于 `PENDING_APPROVAL` 且无响应超过 24h（可配，0=永不超时）→ `STOPPED_APPROVAL_TIMEOUT`。由后台 sweeper 周期检查。

### 6.3 停机条件优先级

| 序 | 条件 | 终态 |
|---|---|---|
| 1 | `done` 被接受 | `COMPLETED` / `COMPLETED_WITH_FAILURE` |
| 2 | parse 熔断 | `FAILED_PARSE` |
| 3 | 硬熔断 | `STOPPED_FAILURE_BREAKER` |
| 4 | 循环熔断 | `STOPPED_LOOP` |
| 5 | 最大轮数 | `STOPPED_MAX_ROUNDS` |
| — | 审批超时（sweeper） | `STOPPED_APPROVAL_TIMEOUT` |
| — | 用户 WebUI 手动中止 | `ABORTED` |

### 6.4 Session 状态机

```
RUNNING ──action 需审批──> PENDING_APPROVAL ──批准──> RUNNING
   │                            │
   │                            ├──拒绝──> RUNNING(回灌拒绝结果)
   │                            └──超时──> STOPPED_APPROVAL_TIMEOUT
   ├──用户暂停──> PAUSED ──恢复──> RUNNING
   └──满足 1-5 任一──> 终态(见上表)
```

非终态：`RUNNING` / `PENDING_APPROVAL` / `PAUSED`
终态：`COMPLETED` / `COMPLETED_WITH_FAILURE` / `FAILED_PARSE` / `STOPPED_FAILURE_BREAKER` / `STOPPED_LOOP` / `STOPPED_MAX_ROUNDS` / `STOPPED_APPROVAL_TIMEOUT` / `ABORTED`

### 6.5 可测试断言

- `T3.1` mock LLM 第 50 轮仍未 done → 第 51 轮前 Session 变 `STOPPED_MAX_ROUNDS`。
- `T3.2` mock LLM 连续 3 轮返回 `read_file` 不存在路径（`ok=false`）→ 第 3 轮后 `STOPPED_FAILURE_BREAKER`。
- `T3.3` mock LLM 第 1 轮 `ok=false`、第 2 轮 `ok=true`、第 3 轮 `ok=false` → 不熔断（计数器被清零）。
- `T3.4` mock LLM 连续 3 轮 `read_file(path="a.py")`（文件存在，`ok=true`）→ `STOPPED_LOOP`。
- `T3.5` mock LLM 调 `done(success=true)`，上次 run_tests 有失败，`require_green_tests_to_done=true` → 不停机，回灌提示。
- `T3.6` mock LLM 调 `done(success=false)` → `COMPLETED_WITH_FAILURE`，停机。
- `T3.7` Session 在 `PENDING_APPROVAL`，模拟 25h 后 sweeper → `STOPPED_APPROVAL_TIMEOUT`。
- `T3.8` 用户通过 WebUI 调 abort → `ABORTED`，主循环退出。

---

## 7. 主题块 4 — 反馈信号结构（Feedback Signal）

### 7.1 核心原则

反馈闭环是一条**纯函数流水线**，全程无 LLM 参与：

```
工具执行 → 原始 stdout + exit_code
  → FeedbackClassifier（选解析器）
  → Parser（pytest / ruff）→ FeedbackSignal（结构化）
  → Renderer（渲染为消息文本）
  → 注入下一轮 context（user 角色消息）
```

### 7.2 FeedbackSignal 统一 schema

```json
{
  "kind": "test" | "lint" | "raw",
  "source_tool": "run_tests" | "run_shell",
  "source_action_id": "act_007",
  "passed": true,
  "summary": "10 passed, 2 failed in 3.2s",
  "stats": {"passed": 10, "failed": 2, "errors": 0, "skipped": 0},
  "failures": [
    {
      "id": "tests/test_foo.py::test_foo",
      "file": "tests/test_foo.py",
      "line": 12,
      "type": "AssertionError",
      "message": "assert 1 == 2",
      "classification": "assertion_failure"
    }
  ],
  "raw_excerpt": "...(截断的原始输出)..."
}
```

`lint` kind 的 `failures` 元素为 `{id, file, line, col, code, message, classification}`，无 `stats`。

### 7.3 解析器

#### TestParser（pytest，主解析器）
- 触发：`run_tests` 工具结果，或 `run_shell` 命令匹配 `^pytest\b`。
- pytest 调用参数：`pytest {target} --tb=short -ra -q`。
- 解析步骤（正则 + 状态机）：
  1. 抓 summary 行：`(\d+) passed(?:, (\d+) failed)?(?:, (\d+) errors?)?(?:, (\d+) skipped)?` → `stats`。
  2. 抓 `==== short test summary info ===` 段：每行 `FAILED tests/test_x.py::test_name - ErrorType: message` → `failures[].{id, type, message}`。
  3. 从 `failures` 的 `id` 解析 `file` 与 `line`。
  4. exit_code=2 且无 summary → `collection_error`。
- 健壮性：解析失败不抛异常，降级为 `kind=raw`，把原始 stdout 塞进 `raw_excerpt`，`passed=(exit_code==0)`。绝不阻塞主循环。

#### LintParser（ruff，次解析器）
- 触发：`run_shell` 命令匹配 `^ruff\b` 或 `^flake8\b`。
- ruff 输出格式：`path:line:col: CODE message` 每行一条。
- 解析：逐行正则 `^(.+?):(\d+):(\d+): (\w+) (.+)$` → `failures[]`。`passed = (violations == 0)`。

#### FeedbackClassifier（分发器）
```python
def classify(tool_name, command, stdout, exit_code) -> FeedbackSignal:
    if tool_name == "run_tests":
        return TestParser().parse(stdout, exit_code)
    if tool_name == "run_shell" and re.match(r"^(ruff|flake8)\b", command):
        return LintParser().parse(stdout, exit_code)
    return RawPassThrough(stdout, exit_code)  # kind=raw
```

### 7.4 失败分类（classification）

| 匹配（type 含） | classification | 给 agent 的隐含指引 |
|---|---|---|
| `AssertionError` / `Assert` | `assertion_failure` | 逻辑错，读测试与被测代码 |
| `ImportError` / `ModuleNotFoundError` | `import_error` | 依赖缺失或路径错 |
| `SyntaxError` | `syntax_error` | 代码语法非法，先修语法 |
| `Timeout` / `timeout` | `timeout` | 超时，查死循环/慢操作 |
| exit_code=2 且无 summary | `collection_error` | 测试文件本身导不出 |
| 其它 | `other` | 读 raw_excerpt |

纯函数 `classify_failure(type_str, exit_code, has_summary) -> str`。

### 7.5 注入下一轮 context

`Renderer.render(signal) -> str` 把 FeedbackSignal 渲染成文本，作为 **`user` 角色消息**注入下一轮：

```
[FEEDBACK] run_tests (action act_007) → FAILED
Summary: 10 passed, 2 failed in 3.2s
Failures:
1. tests/test_foo.py::test_foo (tests/test_foo.py:12) [assertion_failure]
   AssertionError: assert 1 == 2
2. tests/test_bar.py::test_bar (tests/test_bar.py:5) [import_error]
   ModuleNotFoundError: No module named 'frob'
Next: address the failures above. Read the failing tests and the code under test before editing.
```

- 结构化事实在前，`raw_excerpt` 在后供细节参考。
- 末尾一句固定指引（非"让 LLM 自查"，而是给方向）。
- `passed=true` 时渲染为 `[FEEDBACK] run_tests → PASSED (10 passed in 3.2s). Task may be complete; consider calling done.`

### 7.6 备选与取舍

| 决策点 | 备选 | 采用 | 理由 |
|---|---|---|---|
| pytest 解析 | stdout 正则 / `--json-report` 插件 | stdout 正则 | 不引依赖；解析失败降级 raw 不阻塞 |
| lint 范围 | 不做 / ruff / ruff+flake8+pylint | 仅 ruff（+flake8 同格式） | 现代默认；pylint 格式不同，YAGNI |
| 注入角色 | system / user / tool | user | 不用原生 tool-calling 故无 tool 角色 |
| 失败分类 | 不分类 / 按 type 字符串 / 用 LLM 分类 | 按 type 字符串 | 确定性；LLM 分类即"让 LLM 自查"，被禁 |

### 7.7 可测试断言

- `T4.1` TestParser 喂 fixture `pytest_fixtures/2_failed.txt` → `signal.passed=false, stats.failed=2, failures[0].classification="assertion_failure"`。
- `T4.2` TestParser 喂全通过 fixture → `passed=true, failures=[]`。
- `T4.3` TestParser 喂乱码 stdout → 降级 `kind=raw`，不抛异常。
- `T4.4` LintParser 喂 ruff 输出 `src/a.py:3:5: F841 local variable x is unused` → `failures[0]={file:"src/a.py",line:3,col:5,code:"F841"}`。
- `T4.5` `classify_failure("ModuleNotFoundError: No module named 'frob'", 1, True)` → `"import_error"`。
- `T4.6` `classify_failure("SyntaxError: invalid syntax", 1, True)` → `"syntax_error"`。
- `T4.7` Renderer 渲染含 2 failures 的 signal → 输出文本含 `[FEEDBACK]`、`FAILED`、两个 `id`、两个 `[classification]`。
- `T4.8` 端到端：mock LLM 第 1 轮调 run_tests → 第 2 轮收到的 context 含 `[FEEDBACK]` 段且 classification 正确。

---

## 8. 主题块 5 — 治理护栏（Governance Guardrails）— Main Contribution

三大子机制：路径围栏 + 规则引擎 + HITL 审批状态机。

### 8.1 路径围栏（Path Fence）

**硬约束**：所有文件写操作限制在 `workspace_root` 内。不可协商的安全底线，在规则引擎之前执行，配置无法关闭。

```python
def fence_path(path, workspace_root, mode) -> FenceResult:
    # 1. 解析为绝对路径（相对 workspace_root）
    # 2. os.path.realpath 解符号链接
    # 3. os.path.normpath 规整 ..
    # 4. 检查 commonpath([resolved, workspace_root]) == workspace_root
    #    不等 → Deny("path_outside_workspace")
    # 5. writes 永远围栏；reads 按 path_fencing.reads 配置
```

边界情况：
- `..` 穿越：`workspace/../etc/passwd` → 解析后越界 → Deny。
- 符号链接逃逸：`workspace/link → /etc` → realpath 解析后越界 → Deny。
- Windows 盘符：`D:\ccc\forgeloop` vs `C:\Windows` → commonpath 不符 → Deny。
- 大小写：Windows 不区分大小写，比较前 lower-case（仅 win32）。
- `read_allowlist`：`/tmp/`、`~/.config/forgeloop/` 等可配放行读。

### 8.2 规则引擎（Rule Engine）

**评估模型**：规则按 YAML 声明顺序自上而下评估，**首匹配胜出**（类 iptables）。路径围栏在规则引擎之前硬执行。无规则匹配 → `default_decision`（默认 `RequireApproval`，保守）。

```python
@dataclass
class Decision:
    verdict: Literal["Allow", "Deny", "RequireApproval"]
    rule_id: str
    reason: str
```

### 8.3 规则 schema（YAML）

```yaml
guardrails:
  workspace_root: "."
  path_fencing:
    writes: true                  # 硬约束，恒 true（配置写 false 也被强制为 true）
    reads: true
    read_allowlist: ["/tmp/", "~/.config/forgeloop/"]

  rules:
    - id: deny_rm_rf_root
      tool: [run_shell]
      match:
        command_regex: 'rm\s+(-[a-z]*f[a-z]*\s+)?-?r?f?\s+/(?!tmp\b)'
      decision: Deny
      reason: "destructive rm -rf on root"

    - id: deny_curl_pipe_sh
      tool: [run_shell]
      match: { command_regex: 'curl\s+.*\|\s*(sh|bash)' }
      decision: Deny
      reason: "remote code execution"

    - id: deny_sudo
      tool: [run_shell]
      match: { command_regex: '^\s*sudo\b' }
      decision: Deny

    - id: deny_write_git_dir
      tool: [write_file]
      match: { path_regex: '(\.git/|\.git\\)' }
      decision: Deny
      reason: "writing into .git is forbidden"

    - id: allow_git_readonly
      tool: [run_shell]
      match: { command_regex: '^git\s+(status|diff|log|show|ls-files)\b' }
      decision: Allow

    - id: approve_all_writes
      tool: [write_file]
      match: { any: true }
      decision: RequireApproval
      reason: "file write requires approval"

    - id: approve_shell_default
      tool: [run_shell]
      match: { any: true }
      decision: RequireApproval

    - id: allow_reads
      tool: [read_file, list_dir]
      match: { any: true }
      decision: Allow

    - id: allow_tests
      tool: [run_tests]
      match: { any: true }
      decision: Allow

    - id: allow_done
      tool: [done]
      match: { any: true }
      decision: Allow

  default_decision: RequireApproval
  hitl:
    approval_timeout_seconds: 86400   # 24h；0 = 永不超时
    auto_approve_on_timeout: false    # 永远 false
  done_post_check:
    require_green_tests: false        # Block 2 开关
```

### 8.4 match 条件类型

| 条件 | 适用工具 | 语义 |
|---|---|---|
| `any: true` | 全部 | 匹配该工具任意调用 |
| `command_regex: "..."` | run_shell | 正则匹配 command 字符串 |
| `path_regex: "..."` | read_file/write_file/list_dir | 正则匹配 path |
| `path_outside_workspace: true` | read/write/list_dir | 路径越界（围栏已先判，冗余兜底） |
| `args_match: {k: v}` | 全部 | args 子集匹配 |
| `all: [cond, cond]` | 全部 | AND 组合 |

多条件同规则内默认 AND。需要 OR 写多条规则。

### 8.5 配置加载与覆盖

优先级（后者覆盖前者）：
1. 包内置默认 `forgeloop/config/guardrails.default.yaml`
2. 用户全局 `~/.config/forgeloop/guardrails.yaml`（Win: `%APPDATA%\forgeloop\`）
3. 项目本地 `./forgeloop.yaml`
4. CLI `--config <path>`

**规则合并**：按 `id` 去重——用户配置中同 id 规则**替换**默认规则；新 id 规则**追加**。`default_decision`、`hitl`、`done_post_check` 字段深度合并覆盖。

### 8.6 HITL 审批状态机

```
guardrail → RequireApproval
  → 创建 ApprovalRequest(status=PENDING, action_id, requested_at)
  → Action.status = PENDING_APPROVAL
  → Session.status = PENDING_APPROVAL（主循环暂停）
  → WebUI 审批队列显示该请求
  → 用户 POST /approvals/{id}/decision {verdict: approve|deny, reason?}
     ├ approve → Action.status=APPROVED → 执行 → 结果回灌 → Session=RUNNING
     └ deny    → Action.status=DENIED → 回灌 "用户拒绝：{reason}" → Session=RUNNING
  → 超时（24h，sweeper 检查）→ Session=STOPPED_APPROVAL_TIMEOUT
```

**持久化与恢复**：ApprovalRequest 与 Action 落 SQLite。进程崩溃重启后：扫描 `status=PENDING_APPROVAL` 的 Session，重建 ApprovalRequest 队列，Session 保持 `PENDING_APPROVAL` 等用户裁决。满足硬约束 #3"状态可持久化与恢复"。

### 8.7 默认规则集总览

| 工具 | 默认决策 | 理由 |
|---|---|---|
| read_file / list_dir（工作区内） | Allow | 只读 |
| write_file（工作区内） | RequireApproval | 写需确认 |
| write_file（越界 / .git/） | Deny | 围栏 + 保护 |
| run_shell `git status/diff/log` | Allow | 只读 git |
| run_shell `rm -rf /`、`curl|sh`、`sudo` | Deny | 危险 |
| run_shell 其它 | RequireApproval | 默认审 |
| run_tests | Allow | 测试只读 |
| done | Allow | 信号 |

### 8.8 备选与取舍

| 决策点 | 备选 | 采用 | 理由 |
|---|---|---|---|
| 评估模型 | 首匹配 / 优先级数字 / 最严胜出 | 首匹配（YAML 顺序） | 最直观、类 iptables |
| 路径围栏可关 | 可配 / 硬编码 | 硬编码（writes 恒围栏） | 硬约束 #3 不可协商；reads 可配 |
| 规则合并 | 全替换 / id 去重合并 | id 去重合并 | 用户既能加规则又能改默认 |
| 审批超时行为 | 停机 / 自动拒绝 / 自动批准 | 停机 | 自动批准危险；停机最安全 |
| `done_post_check` 位置 | 规则引擎内 / done 工具内 | done 工具内 | 它是 post-check，不是 action-match 规则 |

### 8.9 可测试断言

- `T5.1` `fence_path("workspace/../etc/passwd", ws, "write")` → Deny。
- `T5.2` `fence_path("workspace/sub/../a.py", ws, "write")` → Allow。
- `T5.3` 符号链接 `workspace/link → /etc`，`fence_path("workspace/link/x", ws, "write")` → Deny。
- `T5.4` `guardrail(Action(tool=run_shell, args={command:"rm -rf /"}))` → Deny, rule_id="deny_rm_rf_root"。
- `T5.5` `guardrail(Action(tool=run_shell, args={command:"git status"}))` → Allow, rule_id="allow_git_readonly"。
- `T5.6` `guardrail(Action(tool=write_file, args={path:"ws/a.py"}))` → RequireApproval, rule_id="approve_all_writes"。
- `T5.7` `guardrail(Action(tool=run_shell, args={command:"python foo.py"}))` → RequireApproval（默认）。
- `T5.8` 用户配置覆盖 `deny_sudo` 为 `decision: Allow` → 同 id 替换后 `guardrail(sudo)` → Allow。
- `T5.9` HITL：RequireApproval → ApprovalRequest 创建且 status=PENDING，Session 暂停；mock approve → Action 执行；mock deny → Action.status=DENIED，回灌消息含 "用户拒绝"。
- `T5.10` 持久化恢复：杀进程后重启，PENDING 的 ApprovalRequest 仍在队列，Session 仍 PENDING_APPROVAL。
- `T5.11` `done_post_check.require_green_tests=true`，上次 run_tests 有失败，`done(success=true)` → 被拒绝，回灌提示，不停机。

---

## 9. 主题块 6 — 数据模型（Data Model）

存储：**SQLite**（单文件 `forgeloop.db`，stdlib `sqlite3`，无 ORM，自写 schema）。满足硬约束 #10。

### 9.1 实体关系

```
Session 1──N Turn
Session 1──N Action
Session 1──N ApprovalRequest
Turn    1──0..1 Action
Action  1──0..1 ApprovalRequest
Session 1──N MemoryEntry (session-scoped)
workspace_root 1──N MemoryEntry (project-scoped, session_id nullable)
```

### 9.2 Session

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | uuid |
| task | TEXT | 用户任务描述 |
| workspace_root | TEXT | 绝对路径（围栏边界） |
| config_path | TEXT | 使用的配置文件路径 |
| status | TEXT | 状态机枚举（见 Block 3） |
| round_count | INT | 已执行 round 数 |
| consecutive_failures | INT | 硬熔断计数器 |
| consecutive_identical | INT | 循环熔断计数器 |
| last_action_hash | TEXT | 上一个动作的 args_hash |
| last_test_state | TEXT(JSON) | 上次 run_tests 的 FeedbackSignal 摘要 |
| llm_config | TEXT(JSON) | {model, temperature, base_url}（**不含 key**） |
| created_at / started_at / finished_at / updated_at | TEXT(ISO8601) | |

### 9.3 Turn

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | uuid |
| session_id | TEXT FK | |
| turn_index | INT | session 内序号 |
| llm_raw_output | TEXT | LLM 原始文本 |
| parsed_action_id | TEXT FK | 解析出的 action（null=parse 全失败） |
| parse_attempts | INT | 本 turn 内 parse 重试次数 |
| parse_status | TEXT | OK / PARSE_FAILED |
| llm_call_meta | TEXT(JSON) | {model, prompt_tokens, completion_tokens, latency_ms}（**不含 key、不含 headers**） |
| started_at / finished_at | TEXT | |

### 9.4 Action

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | uuid |
| session_id / turn_id | TEXT FK | |
| tool | TEXT | 工具名 |
| args | TEXT(JSON) | 工具参数 |
| thought | TEXT | LLM 推理 |
| args_hash | TEXT | 稳定 hash（循环熔断用） |
| status | TEXT | PENDING_APPROVAL/APPROVED/DENIED/EXECUTING/SUCCEEDED/FAILED/BLOCKED_BY_GUARDRAIL |
| guardrail_decision | TEXT(JSON) | {verdict, rule_id, reason} |
| result | TEXT(JSON) | 工具结果信封 |
| feedback_signal | TEXT(JSON) | 结构化 FeedbackSignal |
| created_at / started_at / finished_at | TEXT | |

### 9.5 ApprovalRequest

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | uuid |
| action_id | TEXT FK UNIQUE | 一对一 |
| session_id | TEXT FK | |
| status | TEXT | PENDING/APPROVED/DENIED/EXPIRED |
| requested_at / decided_at | TEXT | |
| decided_by | TEXT | "webui" |
| deny_reason | TEXT | 用户拒绝理由 |

### 9.6 MemoryEntry

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | uuid |
| session_id | TEXT FK NULL | null=项目级记忆 |
| workspace_root | TEXT | 归属工作区 |
| kind | TEXT | project_convention/decision/fact/lesson_learned |
| tags | TEXT(JSON) | 标签数组 |
| key | TEXT NULL | 可选结构化键 |
| content | TEXT | 记忆内容 |
| source_turn_id | TEXT FK NULL | 产生该记忆的 turn |
| created_at / updated_at | TEXT | |

### 9.7 记忆检索（自实现）

- **触发**：每轮 LLM 调用前，harness 用 `(task 关键词 + 上一动作关键词)` 检索 memory。
- **算法**：`SELECT * FROM memory WHERE workspace_root=? AND (content LIKE ? OR tags LIKE ?) ORDER BY updated_at DESC LIMIT K`（K=5）。关键词分词后 OR 拼 LIKE。
- **注入**：top-K 命中渲染为 `[MEMORY]` 段注入 context（在 feedback 之前）。
- **写入**：done 时把 summary 作为 lesson_learned 写入；项目约定由用户预置或 agent 显式写。
- 不接任何 memory 框架，纯 SQL LIKE + tag 过滤。

### 9.8 可测试断言

- `T6.1` 创建 Session → 查询返回字段完整，`llm_config` 不含 `api_key`。
- `T6.2` Turn 与 Action 的 1:0..1 关系：parse 全失败的 turn，`parsed_action_id` 为 null。
- `T6.3` ApprovalRequest 持久化：杀进程重启，PENDING 请求仍在。
- `T6.4` 记忆检索：插入 3 条带 tag 的记忆，按关键词检索返回 top-2。
- `T6.5` 跨会话：Session A 写入记忆，Session B（同 workspace）检索命中。

---

## 10. 主题块 7 — 用户故事（INVEST）

| # | 用户故事 | INVEST | 对应机制 |
|---|---|---|---|
| US1 | 作为开发者，我想用一条 CLI 命令启动 agent 会话执行编码任务，以便自动化重复代码修改。 | I/N/V/E/S/T 全过 | 主循环 + CLI |
| US2 | 作为开发者，我想在 agent 执行危险 shell 命令前收到审批请求，在 WebUI 一键批准/拒绝，以防破坏性操作。 | 全过 | 治理 + HITL + WebUI |
| US3 | 作为开发者，我想看到 agent 每轮的 thought/动作/结果轨迹，以便理解推理过程并调试。 | 全过 | 数据模型 + WebUI |
| US4 | 作为开发者，我想 agent 跑测试失败后自动解析分类失败，下一轮针对失败自我修正，以实现真反馈闭环而非一次性生成。 | 全过 | FeedbackSignal + 注入 |
| US5 | 作为开发者，我想用 mock LLM 跑完整 agent 流程的确定性单元测试，以不消耗 API 配额也验证 harness 机制正确。 | 全过 | LLM 抽象层 + 全机制 |
| US6 | 作为开发者，我想 API key 通过 OS 钥匙串安全存储、首次运行引导录入，以使 key 不进源码/Git/日志。 | 全过 | 凭据安全 |
| US7 | 作为开发者，我想 agent 跨会话记住项目约定与历史决策、按需检索注入上下文，以不从零开始。 | 全过 | 记忆持久化 + 检索 |

---

## 11. 主题块 8 — 凭据威胁模型（Credential Threat Model）

### 11.1 泄漏途径 × 对策矩阵

| # | 泄漏途径 | 威胁 | 对策 | 验证 |
|---|---|---|---|---|
| 1 | 源码 | key 硬编码在 .py | key 只从 keyring/env 读；代码中无 key 字面量；CI grep 扫 `sk-[A-Za-z0-9]{20,}` | T8.1 |
| 2 | Git 历史 | key 曾被 commit | `.gitignore` 已覆盖 `.env`；pre-commit hook 扫描；首选用 keyring | T8.2 |
| 3 | 日志 | log/print 泄漏 key | 日志 redact 过滤器（正则 `sk-[A-Za-z0-9]+` → `sk-****`）；LLM meta 不记 headers | T8.3 |
| 4 | 进程环境 | 子进程继承 `OPENAI_API_KEY` | `run_shell` 启动子进程时过滤 env：移除匹配 `*KEY*/*TOKEN*/*SECRET*` 的变量 | T8.4 |
| 5 | WebUI 回显 | API 返回 key 明文 | WebUI 凭据状态端点只返回 `{configured: bool, last_four: "abcd"}`，永不返回明文 | T8.5 |
| 6 | .env 明文 | .env 文件被读/泄露 | .env 作为可选来源但文档警告明文风险；推荐 keyring；`.gitignore` 覆盖 | T8.6 |
| 7 | 异常 traceback | key 出现在异常栈 | 全局异常 handler redact；不把 raw exception 发 WebUI | T8.7 |
| 8 | 配置文件 | key 写进 guardrails.yaml | 配置 schema 不含 key 字段；key 只在 keyring/env | T8.8 |

### 11.2 凭据存储：Python keyring

- 后端：Windows Credential Manager / macOS Keychain / Linux Secret Service（libsecret）。
- API：
  - `set_key(provider, key)` → `keyring.set_password("forgeloop", f"{provider}_api_key", key)`
  - `get_key(provider)` → 返回明文 or None
  - `status(provider)` → `{configured: bool, last_four: "abcd"}`（不回显明文）
  - `update(provider, new_key)` → 覆盖
  - `clear(provider)` → 删除
- **首次运行引导**：`get_key()` 为 None 且无 env → `getpass.getpass()`（隐藏输入，不回显）→ 存 keyring。绝不 echo。
- **.env 可选来源**：`OPENAI_API_KEY` 环境变量作为 fallback。文档明确警告：.env 是明文，泄露风险高于 keyring；推荐 keyring。
- **headless Linux 无 Secret Service**：keyring 后端缺失 → 降级到 .env + 醒目警告。文档说明此限制。

### 11.3 可测试断言

- `T8.1` 仓库内 grep `sk-[A-Za-z0-9]{20,}` → 0 命中（除测试 fixture）。
- `T8.2` `.gitignore` 含 `.env`。
- `T8.3` `redact_log("calling OpenAI with sk-abc123")` → `"calling OpenAI with sk-****"`。
- `T8.4` harness env 含 `OPENAI_API_KEY=sk-xxx`，`run_shell("env")` 子进程输出不含该变量。
- `T8.5` `GET /credentials` 响应 `{"configured": true, "last_four": "abcd"}`，无明文。
- `T8.6` `git ls-files` 不含 `.env`。
- `T8.7` 触发含 key 的异常 → WebUI 响应不含 key 字符串。
- `T8.8` guardrails.yaml schema 无 `api_key` 字段。

---

## 12. 主题块 9 — 风险与未决问题

### 12.1 风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | pytest stdout 解析脆弱（版本变更破坏正则） | 反馈信号降级 raw | 测试 pin pytest 版本；解析失败降级 raw 不阻塞；文档说明 |
| R2 | LLM 输出格式漂移（模型更新降低 JSON 可靠性） | parse 失败增多 | 三级解析 + 熔断；系统提示强约束输出格式 |
| R3 | Windows 路径围栏边界（大小写/盘符/junction） | 越界写漏拦 | 大量 win32 路径测试；realpath + commonpath + lower-case |
| R4 | WebUI 公网暴露（bearer token 暴力破解） | 未授权审批 | 限速；文档推荐反代 + TLS；长随机 token |
| R5 | 审批队列阻塞（用户离线） | agent 挂起 | 24h 超时停机；WebUI 可中止 |
| R6 | 记忆检索质量弱（LIKE 关键词） | 注入无关记忆 | v1 可接受；文档列为已知限制；v2 可加 embedding |
| R7 | token 成本失控 | 烧钱 | MAX_ROUNDS 上限；输出截断；熔断 |
| R8 | run_shell 子进程沙箱逃逸（批准后任意执行） | 系统破坏 | 治理规则；文档推荐 Docker 内运行 |
| R9 | headless Linux 无 keyring 后端 | key 降级 .env 明文 | 文档警告；推荐 Docker secret / 环境管理 |
| R10 | 多并发 session 资源竞争 | CPU/内存/token 竞争 | v1 限制：1 个 RUNNING session + N 个 PENDING_APPROVAL/PAUSED |

### 12.2 未决问题（设计决策已定，记录供 review）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| O1 | 单轮多动作？ | 否，单轮单动作 | 治理/反馈/测试按单动作建模最简 |
| O2 | run_tests 支持非 pytest？ | 否，v1 仅 pytest | 技术栈锁定；YAGNI |
| O3 | 记忆语义检索？ | 否，v1 关键词+标签 | 自实现要求；embedding 引入依赖 |
| O4 | WebUI 多并发 session？ | 数据模型支持，执行模型限 1 RUNNING + N 暂停 | 单用户够用；并发复杂度高 |
| O5 | 原生 function-calling？ | 否，自定义 JSON schema | provider 无关；契合硬约束 #1 |
| O6 | lint 支持 pylint？ | 否，仅 ruff（+flake8 同格式） | pylint 输出格式不同；YAGNI |

---

## 13. 分发与部署

### 13.1 PyPI 包

- 包名 `forgeloop`，`pip install forgeloop`。
- CLI 入口 `forgeloop` 命令。
- 依赖：`httpx`（LLM 调用）、`fastapi`+`uvicorn`（WebUI）、`keyring`（凭据）、`pyyaml`（配置）。不依赖任何 agent SDK。

### 13.2 Docker 镜像

- 单条 `docker build` + 单条 `docker run` 可启动。
- 镜像内含 PyPI 包 + 默认配置。
- 目标机 key 安全配置方式：挂载 keyring 卷 / 环境变量（文档说明明文风险）/ Docker secret。README 详述。

### 13.3 WebUI（FastAPI + 简单前端）

- 端点（全部需 bearer token）：
  - `GET /sessions` / `POST /sessions`（启动）
  - `GET /sessions/{id}`（轨迹：turns + actions + feedback）
  - `GET /approvals` / `POST /approvals/{id}/decision`（HITL 队列）
  - `GET /memory`（记忆内容）
  - `GET /credentials`（状态，不回显明文）
  - `POST /sessions/{id}/abort`
- 前端：简单 HTML+JS（无框架），展示轨迹、审批队列、记忆。

---

## 14. 验收标准（对应硬约束 #5）

移除真实 LLM 后，以下机制都能用确定性单元测试验证（mock LLM 喂固定字符串）：

| 机制 | 关键测试断言 |
|---|---|
| 工具分发 | T2.1–T2.10 |
| 治理拦截 | T5.1–T5.11 |
| 反馈回灌 | T4.1–T4.8 |
| 记忆读写 | T6.1–T6.5 |
| 停机判断 | T3.1–T3.8 |
| 动作解析 | T1.1–T1.7 |
| 凭据安全 | T8.1–T8.8 |

---

## 15. 下一步

本设计定稿后，进入 `writing-plans` skill 产出实现计划。
