from __future__ import annotations
from fastapi import Request, Depends
from fastapi.responses import JSONResponse


class UnauthorizedError(Exception):
    pass


async def verify_token(request: Request, secret: str):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise UnauthorizedError()
    token = auth[7:]
    if token != secret:
        raise UnauthorizedError()
    return token


def create_auth_dependency(secret: str):
    async def _verify_token(request: Request):
        return await verify_token(request, secret)
    return Depends(_verify_token)


def register_auth_handler(app):
    async def _handle_unauthorized(request, exc):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
