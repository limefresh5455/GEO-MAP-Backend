# app/services/exchange_rate_service.py
"""
Real-time INR → USD exchange rate fetcher with Redis caching.

Flow:
  1. Check Redis for a cached rate (TTL = EXCHANGE_RATE_CACHE_TTL, default 10 min).
  2. On cache miss, call the Open Exchange Rates API (no key required for latest).
  3. Store the fetched rate back in Redis before returning.
  4. If both Redis and the HTTP call fail, raise a clear RuntimeError so the
     caller can surface a 503 to the user instead of silently using a stale rate.

The rate is stored as a plain string in Redis (e.g. "83.52") and parsed to float
on every read — simple, no serialisation overhead.
"""

import logging
from typing import Optional

import httpx

from app.core.config import settings
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

# Redis key used to cache the INR/USD rate
_REDIS_KEY = "exchange_rate:INR_USD"

# Public, no-auth endpoint that returns USD-based rates
_RATE_URL = "https://open.er-api.com/v6/latest/USD"


async def get_inr_to_usd_rate() -> float:
    # ── 1. Try Redis cache first ──────────────────────────────────────────
    redis = get_redis_client()
    if redis is not None:
        try:
            cached = await redis.get(_REDIS_KEY)
            if cached:
                rate = float(cached)
                logger.debug("Exchange rate served from Redis cache: %s INR/USD", rate)
                return rate
        except Exception as exc:
            # Redis failure is non-fatal; fall through to API call
            logger.warning("Redis read failed for exchange rate: %s", exc)

    # ── 2. Fetch from Open Exchange Rates API ─────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_RATE_URL)
            response.raise_for_status()
            data = response.json()

        # data["rates"]["INR"] = how many INR = 1 USD
        inr_rate: Optional[float] = data.get("rates", {}).get("INR")
        if not inr_rate or inr_rate <= 0:
            raise ValueError(
                f"Invalid INR rate in API response: {inr_rate!r}"
            )

        logger.info("Fetched live exchange rate: 1 USD = %s INR", inr_rate)

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Exchange rate API returned HTTP {exc.response.status_code}. "
            "Cannot process payment without a valid exchange rate."
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            f"Exchange rate API unreachable: {exc}. "
            "Cannot process payment without a valid exchange rate."
        ) from exc
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            f"Unexpected exchange rate API response format: {exc}"
        ) from exc

    # ── 3. Store in Redis with TTL ─────────────────────────────────────────
    if redis is not None:
        try:
            await redis.set(
                _REDIS_KEY,
                str(inr_rate),
                ex=settings.EXCHANGE_RATE_CACHE_TTL,
            )
            logger.debug(
                "Exchange rate cached in Redis for %s seconds", settings.EXCHANGE_RATE_CACHE_TTL
            )
        except Exception as exc:
            # Cache write failure is non-fatal
            logger.warning("Redis write failed for exchange rate: %s", exc)

    return float(inr_rate)


def inr_to_usd(amount_inr: int, rate: float) -> float:
    """
    Convert an INR amount to USD using the given rate.

    Args:
        amount_inr: Amount in Indian Rupees (integer).
        rate: INR per 1 USD (e.g. 83.52).

    Returns:
        USD amount rounded to 2 decimal places.
    """
    if rate <= 0:
        raise ValueError(f"Exchange rate must be positive, got {rate}")
    usd = round(amount_inr / rate, 2)
    logger.debug("Converted ₹%s → $%s (rate: %s INR/USD)", amount_inr, usd, rate)
    return usd
