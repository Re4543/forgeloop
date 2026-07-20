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
