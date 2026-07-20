# ForgeLoop Core Harness Library — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ForgeLoop core harness library — a fully testable Python package where a mock LLM can drive the complete agent loop (parse → govern → execute → feedback → shutdown) with deterministic unit tests and zero real API calls.

**Architecture:** Layered library. Pure-function cores (parser, feedback classifier, path fence, rule engine) have no I/O deps and are tested with fixtures. I/O layers (tools, storage, LLM, credentials) are tested with tmp dirs and mocks. The agent loop orchestrates all layers and is tested end-to-end with MockLLMProvider.

**Tech Stack:** Python 3.12, pytest, httpx, pyyaml, keyring, sqlite3 (stdlib). No agent SDK. No ORM.

**Scope note:** This is Plan 1 of 3. Plan 2 = CLI + WebUI (FastAPI). Plan 3 = Docker + PyPI packaging. This plan produces `forgeloop` as an importable, fully-tested library. No CLI entrypoint, no server — those come in Plan 2.

## Global Constraints

- Python 3.12+ (uses `X | Y` union syntax, `match` statements).
- No agent SDK deps (no LangChain, AutoGen, CrewAI, LlamaIndex). Only底层零件: httpx, pyyaml, keyring, stdlib.
- API key never in source, git, logs, process env of children, or any returned value. Key lives in keyring (or .env fallback with documented risk).
- All file writes fenced to workspace_root; path fence hardcoded, not config-disableable for writes.
- Feedback parsing is deterministic code (no LLM self-check).
- Every mechanism must have a deterministic unit test runnable with mock LLM / no network.
- TDD: write failing test first, then minimal impl, then commit.
- No comments in code unless explicitly requested.
- DRY, YAGNI.

---

## File Structure

```
forgeloop/
  __init__.py
  config/
    __init__.py
    guardrails.default.yaml
    loader.py            # load + id-merge configs
  llm/
    __init__.py
    base.py              # LLMProvider Protocol, Message, LLMConfig, LLMResponse, LLMCallMeta
    mock.py              # MockLLMProvider
    real.py              # RealLLMProvider (httpx, OpenAI-compat)
  credentials/
    __init__.py
    store.py             # keyring wrapper
    redact.py            # log redaction
  parser/
    __init__.py
    types.py             # Action, ParseError
    parse.py             # parse(raw) -> Action | ParseError
  tools/
    __init__.py
    base.py              # Tool protocol, ToolResult, ToolRegistry
    read_file.py
    write_file.py
    run_shell.py
    run_tests.py
    list_dir.py
    done.py
  feedback/
    __init__.py
    types.py             # FeedbackSignal, Failure
    classify_failure.py
    test_parser.py
    lint_parser.py
    renderer.py
    classifier.py
  governance/
    __init__.py
    types.py             # Decision, Rule
    path_fence.py
    rule_engine.py
    approval.py          # ApprovalRequest, ApprovalFSM
  storage/
    __init__.py
    db.py                # connection + schema init
    models.py            # Session/Turn/Action/ApprovalRequest/MemoryEntry + CRUD
    memory.py            # retrieve + write
  agent/
    __init__.py
    session.py           # SessionStatus enum, state machine helpers
    shutdown.py          # breakers + check_shutdown
    context.py           # build_context
    loop.py              # main agent loop
tests/
  conftest.py
  fixtures/pytest_output/{2_failed,all_passed,garbage,collection_error}.txt
  fixtures/ruff_output/basic.txt
  test_*.py              # one per module, named after module
pyproject.toml
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `forgeloop/__init__.py` and all subpackage `__init__.py` files
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: importable `forgeloop` package; pytest configured.

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "forgeloop"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "pyyaml>=6.0",
    "keyring>=24",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5"]

[tool.setuptools.packages.find]
include = ["forgeloop*"]

[tool.setuptools.package-data]
forgeloop = ["config/*.yaml"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

- [ ] **Step 2: Create package init files**

`forgeloop/__init__.py`:
```python
__version__ = "0.1.0"
```

All subpackage `__init__.py` files (`config`, `llm`, `credentials`, `parser`, `tools`, `feedback`, `governance`, `storage`, `agent`) are empty.

- [ ] **Step 3: Write conftest.py and smoke test**

`tests/conftest.py`:
```python
import pytest
from pathlib import Path


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path
```

`tests/test_smoke.py`:
```python
def test_package_imports():
    import forgeloop
    assert forgeloop.__version__ == "0.1.0"
```

- [ ] **Step 4: Install dev deps and run smoke test**

Run: `python -m pip install -e ".[dev]"; python -m pytest tests/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml forgeloop/ tests/conftest.py tests/test_smoke.py
git commit -m "chore: project scaffolding for forgeloop core library"
```

---

## Task 2: LLM Abstraction Layer

**Files:**
- Create: `forgeloop/llm/base.py`
- Create: `forgeloop/llm/mock.py`
- Create: `forgeloop/llm/real.py`
- Test: `tests/test_llm_mock.py`, `tests/test_llm_real.py`

**Interfaces:**
- Produces: `LLMProvider` Protocol, `Message`, `LLMConfig`, `LLMResponse`, `LLMCallMeta` in `base.py`; `MockLLMProvider` in `mock.py`; `RealLLMProvider` in `real.py`.

- [ ] **Step 1: Write failing test for MockLLMProvider**

`tests/test_llm_mock.py`:
```python
from forgeloop.llm.base import Message, LLMConfig
from forgeloop.llm.mock import MockLLMProvider


def test_mock_returns_sequence():
    provider = MockLLMProvider(responses=['{"thought":"x","tool":"done","args":{}}'])
    resp = provider.complete([Message(role="user", content="hi")], LLMConfig(model="mock"))
    assert resp.content == '{"thought":"x","tool":"done","args":{}}'
    assert resp.meta.model == "mock"


def test_mock_callable_branching():
    def gen(messages, config):
        return f"echo:{messages[-1].content}"
    provider = MockLLMProvider(responses=gen)
    resp = provider.complete([Message(role="user", content="ping")], LLMConfig(model="mock"))
    assert resp.content == "echo:ping"


