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
