# ForgeLoop 实现计划 (PLAN.md)

> 详细计划文件：
> - Plan 1（核心库）：`docs/superpowers/plans/2026-07-19-forgeloop-core-library.md`
> - Plan 2（CLI + WebUI）：`docs/superpowers/plans/2026-07-22-forgeloop-cli-webui.md`
> - Plan 3a（分发 + CI + Demo）：本文档

## 进度表

### Plan 1: 核心库（25 tasks）

| Task | 状态 | Commit Range | 说明 |
|------|------|-------------|------|
| 1 | ✅ complete | 171baf2..490e418 | 数据模型 + 动作协议 |
| 2 | ✅ complete | 2c5b6dd..8ce13e8 | LLM 抽象层 + mock |
| 3 | ✅ complete | 490e418..2c5b6dd | 工具执行器 |
| 4 | ✅ complete | 8ce13e8..b1a60dc | 护栏规则引擎 |
| 5 | ✅ complete | b1a60dc..639cd03 | HITL 审批 FSM |
| 6 | ✅ complete | 639cd03..d1a4081 | 路径围栏 |
| 7 | ✅ complete | d1a4081..6630d76 | 反馈类型 + 分类器 |
| 8 | ✅ complete | 6630d76..7fb1279 | pytest/ruff 解析器 |
| 9 | ✅ complete | 7fb1279..3b7ece3 | 反馈渲染器 |
| 10 | ✅ complete | 3b7ece3..547b5e7 | 记忆持久化 |
| 11 | ✅ complete | 547b5e7..c2746a2 | 配置加载器 |
| 12 | ✅ complete | c2746a2..cfee423 | 凭据存储 + redact |
| 13 | ✅ complete | cfee423..bdced22 | Session 状态枚举 |
| 14 | ✅ complete | bdced22..a12ab66 | 停机判断 |
| 15 | ✅ complete | a12ab66..7054f42 | 上下文构建器 |
| 16 | ✅ complete | 7054f42..829ce0c | Agent 主循环 |
| 17 | ✅ complete | 829ce0c..9ceb014 | 集成测试 |
| 18 | ✅ complete | 9ceb014..16480dd | mkdir 修复 |
| 19 | ✅ complete | 16480dd..2f8f77c | 测试修复 |
| 20 | ✅ complete | 2f8f77c..92d4f79 | FK 修复 |
| 21 | ✅ complete | 92d4f79..2304e5b | 记忆检索 |
| 22 | ✅ complete | 2304e5b..d741486 | 截断修复 |
| 23 | ✅ complete | d741486..b1b4863 | NameError 修复 |
| 24 | ✅ complete | b1b4863..8aaa8e0 | Deny 分支修复 |
| 25 | ✅ complete | 8aaa8e0..7e1707e | 集成反馈测试 |

**Plan 1 总计**：99 tests passed, 1 skipped

### Plan 2: CLI + WebUI（9 tasks）

| Task | 状态 | Commit Range | 说明 |
|------|------|-------------|------|
| 1 | ✅ complete | 18d6502..1bfe628 | AppConfig + 依赖 |
| 2 | ✅ complete | 1bfe628..4109b0b | DB WAL + 查询函数 |
| 3 | ✅ complete | 4109b0b..4c5fc91 | _await_approval 重写 |
| 4 | ✅ complete | 4c5fc91..261e55a | 超时清理线程 |
| 5 | ✅ complete | 261e55a..95c1539 | FastAPI 认证 + Schema |
| 6 | ✅ complete | 95c1539..c17962c | FastAPI 9 端点 |
| 7 | ✅ complete | c17962c..00b21a6 | CLI 入口 |
| 8 | ✅ complete | 00b21a6..07169af | 前端 HTML |
| 9 | ✅ complete | 07169af..f82174a | E2E 审批流测试 |

**Plan 2 总计**：147 tests passed, 1 skipped (48 new)

### Plan 3a: 分发 + CI + Demo

| Task | 状态 | Commit | 说明 |
|------|------|--------|------|
| demo | ✅ complete | (pending) | 三场景机制演示 |
| Dockerfile | ✅ complete | (pending) | 多阶段构建 |
| .gitlab-ci.yml | ✅ complete | (pending) | unit-test + build-image |
| GitHub Actions | ✅ complete | (pending) | 等价 CI |
| README | ✅ complete | (pending) | 11 章节补全 |
| CLI 子命令 | ✅ complete | (pending) | serve/resume/key |
| SPEC_PROCESS.md | ✅ complete | (pending) | 协作过程记录 |
| AGENT_LOG.md | ✅ complete | (pending) | subagent 日志 |

## 依赖关系

```
Plan 1 (核心库) ──→ Plan 2 (CLI + WebUI) ──→ Plan 3a (分发)
                                              ↓
                                         Plan 3b (多会话 + WebSocket) [未开始]
```

## TDD 顺序

每个 task 严格遵循：
1. 写失败测试 → 运行确认 RED
2. 写最少实现 → 运行确认 GREEN
3. 重构（如需要）
4. 全量测试 → commit
