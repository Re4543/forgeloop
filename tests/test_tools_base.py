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
