"""
Google Places Photos (New) client — Phase 6 / Photos Feature.

Resolves a photo resource name into a usable media URL.

How the Google Places Photos API works
---------------------------------------
A Place Details response returns photo objects like:
    {
        "name": "places/ChIJN1t_tDeuEmsRUsoyG83frY4/photos/AUacShh3...",
        "widthPx": 4032,
        "heightPx": 3024
    }

The "name" is a resource path, NOT an image URL.  To get the actual image
you call:

    GET https://places.googleapis.com/v1/{name}/media
        ?maxWidthPx=800
        &key=YOUR_API_KEY

Google responds with HTTP 302 and a Location header containing the real
CDN image URL (e.g. https://lh3.googleusercontent.com/...).

Strategy used here
------------------
We follow the redirect transparently (httpx follow_redirects=True).
The final response URL is what we store and return — it is a stable CDN
URL valid for several hours.  We cache these URLs in Redis to avoid
re-resolving the same photo name on every request.

Architecture notes
------------------
- Shares the same shared httpx.AsyncClient pattern as all other Google
  clients (B10 pattern — connection pool injected from app.state).
- Only photos that are already stored in place_details.photos are
  fetched — no new Google searches are triggered.
- Raises the same exception hierarchy (GooglePlacesAPIError etc.) so
  the service layer has one consistent error surface.
- max_width_px defaults to 800 — a good balance of quality and bandwidth.
  Frontend can request smaller sizes for thumbnails (e.g. 400px).
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
)

logger = logging.getLogger(__name__)

# Default photo width requested from Google CDN.
# 800px is suitable for detail cards; use 400px for thumbnails.
_DEFAULT_MAX_WIDTH_PX = 800
_DEFAULT_MAX_HEIGHT_PX = 800


class GooglePlacePhotosClient:
    """
    Async client for the Google Places Photos (New) API.

    Resolves one or more photo resource names into CDN image URLs.

    Parameters
    ----------
    http_client : httpx.AsyncClient, optional
        Shared connection-pooled client from app.state (B10 pattern).
        When None, a per-call client is created (test/fallback mode).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self._http_client = http_client
        # Slightly shorter read timeout — photo redirect should be fast
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_photo_url(self, photo_name: str, max_width_px: int) -> str:
        """
        Build the Google Places Photos media URL for a given resource name.

        photo_name format: "places/{place_id}/photos/{photo_reference}"
        Google requires the full resource name, not just the reference.
        """
        return (
            f"{self.base_url}/{photo_name}/media"
            f"?maxWidthPx={max_width_px}"
            f"&key={self.api_key}"
        )

    async def _resolve_single(
        self,
        photo_name: str,
        max_width_px: int,
        http_client: httpx.AsyncClient,
    ) -> Optional[str]:
        """
        Resolve one photo resource name to a CDN URL.

        Returns the final URL string, or None if resolution fails.
        We return None (not raise) on individual failures so that a single
        bad photo does not block all other photos from resolving.
        """
        url = self._build_photo_url(photo_name, max_width_px)
        try:
            # follow_redirects=True — httpx follows the 302 to the CDN URL.
            # The str_url of the final response is the actual image URL.
            response = await http_client.get(
                url,
                follow_redirects=True,
                headers={"Accept": "image/*,*/*"},
            )

            if response.status_code == 429:
                # Rate limit on photos — raise so the service can back off
                raise GooglePlacesRateLimitError(
                    "Places Photos API rate limit exceeded (429)"
                )

            if response.status_code == 403:
                raise GooglePlacesAPIError(
                    "Places Photos API: 403 Forbidden — check API key billing."
                )

            if response.status_code not in (200, 301, 302):
                logger.warning(
                    "Photo resolve failed for %s — status: %s",
                    photo_name,
                    response.status_code,
                )
                return None

            # After following redirects, str(response.url) is the final CDN URL.
            final_url = str(response.url)
            logger.debug("Resolved photo %s → %s", photo_name, final_url[:80])
            return final_url

        except (GooglePlacesRateLimitError, GooglePlacesAPIError):
            raise
        except httpx.TimeoutException:
            logger.warning("Photo resolve timed out for %s", photo_name)
            return None
        except Exception as exc:
            logger.warning("Unexpected error resolving photo %s: %s", photo_name, exc)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_photo_urls(
        self,
        photo_names: List[str],
        max_width_px: int = _DEFAULT_MAX_WIDTH_PX,
        max_height_px: int = _DEFAULT_MAX_HEIGHT_PX,
    ) -> List[Dict[str, Any]]:
        """
        Resolve a list of photo resource names to CDN image URLs.

        Each resolution is performed sequentially to stay within rate
        limits.  For a typical place with 5 photos this takes ~500ms total
        on first call; subsequent calls are served from Redis cache.

        Parameters
        ----------
        photo_names   : list of resource names, e.g.
                        ["places/ChIJ.../photos/AUacShh...", ...]
        max_width_px  : maximum width of the returned image (default 800)
        max_height_px : maximum height (not sent to Google — for metadata)

        Returns
        -------
        List of dicts, one per successfully resolved photo:
            {
                "photo_name": str,   # original resource name (for deduplication)
                "url": str,          # CDN image URL ready for <img src>
                "max_width_px": int,
            }
        Unresolvable photos are silently omitted from the list.

        Raises
        ------
        GooglePlacesRateLimitError : if Google returns 429 on any photo
        GooglePlacesAPIError       : on 403 (auth/billing failure)
        GooglePlacesTimeoutError   : if the shared client itself times out
        """
        if not photo_names:
            return []

        results: List[Dict[str, Any]] = []

        async def _run(client: httpx.AsyncClient) -> None:
            for name in photo_names:
                if not name:
                    continue
                url = await self._resolve_single(name, max_width_px, client)
                if url:
                    results.append({
                        "photo_name": name,
                        "url": url,
                        "max_width_px": max_width_px,
                    })

        try:
            if self._http_client:
                await _run(self._http_client)
            else:
                logger.warning(
                    "GooglePlacePhotosClient: no shared client — "
                    "creating per-call client (should only happen in tests)"
                )
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    await _run(client)
        except httpx.TimeoutException as exc:
            raise GooglePlacesTimeoutError(
                f"Places Photos client timed out: {exc}"
            ) from exc

        logger.info(
            "Photo resolution complete — requested: %d, resolved: %d",
            len(photo_names),
            len(results),
        )
        return results
