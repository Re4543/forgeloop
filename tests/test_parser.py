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
