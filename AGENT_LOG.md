# AGENT_LOG.md — Subagent 驱动开发日志

## Plan 1: 核心库（25 tasks, 99 tests）

| Task | Commit | Subagent | 人工干预 | 教训 |
|------|--------|----------|----------|------|
| 1-6 | 171baf2..d1a4081 | general | 无 | 数据模型 + 动作协议 + LLM 抽象 + 工具执行器分层清晰 |
| 7 | d1a4081..6630d76 | general | 4 个 plan bug 修复 | 规则引擎的 first-match 逻辑需仔细测试 |
| 8-9 | 6630d76..3b7ece3 | general | 无 | HITL FSM 状态持久化用 SQLite，跨重启可恢复 |
| 10-12 | 3b7ece3..cfee423 | general | 无 | 反馈解析器需处理退化情况（unparseable output） |
| 13-15 | cfee423..7054f42 | general | 无 | 记忆检索用 LIKE 关键词匹配，够用 |
| 16-17 | 7054f42..9ceb014 | general | regex 修复 | 路径围栏的 commonpath 在 Windows 上需 normpath |
| 18 | 9ceb014..16480dd | general | mkdir 修复 | 测试中 exist_ok=True 防止目录已存在报错 |
| 19-20 | 16480dd..92d4f79 | general | 2 个 test 修复 | FK 约束需在 init_schema 中正确定义 |
| 21-23 | 92d4f79..b1b4863 | general | 无 | 截断修复 + NameError 修复 |
| 24 | b1b4863..8aaa8e0 | general | Deny 分支 NameError | stub 方法应标注 "intentional stub" |
| 25 | 8aaa8e0..7e1707e | general | 无 | 集成测试验证反馈信号注入 |

**Plan 1 总结**：25 tasks, 99 tests passed, 1 skipped。Subagent-driven development 有效，每个 task 平均 1-2 个 commit。reviewer 发现了 4 个 Important 级别问题，全部修复。

---

## Plan 2: CLI + WebUI（9 tasks, 147 tests total）

| Task | Commit | Subagent | 人工干预 | 教训 |
|------|--------|----------|----------|------|
| 1 | 1bfe628 | general | 无 | AppConfig 数据类 + YAML 加载，verbatim 实现 |
| 2 | 4109b0b | general | MemoryEntry 时间戳修复 | brief 的测试代码遗漏了必填字段 |
| 3 | 4c5fc91 | general | check_same_thread 作用域 | stub→DB 轮询重写，需限定 test 参数 |
| 4 | 261e55a | general | 无 | 超时清理线程，daemon + Event 停止 |
| 5 | 95c1539 | general | FastAPI 兼容性修复 ×3 | brief 代码与 FastAPI 不兼容：Depends 嵌套、HTTPException 序列化 |
| 6 | c17962c | general | 扁平错误体修复 | HTTPException handler 统一为 {"error": "msg"} |
| 7 | 00b21a6 | general | workspace 默认值修复 | `if args.workspace` 恒真，改用 `is not None` |
| 8 | 07169af | general | 无 | 单页 HTML+JS，无构建步骤 |
| 9 | f82174a | general | GuardrailsConfig→load_config 修复 | 直接构造丢失默认规则，done 触发 RequireApproval |

**Plan 2 总结**：9 tasks, 147 tests passed (48 new), 1 skipped。4 个 task 需要 fix subagent。brief 中的代码 bug 主要集中在 FastAPI 兼容性和测试代码遗漏。

---

## Plan 3: 分发 + CI + Demo

| Task | Commit | Subagent | 人工干预 | 教训 |
|------|--------|----------|----------|------|
| demo | (pending) | controller 直接实现 | run_tests 挂起 | write_file 触发 RequireApproval，需 auto_approve_writes 配置 |
| Dockerfile | (pending) | controller 直接实现 | — | 多阶段构建，serve 子命令为入口 |
| CI | (pending) | controller 直接实现 | — | unit-test job + build-image job |
| README | (pending) | controller 直接实现 | — | 11 个必备章节 |
| CLI 子命令 | (pending) | controller 直接实现 | — | serve/resume/key set/status/clear |

**Plan 3 教训**：
1. demo 脚本中 `run_tests` 工具默认 target 是 "tests" 目录，需显式指定
2. `write_file` 动作默认触发 RequireApproval，demo 中需 override 为 Allow
3. brief 代码与框架（FastAPI）的兼容性问题需在 review 阶段发现
