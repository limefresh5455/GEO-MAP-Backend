import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from app.models.place_visit_log import PlaceVisitLog

logger = logging.getLogger(__name__)


class VisitRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, visit_id: int, user_id: int) -> Optional[PlaceVisitLog]:
        """Get a single visit log entry by PK (with ownership check)."""
        return (
            self.db.query(PlaceVisitLog)
            .filter(
                and_(
                    PlaceVisitLog.id == visit_id,
                    PlaceVisitLog.user_id == user_id,
                )
            )
            .first()
        )

    def create(
        self,
        *,
        user_id: int,
        place_id: str,
        display_name: Optional[str] = None,
        formatted_address: Optional[str] = None,
        primary_type: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        rating_given: Optional[float] = None,
        review_text: Optional[str] = None,
        with_whom: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> PlaceVisitLog:
        record = PlaceVisitLog(
            user_id=user_id,
            place_id=place_id,
            display_name=display_name,
            formatted_address=formatted_address,
            primary_type=primary_type,
            latitude=latitude,
            longitude=longitude,
            rating_given=rating_given,
            review_text=review_text,
            with_whom=with_whom,
            mood=mood,
        )
        self.db.add(record)
        self.db.flush()
        logger.info("Visit logged: user=%s place=%s", user_id, place_id)
        return record

    def update(
        self,
        record: PlaceVisitLog,
        *,
        rating_given: Optional[float] = None,
        review_text: Optional[str] = None,
        with_whom: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> PlaceVisitLog:
        if rating_given is not None:
            record.rating_given = rating_given
        if review_text is not None:
            record.review_text = review_text
        if with_whom is not None:
            record.with_whom = with_whom
        if mood is not None:
            record.mood = mood
        self.db.flush()
        logger.debug("Updated visit log id=%s", record.id)
        return record

    def delete(self, record: PlaceVisitLog) -> None:
        self.db.delete(record)
        self.db.flush()
        logger.info("Deleted visit log id=%s", record.id)

    def list_visits(
        self,
        user_id: int,
        *,
        place_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[PlaceVisitLog], int]:
        """List user's visit history with optional place filter."""
        query = self.db.query(PlaceVisitLog).filter(PlaceVisitLog.user_id == user_id)
        if place_id:
            query = query.filter(PlaceVisitLog.place_id == place_id)

        total = query.count()
        records = (
            query.order_by(PlaceVisitLog.visited_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return records, total

    def get_latest_visits_by_place_ids(
        self, user_id: int, place_ids: List[str]
    ) -> List[PlaceVisitLog]:
        """
        Batch-fetch the most recent visit per place for multiple place_ids.
        Uses a subquery to get the latest visit_id per place, then fetches full rows.
        """
        if not place_ids:
            return []

        # Subquery: latest visit_id per place_id
        from sqlalchemy import func as sa_func

        latest = (
            self.db.query(
                PlaceVisitLog.place_id,
                sa_func.max(PlaceVisitLog.id).label("max_id"),
            )
            .filter(
                and_(
                    PlaceVisitLog.user_id == user_id,
                    PlaceVisitLog.place_id.in_(place_ids),
                )
            )
            .group_by(PlaceVisitLog.place_id)
            .subquery()
        )

        return (
            self.db.query(PlaceVisitLog)
            .join(
                latest,
                and_(
                    PlaceVisitLog.id == latest.c.max_id,
                    PlaceVisitLog.place_id == latest.c.place_id,
                ),
            )
            .all()
        )

    def get_stats(self, user_id: int) -> Dict:
        total = (
            self.db.query(func.count(PlaceVisitLog.id))
            .filter(PlaceVisitLog.user_id == user_id)
            .scalar()
        ) or 0

        unique = (
            self.db.query(func.count(func.distinct(PlaceVisitLog.place_id)))
            .filter(PlaceVisitLog.user_id == user_id)
            .scalar()
        ) or 0

        # By category (primary_type)
        from sqlalchemy import text

        cat_sql = text("""
            SELECT COALESCE(primary_type, 'unknown') as category, COUNT(*) as cnt
            FROM place_visit_logs
            WHERE user_id = :uid
            GROUP BY category
            ORDER BY cnt DESC
        """)
        by_category = {}
        for row in self.db.execute(cat_sql, {"uid": user_id}).fetchall():
            by_category[row[0]] = row[1]

        # By month
        month_sql = text("""
            SELECT to_char(visited_at, 'YYYY-MM') as month, COUNT(*) as cnt
            FROM place_visit_logs
            WHERE user_id = :uid
            GROUP BY month
            ORDER BY month DESC
        """)
        by_month = {}
        for row in self.db.execute(month_sql, {"uid": user_id}).fetchall():
            by_month[row[0]] = row[1]

        return {
            "total_visits": total,
            "unique_places": unique,
            "by_category": by_category,
            "by_month": by_month,
        }
