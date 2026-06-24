# app/core/rate_limiter.py
"""
Shared rate limiter instance for the entire application.

All router-level @limiter.limit(...) decorators should import from here,
and the lifespan should assign this instance to app.state.limiter so that
SlowAPIMiddleware can coordinate with the decorators.

Usage in lifespan:
    from app.core.rate_limiter import shared_limiter
    app.state.limiter = shared_limiter

Usage in routers:
    from app.core.rate_limiter import shared_limiter
    @shared_limiter.limit("10/minute")
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

shared_limiter = Limiter(key_func=get_remote_address)
