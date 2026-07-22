from __future__ import annotations
from fastapi import Request, HTTPException, Depends


async def verify_token(request: Request, secret: str):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    token = auth[7:]
    if token != secret:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return token


def create_auth_dependency(secret: str):
    async def _verify_token(request: Request):
        return await verify_token(request, secret)
    return Depends(_verify_token)