def test_mock_exhausts_sequence_raises():
    import pytest
    provider = MockLLMProvider(responses=["only-one"])
    provider.complete([Message(role="user", content="x")], LLMConfig(model="mock"))
    with pytest.raises(StopIteration):
        provider.complete([Message(role="user", content="x")], LLMConfig(model="mock"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_mock.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write base.py and mock.py**

`forgeloop/llm/base.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.0
    base_url: str | None = None


@dataclass
class LLMCallMeta:
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class LLMResponse:
    content: str
    meta: LLMCallMeta


class LLMProvider(Protocol):
    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse: ...
```

`forgeloop/llm/mock.py`:
```python
from __future__ import annotations
from time import perf_counter_ns
from forgeloop.llm.base import Message, LLMConfig, LLMResponse, LLMCallMeta


class MockLLMProvider:
    def __init__(self, responses):
        if callable(responses):
            self._gen = responses
            self._seq = None
        else:
            self._gen = None
            self._seq = iter(responses)

    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        start = perf_counter_ns()
        if self._gen is not None:
            content = self._gen(messages, config)
        else:
            content = next(self._seq)
        latency = (perf_counter_ns() - start) // 1_000_000
        return LLMResponse(
            content=content,
            meta=LLMCallMeta(model=config.model, prompt_tokens=0, completion_tokens=0, latency_ms=latency),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_mock.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write failing test for RealLLMProvider (monkeypatch httpx + get_key)**

`tests/test_llm_real.py`:
```python
import pytest
from unittest.mock import MagicMock
from forgeloop.llm.base import Message, LLMConfig
from forgeloop.llm.real import RealLLMProvider


def test_real_uses_key_from_get_key(monkeypatch):
    monkeypatch.setattr("forgeloop.llm.real.get_key", lambda p: "sk-test-key")
    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        def raise_for_status(self):
            pass

    def fake_post(url, headers, json):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        captured["body"] = json
        return FakeResp()

    fake_client = MagicMock()
    fake_client.post = fake_post
    fake_client.__enter__ = lambda self: self
    fake_client.__exit__ = lambda self, *a: None
    monkeypatch.setattr("forgeloop.llm.real.httpx.Client", lambda **kw: fake_client)

    provider = RealLLMProvider()
    resp = provider.complete([Message(role="user", content="hi")], LLMConfig(model="gpt-4o"))
    assert resp.content == "hello"
    assert resp.meta.prompt_tokens == 5
    assert captured["auth"] == "Bearer sk-test-key"
    assert "api_key" not in str(captured["body"])


def test_real_raises_when_no_key(monkeypatch):
    monkeypatch.setattr("forgeloop.llm.real.get_key", lambda p: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = RealLLMProvider()
    with pytest.raises(RuntimeError, match="no api key"):
        provider.complete([Message(role="user", content="x")], LLMConfig(model="gpt-4o"))
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_real.py -v`
Expected: FAIL (module not found).

- [ ] **Step 7: Write real.py**

`forgeloop/llm/real.py`:
```python
from __future__ import annotations
import os
import time
import httpx
from forgeloop.llm.base import Message, LLMConfig, LLMResponse, LLMCallMeta
from forgeloop.credentials.store import get_key


class RealLLMProvider:
    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        api_key = get_key("openai") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("no api key configured: run `forgeloop credentials set` (Plan 2) or set OPENAI_API_KEY")
        base_url = config.base_url or "https://api.openai.com/v1"
        body = {
            "model": config.model,
            "temperature": config.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        start = time.perf_counter()
        with httpx.Client(timeout=120) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        latency = int((time.perf_counter() - start) * 1000)
        r.raise_for_status()
        data = r.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            meta=LLMCallMeta(
                model=config.model,
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                latency_ms=latency,
            ),
        )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_real.py -v`
Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add forgeloop/llm/ tests/test_llm_mock.py tests/test_llm_real.py
git commit -m "feat(llm): abstraction layer with mock and real OpenAI-compatible providers"
```

---

## Task 3: Credential Store + Log Redaction

**Files:**
- Create: `forgeloop/credentials/store.py`
- Create: `forgeloop/credentials/redact.py`
- Test: `tests/test_credentials_store.py`, `tests/test_credentials_redact.py`

**Interfaces:**
- Produces: `get_key(provider)`, `set_key(provider, key)`, `status(provider)`, `update_key(provider, key)`, `clear_key(provider)` in `store.py`; `redact(text)` in `redact.py`.

- [ ] **Step 1: Write failing test for store (monkeypatch keyring)**

`tests/test_credentials_store.py`:
```python
def test_set_get_roundtrip(monkeypatch):
    store = {}
    monkeypatch.setattr("forgeloop.credentials.store.keyring.set_password", lambda s, u, k: store.__setitem__(u, k))
    monkeypatch.setattr("forgeloop.credentials.store.keyring.get_password", lambda s, u: store.get(u))
    from forgeloop.credentials.store import set_key, get_key
    set_key("openai", "sk-abc123")
    assert get_key("openai") == "sk-abc123"


def test_status_masks_key(monkeypatch):
    store = {"openai_api_key": "sk-abcdefgh1234"}
    monkeypatch.setattr("forgeloop.credentials.store.keyring.get_password", lambda s, u: store.get(u))
    from forgeloop.credentials.store import status
    s = status("openai")
    assert s == {"configured": True, "last_four": "1234"}
    assert "abcdefgh" not in str(s)


def test_status_not_configured(monkeypatch):
    monkeypatch.setattr("forgeloop.credentials.store.keyring.get_password", lambda s, u: None)
    from forgeloop.credentials.store import status
    assert status("openai") == {"configured": False, "last_four": None}


def test_clear_key(monkeypatch):
    store = {"openai_api_key": "sk-x"}
    monkeypatch.setattr("forgeloop.credentials.store.keyring.delete_password", lambda s, u: store.pop(u, None))
    from forgeloop.credentials.store import clear_key, get_key
    monkeypatch.setattr("forgeloop.credentials.store.keyring.get_password", lambda s, u: store.get(u))
    clear_key("openai")
    assert get_key("openai") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_credentials_store.py -v`
Expected: FAIL.

- [ ] **Step 3: Write store.py**

`forgeloop/credentials/store.py`:
```python
from __future__ import annotations
import keyring

SERVICE = "forgeloop"


def _user(provider: str) -> str:
    return f"{provider}_api_key"


def set_key(provider: str, key: str) -> None:
    keyring.set_password(SERVICE, _user(provider), key)


def get_key(provider: str) -> str | None:
    return keyring.get_password(SERVICE, _user(provider))


def update_key(provider: str, key: str) -> None:
    set_key(provider, key)


def status(provider: str) -> dict:
    k = get_key(provider)
    if not k:
        return {"configured": False, "last_four": None}
    return {"configured": True, "last_four": k[-4:]}


def clear_key(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE, _user(provider))
    except keyring.errors.PasswordDeleteError:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_credentials_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write failing test for redact**

`tests/test_credentials_redact.py`:
```python
from forgeloop.credentials.redact import redact


def test_redact_sk_key():
    assert redact("calling with sk-abc123XYZ") == "calling with sk-****"


def test_redact_no_key_passthrough():
    assert redact("plain log line") == "plain log line"


def test_redact_multiple_keys():
    assert redact("a=sk-aaa111 b=sk-bbb222") == "a=sk-**** b=sk-****"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_credentials_redact.py -v`
Expected: FAIL.

- [ ] **Step 7: Write redact.py**

`forgeloop/credentials/redact.py`:
```python
from __future__ import annotations
import re

_KEY_RE = re.compile(r"sk-[A-Za-z0-9]+")


def redact(text: str) -> str:
    return _KEY_RE.sub("sk-****", text)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_credentials_redact.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add forgeloop/credentials/ tests/test_credentials_store.py tests/test_credentials_redact.py
git commit -m "feat(credentials): keyring store with masked status + log redaction"
```

---

## Task 4: Config Loader + Default Guardrails YAML

**Files:**
- Create: `forgeloop/config/guardrails.default.yaml`
- Create: `forgeloop/config/loader.py`
- Test: `tests/test_config_loader.py`

**Interfaces:**
- Produces: `load_config(overrides: list[Path] | None = None) -> GuardrailsConfig` in `loader.py`; `GuardrailsConfig` dataclass with `.rules`, `.default_decision`, `.hitl`, `.done_post_check`, `.workspace_root`, `.path_fencing`.

- [ ] **Step 1: Write default YAML**

`forgeloop/config/guardrails.default.yaml`:
```yaml
workspace_root: "."
path_fencing:
  writes: true
  reads: true
  read_allowlist: ["/tmp/", "~/.config/forgeloop/"]

default_decision: RequireApproval
hitl:
  approval_timeout_seconds: 86400
  auto_approve_on_timeout: false
done_post_check:
  require_green_tests: false

rules:
  - id: deny_rm_rf_root
    tool: [run_shell]
    match: {command_regex: 'rm\s+(-[a-z]*f[a-z]*\s+)?-?r?f?\s+/(?!tmp\b)'}
    decision: Deny
    reason: "destructive rm -rf on root"
  - id: deny_curl_pipe_sh
    tool: [run_shell]
    match: {command_regex: 'curl\s+.*\|\s*(sh|bash)'}
    decision: Deny
    reason: "remote code execution"
  - id: deny_sudo
    tool: [run_shell]
    match: {command_regex: '^\s*sudo\b'}
    decision: Deny
  - id: deny_write_git_dir
    tool: [write_file]
    match: {path_regex: '(\.git/|\.git\\)'}
    decision: Deny
    reason: "writing into .git is forbidden"
  - id: allow_git_readonly
    tool: [run_shell]
    match: {command_regex: '^git\s+(status|diff|log|show|ls-files)\b'}
    decision: Allow
  - id: approve_all_writes
    tool: [write_file]
    match: {any: true}
    decision: RequireApproval
    reason: "file write requires approval"
  - id: approve_shell_default
    tool: [run_shell]
    match: {any: true}
    decision: RequireApproval
  - id: allow_reads
    tool: [read_file, list_dir]
    match: {any: true}
    decision: Allow
  - id: allow_tests
    tool: [run_tests]
    match: {any: true}
    decision: Allow
  - id: allow_done
    tool: [done]
    match: {any: true}
    decision: Allow
```

- [ ] **Step 2: Write failing test**

`tests/test_config_loader.py`:
```python
from pathlib import Path
from forgeloop.config.loader import load_config


def test_load_default_has_rules():
    cfg = load_config([])
    assert cfg.default_decision == "RequireApproval"
    ids = [r["id"] for r in cfg.rules]
    assert "deny_rm_rf_root" in ids
    assert "allow_done" in ids
    assert cfg.path_fencing["writes"] is True


def test_override_replaces_by_id(tmp_path: Path):
    override = tmp_path / "override.yaml"
    override.write_text(
        "rules:\n  - id: deny_sudo\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n",
        encoding="utf-8",
    )
    cfg = load_config([override])
    sudo_rule = next(r for r in cfg.rules if r["id"] == "deny_sudo")
    assert sudo_rule["decision"] == "Allow"


def test_override_appends_new_id(tmp_path: Path):
    override = tmp_path / "add.yaml"
    override.write_text(
        "rules:\n  - id: my_custom_rule\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n",
        encoding="utf-8",
    )
    cfg = load_config([override])
    assert any(r["id"] == "my_custom_rule" for r in cfg.rules)


def test_writes_fencing_forced_true(tmp_path: Path):
    override = tmp_path / "bad.yaml"
    override.write_text("path_fencing: {writes: false}\n", encoding="utf-8")
    cfg = load_config([override])
    assert cfg.path_fencing["writes"] is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_config_loader.py -v`
Expected: FAIL.

- [ ] **Step 4: Write loader.py**

`forgeloop/config/loader.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from importlib import resources


@dataclass
class GuardrailsConfig:
    workspace_root: str = "."
    path_fencing: dict = field(default_factory=dict)
    default_decision: str = "RequireApproval"
    hitl: dict = field(default_factory=dict)
    done_post_check: dict = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_default() -> dict:
    with resources.files("forgeloop.config").joinpath("guardrails.default.yaml").open("r") as f:
        return yaml.safe_load(f) or {}


def _merge_rules(default_rules: list[dict], override_rules: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in default_rules}
    for r in override_rules:
        by_id[r["id"]] = r
    return list(by_id.values())


def load_config(overrides: list[Path] | None = None) -> GuardrailsConfig:
    data = _load_default()
    for ov in overrides or []:
        ov_data = _load_yaml(ov)
        if "rules" in ov_data:
            data["rules"] = _merge_rules(data.get("rules", []), ov_data.pop("rules"))
        for k, v in ov_data.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k] = {**data[k], **v}
            else:
                data[k] = v
    data.setdefault("path_fencing", {})
    data["path_fencing"]["writes"] = True
    return GuardrailsConfig(
        workspace_root=data.get("workspace_root", "."),
        path_fencing=data["path_fencing"],
        default_decision=data.get("default_decision", "RequireApproval"),
        hitl=data.get("hitl", {"approval_timeout_seconds": 86400, "auto_approve_on_timeout": False}),
        done_post_check=data.get("done_post_check", {"require_green_tests": False}),
        rules=data.get("rules", []),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_config_loader.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add forgeloop/config/ tests/test_config_loader.py
git commit -m "feat(config): default guardrails YAML + id-merge loader"
```

---

## Task 5: Action Parser

**Files:**
- Create: `forgeloop/parser/types.py`
- Create: `forgeloop/parser/parse.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `Action(thought, tool, args)`, `ParseError(code, message)`, `parse(raw_text) -> Action | ParseError`. Allowed tools: `{read_file, write_file, run_shell, run_tests, list_dir, done}`.

- [ ] **Step 1: Write failing test**

`tests/test_parser.py`:
```python
from forgeloop.parser.parse import parse, Action, ParseError


def test_parse_strict_json():
    a = parse('{"thought":"x","tool":"read_file","args":{"path":"a.py"}}')
    assert isinstance(a, Action)
    assert a.tool == "read_file"
    assert a.args == {"path": "a.py"}


def test_parse_fenced_json():
    raw = 'Here is my action:\n```json\n{"thought":"x","tool":"done","args":{}}\n```\n'
    a = parse(raw)
    assert isinstance(a, Action)
    assert a.tool == "done"


def test_parse_brace_match():
    raw = 'prose {"thought":"x","tool":"list_dir","args":{"path":"."}} trailing'
    a = parse(raw)
    assert isinstance(a, Action)
    assert a.tool == "list_dir"


def test_parse_unknown_tool():
    a = parse('{"thought":"x","tool":"bogus","args":{}}')
    assert isinstance(a, ParseError)
    assert a.code == "tool_not_found"


def test_parse_missing_thought():
    a = parse('{"tool":"done","args":{}}')
    assert isinstance(a, ParseError)
    assert a.code == "missing_field"


def test_parse_unparseable():
    a = parse("totally not json at all")
    assert isinstance(a, ParseError)
    assert a.code == "unparseable"


def test_parse_multiple_actions_takes_first():
    raw = '{"thought":"a","tool":"done","args":{}}\n{"thought":"b","tool":"done","args":{}}'
    a = parse(raw)
    assert isinstance(a, Action)
    assert a.thought == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_parser.py -v`
Expected: FAIL.

- [ ] **Step 3: Write types.py and parse.py**

`forgeloop/parser/types.py`:
```python
from __future__ import annotations
from dataclasses import dataclass

ALLOWED_TOOLS = {"read_file", "write_file", "run_shell", "run_tests", "list_dir", "done"}


@dataclass
class Action:
    thought: str
    tool: str
    args: dict


@dataclass
class ParseError:
    code: str
    message: str
```

`forgeloop/parser/parse.py`:
```python
from __future__ import annotations
import json
import re
from forgeloop.parser.types import Action, ParseError, ALLOWED_TOOLS

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_candidates(raw: str) -> list[str]:
    candidates = [raw]
    m = _FENCE_RE.search(raw)
    if m:
        candidates.append(m.group(1))
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start:i + 1])
                    break
    return candidates


def _validate(obj) -> Action | ParseError:
    if not isinstance(obj, dict):
        return ParseError("unparseable", "not a json object")
    thought = obj.get("thought")
    tool = obj.get("tool")
    args = obj.get("args")
    if not thought or not isinstance(thought, str):
        return ParseError("missing_field", "thought missing or non-string")
    if not tool or not isinstance(tool, str):
        return ParseError("missing_field", "tool missing or non-string")
    if tool not in ALLOWED_TOOLS:
        return ParseError("tool_not_found", f"tool {tool!r} not in {sorted(ALLOWED_TOOLS)}")
    if not isinstance(args, dict):
        return ParseError("missing_field", "args missing or non-object")
    return Action(thought=thought, tool=tool, args=args)


def parse(raw: str) -> Action | ParseError:
    for cand in _extract_candidates(raw):
        cand = cand.strip()
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        return _validate(obj)
    return ParseError("unparseable", "no valid json object found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_parser.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/parser/ tests/test_parser.py
git commit -m "feat(parser): three-level action parser with schema validation"
```

---

## Task 6: Storage — SQLite Schema + Connection

**Files:**
- Create: `forgeloop/storage/db.py`
- Test: `tests/test_storage_db.py`

**Interfaces:**
- Produces: `connect(db_path: Path) -> sqlite3.Connection`, `init_schema(conn)` in `db.py`.

- [ ] **Step 1: Write failing test**

`tests/test_storage_db.py`:
```python
from pathlib import Path
from forgeloop.storage.db import connect, init_schema


def test_init_schema_creates_tables(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert {"sessions", "turns", "actions", "approval_requests", "memory"} <= names
    conn.close()


def test_init_schema_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    init_schema(conn)
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_db.py -v`
Expected: FAIL.

- [ ] **Step 3: Write db.py**

`forgeloop/storage/db.py`:
```python
from __future__ import annotations
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    config_path TEXT,
    status TEXT NOT NULL,
    round_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_identical INTEGER NOT NULL DEFAULT 0,
    last_action_hash TEXT,
    last_test_state TEXT,
    llm_config TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    llm_raw_output TEXT,
    parsed_action_id TEXT,
    parse_attempts INTEGER NOT NULL DEFAULT 0,
    parse_status TEXT,
    llm_call_meta TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_id TEXT NOT NULL REFERENCES turns(id),
    tool TEXT NOT NULL,
    args TEXT,
    thought TEXT,
    args_hash TEXT,
    status TEXT NOT NULL,
    guardrail_decision TEXT,
    result TEXT,
    feedback_signal TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    deny_reason TEXT
);

CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    workspace_root TEXT NOT NULL,
    kind TEXT NOT NULL,
    tags TEXT,
    key TEXT,
    content TEXT NOT NULL,
    source_turn_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_db.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/storage/db.py tests/test_storage_db.py
git commit -m "feat(storage): sqlite schema for sessions/turns/actions/approvals/memory"
```

---

## Task 7: Storage Models + CRUD

**Files:**
- Create: `forgeloop/storage/models.py`
- Test: `tests/test_storage_models.py`

**Interfaces:**
- Produces: `Session`, `Turn`, `Action`, `ApprovalRequest` dataclasses; `create_session`, `get_session`, `update_session_status`, `create_turn`, `create_action`, `update_action`, `create_approval_request`, `update_approval_request`, `list_pending_approvals`.

- [ ] **Step 1: Write failing test**

`tests/test_storage_models.py`:
```python
from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import (
    Session, Turn, Action, ApprovalRequest,
    create_session, get_session, update_session_status,
    create_turn, create_action, update_action,
    create_approval_request, update_approval_request, list_pending_approvals,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_session_roundtrip(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    s = Session(id="s1", task="do thing", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now(), llm_config='{"model":"gpt-4o"}')
    create_session(conn, s)
    got = get_session(conn, "s1")
    assert got.status == "RUNNING"
    assert got.llm_config == '{"model":"gpt-4o"}'
    assert "api_key" not in got.llm_config
    conn.close()


def test_update_session_status(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    s = Session(id="s2", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now())
    create_session(conn, s)
    update_session_status(conn, "s2", "COMPLETED", round_count=5)
    assert get_session(conn, "s2").status == "COMPLETED"
    assert get_session(conn, "s2").round_count == 5
    conn.close()


def test_action_and_approval(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    now = _now()
    create_session(conn, Session(id="s3", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=now, updated_at=now))
    create_turn(conn, Turn(id="t1", session_id="s3", turn_index=0, parse_status="OK", started_at=now, finished_at=now))
    create_action(conn, Action(id="a1", session_id="s3", turn_id="t1", tool="run_shell", args='{"command":"ls"}', thought="x", args_hash="h1", status="PENDING_APPROVAL", created_at=now))
    create_approval_request(conn, ApprovalRequest(id="ap1", action_id="a1", session_id="s3", status="PENDING", requested_at=now))
    pending = list_pending_approvals(conn)
    assert len(pending) == 1
    assert pending[0].action_id == "a1"
    update_approval_request(conn, "ap1", status="APPROVED", decided_at=now, decided_by="webui")
    assert len(list_pending_approvals(conn)) == 0
    update_action(conn, "a1", status="SUCCEEDED", result='{"ok":true}')
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Write models.py**

`forgeloop/storage/models.py`:
```python
from __future__ import annotations
import sqlite3
from dataclasses import dataclass


@dataclass
class Session:
    id: str
    task: str
    workspace_root: str
    status: str
    created_at: str
    updated_at: str
    config_path: str | None = None
    round_count: int = 0
    consecutive_failures: int = 0
    consecutive_identical: int = 0
    last_action_hash: str | None = None
    last_test_state: str | None = None
    llm_config: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class Turn:
    id: str
    session_id: str
    turn_index: int
    started_at: str
    parse_status: str = "OK"
    finished_at: str | None = None
    llm_raw_output: str | None = None
    parsed_action_id: str | None = None
    parse_attempts: int = 0
    llm_call_meta: str | None = None


@dataclass
class Action:
    id: str
    session_id: str
    turn_id: str
    tool: str
    thought: str
    args_hash: str
    status: str
    created_at: str
    args: str | None = None
    guardrail_decision: str | None = None
    result: str | None = None
    feedback_signal: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class ApprovalRequest:
    id: str
    action_id: str
    session_id: str
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    deny_reason: str | None = None


def _row_to(cls, row: sqlite3.Row):
    cols = [d[0] for d in row.cursor.description]
    return cls(**{c: row[c] for c in cols if c in cls.__dataclass_fields__})


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def create_session(conn: sqlite3.Connection, s: Session) -> None:
    conn.execute(
        "INSERT INTO sessions (id,task,workspace_root,config_path,status,round_count,consecutive_failures,consecutive_identical,last_action_hash,last_test_state,llm_config,created_at,started_at,finished_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.id, s.task, s.workspace_root, s.config_path, s.status, s.round_count, s.consecutive_failures, s.consecutive_identical, s.last_action_hash, s.last_test_state, s.llm_config, s.created_at, s.started_at, s.finished_at, s.updated_at),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, sid: str) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    return _row_to(Session, row) if row else None


def update_session_status(conn: sqlite3.Connection, sid: str, status: str, **fields) -> None:
    sets = ["status=?", "updated_at=?"]
    vals = [status, fields.get("updated_at") or _now()]
    for k, v in fields.items():
        if k in Session.__dataclass_fields__ and k not in ("status", "updated_at"):
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(sid)
    conn.execute(f"UPDATE sessions SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def create_turn(conn: sqlite3.Connection, t: Turn) -> None:
    conn.execute(
        "INSERT INTO turns (id,session_id,turn_index,llm_raw_output,parsed_action_id,parse_attempts,parse_status,llm_call_meta,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (t.id, t.session_id, t.turn_index, t.llm_raw_output, t.parsed_action_id, t.parse_attempts, t.parse_status, t.llm_call_meta, t.started_at, t.finished_at),
    )
    conn.commit()


def create_action(conn: sqlite3.Connection, a: Action) -> None:
    conn.execute(
        "INSERT INTO actions (id,session_id,turn_id,tool,args,thought,args_hash,status,guardrail_decision,result,feedback_signal,created_at,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a.id, a.session_id, a.turn_id, a.tool, a.args, a.thought, a.args_hash, a.status, a.guardrail_decision, a.result, a.feedback_signal, a.created_at, a.started_at, a.finished_at),
    )
    conn.commit()


def update_action(conn: sqlite3.Connection, aid: str, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k in Action.__dataclass_fields__:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(aid)
    conn.execute(f"UPDATE actions SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def create_approval_request(conn: sqlite3.Connection, ar: ApprovalRequest) -> None:
    conn.execute(
        "INSERT INTO approval_requests (id,action_id,session_id,status,requested_at,decided_at,decided_by,deny_reason) VALUES (?,?,?,?,?,?,?,?)",
        (ar.id, ar.action_id, ar.session_id, ar.status, ar.requested_at, ar.decided_at, ar.decided_by, ar.deny_reason),
    )
    conn.commit()


def update_approval_request(conn: sqlite3.Connection, arid: str, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k in ApprovalRequest.__dataclass_fields__:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(arid)
    conn.execute(f"UPDATE approval_requests SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def list_pending_approvals(conn: sqlite3.Connection) -> list[ApprovalRequest]:
    rows = conn.execute("SELECT * FROM approval_requests WHERE status='PENDING'").fetchall()
    return [_row_to(ApprovalRequest, r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_models.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/storage/models.py tests/test_storage_models.py
git commit -m "feat(storage): CRUD for sessions/turns/actions/approvals"
```

---

## Task 8: Tool Infrastructure — ToolResult + ToolRegistry

**Files:**
- Create: `forgeloop/tools/base.py`
- Test: `tests/test_tools_base.py`

**Interfaces:**
- Produces: `ToolResult(ok, result, error, truncated)`, `Tool` Protocol (`name`, `execute(args, ctx) -> ToolResult`), `ToolRegistry` with `register(tool)` and `dispatch(action, ctx) -> ToolResult`.

- [ ] **Step 1: Write failing test**

`tests/test_tools_base.py`:
```python
from forgeloop.tools.base import ToolResult, ToolRegistry
from forgeloop.parser.types import Action


class EchoTool:
    name = "echo"
    def execute(self, args, ctx):
        return ToolResult(ok=True, result={"echoed": args.get("msg")}, error=None, truncated=False)


def test_registry_dispatch():
    reg = ToolRegistry()
    reg.register(EchoTool())
    a = Action(thought="x", tool="echo", args={"msg": "hi"})
    r = reg.dispatch(a, ctx={})
    assert r.ok is True
    assert r.result == {"echoed": "hi"}


def test_registry_unknown_tool():
    reg = ToolRegistry()
    a = Action(thought="x", tool="nope", args={})
    r = reg.dispatch(a, ctx={})
    assert r.ok is False
    assert r.error["code"] == "unknown_tool"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_base.py -v`
Expected: FAIL.

- [ ] **Step 3: Write base.py**

`forgeloop/tools/base.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from forgeloop.parser.types import Action


@dataclass
class ToolResult:
    ok: bool
    result: dict | None
    error: dict | None
    truncated: bool = False


class Tool(Protocol):
    name: str
    def execute(self, args: dict, ctx: dict) -> ToolResult: ...


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def dispatch(self, action: Action, ctx: dict) -> ToolResult:
        tool = self._tools.get(action.tool)
        if tool is None:
            return ToolResult(ok=False, result=None, error={"code": "unknown_tool", "message": f"no tool named {action.tool!r}"}, truncated=False)
        return tool.execute(action.args, ctx)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_base.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/base.py tests/test_tools_base.py
git commit -m "feat(tools): ToolResult envelope + ToolRegistry"
```

---

## Task 9: Tool — read_file + path_fence foundation

**Files:**
- Create: `forgeloop/governance/path_fence.py`
- Create: `forgeloop/tools/read_file.py`
- Test: `tests/test_tools_read_file.py`

**Interfaces:**
- Produces: `fence_path(path, workspace_root, mode, read_allowlist) -> FenceResult` in `path_fence.py`; `ReadFileTool` with `name="read_file"`.

- [ ] **Step 1: Write failing test**

`tests/test_tools_read_file.py`:
```python
from forgeloop.tools.read_file import ReadFileTool


def test_read_existing(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "src/main.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "print('hi')" in r.result["content"]


def test_read_missing(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "nope.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "file_not_found"


def test_read_outside_workspace(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "../etc/passwd"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_read_file.py -v`
Expected: FAIL.

- [ ] **Step 3: Write path_fence.py and read_file.py**

`forgeloop/governance/path_fence.py`:
```python
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class FenceResult:
    allowed: bool
    resolved: str
    reason: str = ""


def _resolve(path: str, workspace_root: str) -> str:
    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(workspace_root, path))


def _is_within(resolved: str, workspace_root: str) -> bool:
    ws_real = os.path.realpath(workspace_root)
    try:
        return os.path.commonpath([resolved, ws_real]) == ws_real
    except ValueError:
        return False


def fence_path(path: str, workspace_root: str, mode: str, read_allowlist: list[str] | None = None) -> FenceResult:
    resolved = _resolve(path, workspace_root)
    if mode == "write":
        if not _is_within(resolved, workspace_root):
            return FenceResult(allowed=False, resolved=resolved, reason=f"path {path} outside workspace")
        return FenceResult(allowed=True, resolved=resolved)
    if mode == "read":
        if _is_within(resolved, workspace_root):
            return FenceResult(allowed=True, resolved=resolved)
        for allowed in read_allowlist or []:
            allowed_exp = os.path.realpath(os.path.expanduser(allowed))
            try:
                if os.path.commonpath([resolved, allowed_exp]) == allowed_exp:
                    return FenceResult(allowed=True, resolved=resolved)
            except ValueError:
                continue
        return FenceResult(allowed=False, resolved=resolved, reason=f"path {path} outside workspace and not in allowlist")
    return FenceResult(allowed=False, resolved=resolved, reason=f"unknown mode {mode}")
```

`forgeloop/tools/read_file.py`:
```python
from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path


class ReadFileTool:
    name = "read_file"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", "")
        offset = args.get("offset", 0)
        limit = args.get("limit", 2000)
        fence = fence_path(path, ws, mode="read", read_allowlist=ctx.get("read_allowlist", []))
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        if not os.path.isfile(full):
            return ToolResult(ok=False, result=None, error={"code": "file_not_found", "message": f"{path} not found"}, truncated=False)
        try:
            with open(full, "rb") as f:
                data = f.read()
            if b"\x00" in data:
                return ToolResult(ok=False, result=None, error={"code": "binary_file", "message": "binary content"}, truncated=False)
            text = data.decode("utf-8", errors="replace")
        except OSError as e:
            return ToolResult(ok=False, result=None, error={"code": "read_error", "message": str(e)}, truncated=False)
        lines = text.splitlines()
        sel = lines[offset:offset + limit]
        content = "\n".join(sel)
        truncated = len(lines) > offset + limit
        return ToolResult(ok=True, result={"path": path, "content": content, "lines": len(sel), "truncated": truncated}, error=None, truncated=truncated)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_read_file.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/governance/path_fence.py forgeloop/tools/read_file.py tests/test_tools_read_file.py
git commit -m "feat(tools): read_file tool + path fence foundation"
```

---

## Task 10: Tool — write_file (overwrite + edit)

**Files:**
- Create: `forgeloop/tools/write_file.py`
- Test: `tests/test_tools_write_file.py`

- [ ] **Step 1: Write failing test**

`tests/test_tools_write_file.py`:
```python
from forgeloop.tools.write_file import WriteFileTool


def test_overwrite_new(tmp_workspace):
    t = WriteFileTool()
    r = t.execute({"path": "src/new.py", "mode": "overwrite", "content": "x = 1\n"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert (tmp_workspace / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


def test_edit_unique_match(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "return 1", "new_string": "return 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "return 2" in (tmp_workspace / "src" / "main.py").read_text(encoding="utf-8")


def test_edit_ambiguous(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "x = 1", "new_string": "x = 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "old_string_ambiguous"


def test_edit_not_found(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "nope", "new_string": "x = 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "old_string_not_found"


def test_write_outside_workspace(tmp_workspace):
    import os
    t = WriteFileTool()
    r = t.execute({"path": "../evil.py", "mode": "overwrite", "content": "x"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"
    assert not os.path.exists(os.path.join(os.path.dirname(str(tmp_workspace)), "evil.py"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_write_file.py -v`
Expected: FAIL.

- [ ] **Step 3: Write write_file.py**

`forgeloop/tools/write_file.py`:
```python
from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path


class WriteFileTool:
    name = "write_file"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", "")
        mode = args.get("mode", "overwrite")
        fence = fence_path(path, ws, mode="write")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        try:
            if mode == "overwrite":
                content = args.get("content", "")
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(content)
                return ToolResult(ok=True, result={"path": path, "bytes_written": len(content.encode("utf-8")), "mode": "overwrite"}, error=None, truncated=False)
            if mode == "edit":
                old = args.get("old_string")
                new = args.get("new_string")
                if old is None or new is None:
                    return ToolResult(ok=False, result=None, error={"code": "missing_field", "message": "edit requires old_string and new_string"}, truncated=False)
                if not os.path.isfile(full):
                    return ToolResult(ok=False, result=None, error={"code": "file_not_found", "message": f"{path} not found"}, truncated=False)
                with open(full, "r", encoding="utf-8") as f:
                    text = f.read()
                count = text.count(old)
                if count == 0:
                    return ToolResult(ok=False, result=None, error={"code": "old_string_not_found", "message": "old_string not in file"}, truncated=False)
                if count > 1:
                    return ToolResult(ok=False, result=None, error={"code": "old_string_ambiguous", "message": f"old_string matches {count} times"}, truncated=False)
                new_text = text.replace(old, new, 1)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(new_text)
                return ToolResult(ok=True, result={"path": path, "bytes_written": len(new_text.encode("utf-8")), "mode": "edit"}, error=None, truncated=False)
            return ToolResult(ok=False, result=None, error={"code": "bad_mode", "message": f"unknown mode {mode!r}"}, truncated=False)
        except OSError as e:
            return ToolResult(ok=False, result=None, error={"code": "write_error", "message": str(e)}, truncated=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_write_file.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/write_file.py tests/test_tools_write_file.py
git commit -m "feat(tools): write_file with overwrite + edit modes"
```

---

## Task 11: Tool — list_dir

**Files:**
- Create: `forgeloop/tools/list_dir.py`
- Test: `tests/test_tools_list_dir.py`

- [ ] **Step 1: Write failing test**

`tests/test_tools_list_dir.py`:
```python
from forgeloop.tools.list_dir import ListDirTool


def test_list_flat(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": "src"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    names = [e["name"] for e in r.result["entries"]]
    assert "main.py" in names


def test_list_outside(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": ".."}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"


def test_list_not_a_dir(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": "src/main.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "not_a_dir"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_list_dir.py -v`
Expected: FAIL.

- [ ] **Step 3: Write list_dir.py**

`forgeloop/tools/list_dir.py`:
```python
from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_ENTRIES = 500


class ListDirTool:
    name = "list_dir"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", ".")
        recursive = args.get("recursive", False)
        fence = fence_path(path, ws, mode="read", read_allowlist=ctx.get("read_allowlist", []))
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        if not os.path.exists(full):
            return ToolResult(ok=False, result=None, error={"code": "not_found", "message": f"{path} not found"}, truncated=False)
        if not os.path.isdir(full):
            return ToolResult(ok=False, result=None, error={"code": "not_a_dir", "message": f"{path} not a dir"}, truncated=False)
        entries = []
        truncated = False
        if recursive:
            for root, dirs, files in os.walk(full):
                for name in sorted(dirs + files):
                    p = os.path.join(root, name)
                    entries.append({"name": os.path.relpath(p, full), "type": "dir" if os.path.isdir(p) else "file", "size": os.path.getsize(p) if os.path.isfile(p) else 0})
                    if len(entries) >= MAX_ENTRIES:
                        truncated = True
                        break
                if truncated:
                    break
        else:
            for name in sorted(os.listdir(full)):
                p = os.path.join(full, name)
                entries.append({"name": name, "type": "dir" if os.path.isdir(p) else "file", "size": os.path.getsize(p) if os.path.isfile(p) else 0})
                if len(entries) >= MAX_ENTRIES:
                    truncated = True
                    break
        return ToolResult(ok=True, result={"path": path, "entries": entries, "truncated": truncated}, error=None, truncated=truncated)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_list_dir.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/list_dir.py tests/test_tools_list_dir.py
git commit -m "feat(tools): list_dir with recursive option"
```

---

## Task 12: Tool — run_shell (env filtering + timeout)

**Files:**
- Create: `forgeloop/tools/run_shell.py`
- Test: `tests/test_tools_run_shell.py`

- [ ] **Step 1: Write failing test**

`tests/test_tools_run_shell.py`:
```python
from forgeloop.tools.run_shell import RunShellTool


def test_echo(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "echo hi"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert r.result["exit_code"] == 0
    assert "hi" in r.result["stdout"]


def test_env_filters_keys(tmp_workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    t = RunShellTool()
    r = t.execute({"command": "echo %OPENAI_API_KEY%"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "sk-secret" not in r.result["stdout"]


def test_timeout(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "ping -n 10 127.0.0.1", "timeout": 1}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "timeout"


def test_cwd_outside(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "echo hi", "cwd": ".."}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "cwd_outside_workspace"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_run_shell.py -v`
Expected: FAIL.

- [ ] **Step 3: Write run_shell.py**

`forgeloop/tools/run_shell.py`:
```python
from __future__ import annotations
import os
import re
import subprocess
import sys
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_OUTPUT = 10240
_SENSITIVE_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


def _filtered_env() -> dict:
    return {k: v for k, v in os.environ.items() if not _SENSITIVE_RE.search(k)}


class RunShellTool:
    name = "run_shell"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        command = args.get("command", "")
        cwd = args.get("cwd", ".")
        timeout = args.get("timeout", 60)
        fence = fence_path(cwd, ws, mode="read")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "cwd_outside_workspace", "message": fence.reason}, truncated=False)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=fence.resolved,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_filtered_env(),
                executable=(os.environ.get("COMSPEC") or "cmd.exe") if sys.platform == "win32" else "/bin/sh",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, result=None, error={"code": "timeout", "message": f"timed out after {timeout}s"}, truncated=False)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        truncated = False
        if len(stdout) > MAX_OUTPUT:
            stdout = stdout[:MAX_OUTPUT]
            truncated = True
        if len(stderr) > MAX_OUTPUT:
            stderr = stderr[:MAX_OUTPUT]
            truncated = True
        return ToolResult(
            ok=True,
            result={"command": command, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr, "duration_ms": 0, "timed_out": False},
            error=None,
            truncated=truncated,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_run_shell.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/run_shell.py tests/test_tools_run_shell.py
git commit -m "feat(tools): run_shell with env filtering + timeout"
```

---

## Task 13: Tool — run_tests

**Files:**
- Create: `forgeloop/tools/run_tests.py`
- Test: `tests/test_tools_run_tests.py`

**Interfaces:**
- Produces: `RunTestsTool` returning raw stdout + exit_code (NOT structured — parsing is FeedbackClassifier's job, Task 17).

- [ ] **Step 1: Write failing test**

`tests/test_tools_run_tests.py`:
```python
from forgeloop.tools.run_tests import RunTestsTool


def test_run_tests_returns_raw_stdout(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    t = RunTestsTool()
    r = t.execute({"target": "tests"}, ctx={"workspace_root": str(tmp_path)})
    assert r.ok is True
    assert "passed" in r.result["stdout"]
    assert r.result["exit_code"] == 0


def test_run_tests_failing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert 1 == 2\n", encoding="utf-8")
    t = RunTestsTool()
    r = t.execute({"target": "tests"}, ctx={"workspace_root": str(tmp_path)})
    assert r.ok is True
    assert r.result["exit_code"] == 1
    assert "failed" in r.result["stdout"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_run_tests.py -v`
Expected: FAIL.

- [ ] **Step 3: Write run_tests.py**

`forgeloop/tools/run_tests.py`:
```python
from __future__ import annotations
import subprocess
import sys
import time
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_OUTPUT = 10240


class RunTestsTool:
    name = "run_tests"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        target = args.get("target", "tests")
        extra = args.get("args", [])
        fence = fence_path(target, ws, mode="read")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "target_outside_workspace", "message": fence.reason}, truncated=False)
        cmd = [sys.executable, "-m", "pytest", fence.resolved, "--tb=short", "-ra", "-q"] + list(extra)
        start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ws)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, result=None, error={"code": "timeout", "message": "pytest timed out"}, truncated=False)
        except FileNotFoundError:
            return ToolResult(ok=False, result=None, error={"code": "pytest_not_installed", "message": "pytest not found"}, truncated=False)
        duration = int((time.perf_counter() - start) * 1000)
        stdout = proc.stdout or ""
        truncated = len(stdout) > MAX_OUTPUT
        if truncated:
            stdout = stdout[:MAX_OUTPUT]
        return ToolResult(
            ok=True,
            result={"command": " ".join(cmd), "exit_code": proc.returncode, "stdout": stdout, "duration_ms": duration},
            error=None,
            truncated=truncated,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_run_tests.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/run_tests.py tests/test_tools_run_tests.py
git commit -m "feat(tools): run_tests returns raw pytest stdout for classifier"
```

---

## Task 14: Tool — done

**Files:**
- Create: `forgeloop/tools/done.py`
- Test: `tests/test_tools_done.py`

- [ ] **Step 1: Write failing test**

`tests/test_tools_done.py`:
```python
from forgeloop.tools.done import DoneTool


def test_done_returns_terminal(tmp_workspace):
    t = DoneTool()
    r = t.execute({"summary": "all done", "success": True}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert r.result["terminal"] is True
    assert r.result["summary"] == "all done"
    assert r.result["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools_done.py -v`
Expected: FAIL.

- [ ] **Step 3: Write done.py**

`forgeloop/tools/done.py`:
```python
from __future__ import annotations
from forgeloop.tools.base import ToolResult


class DoneTool:
    name = "done"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        summary = args.get("summary", "")
        success = bool(args.get("success", False))
        return ToolResult(ok=True, result={"terminal": True, "summary": summary, "success": success}, error=None, truncated=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tools_done.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/tools/done.py tests/test_tools_done.py
git commit -m "feat(tools): done terminal signal tool"
```

---

## Task 15: Feedback — types + classify_failure

**Files:**
- Create: `forgeloop/feedback/types.py`
- Create: `forgeloop/feedback/classify_failure.py`
- Test: `tests/test_feedback_classify_failure.py`

**Interfaces:**
- Produces: `FeedbackSignal`, `Failure` dataclasses in `types.py`; `classify_failure(type_str, exit_code, has_summary) -> str` in `classify_failure.py`.

- [ ] **Step 1: Write failing test**

`tests/test_feedback_classify_failure.py`:
```python
from forgeloop.feedback.classify_failure import classify_failure


def test_assertion():
    assert classify_failure("AssertionError: assert 1==2", 1, True) == "assertion_failure"

def test_import():
    assert classify_failure("ModuleNotFoundError: No module named 'frob'", 1, True) == "import_error"

def test_syntax():
    assert classify_failure("SyntaxError: invalid syntax", 1, True) == "syntax_error"

def test_timeout():
    assert classify_failure("Timeout: test took >30s", 1, True) == "timeout"

def test_collection_error():
    assert classify_failure("", 2, False) == "collection_error"

def test_other():
    assert classify_failure("RuntimeError: boom", 1, True) == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_feedback_classify_failure.py -v`
Expected: FAIL.

- [ ] **Step 3: Write types.py and classify_failure.py**

`forgeloop/feedback/types.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Failure:
    id: str
    file: str | None = None
    line: int | None = None
    col: int | None = None
    type: str | None = None
    message: str | None = None
    classification: str = "other"
    code: str | None = None


@dataclass
class FeedbackSignal:
    kind: str
    source_tool: str
    source_action_id: str
    passed: bool
    summary: str
    failures: list[Failure] = field(default_factory=list)
    stats: dict | None = None
    raw_excerpt: str = ""
```

`forgeloop/feedback/classify_failure.py`:
```python
from __future__ import annotations


def classify_failure(type_str: str, exit_code: int, has_summary: bool) -> str:
    t = (type_str or "").lower()
    if "importerror" in t or "modulenotfounderror" in t:
        return "import_error"
    if "syntaxerror" in t:
        return "syntax_error"
    if "timeout" in t:
        return "timeout"
    if "assertionerror" in t or "assert" in t:
        return "assertion_failure"
    if exit_code == 2 and not has_summary:
        return "collection_error"
    return "other"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_feedback_classify_failure.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/feedback/types.py forgeloop/feedback/classify_failure.py tests/test_feedback_classify_failure.py
git commit -m "feat(feedback): FeedbackSignal types + failure classifier"
```

---

## Task 16: Feedback — TestParser (pytest) + LintParser (ruff)

**Files:**
- Create: `forgeloop/feedback/test_parser.py`
- Create: `forgeloop/feedback/lint_parser.py`
- Create: `tests/fixtures/pytest_output/{2_failed,all_passed,garbage,collection_error}.txt`
- Create: `tests/fixtures/ruff_output/basic.txt`
- Test: `tests/test_feedback_parsers.py`

- [ ] **Step 1: Create fixtures**

`tests/fixtures/pytest_output/2_failed.txt`:
```
FAILED tests/test_foo.py::test_foo - AssertionError: assert 1 == 2
FAILED tests/test_bar.py::test_bar - ModuleNotFoundError: No module named 'frob'

==== short test summary info ====
2 failed, 10 passed in 3.2s
```

`tests/fixtures/pytest_output/all_passed.txt`:
```
12 passed in 1.5s
```

`tests/fixtures/pytest_output/garbage.txt`:
```
this is not pytest output at all
random text without summary line
```

`tests/fixtures/pytest_output/collection_error.txt`:
```
ERROR collecting tests/test_bad.py
```

`tests/fixtures/ruff_output/basic.txt`:
```
src/a.py:3:5: F841 local variable x is unused
src/b.py:10:1: E302 expected 2 blank lines
```

- [ ] **Step 2: Write failing test**

`tests/test_feedback_parsers.py`:
```python
from pathlib import Path
from forgeloop.feedback.test_parser import TestParser
from forgeloop.feedback.lint_parser import LintParser

FIX = Path(__file__).parent / "fixtures"


def test_parse_2_failed():
    stdout = (FIX / "pytest_output" / "2_failed.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "test"
    assert sig.passed is False
    assert sig.stats["failed"] == 2
    assert sig.stats["passed"] == 10
    assert len(sig.failures) == 2
    assert sig.failures[0].classification == "assertion_failure"
    assert sig.failures[1].classification == "import_error"
    assert sig.failures[0].file == "tests/test_foo.py"


def test_parse_all_passed():
    stdout = (FIX / "pytest_output" / "all_passed.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=0, action_id="a1")
    assert sig.passed is True
    assert sig.stats["passed"] == 12
    assert sig.failures == []


def test_parse_garbage_degrades_to_raw():
    stdout = (FIX / "pytest_output" / "garbage.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "raw"
    assert "random text" in sig.raw_excerpt


def test_parse_collection_error():
    stdout = (FIX / "pytest_output" / "collection_error.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=2, action_id="a1")
    assert sig.passed is False
    assert sig.kind in ("raw", "test")


def test_lint_parse_basic():
    stdout = (FIX / "ruff_output" / "basic.txt").read_text(encoding="utf-8")
    sig = LintParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "lint"
    assert sig.passed is False
    assert len(sig.failures) == 2
    assert sig.failures[0].file == "src/a.py"
    assert sig.failures[0].line == 3
    assert sig.failures[0].col == 5
    assert sig.failures[0].code == "F841"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_feedback_parsers.py -v`
Expected: FAIL.

- [ ] **Step 4: Write test_parser.py and lint_parser.py**

`forgeloop/feedback/test_parser.py`:
```python
from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal, Failure
from forgeloop.feedback.classify_failure import classify_failure

_SUMMARY_RE = re.compile(r"(\d+)\s+passed(?:[,\s]+(\d+)\s+failed)?(?:[,\s]+(\d+)\s+errors?)?(?:[,\s]+(\d+)\s+skipped)?")
_FAIL_LINE_RE = re.compile(r"^FAILED\s+(\S+?)\s*-\s*(.+)")


class TestParser:
    def parse(self, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        m = _SUMMARY_RE.search(stdout)
        if not m:
            return FeedbackSignal(
                kind="raw", source_tool="run_tests", source_action_id=action_id,
                passed=(exit_code == 0), summary="unparseable", failures=[],
                stats=None, raw_excerpt=stdout[:2000],
            )
        passed = int(m.group(1))
        failed = int(m.group(2) or 0)
        errors = int(m.group(3) or 0)
        skipped = int(m.group(4) or 0)
        failures: list[Failure] = []
        for line in stdout.splitlines():
            fm = _FAIL_LINE_RE.match(line)
            if fm:
                fid = fm.group(1)
                rest = fm.group(2)
                type_str = rest.split(":")[0] if ":" in rest else rest
                file_part = fid.split("::")[0] if "::" in fid else fid
                cls = classify_failure(type_str, exit_code, True)
                failures.append(Failure(id=fid, file=file_part, type=type_str, message=rest, classification=cls))
        return FeedbackSignal(
            kind="test", source_tool="run_tests", source_action_id=action_id,
            passed=(failed == 0 and errors == 0 and exit_code == 0),
            summary=f"{passed} passed, {failed} failed, {errors} errors, {skipped} skipped",
            failures=failures,
            stats={"passed": passed, "failed": failed, "errors": errors, "skipped": skipped},
            raw_excerpt=stdout[:2000],
        )
```

`forgeloop/feedback/lint_parser.py`:
```python
from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal, Failure
from forgeloop.feedback.classify_failure import classify_failure

_LINE_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(\w+)\s+(.+)$")


class LintParser:
    def parse(self, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        failures: list[Failure] = []
        for line in stdout.splitlines():
            m = _LINE_RE.match(line)
            if m:
                failures.append(Failure(
                    id=f"{m.group(1)}:{m.group(2)}:{m.group(3)}",
                    file=m.group(1), line=int(m.group(2)), col=int(m.group(3)),
                    code=m.group(4), message=m.group(5),
                    classification=classify_failure(m.group(4), exit_code, True),
                ))
        return FeedbackSignal(
            kind="lint", source_tool="run_shell", source_action_id=action_id,
            passed=(len(failures) == 0),
            summary=f"{len(failures)} lint violations",
            failures=failures, stats=None, raw_excerpt=stdout[:2000],
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_feedback_parsers.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add forgeloop/feedback/test_parser.py forgeloop/feedback/lint_parser.py tests/fixtures/ tests/test_feedback_parsers.py
git commit -m "feat(feedback): pytest + ruff parsers with degradation"
```

---

## Task 17: Feedback — Renderer + Classifier

**Files:**
- Create: `forgeloop/feedback/renderer.py`
- Create: `forgeloop/feedback/classifier.py`
- Test: `tests/test_feedback_classifier.py`

**Interfaces:**
- Produces: `render(signal) -> str` in `renderer.py`; `FeedbackClassifier.classify(tool_name, command, stdout, exit_code, action_id) -> FeedbackSignal` in `classifier.py`.

- [ ] **Step 1: Write failing test**

`tests/test_feedback_classifier.py`:
```python
from forgeloop.feedback.classifier import FeedbackClassifier
from forgeloop.feedback.renderer import render
from forgeloop.feedback.types import FeedbackSignal, Failure


def test_classifier_routes_run_tests():
    stdout = "2 failed, 10 passed in 3.2s\nFAILED tests/test_foo.py::test_foo - AssertionError: assert 1 == 2\n"
    sig = FeedbackClassifier().classify("run_tests", "", stdout, 1, "a1")
    assert sig.kind == "test"
    assert sig.stats["failed"] == 2


def test_classifier_routes_ruff():
    sig = FeedbackClassifier().classify("run_shell", "ruff check .", "src/a.py:3:5: F841 unused x", 1, "a1")
    assert sig.kind == "lint"
    assert sig.failures[0].code == "F841"


def test_classifier_raw_passthrough():
    sig = FeedbackClassifier().classify("run_shell", "echo hi", "hi\n", 0, "a1")
    assert sig.kind == "raw"


def test_render_failed():
    sig = FeedbackSignal(kind="test", source_tool="run_tests", source_action_id="a1", passed=False, summary="10 passed, 2 failed", failures=[
        Failure(id="tests/test_foo.py::test_foo", file="tests/test_foo.py", line=12, type="AssertionError", message="assert 1==2", classification="assertion_failure"),
    ])
    out = render(sig)
    assert "[FEEDBACK]" in out
    assert "FAILED" in out
    assert "test_foo" in out
    assert "[assertion_failure]" in out


def test_render_passed():
    sig = FeedbackSignal(kind="test", source_tool="run_tests", source_action_id="a1", passed=True, summary="12 passed in 1.5s", failures=[])
    out = render(sig)
    assert "PASSED" in out
    assert "consider calling done" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_feedback_classifier.py -v`
Expected: FAIL.

- [ ] **Step 3: Write renderer.py and classifier.py**

`forgeloop/feedback/renderer.py`:
```python
from __future__ import annotations
from forgeloop.feedback.types import FeedbackSignal


def render(signal: FeedbackSignal) -> str:
    if signal.passed:
        return f"[FEEDBACK] {signal.source_tool} (action {signal.source_action_id}) -> PASSED ({signal.summary}). Task may be complete; consider calling done."
    lines = [f"[FEEDBACK] {signal.source_tool} (action {signal.source_action_id}) -> FAILED", f"Summary: {signal.summary}", "Failures:"]
    for i, f in enumerate(signal.failures, 1):
        loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or f.id)
        lines.append(f"{i}. {f.id} ({loc}) [{f.classification}]")
        if f.message:
            lines.append(f"   {f.message}")
    lines.append("Next: address the failures above. Read the failing tests and the code under test before editing.")
    return "\n".join(lines)
```

`forgeloop/feedback/classifier.py`:
```python
from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal
from forgeloop.feedback.test_parser import TestParser
from forgeloop.feedback.lint_parser import LintParser


class FeedbackClassifier:
    def classify(self, tool_name: str, command: str, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        if tool_name == "run_tests":
            return TestParser().parse(stdout, exit_code, action_id)
        if tool_name == "run_shell" and re.match(r"^(ruff|flake8)\b", command):
            return LintParser().parse(stdout, exit_code, action_id)
        return FeedbackSignal(
            kind="raw", source_tool=tool_name, source_action_id=action_id,
            passed=(exit_code == 0), summary=f"exit_code={exit_code}",
            failures=[], stats=None, raw_excerpt=stdout[:2000],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_feedback_classifier.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/feedback/renderer.py forgeloop/feedback/classifier.py tests/test_feedback_classifier.py
git commit -m "feat(feedback): renderer + classifier dispatcher"
```

---

## Task 18: Governance — path_fence full tests + Decision type

**Files:**
- Create: `forgeloop/governance/types.py`
- Test: `tests/test_governance_path_fence.py`

- [ ] **Step 1: Write failing test**

`tests/test_governance_path_fence.py`:
```python
import os
from forgeloop.governance.path_fence import fence_path


def test_dotdot_traversal_denied(tmp_workspace):
    r = fence_path("../etc/passwd", str(tmp_workspace), mode="write")
    assert r.allowed is False


def test_dotdot_within_workspace_allowed(tmp_workspace):
    (tmp_workspace / "sub").mkdir()
    (tmp_workspace / "sub" / "a.py").write_text("x", encoding="utf-8")
    r = fence_path("sub/../a.py", str(tmp_workspace), mode="write")
    assert r.allowed is True


def test_symlink_escape_denied(tmp_workspace):
    link = tmp_workspace / "link"
    os.symlink(os.path.dirname(str(tmp_workspace)), link)
    r = fence_path("link/x", str(tmp_workspace), mode="write")
    assert r.allowed is False


def test_read_allowlist(tmp_workspace):
    r = fence_path("/tmp/foo", str(tmp_workspace), mode="read", read_allowlist=["/tmp/"])
    assert r.allowed is True


def test_write_always_fenced():
    r = fence_path("/etc/passwd", "/tmp/ws", mode="write")
    assert r.allowed is False
```

- [ ] **Step 2: Run test to verify it passes (path_fence already implemented in Task 9)**

Run: `python -m pytest tests/test_governance_path_fence.py -v`
Expected: 5 passed. If symlink test fails on Windows due to permissions, add `@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlink")`.

- [ ] **Step 3: Write governance/types.py**

`forgeloop/governance/types.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["Allow", "Deny", "RequireApproval"]


@dataclass
class Decision:
    verdict: Verdict
    rule_id: str
    reason: str = ""
```

- [ ] **Step 4: Commit**

```bash
git add forgeloop/governance/types.py tests/test_governance_path_fence.py
git commit -m "test(governance): full path fence tests + Decision type"
```

---

## Task 19: Governance — rule_engine

**Files:**
- Create: `forgeloop/governance/rule_engine.py`
- Test: `tests/test_governance_rule_engine.py`

**Interfaces:**
- Produces: `guardrail(action, config) -> Decision` in `rule_engine.py`. Path fence runs first (writes always fenced); then rules top-to-bottom, first match wins; then `default_decision`.

- [ ] **Step 1: Write failing test**

`tests/test_governance_rule_engine.py`:
```python
from forgeloop.config.loader import load_config
from forgeloop.governance.rule_engine import guardrail
from forgeloop.parser.types import Action


def _cfg():
    return load_config([])


def test_deny_rm_rf():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "rm -rf /"}), _cfg())
    assert d.verdict == "Deny"
    assert d.rule_id == "deny_rm_rf_root"


def test_allow_git_status():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "git status"}), _cfg())
    assert d.verdict == "Allow"
    assert d.rule_id == "allow_git_readonly"


def test_approve_write(tmp_path):
    d = guardrail(Action(thought="x", tool="write_file", args={"path": str(tmp_path / "a.py"), "mode": "overwrite", "content": "x"}), _cfg())
    assert d.verdict == "RequireApproval"
    assert d.rule_id == "approve_all_writes"


def test_deny_write_outside_workspace():
    d = guardrail(Action(thought="x", tool="write_file", args={"path": "/etc/evil", "mode": "overwrite", "content": "x"}), _cfg())
    assert d.verdict == "Deny"


def test_default_require_approval():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "python foo.py"}), _cfg())
    assert d.verdict == "RequireApproval"
    assert d.rule_id == "approve_shell_default"


def test_allow_done():
    d = guardrail(Action(thought="x", tool="done", args={"summary": "ok", "success": True}), _cfg())
    assert d.verdict == "Allow"


def test_override_replaces_rule(tmp_path):
    override = tmp_path / "ov.yaml"
    override.write_text("rules:\n  - id: deny_sudo\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n", encoding="utf-8")
    cfg = load_config([override])
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "sudo rm -rf /"}), cfg)
    assert d.verdict == "Allow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_rule_engine.py -v`
Expected: FAIL.

- [ ] **Step 3: Write rule_engine.py**

`forgeloop/governance/rule_engine.py`:
```python
from __future__ import annotations
import re
from forgeloop.parser.types import Action
from forgeloop.governance.types import Decision
from forgeloop.governance.path_fence import fence_path
from forgeloop.config.loader import GuardrailsConfig


def _match(action: Action, rule: dict) -> bool:
    tools = rule.get("tool", [])
    if tools and action.tool not in tools:
        return False
    match = rule.get("match", {})
    if match.get("any"):
        return True
    if "command_regex" in match and action.tool == "run_shell":
        if not re.search(match["command_regex"], action.args.get("command", "")):
            return False
    if "path_regex" in match and action.tool in ("read_file", "write_file", "list_dir"):
        if not re.search(match["path_regex"], action.args.get("path", "")):
            return False
    if "args_match" in match:
        for k, v in match["args_match"].items():
            if action.args.get(k) != v:
                return False
    return True


def guardrail(action: Action, config: GuardrailsConfig) -> Decision:
    if action.tool in ("write_file", "read_file", "list_dir"):
        mode = "write" if action.tool == "write_file" else "read"
        fence = fence_path(action.args.get("path", ""), config.workspace_root, mode=mode, read_allowlist=config.path_fencing.get("read_allowlist", []))
        if not fence.allowed:
            return Decision(verdict="Deny", rule_id="path_fence", reason=fence.reason)
    for rule in config.rules:
        if _match(action, rule):
            return Decision(verdict=rule["decision"], rule_id=rule["id"], reason=rule.get("reason", ""))
    return Decision(verdict=config.default_decision, rule_id="default", reason="no rule matched")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_rule_engine.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/governance/rule_engine.py tests/test_governance_rule_engine.py
git commit -m "feat(governance): rule engine with first-match + path fence"
```

---

## Task 20: Governance — Approval FSM

**Files:**
- Create: `forgeloop/governance/approval.py`
- Test: `tests/test_governance_approval.py`

**Interfaces:**
- Produces: `ApprovalFSM` with `request(action_id, session_id) -> ApprovalRequest`, `approve(ar_id, decided_by)`, `deny(ar_id, decided_by, reason)`, `pending() -> list`.

- [ ] **Step 1: Write failing test**

`tests/test_governance_approval.py`:
```python
from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.governance.approval import ApprovalFSM
from forgeloop.storage.models import Session, Action, create_session, create_action


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_request_then_approve(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    ar = fsm.request(action_id="a1", session_id="s1")
    assert ar.status == "PENDING"
    assert len(fsm.pending()) == 1
    fsm.approve(ar.id, decided_by="webui")
    assert len(fsm.pending()) == 0
    conn.close()


def test_deny_with_reason(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_action(conn, Action(id="a2", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    ar = fsm.request(action_id="a2", session_id="s1")
    fsm.deny(ar.id, decided_by="webui", reason="too risky")
    assert len(fsm.pending()) == 0
    conn.close()


def test_persistence_after_reconnect(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_action(conn, Action(id="a3", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    fsm.request(action_id="a3", session_id="s1")
    conn.close()
    conn2 = connect(tmp_path / "t.db")
    fsm2 = ApprovalFSM(conn2)
    assert len(fsm2.pending()) == 1
    conn2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_approval.py -v`
Expected: FAIL.

- [ ] **Step 3: Write approval.py**

`forgeloop/governance/approval.py`:
```python
from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from forgeloop.storage.models import ApprovalRequest, create_approval_request, update_approval_request, list_pending_approvals


def _now():
    return datetime.now(timezone.utc).isoformat()


class ApprovalFSM:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def request(self, action_id: str, session_id: str) -> ApprovalRequest:
        ar = ApprovalRequest(id=str(uuid.uuid4()), action_id=action_id, session_id=session_id, status="PENDING", requested_at=_now())
        create_approval_request(self._conn, ar)
        return ar

    def approve(self, ar_id: str, decided_by: str = "webui") -> None:
        update_approval_request(self._conn, ar_id, status="APPROVED", decided_at=_now(), decided_by=decided_by)

    def deny(self, ar_id: str, decided_by: str = "webui", reason: str = "") -> None:
        update_approval_request(self._conn, ar_id, status="DENIED", decided_at=_now(), decided_by=decided_by, deny_reason=reason)

    def pending(self) -> list[ApprovalRequest]:
        return list_pending_approvals(self._conn)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_approval.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/governance/approval.py tests/test_governance_approval.py
git commit -m "feat(governance): HITL approval FSM with persistence"
```

---

## Task 21: Memory — retrieval + write

**Files:**
- Create: `forgeloop/storage/memory.py`
- Test: `tests/test_storage_memory.py`

**Interfaces:**
- Produces: `MemoryEntry` dataclass, `write_memory(conn, entry)`, `retrieve_memory(conn, workspace_root, keywords, k=5) -> list[MemoryEntry]`.

- [ ] **Step 1: Write failing test**

`tests/test_storage_memory.py`:
```python
from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.memory import write_memory, retrieve_memory, MemoryEntry


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_write_and_retrieve(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    write_memory(conn, MemoryEntry(id="m1", workspace_root=str(tmp_path), kind="convention", tags='["python","style"]', content="use 4 spaces for indent", created_at=_now(), updated_at=_now()))
    write_memory(conn, MemoryEntry(id="m2", workspace_root=str(tmp_path), kind="decision", tags='["arch"]', content="use sqlite not postgres", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["sqlite"])
    assert len(results) == 1
    assert "sqlite" in results[0].content


def test_cross_session_same_workspace(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    write_memory(conn, MemoryEntry(id="m1", session_id="sA", workspace_root=str(tmp_path), kind="lesson", tags='[]', content="always run tests", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["tests"])
    assert len(results) == 1
    assert results[0].session_id == "sA"
    conn.close()


def test_top_k_limit(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    for i in range(10):
        write_memory(conn, MemoryEntry(id=f"m{i}", workspace_root=str(tmp_path), kind="fact", tags='[]', content=f"fact number {i}", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["fact"], k=3)
    assert len(results) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_memory.py -v`
Expected: FAIL.

- [ ] **Step 3: Write memory.py**

`forgeloop/storage/memory.py`:
```python
from __future__ import annotations
import sqlite3
import uuid
from dataclasses import dataclass


@dataclass
class MemoryEntry:
    workspace_root: str
    kind: str
    content: str
    created_at: str
    updated_at: str
    id: str | None = None
    session_id: str | None = None
    tags: str | None = None
    key: str | None = None
    source_turn_id: str | None = None


def write_memory(conn: sqlite3.Connection, entry: MemoryEntry) -> str:
    if not entry.id:
        entry.id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO memory (id,session_id,workspace_root,kind,tags,key,content,source_turn_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (entry.id, entry.session_id, entry.workspace_root, entry.kind, entry.tags, entry.key, entry.content, entry.source_turn_id, entry.created_at, entry.updated_at),
    )
    conn.commit()
    return entry.id


def retrieve_memory(conn: sqlite3.Connection, workspace_root: str, keywords: list[str], k: int = 5) -> list[MemoryEntry]:
    if not keywords:
        return []
    clauses = []
    params: list = [workspace_root]
    for kw in keywords:
        clauses.append("(content LIKE ? OR tags LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    where = " OR ".join(clauses)
    sql = f"SELECT * FROM memory WHERE workspace_root=? AND ({where}) ORDER BY updated_at DESC LIMIT ?"
    params.append(k)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(MemoryEntry(
            id=r["id"], session_id=r["session_id"], workspace_root=r["workspace_root"],
            kind=r["kind"], tags=r["tags"], key=r["key"], content=r["content"],
            source_turn_id=r["source_turn_id"], created_at=r["created_at"], updated_at=r["updated_at"],
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_memory.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/storage/memory.py tests/test_storage_memory.py
git commit -m "feat(memory): keyword/tag retrieval + cross-session persistence"
```

---

## Task 22: Agent — session state machine + shutdown breakers

**Files:**
- Create: `forgeloop/agent/session.py`
- Create: `forgeloop/agent/shutdown.py`
- Test: `tests/test_agent_shutdown.py`

**Interfaces:**
- Produces: `SessionStatus` enum, `is_terminal(status)`, `TERMINAL_STATUSES` in `session.py`; `BreakerState` dataclass, `check_shutdown(state, config, max_rounds, done_called, done_success) -> str` in `shutdown.py`.

- [ ] **Step 1: Write failing test**

`tests/test_agent_shutdown.py`:
```python
from forgeloop.agent.session import SessionStatus, is_terminal
from forgeloop.agent.shutdown import check_shutdown, BreakerState
from forgeloop.config.loader import load_config


def test_terminal_states():
    assert is_terminal("COMPLETED")
    assert is_terminal("FAILED_PARSE")
    assert is_terminal("STOPPED_MAX_ROUNDS")
    assert not is_terminal("RUNNING")
    assert not is_terminal("PENDING_APPROVAL")


def test_max_rounds():
    cfg = load_config([])
    state = BreakerState(round_count=51, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_MAX_ROUNDS"


def test_hard_breaker():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=3, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_FAILURE_BREAKER"


def test_loop_breaker():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=3, last_action_hash="abc", last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_LOOP"


def test_no_shutdown_when_running():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "RUNNING"


def test_done_post_check_blocks_success_when_tests_failed():
    cfg = load_config([])
    cfg.done_post_check["require_green_tests"] = True
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state={"passed": False, "failed": 2})
    result = check_shutdown(state, cfg, max_rounds=50, done_called=True, done_success=True)
    assert result == "RUNNING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_shutdown.py -v`
Expected: FAIL.

- [ ] **Step 3: Write session.py and shutdown.py**

`forgeloop/agent/session.py`:
```python
from __future__ import annotations
from enum import Enum


class SessionStatus(str, Enum):
    RUNNING = "RUNNING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURE = "COMPLETED_WITH_FAILURE"
    FAILED_PARSE = "FAILED_PARSE"
    STOPPED_FAILURE_BREAKER = "STOPPED_FAILURE_BREAKER"
    STOPPED_LOOP = "STOPPED_LOOP"
    STOPPED_MAX_ROUNDS = "STOPPED_MAX_ROUNDS"
    STOPPED_APPROVAL_TIMEOUT = "STOPPED_APPROVAL_TIMEOUT"
    ABORTED = "ABORTED"


TERMINAL_STATUSES = {
    SessionStatus.COMPLETED, SessionStatus.COMPLETED_WITH_FAILURE,
    SessionStatus.FAILED_PARSE, SessionStatus.STOPPED_FAILURE_BREAKER,
    SessionStatus.STOPPED_LOOP, SessionStatus.STOPPED_MAX_ROUNDS,
    SessionStatus.STOPPED_APPROVAL_TIMEOUT, SessionStatus.ABORTED,
}


def is_terminal(status: str) -> bool:
    return status in {s.value for s in TERMINAL_STATUSES}
```

`forgeloop/agent/shutdown.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from forgeloop.config.loader import GuardrailsConfig


@dataclass
class BreakerState:
    round_count: int
    consecutive_failures: int
    consecutive_identical: int
    last_action_hash: str | None
    last_test_state: dict | None


def check_shutdown(state: BreakerState, config: GuardrailsConfig, max_rounds: int, done_called: bool = False, done_success: bool = False) -> str:
    if done_called:
        if done_success and config.done_post_check.get("require_green_tests"):
            ts = state.last_test_state
            if ts and (ts.get("failed", 0) > 0 or not ts.get("passed", True)):
                return "RUNNING"
        return "COMPLETED" if done_success else "COMPLETED_WITH_FAILURE"
    if state.consecutive_failures >= 3:
        return "STOPPED_FAILURE_BREAKER"
    if state.consecutive_identical >= 3:
        return "STOPPED_LOOP"
    if state.round_count >= max_rounds:
        return "STOPPED_MAX_ROUNDS"
    return "RUNNING"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_shutdown.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/agent/session.py forgeloop/agent/shutdown.py tests/test_agent_shutdown.py
git commit -m "feat(agent): session status enum + shutdown breakers"
```

---

## Task 23: Agent — build_context

**Files:**
- Create: `forgeloop/agent/context.py`
- Test: `tests/test_agent_context.py`

**Interfaces:**
- Produces: `SYSTEM_PROMPT` constant, `build_context(task, history, memory_entries, feedback_text, parse_error_text, max_history_turns) -> list[Message]` in `context.py`.

- [ ] **Step 1: Write failing test**

`tests/test_agent_context.py`:
```python
from forgeloop.agent.context import build_context
from forgeloop.llm.base import Message


def test_context_has_system_user_memory_feedback():
    msgs = build_context(task="add a foo function", history=[], memory_entries=["convention: use 4 spaces"], feedback_text=None, parse_error_text=None)
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "add a foo function" in msgs[1].content
    assert any("[MEMORY]" in m.content for m in msgs)


def test_context_includes_feedback():
    msgs = build_context(task="x", history=[], memory_entries=[], feedback_text="[FEEDBACK] FAILED", parse_error_text=None)
    assert any("[FEEDBACK]" in m.content for m in msgs)


def test_context_includes_parse_error():
    msgs = build_context(task="x", history=[], memory_entries=[], feedback_text=None, parse_error_text="missing field thought")
    assert any("无法解析" in m.content for m in msgs)


def test_history_truncation():
    hist = [Message(role="assistant", content=f'{{"thought":"t{i}","tool":"done","args":{{}}}}') for i in range(30)]
    msgs = build_context(task="x", history=hist, memory_entries=[], feedback_text=None, parse_error_text=None, max_history_turns=20)
    assistant_count = sum(1 for m in msgs if m.role == "assistant")
    assert assistant_count <= 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_context.py -v`
Expected: FAIL.

- [ ] **Step 3: Write context.py**

`forgeloop/agent/context.py`:
```python
from __future__ import annotations
from forgeloop.llm.base import Message

SYSTEM_PROMPT = """You are a coding agent. Output ONLY a single JSON object per turn with fields:
- thought (string, required): your reasoning
- tool (string, required): one of read_file, write_file, run_shell, run_tests, list_dir, done
- args (object, required): tool arguments

Tool schemas:
- read_file: {path: string, offset?: int, limit?: int}
- write_file: {path: string, mode: "overwrite"|"edit", content?: string, old_string?: string, new_string?: string}
- run_shell: {command: string, cwd?: string, timeout?: int}
- run_tests: {target?: string, args?: list}
- list_dir: {path?: string, recursive?: bool}
- done: {summary: string, success: bool}

You may only operate within the workspace. Do not output prose, only the JSON object."""


def build_context(task: str, history: list[Message], memory_entries: list[str], feedback_text: str | None, parse_error_text: str | None, max_history_turns: int = 20) -> list[Message]:
    msgs: list[Message] = [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content=task)]
    if memory_entries:
        mem = "\n".join(f"- {m}" for m in memory_entries)
        msgs.append(Message(role="user", content=f"[MEMORY]\n{mem}"))
    if len(history) > max_history_turns * 2:
        history = history[-max_history_turns * 2:]
    msgs.extend(history)
    if feedback_text:
        msgs.append(Message(role="user", content=feedback_text))
    if parse_error_text:
        msgs.append(Message(role="user", content=f"上一条输出无法解析为合法动作。请只输出一个 JSON 对象。上次错误：{parse_error_text}"))
    return msgs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_context.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/agent/context.py tests/test_agent_context.py
git commit -m "feat(agent): context builder with system prompt + memory + feedback"
```

---

## Task 24: Agent — main loop

**Files:**
- Create: `forgeloop/agent/loop.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Produces: `AgentLoop` class with `run() -> str` (returns terminal status). Consumes: `LLMProvider`, `LLMConfig`, `GuardrailsConfig`, `ToolRegistry`, sqlite3.Connection, workspace_root, task.

- [ ] **Step 1: Write failing test (end-to-end with mock LLM)**

`tests/test_agent_loop.py`:
```python
from forgeloop.agent.loop import AgentLoop
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.config.loader import load_config
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool
from forgeloop.storage.db import connect, init_schema


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def test_loop_completes_with_done(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"read","tool":"read_file","args":{"path":"src/main.py"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="read the file then done")
    status = loop.run()
    assert status == "COMPLETED"
    conn.close()


def test_loop_parse_failure_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=["garbage", "more garbage", "still garbage"])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "FAILED_PARSE"
    conn.close()


def test_loop_hard_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=[
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "STOPPED_FAILURE_BREAKER"
    conn.close()


def test_loop_loop_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=[
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "STOPPED_LOOP"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_loop.py -v`
Expected: FAIL.

- [ ] **Step 3: Write loop.py**

`forgeloop/agent/loop.py`:
```python
from __future__ import annotations
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from forgeloop.llm.base import LLMProvider, LLMConfig, Message
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.tools.base import ToolRegistry
from forgeloop.feedback.classifier import FeedbackClassifier
from forgeloop.feedback.renderer import render
from forgeloop.governance.rule_engine import guardrail
from forgeloop.governance.approval import ApprovalFSM
from forgeloop.parser.parse import parse
from forgeloop.parser.types import Action, ParseError
from forgeloop.agent.context import build_context
from forgeloop.agent.shutdown import check_shutdown, BreakerState
from forgeloop.storage.models import Session, Turn, Action as ActionRow, create_session, create_turn, create_action, update_action, update_session_status
from forgeloop.storage.memory import retrieve_memory


def _now():
    return datetime.now(timezone.utc).isoformat()


def _args_hash(action: Action) -> str:
    return hashlib.sha1(json.dumps({"tool": action.tool, "args": action.args}, sort_keys=True).encode()).hexdigest()[:16]


class AgentLoop:
    def __init__(self, llm: LLMProvider, llm_config: LLMConfig, config: GuardrailsConfig, registry: ToolRegistry, conn: sqlite3.Connection, workspace_root: str, task: str, max_rounds: int = 50, parse_fail_limit: int = 3):
        self._llm = llm
        self._llm_config = llm_config
        self._config = config
        self._registry = registry
        self._conn = conn
        self._workspace_root = workspace_root
        self._task = task
        self._max_rounds = max_rounds
        self._parse_fail_limit = parse_fail_limit
        self._classifier = FeedbackClassifier()
        self._fsm = ApprovalFSM(conn)
        self._history: list[Message] = []
        self._round = 0
        self._consec_fail = 0
        self._consec_ident = 0
        self._last_hash: str | None = None
        self._last_test_state: dict | None = None
        self._last_feedback: str | None = None
        self._last_parse_err: str | None = None
        self._session_id = str(uuid.uuid4())
        self._turn_index = 0

    def run(self) -> str:
        s = Session(id=self._session_id, task=self._task, workspace_root=self._workspace_root, status="RUNNING", created_at=_now(), updated_at=_now(), llm_config=json.dumps({"model": self._llm_config.model}))
        create_session(self._conn, s)
        while True:
            mem = retrieve_memory(self._conn, self._workspace_root, self._task.split()[:3])
            mem_texts = [f"[{m.kind}] {m.content}" for m in mem]
            msgs = build_context(self._task, self._history, mem_texts, self._last_feedback, self._last_parse_err)
            turn_id = str(uuid.uuid4())
            parse_attempts = 0
            action: Action | None = None
            resp = None
            while parse_attempts < self._parse_fail_limit:
                resp = self._llm.complete(msgs, self._llm_config)
                parsed = parse(resp.content)
                if isinstance(parsed, Action):
                    action = parsed
                    break
                parse_attempts += 1
                self._last_parse_err = parsed.message
                msgs = build_context(self._task, self._history, mem_texts, self._last_feedback, self._last_parse_err)
            if action is None:
                create_turn(self._conn, Turn(id=turn_id, session_id=self._session_id, turn_index=self._turn_index, started_at=_now(), finished_at=_now(), parse_status="PARSE_FAILED", parse_attempts=parse_attempts, llm_raw_output=resp.content if resp else ""))
                update_session_status(self._conn, self._session_id, "FAILED_PARSE")
                return "FAILED_PARSE"
            create_turn(self._conn, Turn(id=turn_id, session_id=self._session_id, turn_index=self._turn_index, started_at=_now(), finished_at=_now(), parse_status="OK", parse_attempts=parse_attempts, llm_raw_output=resp.content))
            self._turn_index += 1
            self._history.append(Message(role="assistant", content=resp.content))
            self._last_parse_err = None
            ahash = _args_hash(action)
            action_row = ActionRow(id=str(uuid.uuid4()), session_id=self._session_id, turn_id=turn_id, tool=action.tool, args=json.dumps(action.args), thought=action.thought, args_hash=ahash, status="EXECUTING", created_at=_now())
            create_action(self._conn, action_row)
            decision = guardrail(action, self._config)
            if decision.verdict == "Deny":
                update_action(self._conn, action_row.id, status="BLOCKED_BY_GUARDRAIL", guardrail_decision=json.dumps({"verdict": "Deny", "rule_id": decision.rule_id, "reason": decision.reason}), finished_at=_now())
                self._consec_fail += 1
                self._history.append(Message(role="user", content=f"[BLOCKED] action denied by guardrail: {decision.reason} (rule: {decision.rule_id})"))
                self._last_feedback = None
            elif decision.verdict == "RequireApproval":
                update_action(self._conn, action_row.id, status="PENDING_APPROVAL", guardrail_decision=json.dumps({"verdict": "RequireApproval", "rule_id": decision.rule_id, "reason": decision.reason}))
                ar = self._fsm.request(action_id=action_row.id, session_id=self._session_id)
                update_session_status(self._conn, self._session_id, "PENDING_APPROVAL")
                self._await_approval(ar.id)
                if self._fsm_denied(ar.id):
                    update_action(self._conn, action_row.id, status="DENIED", finished_at=_now())
                    self._consec_fail += 1
                    self._history.append(Message(role="user", content="[DENIED] user denied your action."))
                    self._last_feedback = None
                    st = self._check_and_update()
                    if st != "RUNNING":
                        return st
                    continue
                update_action(self._conn, action_row.id, status="APPROVED")
                update_session_status(self._conn, self._session_id, "RUNNING")
                result = self._registry.dispatch(action, ctx={"workspace_root": self._workspace_root, "read_allowlist": self._config.path_fencing.get("read_allowlist", [])})
                self._finish_action(action_row, action, result, ahash)
            else:
                result = self._registry.dispatch(action, ctx={"workspace_root": self._workspace_root, "read_allowlist": self._config.path_fencing.get("read_allowlist", [])})
                self._finish_action(action_row, action, result, ahash)
            self._round += 1
            done_called = action.tool == "done" and result.ok
            done_success = done_called and result.result.get("success", False) if result.result else False
            st = self._check_and_update(done_called=done_called, done_success=done_success)
            if st != "RUNNING":
                return st

    def _finish_action(self, action_row, action: Action, result, ahash: str) -> None:
        update_action(self._conn, action_row.id, status="SUCCEEDED" if result.ok else "FAILED", result=json.dumps({"ok": result.ok, "result": result.result, "error": result.error, "truncated": result.truncated}), finished_at=_now())
        if result.ok:
            self._consec_fail = 0
        else:
            self._consec_fail += 1
        if ahash == self._last_hash:
            self._consec_ident += 1
        else:
            self._consec_ident = 1
        self._last_hash = ahash
        feedback_text = None
        if result.ok and result.result:
            if action.tool == "run_tests":
                sig = self._classifier.classify("run_tests", "", result.result.get("stdout", ""), result.result.get("exit_code", 0), action_row.id)
                self._last_test_state = {"passed": sig.passed, "failed": sig.stats.get("failed", 0) if sig.stats else 0}
                feedback_text = render(sig)
                update_action(self._conn, action_row.id, feedback_signal=json.dumps({"kind": sig.kind, "passed": sig.passed, "summary": sig.summary}))
            elif action.tool == "run_shell":
                cmd = action.args.get("command", "")
                sig = self._classifier.classify("run_shell", cmd, result.result.get("stdout", ""), result.result.get("exit_code", 0), action_row.id)
                if sig.kind in ("test", "lint"):
                    feedback_text = render(sig)
                    update_action(self._conn, action_row.id, feedback_signal=json.dumps({"kind": sig.kind, "passed": sig.passed, "summary": sig.summary}))
        if feedback_text is None and result.result is not None:
            feedback_text = json.dumps({"ok": result.ok, "result": result.result, "error": result.error, "truncated": result.truncated})
        self._history.append(Message(role="user", content=feedback_text or ""))
        self._last_feedback = feedback_text

    def _check_and_update(self, done_called: bool = False, done_success: bool = False) -> str:
        state = BreakerState(round_count=self._round, consecutive_failures=self._consec_fail, consecutive_identical=self._consec_ident, last_action_hash=self._last_hash, last_test_state=self._last_test_state)
        st = check_shutdown(state, self._config, self._max_rounds, done_called=done_called, done_success=done_success)
        if st != "RUNNING":
            update_session_status(self._conn, self._session_id, st, finished_at=_now() if st.startswith("COMPLETED") else None)
        return st

    def _await_approval(self, ar_id: str) -> None:
        pass

    def _fsm_denied(self, ar_id: str) -> bool:
        row = self._conn.execute("SELECT status FROM approval_requests WHERE id=?", (ar_id,)).fetchone()
        return bool(row and row["status"] == "DENIED")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_loop.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add forgeloop/agent/loop.py tests/test_agent_loop.py
git commit -m "feat(agent): main loop orchestrating parse/govern/execute/feedback/shutdown"
```

---

## Task 25: Integration — feedback loop end-to-end

**Files:**
- Create: `tests/test_integration_feedback_loop.py`

- [ ] **Step 1: Write failing test (verifies feedback signal is injected into next turn's context)**

`tests/test_integration_feedback_loop.py`:
```python
from forgeloop.agent.loop import AgentLoop
from forgeloop.llm.base import LLMConfig, Message
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.config.loader import load_config
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool
from forgeloop.storage.db import connect, init_schema


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def test_feedback_injected_after_failed_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert 1 == 2\n", encoding="utf-8")
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_path)
    cfg.done_post_check["require_green_tests"] = False
    captured_contexts: list[list[Message]] = []

    def gen(messages, config):
        captured_contexts.append(list(messages))
        if len(captured_contexts) == 1:
            return '{"thought":"run tests","tool":"run_tests","args":{"target":"tests"}}'
        return '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'

    mock = MockLLMProvider(responses=gen)
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_path), task="run tests then done")
    status = loop.run()
    assert status == "COMPLETED"
    assert len(captured_contexts) >= 2
    second_context_text = " ".join(m.content for m in captured_contexts[1])
    assert "[FEEDBACK]" in second_context_text
    assert "FAILED" in second_context_text or "assertion_failure" in second_context_text
    conn.close()
```

- [ ] **Step 2: Run test to verify it passes (loop already implemented in Task 24)**

Run: `python -m pytest tests/test_integration_feedback_loop.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_feedback_loop.py
git commit -m "test(integration): feedback signal injected into next turn context"
```

---

## Self-Review Notes

**Spec coverage check** (Plan 1 = core library only; CLI/WebUI/Packaging deferred to Plans 2-3):

- Block 1 (action protocol): Task 5 ✓
- Block 2 (tools): Tasks 8-14 ✓
- Block 3 (shutdown): Task 22 ✓
- Block 4 (feedback): Tasks 15-17 ✓
- Block 5 (governance): Tasks 9 (path_fence), 18, 19, 20 ✓
- Block 6 (data model): Tasks 6, 7, 21 ✓
- Block 8 (credentials): Task 3 ✓
- LLM abstraction (spec 3.1): Task 2 ✓
- Context structure (spec 3.2): Task 23 ✓
- Main loop (spec section 3): Task 24 ✓
- End-to-end mock test (hard constraint #5): Tasks 24, 25 ✓

**Placeholder scan:** No TBD/TODO/FIXME in any task. All steps contain complete code.

**Type consistency check:**
- `ToolResult(ok, result, error, truncated)` — used consistently in Tasks 8-14, 24.
- `Action(thought, tool, args)` — defined Task 5, used Tasks 8, 19, 24.
- `FeedbackSignal(kind, source_tool, source_action_id, passed, summary, failures, stats, raw_excerpt)` — defined Task 15, used Tasks 16-17, 24.
- `Decision(verdict, rule_id, reason)` — defined Task 18, used Tasks 19, 24.
- `BreakerState(round_count, consecutive_failures, consecutive_identical, last_action_hash, last_test_state)` — defined Task 22, used Task 24.
- `Message(role, content)` — defined Task 2, used Tasks 23-24.

**Known simplifications for Plan 1 (to be addressed in Plan 2):**
- `_await_approval` is a no-op stub (Task 24). In Plan 2 (WebUI), the loop will integrate with the FastAPI server to actually block on approval. For Plan 1's mock-LLM tests, approval-requiring actions are avoided by the mock LLM's responses (it only calls read_file/list_dir/done which are Allow). The stub is sufficient for Plan 1's test coverage.
- No CLI entrypoint (Plan 2).
- No WebUI server (Plan 2).
- No Docker/PyPI packaging (Plan 3).
