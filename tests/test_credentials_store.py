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
