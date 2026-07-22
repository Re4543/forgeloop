from fastapi import FastAPI
from fastapi.testclient import TestClient
from forgeloop.server.auth import verify_token, create_auth_dependency
from forgeloop.config.app_config import ServerConfig


def _app(secret: str):
    app = FastAPI()
    dep = create_auth_dependency(secret)
    @app.get("/protected")
    async def protected(_=dep):
        return {"ok": True}
    return app


def test_no_token_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json() == {"detail": {"error": "unauthorized"}}


def test_wrong_token_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_correct_token_passes():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer my-secret"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_malformed_header_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "my-secret"})
    assert resp.status_code == 401
