import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_WIKI_API_BASE = "https://en.wikipedia.org/api/rest_v1"
_WIKI_QUERY_BASE = "https://en.wikipedia.org/w/api.php"
# Delay between consecutive calls to respect rate limits
_INTER_REQUEST_DELAY = 0.3


class WikipediaClient:
    """Fetch encyclopedic summaries about places from Wikipedia."""

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=3.0, pool=5.0)
        self._last_call_time: float = 0.0

    async def _rate_limit(self) -> None:
        """Ensure minimum delay between requests."""
        now = asyncio.get_running_loop().time()
        elapsed = now - self._last_call_time
        if elapsed < _INTER_REQUEST_DELAY:
            await asyncio.sleep(_INTER_REQUEST_DELAY - elapsed)
        self._last_call_time = asyncio.get_running_loop().time()

    async def _do_get(self, url: str, params: Optional[Dict] = None) -> httpx.Response:
        await self._rate_limit()

        # Wikipedia requires a descriptive User-Agent header per their API policy
        # https://meta.wikimedia.org/wiki/User-Agent_policy
        headers = {
            "User-Agent": "GeoMapBackend/3.0 (place-enrichment; contact@geomap.app)"
        }

        if self._http_client is not None:
            return await self._http_client.get(url, params=params, headers=headers)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.get(url, params=params, headers=headers)

    async def search_page(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Search Wikipedia for pages matching the query.
        Returns a list of {title, page_id, description} dicts.
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srprop": "snippet",
        }
        try:
            resp = await self._do_get(_WIKI_QUERY_BASE, params)
            if resp.status_code != 200:
                logger.warning(
                    "Wikipedia search returned %s for %r", resp.status_code, query
                )
                return []

            data = resp.json()
            results = []
            for item in data.get("query", {}).get("search", []):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "page_id": item.get("pageid"),
                        "description": item.get("snippet", "")
                        .replace('<span class="searchmatch">', "")
                        .replace("</span>", ""),
                    }
                )
            return results
        except Exception as exc:
            logger.warning("Wikipedia search failed for %r: %s", query, exc)
            return []

    async def get_summary(self, title: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the summary/extract for a Wikipedia page by title.
        Returns {title, extract, page_url, thumbnail} or None.
        """
        # Use the REST API summary endpoint
        safe_title = title.replace(" ", "_")
        url = f"{_WIKI_API_BASE}/page/summary/{safe_title}"

        try:
            resp = await self._do_get(url)
            if resp.status_code == 404:
                logger.info("Wikipedia page not found: %s", title)
                return None
            if resp.status_code != 200:
                logger.warning(
                    "Wikipedia summary returned %s for %s", resp.status_code, title
                )
                return None

            data = resp.json()
            thumbnail = data.get("thumbnail", {})
            return {
                "title": data.get("title", title),
                "extract": data.get("extract", ""),
                "page_url": data.get("content_urls", {})
                .get("desktop", {})
                .get("page", ""),
                "thumbnail_url": thumbnail.get("source") if thumbnail else None,
                "description": data.get("description", ""),
            }
        except Exception as exc:
            logger.warning("Wikipedia summary fetch failed for %s: %s", title, exc)
            return None

    async def get_place_knowledge(
        self, place_name: str, place_types: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        High-level method: search for a place and fetch the best matching page's summary.
        Returns a dict with {extract, page_url, source} or None.
        """
        if not place_name:
            return None

        # Build search queries from place name + type hints
        search_queries = [place_name]
        if place_types:
            primary = place_types[0] if isinstance(place_types, list) else place_types
            search_queries.append(f"{place_name} {primary}")

        for query in search_queries:
            results = await self.search_page(query, limit=2)
            if not results:
                continue

            # Try the first result
            best = results[0]
            summary = await self.get_summary(best["title"])
            if summary and summary.get("extract"):
                return {
                    "extract": summary["extract"],
                    "page_url": summary["page_url"],
                    "source": "wikipedia",
                    "title": summary["title"],
                }

        return None
