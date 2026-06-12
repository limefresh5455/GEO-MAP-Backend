"""
Pinecone vector database wrapper — SDK 4.1.0 (pinecone-client).

Index spec
----------
- Index name    : settings.PINECONE_INDEX_NAME  (default: "geo-map-places")
- Dimensions    : 1536  (text-embedding-3-small)
- Metric        : cosine
- Namespaces    : "place_{place_id}" — one namespace per place keeps
                  retrieval scoped without any metadata filter overhead.
                  Phase 4 Q&A queries against a single namespace, so
                  there is no risk of cross-place bleed.

Design rules
------------
- The Pinecone client is synchronous in SDK 4.x; we wrap blocking calls
  in asyncio.get_event_loop().run_in_executor() so they do not block
  FastAPI's async event loop.
- Index is looked up once per instance (not per call) and cached as
  self._index.
- Raises PineconeError (HTTPException subclass) on all failures.
- upsert() is idempotent — re-upserting the same vector ID overwrites it.
- query() returns up to top_k ScoredVector objects with metadata.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from pinecone import Pinecone, ServerlessSpec

from app.core.config import settings

logger = logging.getLogger(__name__)

# Embedding dimension for text-embedding-3-small
_EMBEDDING_DIM = 1536

# Thread pool for wrapping synchronous Pinecone SDK calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pinecone")


class PineconeError(HTTPException):
    """Raised when a Pinecone operation fails."""

    def __init__(self, detail: str = "Pinecone operation failed"):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class PineconeClient:
    """
    Thin async wrapper around the Pinecone SDK.

    Responsibilities:
    - Ensure the index exists (create if absent, serverless spec).
    - Upsert vectors with metadata into a place-scoped namespace.
    - Query vectors with an optional metadata filter.
    - Delete all vectors in a namespace (used when re-syncing a place).
    """

    def __init__(self) -> None:
        self._pc: Optional[Pinecone] = None
        self._index = None
        self._index_name = settings.PINECONE_INDEX_NAME

    # ------------------------------------------------------------------
    # Internal: lazy init
    # ------------------------------------------------------------------

    def _get_pinecone(self) -> Pinecone:
        if self._pc is None:
            self._pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        return self._pc

    def _get_index(self):
        """Return (or lazily create) the Pinecone index handle."""
        if self._index is not None:
            return self._index

        pc = self._get_pinecone()

        # List existing indexes
        existing_names = [idx.name for idx in pc.list_indexes()]

        if self._index_name not in existing_names:
            logger.info(
                "Pinecone index '%s' not found — creating serverless index",
                self._index_name,
            )
            pc.create_index(
                name=self._index_name,
                dimension=_EMBEDDING_DIM,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region=settings.PINECONE_ENVIRONMENT or "us-east-1",
                ),
            )
            logger.info(
                "Pinecone index '%s' created successfully", self._index_name
            )

        self._index = pc.Index(self._index_name)
        return self._index

    def _make_namespace(self, place_id: str) -> str:
        """One namespace per place for zero-cost scoped retrieval."""
        return f"place_{place_id}"

    # ------------------------------------------------------------------
    # Internal: sync helpers (run in executor)
    # ------------------------------------------------------------------

    def _sync_upsert(
        self,
        vectors: List[Dict[str, Any]],
        namespace: str,
    ) -> int:
        """
        Synchronous upsert. Each item in vectors must be:
          {"id": str, "values": List[float], "metadata": dict}
        Returns the number of upserted vectors.
        """
        idx = self._get_index()
        response = idx.upsert(vectors=vectors, namespace=namespace)
        return response.upserted_count

    def _sync_query(
        self,
        vector: List[float],
        namespace: str,
        top_k: int,
        filter_dict: Optional[Dict[str, Any]],
        include_metadata: bool,
    ) -> List[Dict[str, Any]]:
        """
        Synchronous query. Returns a list of match dicts:
          [{"id": str, "score": float, "metadata": dict}, ...]
        """
        idx = self._get_index()
        kwargs: Dict[str, Any] = {
            "vector": vector,
            "top_k": top_k,
            "namespace": namespace,
            "include_metadata": include_metadata,
        }
        if filter_dict:
            kwargs["filter"] = filter_dict

        response = idx.query(**kwargs)
        return [
            {
                "id": match.id,
                "score": match.score,
                "metadata": match.metadata or {},
            }
            for match in response.matches
        ]

    def _sync_delete_namespace(self, namespace: str) -> None:
        """Delete ALL vectors in a namespace (used before re-sync)."""
        idx = self._get_index()
        idx.delete(delete_all=True, namespace=namespace)

    def _sync_describe_index_stats(self) -> Dict[str, Any]:
        idx = self._get_index()
        stats = idx.describe_index_stats()
        return {
            "dimension": stats.dimension,
            "total_vector_count": stats.total_vector_count,
            "namespaces": {
                ns: info.vector_count
                for ns, info in (stats.namespaces or {}).items()
            },
        }

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def upsert_vectors(
        self,
        place_id: str,
        vectors: List[Dict[str, Any]],
    ) -> int:
        """
        Upsert embedding vectors for a place into its dedicated namespace.

        Parameters
        ----------
        place_id : str
            Google place ID — used to derive the Pinecone namespace.
        vectors : List[dict]
            Each dict: {"id": str, "values": List[float], "metadata": dict}

        Returns
        -------
        int — number of vectors upserted.

        Raises
        ------
        PineconeError on any SDK-level failure.
        """
        namespace = self._make_namespace(place_id)
        logger.info(
            "Pinecone upsert — place_id: %s, namespace: %s, vectors: %d",
            place_id, namespace, len(vectors),
        )
        try:
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(
                _executor,
                lambda: self._sync_upsert(vectors, namespace),
            )
            logger.info(
                "Pinecone upsert complete — place_id: %s, upserted: %d",
                place_id, count,
            )
            return count
        except PineconeError:
            raise
        except Exception as exc:
            logger.error(
                "Pinecone upsert failed for place_id %s: %s", place_id, exc
            )
            raise PineconeError(f"Pinecone upsert failed: {exc}")

    async def query_vectors(
        self,
        place_id: str,
        query_vector: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search within a single place's namespace.

        Parameters
        ----------
        place_id       : Google place ID (scopes the query to one namespace).
        query_vector   : Embedding of the user's question.
        top_k          : Number of matches to return.
        filter_dict    : Optional Pinecone metadata filter.
        include_metadata : Whether to return metadata alongside scores.

        Returns
        -------
        List[{"id": str, "score": float, "metadata": dict}]

        Raises
        ------
        PineconeError on any SDK-level failure.
        """
        namespace = self._make_namespace(place_id)
        logger.info(
            "Pinecone query — place_id: %s, namespace: %s, top_k: %d",
            place_id, namespace, top_k,
        )
        try:
            loop = asyncio.get_event_loop()
            matches = await loop.run_in_executor(
                _executor,
                lambda: self._sync_query(
                    query_vector, namespace, top_k, filter_dict, include_metadata
                ),
            )
            logger.info(
                "Pinecone query returned %d matches for place_id: %s",
                len(matches), place_id,
            )
            return matches
        except PineconeError:
            raise
        except Exception as exc:
            logger.error(
                "Pinecone query failed for place_id %s: %s", place_id, exc
            )
            raise PineconeError(f"Pinecone query failed: {exc}")

    async def delete_place_namespace(self, place_id: str) -> None:
        """
        Delete all vectors for a place (called before re-sync to avoid stale chunks).
        Safe to call even if the namespace is empty.
        """
        namespace = self._make_namespace(place_id)
        logger.info(
            "Pinecone delete namespace — place_id: %s, namespace: %s",
            place_id, namespace,
        )
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _executor,
                lambda: self._sync_delete_namespace(namespace),
            )
        except Exception as exc:
            # Non-fatal — log and continue; worst case is stale vectors
            logger.warning(
                "Pinecone namespace delete failed for place_id %s: %s",
                place_id, exc,
            )

    async def get_namespace_vector_count(self, place_id: str) -> int:
        """Return current vector count for a place's namespace. Returns 0 on error."""
        namespace = self._make_namespace(place_id)
        try:
            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(
                _executor,
                self._sync_describe_index_stats,
            )
            return stats.get("namespaces", {}).get(namespace, 0)
        except Exception as exc:
            logger.warning(
                "Pinecone stats failed for place_id %s: %s", place_id, exc
            )
            return 0
