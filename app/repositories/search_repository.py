"""
SearchRepository — all PostgreSQL operations for search_queries and search_results.

Rules
-----
- No HTTP exceptions raised here; only DB-level work.
- Both tables are append-only (immutable audit log).
- All writes must be flushed (not committed) so the caller's service controls
  the transaction boundary and can roll back on downstream failure.
"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.search_query import SearchQuery
from app.models.search_result import SearchResult
from app.schemas.discovery import DiscoveryPlaceResult

logger = logging.getLogger(__name__)


class SearchRepository:
    """
    Handles inserts and reads for search_queries and search_results.
    Returned ORM objects are not committed — the caller owns the transaction.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # search_queries
    # ------------------------------------------------------------------

    def create_search_query(
        self,
        *,
        user_id: int,
        search_mode: str,
        resolved_mode: Optional[str],
        raw_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        radius: Optional[float],
        result_count: int,
        from_cache: bool,
    ) -> SearchQuery:
        """
        Insert an audit row for the search that just ran.
        Flushed (not committed) so the caller can batch with search_results.
        """
        record = SearchQuery(
            user_id=user_id,
            search_mode=search_mode,
            resolved_mode=resolved_mode,
            raw_query=raw_query,
            latitude=latitude,
            longitude=longitude,
            radius=radius,
            result_count=result_count,
            from_cache="true" if from_cache else "false",
        )
        self.db.add(record)
        self.db.flush()   # assigns .id without committing
        logger.debug(
            "SearchQuery flushed: id=%s user=%s mode=%s query=%r results=%s cache=%s",
            record.id, user_id, search_mode, raw_query, result_count, from_cache,
        )
        return record

    # ------------------------------------------------------------------
    # search_results
    # ------------------------------------------------------------------

    def create_search_results(
        self,
        *,
        query_id: int,
        user_id: int,
        places: List[DiscoveryPlaceResult],
    ) -> List[SearchResult]:
        """
        Bulk-insert one SearchResult row per place in the result list.
        Flushed together in one batch — caller commits when ready.
        """
        rows: List[SearchResult] = []
        for position, place in enumerate(places):
            row = SearchResult(
                query_id=query_id,
                user_id=user_id,
                place_id=place.place_id or "",
                display_name=place.display_name,
                formatted_address=place.formatted_address,
                primary_type=place.primary_type,
                latitude=place.latitude,
                longitude=place.longitude,
                rating=place.rating,
                user_rating_count=place.user_rating_count,
                business_status=place.business_status,
                rank_position=position,
            )
            self.db.add(row)
            rows.append(row)

        if rows:
            self.db.flush()
            logger.debug(
                "SearchResults flushed: query_id=%s count=%s", query_id, len(rows)
            )
        return rows

    # ------------------------------------------------------------------
    # Reads (analytics / future use)
    # ------------------------------------------------------------------

    def get_recent_queries_for_user(
        self, user_id: int, limit: int = 10
    ) -> List[SearchQuery]:
        """Return the N most recent search queries for a user."""
        return (
            self.db.query(SearchQuery)
            .filter(SearchQuery.user_id == user_id)
            .order_by(SearchQuery.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_results_for_query(self, query_id: int) -> List[SearchResult]:
        """Return all place results stored for a specific query."""
        return (
            self.db.query(SearchResult)
            .filter(SearchResult.query_id == query_id)
            .order_by(SearchResult.rank_position)
            .all()
        )
