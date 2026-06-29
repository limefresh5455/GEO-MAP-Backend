# app/core/rate_limiter.py
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _limiter_key_func(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip
    return get_remote_address(request)


shared_limiter = Limiter(key_func=_limiter_key_func)
