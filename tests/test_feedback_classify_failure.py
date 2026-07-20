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
