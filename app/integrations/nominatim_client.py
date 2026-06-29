import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_INTER_REQUEST_DELAY = 1.1
_USER_AGENT = "GeoMapBackend/3.0 (place-enrichment; contact@geomap.app)"


class NominatimClient:

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http_client = http_client
        self._last_call_time: float = 0.0

    async def _rate_limit(self) -> None:
        now = asyncio.get_running_loop().time()
        elapsed = now - self._last_call_time
        if elapsed < _INTER_REQUEST_DELAY:
            await asyncio.sleep(_INTER_REQUEST_DELAY - elapsed)
        self._last_call_time = asyncio.get_running_loop().time()

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": _USER_AGENT}

    async def _do_get(self, url: str, params: Dict[str, str]) -> httpx.Response:
        await self._rate_limit()

        headers = self._headers()
        if self._http_client is not None:
            return await self._http_client.get(url, params=params, headers=headers)

        # Fallback: should only happen in tests
        logger.warning(
            "NominatimClient: no shared HTTP client — creating per-call client. "
            "Inject http_nominatim from app.state for production use."
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=3.0, pool=5.0)
        ) as client:
            return await client.get(url, params=params, headers=headers)

    async def reverse_geocode(
        self, latitude: float, longitude: float
    ) -> Optional[Dict[str, Any]]:
        params = {
            "lat": str(latitude),
            "lon": str(longitude),
            "format": "jsonv2",
            "addressdetails": "1",
            "extratags": "1",
            "limit": "1",
        }
        url = f"{_NOMINATIM_BASE}/reverse"

        try:
            resp = await self._do_get(url, params)
            if resp.status_code != 200:
                logger.warning(
                    "Nominatim reverse geocode returned %s for (%s, %s)",
                    resp.status_code,
                    latitude,
                    longitude,
                )
                return None

            data = resp.json()
            if not data or "error" in data:
                return None

            address = data.get("address", {})
            extratags = data.get("extratags", {})
            category = data.get("category", "")

            return {
                "display_name": data.get("display_name", ""),
                "neighbourhood": address.get("neighbourhood") or address.get("suburb"),
                "suburb": address.get("suburb"),
                "city": address.get("city")
                or address.get("town")
                or address.get("village"),
                "state": address.get("state"),
                "country": address.get("country"),
                "postcode": address.get("postcode"),
                "osm_type": data.get("osm_type"),
                "osm_id": data.get("osm_id"),
                "category": category,
                "type": data.get("type"),
                "extra_tags": {
                    k: v
                    for k, v in extratags.items()
                    if k
                    in (
                        "wheelchair",
                        "capacity",
                        "website",
                        "phone",
                        "opening_hours",
                        "description",
                        "wikipedia",
                    )
                },
            }
        except (
            httpx.RequestError,
            httpx.TimeoutException,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Nominatim reverse geocode failed for (%s, %s): %s",
                latitude,
                longitude,
                exc,
            )
            return None

    async def search_place(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": "1",
            "extratags": "1",
            "limit": str(limit),
        }
        url = f"{_NOMINATIM_BASE}/search"

        try:
            resp = await self._do_get(url, params)
            if resp.status_code != 200:
                logger.warning(
                    "Nominatim search returned %s for %r", resp.status_code, query
                )
                return []

            results = resp.json()
            if not results:
                return []

            enriched = []
            for item in results:
                address = item.get("address", {})
                enriched.append(
                    {
                        "display_name": item.get("display_name", ""),
                        "latitude": item.get("lat"),
                        "longitude": item.get("lon"),
                        "category": item.get("category"),
                        "type": item.get("type"),
                        "osm_type": item.get("osm_type"),
                        "osm_id": item.get("osm_id"),
                        "neighbourhood": address.get("neighbourhood"),
                        "city": address.get("city") or address.get("town"),
                        "state": address.get("state"),
                        "country": address.get("country"),
                    }
                )
            return enriched
        except (
            httpx.RequestError,
            httpx.TimeoutException,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            logger.warning("Nominatim search failed for %r: %s", query, exc)
            return []
