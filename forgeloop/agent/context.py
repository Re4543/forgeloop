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
    if len(history) > max_history_turns:
        history = history[-max_history_turns:]
    msgs.extend(history)
    if feedback_text:
        msgs.append(Message(role="user", content=feedback_text))
    if parse_error_text:
        msgs.append(Message(role="user", content=f"上一条输出无法解析为合法动作。请只输出一个 JSON 对象。上次错误：{parse_error_text}"))
    return msgs
