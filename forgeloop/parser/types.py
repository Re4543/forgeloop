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
