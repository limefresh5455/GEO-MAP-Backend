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
_DEFAULT_MAX_WIDTH_PX = 800
_DEFAULT_MAX_HEIGHT_PX = 800


class GooglePlacePhotosClient:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_photo_url(self, photo_name: str, max_width_px: int) -> str:
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
        url = self._build_photo_url(photo_name, max_width_px)
        try:
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
