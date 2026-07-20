from forgeloop.credentials.redact import redact


def test_redact_sk_key():
    assert redact("calling with sk-abc123XYZ") == "calling with sk-****"


def test_redact_no_key_passthrough():
    assert redact("plain log line") == "plain log line"


def test_redact_multiple_keys():
    assert redact("a=sk-aaa111 b=sk-bbb222") == "a=sk-**** b=sk-****"
